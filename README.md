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
ae doctor       # Check local setup
ae ctx          # Print current repo/worktree context
ae review <pr>  # Create a PR review worktree/session
```

## Requirements

- `python3`
- `git`
- GitHub SSH access for cloning this private repo
- `gh` authenticated for `ae review`
- `code` if you want review worktrees opened in VS Code
