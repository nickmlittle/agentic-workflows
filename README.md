# agentic-workflows

Small local CLI for agentic engineering workflows.

## Install

Clone the private repo, then run the bootstrap script:

```sh
git clone git@github.com:nickmlittle/agentic-workflows.git
cd agentic-workflows
./install.sh
```

The installer creates a repo-local Python virtualenv, installs the CLI dependency,
symlinks `repo/bin/ae` to `~/bin/ae`, and creates:

- `~/.config/ae/config.json`
- `~/.local/share/ae/sessions`

After install, open a new terminal and run:

```sh
ae doctor
```

Or run it immediately with the full path:

```sh
~/bin/ae doctor
```

## Commands

```sh
ae clean        # Select Claude worktrees to remove
ae doctor       # Check local setup
ae ctx          # Print current repo/worktree context
ae start        # Guided workflow launcher
ae review <pr>  # Create/open a Claude PR review worktree/session
ae review       # Pick a configured repo, then enter a PR number
ae task PED-123 # Create/open a Claude Jira ticket worktree/session
```

`ae review 12345` runs from the current git repo, fetches latest refs, asks
Claude to create/open `pr-12345` as a worktree, saves PR metadata plus a review
prompt under `~/.local/share/ae/sessions/<repo>/pr-12345/`, and opens the
worktree in VS Code when the configured editor CLI is available.

`ae task PED-123` confirms the current repo when run inside one, otherwise it
prompts you to pick from `repos_root`, then asks Claude to create/open a worktree
for the ticket.

After a worktree is ready, `ae` runs configured post-worktree actions. By
default it opens the worktree in the configured editor and opens a Warp window
with four Claude panes, all started in the worktree directory.

`ae clean` scans `repos_root` recursively for `.claude/worktrees/<name>`
directories, lets you select worktrees to remove, then removes them with
`git worktree remove`. When `questionary` is installed, selection uses an
arrow-key checkbox UI; otherwise it falls back to a numbered prompt.

`ae start` opens a guided menu for starting a task, reviewing a PR, resuming an
existing Claude worktree, cleaning worktrees, or running doctor.

Example config:

```json
{
  "repos_root": "~/Projects",
  "worktree_dir_name": ".claude",
  "editor": "code",
  "post_worktree_actions": ["editor", "warp_claude_quad"],
  "warp": {
    "enabled": true,
    "claude_panes": 4,
    "open_new_window": true,
    "start_command": "claude",
    "tab_config_dir": "~/.warp/tab_configs"
  }
}
```

## Requirements

- `python3`
- `git`
- GitHub SSH access for cloning this private repo
- `gh` authenticated for `ae review`
- `claude` for Claude worktree creation
- `questionary` for checkbox selection in `ae clean`
- Warp if you want four Claude panes opened after worktree creation
- `code` if you want review worktrees opened in VS Code
