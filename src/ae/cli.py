from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import typer
except ModuleNotFoundError:
    repo = os.environ.get("AE_REPO", "the agentic-workflows repo")
    sys.stderr.write(f"ae needs Typer. Run {repo}/install.sh to finish setup.\n")
    raise SystemExit(1)


app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="agentic engineering cockpit",
)


@dataclass(frozen=True)
class Settings:
    repo_dir: Path
    config_dir: Path
    data_dir: Path
    config_path: Path
    worktree_root: Path
    editor: str
    github_remote: str
    default_main_branch: str


def main() -> None:
    app(prog_name="ae")


def expand_path(value: str) -> Path:
    return Path(value).expanduser()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise typer.BadParameter(f"Expected an object in {path}")
    return data


def get_settings() -> Settings:
    repo_dir = expand_path(
        os.environ.get("AE_REPO", str(Path(__file__).resolve().parents[2]))
    )
    config_dir = expand_path(os.environ.get("AE_CONFIG_DIR", "~/.config/ae"))
    data_dir = expand_path(os.environ.get("AE_DATA_DIR", "~/.local/share/ae"))
    config_path = config_dir / "config.json"
    config = load_json(config_path)

    return Settings(
        repo_dir=repo_dir,
        config_dir=config_dir,
        data_dir=data_dir,
        config_path=config_path,
        worktree_root=expand_path(str(config.get("worktree_root", "~/worktrees"))),
        editor=str(config.get("editor", "code")),
        github_remote=str(config.get("github_remote", "origin")),
        default_main_branch=str(config.get("main_branch", "main")),
    )


def run_git(
    *args: str,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=check,
    )


def run_command(
    args: list[str],
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=check,
    )


def git_output(*args: str, cwd: Path | None = None, default: str | None = None) -> str:
    result = run_git(*args, cwd=cwd, check=False)
    if result.returncode == 0:
        return result.stdout.strip()
    if default is not None:
        return default
    message = result.stderr.strip() or result.stdout.strip()
    typer.echo(message or f"git {' '.join(args)} failed", err=True)
    raise typer.Exit(1)


def current_repo_root() -> Path:
    repo_root = git_output("rev-parse", "--show-toplevel", default="")
    if not repo_root:
        typer.echo("Not inside a git repo.")
        raise typer.Exit(1)
    return Path(repo_root)


def origin_head_branch(repo_root: Path, fallback: str) -> str:
    ref = git_output(
        "symbolic-ref",
        "refs/remotes/origin/HEAD",
        cwd=repo_root,
        default="",
    )
    if ref.startswith("refs/remotes/origin/"):
        return ref.removeprefix("refs/remotes/origin/")
    return fallback


def status_line(
    binary: str,
    label: str | None = None,
    optional: bool = False,
    missing_text: str | None = None,
) -> None:
    name = label or binary
    if shutil.which(binary):
        typer.echo(f"✅ {name}")
    elif optional:
        typer.echo(missing_text or f"⚠️ {name} CLI not found")
    else:
        typer.echo(missing_text or f"❌ {name} missing")


@app.command("help")
def help_command() -> None:
    """Show this help."""
    typer.echo(
        """ae - agentic engineering cockpit

Commands:
  ae ctx       Print current repo/worktree context
  ae doctor    Check local setup
  ae help      Show this help
  ae review <pr>  Create a PR review worktree/session"""
    )


@app.command()
def doctor() -> None:
    """Check local setup."""
    settings = get_settings()

    typer.echo("Checking agentic workflow setup...")
    status_line("git")
    status_line("gh")
    status_line(settings.editor, missing_text=f"❌ {settings.editor} CLI missing")
    status_line("warp", optional=True, missing_text="⚠️ warp CLI not found")
    if settings.config_path.is_file():
        typer.echo(f"✅ config: {settings.config_path}")
    else:
        typer.echo(f"❌ config missing: {settings.config_path}")


@app.command()
def ctx() -> None:
    """Print current repo/worktree context."""
    settings = get_settings()
    repo_root = current_repo_root()

    repo_name = repo_root.name
    branch = git_output("branch", "--show-current", cwd=repo_root, default="detached")
    branch = branch or "detached"
    head = git_output("rev-parse", "--short", "HEAD", cwd=repo_root)
    remote = git_output(
        "remote",
        "get-url",
        settings.github_remote,
        cwd=repo_root,
        default="none",
    )
    main_branch = origin_head_branch(repo_root, settings.default_main_branch)
    status = run_git("status", "--short", cwd=repo_root, check=False)

    typer.echo(f"Repo:        {repo_name}")
    typer.echo(f"Path:        {repo_root}")
    typer.echo(f"Branch:      {branch}")
    typer.echo(f"HEAD:        {head}")
    typer.echo(f"Remote:      {remote}")
    typer.echo(f"Base:        origin/{main_branch}")
    typer.echo()
    typer.echo("Changed files:")
    if status.stdout:
        typer.echo(status.stdout.rstrip())


@app.command()
def review(pr: int = typer.Argument(..., metavar="pr")) -> None:
    """Create a PR review worktree/session."""
    settings = get_settings()
    repo_root = current_repo_root()
    repo_name = repo_root.name
    pr_id = str(pr)
    worktree_root = settings.worktree_root / repo_name
    worktree_path = worktree_root / f"pr-{pr_id}"
    session_dir = settings.data_dir / "sessions" / repo_name / f"pr-{pr_id}"

    worktree_root.mkdir(parents=True, exist_ok=True)
    session_dir.mkdir(parents=True, exist_ok=True)

    typer.echo("Fetching latest refs...")
    stream_command(["git", "fetch", "--all", "--prune"], cwd=repo_root)

    typer.echo("Fetching PR metadata...")
    pr_metadata = fetch_pr_metadata(pr_id, repo_root)
    write_json(session_dir / "pr.json", pr_metadata)

    title = str(pr_metadata["title"])
    head_ref = str(pr_metadata["headRefName"])
    base_ref = str(pr_metadata["baseRefName"])
    url = str(pr_metadata["url"])

    typer.echo("Creating worktree...")
    if worktree_path.is_dir():
        typer.echo(f"Worktree already exists: {worktree_path}")
    else:
        stream_command(
            ["git", "fetch", settings.github_remote, f"pull/{pr_id}/head:pr-{pr_id}"],
            cwd=repo_root,
        )
        stream_command(
            ["git", "worktree", "add", str(worktree_path), f"pr-{pr_id}"],
            cwd=repo_root,
        )

    session = {
        "type": "pr_review",
        "repo": repo_name,
        "pr": pr_id,
        "title": title,
        "worktree_path": str(worktree_path),
        "base_ref": base_ref,
        "head_ref": head_ref,
        "url": url,
    }
    write_json(session_dir / "session.json", session)
    prompt = build_review_prompt(pr_id, repo_name, title, url, worktree_path, base_ref, head_ref)
    (session_dir / "claude-prompt.md").write_text(prompt, encoding="utf-8")

    typer.echo()
    typer.echo(f"Opening {settings.editor}...")
    subprocess.run(
        [settings.editor, str(worktree_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    typer.echo()
    typer.echo("✅ PR review session ready")
    typer.echo(f"Repo:      {repo_name}")
    typer.echo(f"PR:        #{pr_id} - {title}")
    typer.echo(f"URL:       {url}")
    typer.echo(f"Worktree:  {worktree_path}")
    typer.echo(f"Session:   {session_dir}")
    typer.echo()
    typer.echo("Claude prompt:")
    typer.echo("-------------")
    typer.echo(prompt, nl=False)


def stream_command(args: list[str], cwd: Path) -> None:
    result = subprocess.run(args, cwd=cwd)
    if result.returncode != 0:
        raise typer.Exit(result.returncode)


def fetch_pr_metadata(pr: str, cwd: Path) -> dict[str, Any]:
    result = run_command(
        [
            "gh",
            "pr",
            "view",
            pr,
            "--json",
            "number,title,body,headRefName,baseRefName,url,author",
        ],
        cwd=cwd,
        check=False,
    )
    if result.returncode != 0:
        typer.echo(result.stderr.strip() or result.stdout.strip(), err=True)
        raise typer.Exit(result.returncode)
    data = json.loads(result.stdout)
    required = ["title", "headRefName", "baseRefName", "url"]
    missing = [key for key in required if not data.get(key)]
    if missing:
        typer.echo(f"Missing PR metadata: {', '.join(missing)}", err=True)
        raise typer.Exit(1)
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def build_review_prompt(
    pr: str,
    repo_name: str,
    title: str,
    url: str,
    worktree_path: Path,
    base_ref: str,
    head_ref: str,
) -> str:
    return f"""You are reviewing PR #{pr} in repo {repo_name}.

PR title:
{title}

PR URL:
{url}

Worktree:
{worktree_path}

Base branch:
origin/{base_ref}

Head branch:
{head_ref}

Instructions:
- Do not compare against local main.
- Use: git diff origin/{base_ref}...HEAD
- First read the PR body and explain the intent.
- Then inspect changed files.
- Then identify risks, missing tests, data grain issues, and downstream impacts.
- Do not edit files unless explicitly asked.
"""


if __name__ == "__main__":
    main()
