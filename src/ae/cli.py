from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import quote

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
    repos_root: Path
    worktree_dir_name: str
    editor: str
    github_remote: str
    default_main_branch: str
    post_worktree_actions: list[str]
    warp_enabled: bool
    warp_claude_panes: int
    warp_open_new_window: bool
    warp_start_command: str
    warp_tab_config_dir: Path


@dataclass(frozen=True)
class ClaudeWorktree:
    repo_name: str
    repo_root: Path
    path: Path
    name: str
    is_dirty: bool

    @property
    def label(self) -> str:
        status = "dirty" if self.is_dirty else "clean"
        return f"{self.repo_name}/{self.name} ({status}) - {self.path}"


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


def string_list_config(
    config: dict[str, Any],
    key: str,
    default: list[str],
    config_path: Path,
) -> list[str]:
    value = config.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise typer.BadParameter(f"Expected {key} to be a string list in {config_path}")
    return value


def get_settings() -> Settings:
    repo_dir = expand_path(
        os.environ.get("AE_REPO", str(Path(__file__).resolve().parents[2]))
    )
    config_dir = expand_path(os.environ.get("AE_CONFIG_DIR", "~/.config/ae"))
    data_dir = expand_path(os.environ.get("AE_DATA_DIR", "~/.local/share/ae"))
    config_path = config_dir / "config.json"
    config = load_json(config_path)
    warp_config = config.get("warp", {})
    if not isinstance(warp_config, dict):
        raise typer.BadParameter(f"Expected warp to be an object in {config_path}")

    return Settings(
        repo_dir=repo_dir,
        config_dir=config_dir,
        data_dir=data_dir,
        config_path=config_path,
        repos_root=expand_path(str(config.get("repos_root", "~/Projects"))),
        worktree_dir_name=str(config.get("worktree_dir_name", ".claude")),
        editor=str(config.get("editor", "code")),
        github_remote=str(config.get("github_remote", "origin")),
        default_main_branch=str(config.get("main_branch", "main")),
        post_worktree_actions=string_list_config(
            config,
            "post_worktree_actions",
            ["editor", "warp_claude_quad"],
            config_path,
        ),
        warp_enabled=bool(warp_config.get("enabled", True)),
        warp_claude_panes=int(warp_config.get("claude_panes", 4)),
        warp_open_new_window=bool(warp_config.get("open_new_window", True)),
        warp_start_command=str(warp_config.get("start_command", "claude")),
        warp_tab_config_dir=expand_path(
            str(warp_config.get("tab_config_dir", "~/.warp/tab_configs"))
        ),
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


def maybe_current_repo_root() -> Path | None:
    repo_root = git_output("rev-parse", "--show-toplevel", default="")
    if repo_root:
        return Path(repo_root)
    return None


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
    command = shlex.split(binary)[0] if shlex.split(binary) else binary
    if shutil.which(command):
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
  ae clean     Remove selected Claude worktrees
  ae ctx       Print current repo/worktree context
  ae doctor    Check local setup
  ae help      Show this help
  ae review [pr]  Create/open a Claude PR review worktree/session
  ae start     Guided workflow launcher
  ae task <ticket>  Create/open a Claude Jira ticket worktree/session"""
    )


@app.command()
def doctor() -> None:
    """Check local setup."""
    settings = get_settings()

    typer.echo("Checking agentic workflow setup...")
    status_line("git")
    status_line("gh")
    status_line("claude")
    status_line(settings.editor, missing_text=f"❌ {settings.editor} CLI missing")
    status_line("warp", optional=True, missing_text="⚠️ warp CLI not found")
    if warp_app_exists():
        typer.echo("✅ Warp app")
    else:
        typer.echo("⚠️ Warp app not found")
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
def review(pr: Optional[int] = typer.Argument(None, metavar="pr")) -> None:
    """Create/open a Claude PR review worktree/session."""
    settings = get_settings()
    run_review(settings, pr)


def run_review(settings: Settings, pr: Optional[int]) -> None:
    repo_root = maybe_current_repo_root()
    if repo_root is None or pr is None:
        repo_root = select_repo(settings.repos_root)
        pr = typer.prompt("PR number", type=int)

    repo_name = repo_root.name
    pr_id = str(pr)
    session_dir = settings.data_dir / "sessions" / repo_name / f"pr-{pr_id}"

    session_dir.mkdir(parents=True, exist_ok=True)
    add_info_exclude(repo_root, settings.worktree_dir_name)

    typer.echo("Fetching latest refs...")
    stream_command(["git", "fetch", "--all", "--prune"], cwd=repo_root)

    typer.echo("Fetching PR metadata...")
    pr_metadata = fetch_pr_metadata(pr_id, repo_root)
    write_json(session_dir / "pr.json", pr_metadata)

    title = str(pr_metadata["title"])
    body = str(pr_metadata.get("body") or "")
    head_ref = str(pr_metadata["headRefName"])
    base_ref = str(pr_metadata["baseRefName"])
    url = str(pr_metadata["url"])
    (session_dir / "pr-body.md").write_text(body, encoding="utf-8")

    typer.echo("Creating/opening Claude worktree...")
    worktree_path = open_claude_worktree(
        repo_root,
        settings.worktree_dir_name,
        f"pr-{pr_id}",
        "ae review",
    )

    session = {
        "type": "pr_review",
        "repo": repo_name,
        "repo_root": str(repo_root),
        "pr": pr_id,
        "title": title,
        "worktree_path": str(worktree_path),
        "base_ref": base_ref,
        "head_ref": head_ref,
        "url": url,
    }
    write_json(session_dir / "session.json", session)
    prompt = build_review_prompt(
        pr_id,
        repo_name,
        title,
        url,
        worktree_path,
        base_ref,
        head_ref,
        session_dir / "pr-body.md",
    )
    (session_dir / "review-prompt.md").write_text(prompt, encoding="utf-8")

    run_post_worktree_actions(settings, repo_name, f"pr-{pr_id}", worktree_path)

    typer.echo()
    typer.echo("✅ PR review session ready")
    typer.echo(f"Repo:      {repo_name} ({repo_root})")
    typer.echo(f"PR:        #{pr_id} - {title}")
    typer.echo(f"URL:       {url}")
    typer.echo(f"Base:      {base_ref}")
    typer.echo(f"Worktree:  {worktree_path}")
    typer.echo(f"Session:   {session_dir}")
    typer.echo()
    typer.echo("Suggested next commands:")
    typer.echo(f"  cd {shlex.quote(str(worktree_path))}")
    typer.echo("  git diff origin/{base}...HEAD".format(base=base_ref))
    typer.echo(f"  claude < {shlex.quote(str(session_dir / 'review-prompt.md'))}")


@app.command()
def task(ticket: str = typer.Argument(..., metavar="ticket")) -> None:
    """Create/open a Claude worktree for a Jira ticket."""
    settings = get_settings()
    run_task(settings, ticket)


def run_task(settings: Settings, ticket: str) -> None:
    repo_root = choose_repo_for_worktree(settings.repos_root)
    repo_name = repo_root.name
    ticket_key = ticket.strip()
    if not ticket_key:
        typer.echo("Ticket is required.", err=True)
        raise typer.Exit(1)

    worktree_name = sanitize_worktree_name(ticket_key)
    session_dir = settings.data_dir / "sessions" / repo_name / worktree_name

    session_dir.mkdir(parents=True, exist_ok=True)
    add_info_exclude(repo_root, settings.worktree_dir_name)

    typer.echo("Creating/opening Claude worktree...")
    worktree_path = open_claude_worktree(
        repo_root,
        settings.worktree_dir_name,
        worktree_name,
        "ae task",
    )

    session = {
        "type": "jira_task",
        "repo": repo_name,
        "repo_root": str(repo_root),
        "ticket": ticket_key,
        "worktree_name": worktree_name,
        "worktree_path": str(worktree_path),
    }
    write_json(session_dir / "session.json", session)
    prompt = build_task_prompt(ticket_key, repo_name, worktree_path)
    (session_dir / "task-prompt.md").write_text(prompt, encoding="utf-8")

    run_post_worktree_actions(settings, repo_name, worktree_name, worktree_path)

    typer.echo()
    typer.echo("✅ Task worktree ready")
    typer.echo(f"Repo:      {repo_name} ({repo_root})")
    typer.echo(f"Ticket:    {ticket_key}")
    typer.echo(f"Worktree:  {worktree_path}")
    typer.echo(f"Session:   {session_dir}")
    typer.echo()
    typer.echo("Suggested next commands:")
    typer.echo(f"  cd {shlex.quote(str(worktree_path))}")
    typer.echo(f"  claude < {shlex.quote(str(session_dir / 'task-prompt.md'))}")


@app.command()
def clean(
    all_worktrees: bool = typer.Option(
        False,
        "--all",
        help="Remove all detected Claude worktrees without selecting individually.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Pass --force to git worktree remove.",
    ),
) -> None:
    """Remove selected Claude worktrees under repos_root."""
    settings = get_settings()
    run_clean(settings, all_worktrees, force)


def run_clean(settings: Settings, all_worktrees: bool, force: bool) -> None:
    worktrees = find_claude_worktrees(settings.repos_root, settings.worktree_dir_name)
    if not worktrees:
        typer.echo(f"No Claude worktrees found under {settings.repos_root}.")
        return

    selected = worktrees if all_worktrees else select_worktrees_to_clean(worktrees)
    if not selected:
        typer.echo("No worktrees selected.")
        return

    typer.echo()
    typer.echo("Selected worktrees:")
    for worktree in selected:
        typer.echo(f"  {worktree.label}")

    if not typer.confirm("Remove these worktrees?", default=False):
        typer.echo("Cancelled.")
        return

    failures = 0
    for worktree in selected:
        if remove_worktree(worktree, force):
            typer.echo(f"Removed {worktree.path}")
        else:
            failures += 1

    if failures:
        raise typer.Exit(1)


@app.command()
def start() -> None:
    """Guide through common ae workflows."""
    settings = get_settings()
    action = select_start_action()

    if action == "task":
        ticket = typer.prompt("Jira ticket")
        run_task(settings, ticket)
    elif action == "review":
        pr = typer.prompt("PR number", type=int)
        run_review(settings, pr)
    elif action == "resume":
        run_resume(settings)
    elif action == "clean":
        run_clean(settings, all_worktrees=False, force=False)
    elif action == "doctor":
        doctor()
    else:
        typer.echo("Cancelled.")


def stream_command(args: list[str], cwd: Path) -> None:
    result = subprocess.run(args, cwd=cwd)
    if result.returncode != 0:
        raise typer.Exit(result.returncode)


def choose_repo_for_worktree(repos_root: Path) -> Path:
    repo_root = maybe_current_repo_root()
    if repo_root is not None:
        if typer.confirm(f"Use current repo {repo_root}?", default=True):
            return repo_root
        typer.echo()
    return select_repo(repos_root)


def select_repo(repos_root: Path) -> Path:
    if not repos_root.is_dir():
        typer.echo(f"repos_root does not exist: {repos_root}", err=True)
        raise typer.Exit(1)

    repos = [
        path
        for path in sorted(repos_root.iterdir(), key=lambda item: item.name.lower())
        if path.is_dir() and (path / ".git").exists()
    ]
    if not repos:
        typer.echo(f"No git repos found in {repos_root}", err=True)
        raise typer.Exit(1)

    typer.echo(f"Repos in {repos_root}:")
    for index, repo in enumerate(repos, start=1):
        typer.echo(f"  {index}. {repo.name}")

    choice = typer.prompt("Select repo", type=int)
    if choice < 1 or choice > len(repos):
        typer.echo("Invalid repo selection.", err=True)
        raise typer.Exit(1)
    return repos[choice - 1]


def select_start_action() -> str:
    choices = [
        ("Start Jira task worktree", "task"),
        ("Review GitHub PR", "review"),
        ("Resume existing worktree", "resume"),
        ("Clean Claude worktrees", "clean"),
        ("Run doctor", "doctor"),
        ("Cancel", "cancel"),
    ]
    selected = select_choice("What do you want to do?", choices)
    return selected or "cancel"


def run_resume(settings: Settings) -> None:
    worktrees = find_claude_worktrees(settings.repos_root, settings.worktree_dir_name)
    if not worktrees:
        typer.echo(f"No Claude worktrees found under {settings.repos_root}.")
        return

    worktree = select_one_worktree("Select worktree to resume:", worktrees)
    if worktree is None:
        typer.echo("Cancelled.")
        return

    run_post_worktree_actions(settings, worktree.repo_name, worktree.name, worktree.path)

    typer.echo()
    typer.echo("✅ Worktree resumed")
    typer.echo(f"Repo:      {worktree.repo_name} ({worktree.repo_root})")
    typer.echo(f"Worktree:  {worktree.path}")
    typer.echo()
    typer.echo("Suggested next commands:")
    typer.echo(f"  cd {shlex.quote(str(worktree.path))}")
    typer.echo("  claude")


def select_one_worktree(
    message: str,
    worktrees: Sequence[ClaudeWorktree],
) -> ClaudeWorktree | None:
    choices = [(worktree.label, worktree) for worktree in worktrees]
    return select_choice(message, choices)


def select_choice(
    message: str,
    choices: Sequence[tuple[str, Any]],
) -> Any | None:
    if sys.stdin.isatty():
        try:
            import questionary
        except ModuleNotFoundError:
            pass
        else:
            answer = questionary.select(
                message,
                choices=[
                    questionary.Choice(title=title, value=value)
                    for title, value in choices
                ],
            ).ask()
            return answer

    typer.echo(message)
    for index, (title, _) in enumerate(choices, start=1):
        typer.echo(f"  {index}. {title}")

    choice = typer.prompt("Select", type=int)
    if choice < 1 or choice > len(choices):
        typer.echo("Invalid selection.", err=True)
        raise typer.Exit(1)
    return choices[choice - 1][1]


def find_claude_worktrees(repos_root: Path, worktree_dir_name: str) -> list[ClaudeWorktree]:
    if not repos_root.is_dir():
        typer.echo(f"repos_root does not exist: {repos_root}", err=True)
        raise typer.Exit(1)

    worktrees: list[ClaudeWorktree] = []
    for worktree_parent in repos_root.rglob(f"{worktree_dir_name}/worktrees"):
        if not worktree_parent.is_dir():
            continue
        for path in sorted(worktree_parent.iterdir(), key=lambda item: item.name.lower()):
            if not is_git_worktree_dir(path):
                continue
            repo_root = main_repo_for_worktree(path)
            if repo_root is None:
                continue
            worktrees.append(
                ClaudeWorktree(
                    repo_name=repo_root.name,
                    repo_root=repo_root,
                    path=path,
                    name=path.name,
                    is_dirty=worktree_is_dirty(path),
                )
            )

    return sorted(worktrees, key=lambda item: (item.repo_name.lower(), item.name.lower()))


def main_repo_for_worktree(path: Path) -> Path | None:
    git_file = path / ".git"
    if not git_file.is_file():
        return None

    first_line = git_file.read_text(encoding="utf-8", errors="replace").splitlines()[0:1]
    if not first_line or not first_line[0].startswith("gitdir:"):
        return None

    gitdir_value = first_line[0].removeprefix("gitdir:").strip()
    gitdir = Path(gitdir_value)
    if not gitdir.is_absolute():
        gitdir = (path / gitdir).resolve()

    if gitdir.parent.name != "worktrees":
        return None

    main_git_dir = gitdir.parent.parent
    repo_root = main_git_dir.parent
    if (main_git_dir / "config").exists() and repo_root.is_dir():
        return repo_root
    return None


def worktree_is_dirty(path: Path) -> bool:
    result = run_command(["git", "-C", str(path), "status", "--short"], check=False)
    return bool(result.stdout.strip()) if result.returncode == 0 else True


def select_worktrees_to_clean(worktrees: Sequence[ClaudeWorktree]) -> list[ClaudeWorktree]:
    selected = select_worktrees_with_questionary(worktrees)
    if selected is not None:
        return selected
    return select_worktrees_with_prompt(worktrees)


def select_worktrees_with_questionary(
    worktrees: Sequence[ClaudeWorktree],
) -> list[ClaudeWorktree] | None:
    if not sys.stdin.isatty():
        return None

    try:
        import questionary
    except ModuleNotFoundError:
        return None

    choices = [
        questionary.Choice(title=worktree.label, value=worktree)
        for worktree in worktrees
    ]
    answer = questionary.checkbox(
        "Select Claude worktrees to remove:",
        choices=choices,
    ).ask()
    if answer is None:
        return []
    return list(answer)


def select_worktrees_with_prompt(worktrees: Sequence[ClaudeWorktree]) -> list[ClaudeWorktree]:
    typer.echo("Claude worktrees:")
    for index, worktree in enumerate(worktrees, start=1):
        typer.echo(f"  {index}. {worktree.label}")
    typer.echo()
    raw = typer.prompt("Select worktrees (for example 1,3-5; blank cancels)", default="")
    indexes = parse_index_selection(raw, len(worktrees))
    return [worktrees[index - 1] for index in indexes]


def parse_index_selection(raw: str, max_index: int) -> list[int]:
    selected: set[int] = set()
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            start_raw, end_raw = part.split("-", 1)
            if not start_raw.isdigit() or not end_raw.isdigit():
                typer.echo(f"Invalid selection: {part}", err=True)
                raise typer.Exit(1)
            start = int(start_raw)
            end = int(end_raw)
            if start > end:
                start, end = end, start
            selected.update(range(start, end + 1))
        elif part.isdigit():
            selected.add(int(part))
        else:
            typer.echo(f"Invalid selection: {part}", err=True)
            raise typer.Exit(1)

    invalid = [index for index in selected if index < 1 or index > max_index]
    if invalid:
        typer.echo(f"Selection out of range: {', '.join(map(str, invalid))}", err=True)
        raise typer.Exit(1)
    return sorted(selected)


def remove_worktree(worktree: ClaudeWorktree, force: bool) -> bool:
    args = [
        "git",
        "-C",
        str(worktree.repo_root),
        "worktree",
        "remove",
    ]
    if force:
        args.append("--force")
    args.append(str(worktree.path))

    result = run_command(args, check=False)
    if result.returncode == 0:
        return True

    message = result.stderr.strip() or result.stdout.strip()
    typer.echo(f"Could not remove {worktree.path}: {message}", err=True)
    return False


def add_info_exclude(repo_root: Path, worktree_dir_name: str) -> None:
    exclude_path = Path(
        git_output("rev-parse", "--git-path", "info/exclude", cwd=repo_root)
    )
    if not exclude_path.is_absolute():
        exclude_path = repo_root / exclude_path

    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    entry = f"{worktree_dir_name.rstrip('/')}/"
    existing = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
    if entry not in {line.strip() for line in existing.splitlines()}:
        with exclude_path.open("a", encoding="utf-8") as file:
            if existing and not existing.endswith("\n"):
                file.write("\n")
            file.write(f"{entry}\n")


def open_claude_worktree(
    repo_root: Path,
    worktree_dir_name: str,
    worktree_name: str,
    command_name: str,
) -> Path:
    if not shutil.which("claude"):
        typer.echo(
            f"claude CLI missing. Install Claude Code, then rerun {command_name}.",
            err=True,
        )
        raise typer.Exit(1)

    started_at = time.time()
    result = run_command(
        [
            "claude",
            "--print",
            "--worktree",
            worktree_name,
            "Create or open this worktree and stop. Do not inspect or edit files.",
        ],
        cwd=repo_root,
        check=False,
    )
    output = "\n".join(part for part in [result.stdout, result.stderr] if part)
    if output.strip():
        typer.echo(output.rstrip())
    if result.returncode != 0:
        raise typer.Exit(result.returncode)

    detected = detect_worktree_path(output, repo_root, worktree_dir_name, worktree_name, started_at)
    if detected is None:
        typer.echo("Claude worktree was created, but ae could not detect its path.", err=True)
        raise typer.Exit(1)
    return detected


def sanitize_worktree_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    if not name:
        typer.echo("Ticket did not contain a usable worktree name.", err=True)
        raise typer.Exit(1)
    return name


def detect_worktree_path(
    command_output: str,
    repo_root: Path,
    worktree_dir_name: str,
    worktree_name: str,
    started_at: float,
) -> Path | None:
    worktree_root = repo_root / worktree_dir_name
    expected_paths = [
        worktree_root / worktree_name,
        worktree_root / "worktrees" / worktree_name,
    ]
    candidates = path_candidates(command_output)

    for candidate in candidates:
        if candidate.name == worktree_name and is_git_worktree_dir(candidate):
            return candidate

    for expected in expected_paths:
        if is_git_worktree_dir(expected):
            return expected

    for candidate in candidates:
        if is_git_worktree_dir(candidate):
            return candidate

    search_roots = [
        path for path in [worktree_root, worktree_root / "worktrees"] if path.is_dir()
    ]
    if not search_roots:
        return None

    dirs = [
        path
        for search_root in search_roots
        for path in search_root.iterdir()
        if is_git_worktree_dir(path)
    ]
    if not dirs:
        return None

    named = [path for path in dirs if path.name == worktree_name]
    if named:
        return max(named, key=lambda path: path.stat().st_mtime)

    recent = [
        path
        for path in dirs
        if path.stat().st_mtime >= started_at - 5
    ]
    if recent:
        return max(recent, key=lambda path: path.stat().st_mtime)
    return max(dirs, key=lambda path: path.stat().st_mtime)


def is_git_worktree_dir(path: Path) -> bool:
    return path.is_dir() and (path / ".git").exists()


def path_candidates(output: str) -> list[Path]:
    candidates: list[Path] = []
    for raw in re.split(r"[\s'\"<>]+", output):
        token = raw.strip("`[]()").rstrip(".,:;").strip("`[]()")
        if not token or "/" not in token:
            continue
        path = Path(token).expanduser()
        if path.is_absolute():
            candidates.append(path)
    return candidates


def run_post_worktree_actions(
    settings: Settings,
    repo_name: str,
    session_name: str,
    worktree_path: Path,
) -> None:
    for action in settings.post_worktree_actions:
        if action == "editor":
            open_editor(settings.editor, worktree_path)
        elif action == "warp_claude_quad":
            open_warp_claude_quad(settings, repo_name, session_name, worktree_path)
        else:
            typer.echo(f"Unknown post-worktree action '{action}'; skipping.")


def open_editor(editor: str, worktree_path: Path) -> None:
    args = shlex.split(editor)
    if not args:
        return
    if not shutil.which(args[0]):
        typer.echo(f"{editor} CLI not found; skipping editor open.")
        return

    typer.echo()
    typer.echo(f"Opening {editor}...")
    subprocess.run(
        [*args, str(worktree_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def open_warp_claude_quad(
    settings: Settings,
    repo_name: str,
    session_name: str,
    worktree_path: Path,
) -> None:
    if not settings.warp_enabled:
        return

    if settings.warp_claude_panes < 1:
        typer.echo("Warp Claude panes is less than 1; skipping Warp launch.")
        return

    if not warp_app_exists() and not shutil.which("warp"):
        typer.echo("Warp app not found; skipping Warp launch.")
        return

    config_stem = sanitize_worktree_name(f"ae-{repo_name}-{session_name}").lower()
    config_path = settings.warp_tab_config_dir / f"{config_stem}.toml"
    settings.warp_tab_config_dir.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        build_warp_claude_tab_config(
            repo_name,
            session_name,
            worktree_path,
            settings.warp_claude_panes,
            settings.warp_start_command,
        ),
        encoding="utf-8",
    )

    url = f"warp://tab_config/{quote(config_stem)}"
    if settings.warp_open_new_window:
        url = f"{url}?new_window=true"

    typer.echo()
    typer.echo("Opening Warp Claude workspace...")
    if not shutil.which("open"):
        typer.echo(f"Warp tab config written, but open command was not found: {config_path}")
        return

    result = subprocess.run(
        ["open", url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        typer.echo(f"Warp tab config written, but could not open it: {config_path}")


def warp_app_exists() -> bool:
    return (
        Path("/Applications/Warp.app").exists()
        or Path("~/Applications/Warp.app").expanduser().exists()
    )


def build_warp_claude_tab_config(
    repo_name: str,
    session_name: str,
    worktree_path: Path,
    pane_count: int,
    start_command: str,
) -> str:
    title = f"{repo_name}: {session_name}"
    pane_ids = [f"claude_{index}" for index in range(1, pane_count + 1)]
    lines = [
        f"name = {toml_string('ae: ' + title)}",
        f"title = {toml_string(title)}",
        'color = "cyan"',
        "",
    ]

    lines.extend(build_warp_split_panes(pane_ids))

    for index, pane_id in enumerate(pane_ids, start=1):
        lines.extend(
            [
                "",
                "[[panes]]",
                f"id = {toml_string(pane_id)}",
                'type = "terminal"',
                f"directory = {toml_string(str(worktree_path))}",
                f"commands = [{toml_string(start_command)}]",
            ]
        )
        if index == 1:
            lines.append("is_focused = true")

    return "\n".join(lines) + "\n"


def build_warp_split_panes(pane_ids: list[str]) -> list[str]:
    if len(pane_ids) == 1:
        return []
    if len(pane_ids) == 2:
        return [
            "[[panes]]",
            'id = "root"',
            'split = "horizontal"',
            f"children = {toml_string_list(pane_ids)}",
        ]

    midpoint = (len(pane_ids) + 1) // 2
    left_ids = pane_ids[:midpoint]
    right_ids = pane_ids[midpoint:]
    return [
        "[[panes]]",
        'id = "root"',
        'split = "horizontal"',
        'children = ["left", "right"]',
        "",
        "[[panes]]",
        'id = "left"',
        'split = "vertical"',
        f"children = {toml_string_list(left_ids)}",
        "",
        "[[panes]]",
        'id = "right"',
        'split = "vertical"',
        f"children = {toml_string_list(right_ids)}",
    ]


def toml_string(value: str) -> str:
    return json.dumps(value)


def toml_string_list(values: list[str]) -> str:
    return "[" + ", ".join(toml_string(value) for value in values) + "]"


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
    pr_body_path: Path,
) -> str:
    return f"""You are reviewing PR #{pr} in repo {repo_name}.

PR: #{pr} - {title}

PR URL:
{url}

Base branch:
origin/{base_ref}

Head branch:
{head_ref}

Worktree:
{worktree_path}

PR body:
{pr_body_path}

Compare command:
git diff origin/{base_ref}...HEAD

Instructions:
- Read the PR body first.
- Compare using git diff origin/{base_ref}...HEAD.
- Explain the PR intent.
- Summarize the changed files.
- Identify risks, tests, grain issues, and downstream impacts.
- Do not edit files unless explicitly asked.
"""


def build_task_prompt(ticket: str, repo_name: str, worktree_path: Path) -> str:
    return f"""You are working on Jira ticket {ticket} in repo {repo_name}.

Ticket:
{ticket}

Worktree:
{worktree_path}

Instructions:
- Understand the ticket intent before editing files.
- Inspect the repo context and existing patterns first.
- Explain your intended approach before making broad changes.
- Keep changes focused on the ticket.
- Run relevant tests or explain why they were not run.
"""


if __name__ == "__main__":
    main()
