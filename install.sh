#!/usr/bin/env zsh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$HOME/bin"
CONFIG_DIR="$HOME/.config/ae"
DATA_DIR="$HOME/.local/share/ae"
VENV_DIR="$REPO_DIR/.venv"
SHELL_RC="${AE_SHELL_RC:-$HOME/.zshrc}"
PATH_UPDATED=0

function fail() {
  echo "Install failed: $*" >&2
  exit 1
}

command -v python3 >/dev/null || fail "python3 is required. Install Python 3, then rerun ./install.sh."

mkdir -p "$BIN_DIR" "$CONFIG_DIR" "$DATA_DIR/sessions" || fail "could not create ae directories"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  python3 -m venv "$VENV_DIR" || fail "could not create Python virtualenv at $VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install -q --disable-pip-version-check "typer>=0.12" "questionary>=2.0" || fail "could not install Python dependencies"
"$VENV_DIR/bin/python" -c "import typer" || fail "Typer was installed but could not be imported"
"$VENV_DIR/bin/python" -c "import questionary" || fail "Questionary was installed but could not be imported"

ln -sf "$REPO_DIR/bin/ae" "$BIN_DIR/ae"
chmod +x "$REPO_DIR/bin/ae"

if [[ ! -f "$CONFIG_DIR/config.json" ]]; then
  cp "$REPO_DIR/config/config.example.json" "$CONFIG_DIR/config.json"
fi

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  touch "$SHELL_RC" || fail "could not update $SHELL_RC"
  if ! grep -Fq 'export PATH="$HOME/bin:$PATH"' "$SHELL_RC"; then
    {
      echo
      echo "# ae CLI"
      echo 'export PATH="$HOME/bin:$PATH"'
    } >> "$SHELL_RC" || fail "could not update $SHELL_RC"
  fi
  PATH_UPDATED=1
fi

echo "Installed ae."
echo
echo "Repo:    $REPO_DIR"
echo "Binary:  $BIN_DIR/ae -> $REPO_DIR/bin/ae"
echo "Config:  $CONFIG_DIR/config.json"
echo "Data:    $DATA_DIR"
echo
if [[ "$PATH_UPDATED" -eq 1 ]]; then
  echo "Added $BIN_DIR to $SHELL_RC"
  echo "Run now:       $BIN_DIR/ae doctor"
  echo "New terminals: ae doctor"
else
  echo "Run:     ae doctor"
fi
