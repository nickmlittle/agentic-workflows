#!/usr/bin/env zsh

set -euo pipefail

INSTALL_DIR="$HOME/.agentic-workflows"
BIN_DIR="$HOME/bin"
SOURCE_DIR="$(pwd)"

mkdir -p "$BIN_DIR"

echo "Installing from $SOURCE_DIR to $INSTALL_DIR"

rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

rsync -a \
  --exclude '.git' \
  --exclude 'sessions' \
  --exclude 'config/config.local.json' \
  "$SOURCE_DIR/" "$INSTALL_DIR/"

ln -sf "$INSTALL_DIR/bin/ae" "$BIN_DIR/ae"

if [[ ! -f "$INSTALL_DIR/config/config.local.json" ]]; then
  cp "$INSTALL_DIR/config/config.example.json" "$INSTALL_DIR/config/config.local.json"
fi

echo
echo "Installed ae."
echo "Run:"
echo '  export PATH="$HOME/bin:$PATH"'
echo '  ae doctor'
