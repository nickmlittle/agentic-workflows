#!/usr/bin/env zsh

set -euo pipefail

INSTALL_DIR="$HOME/.agentic-workflows"
BIN_DIR="$HOME/bin"

mkdir -p "$BIN_DIR"

if [[ "$PWD" != "$INSTALL_DIR" ]]; then
  echo "Installing to $INSTALL_DIR"
  rm -rf "$INSTALL_DIR"
  git clone "$(pwd)" "$INSTALL_DIR"
else
  echo "Already in install dir."
fi

ln -sf "$INSTALL_DIR/bin/ae" "$BIN_DIR/ae"

if [[ ! -f "$INSTALL_DIR/config/config.local.json" ]]; then
  cp "$INSTALL_DIR/config/config.example.json" "$INSTALL_DIR/config/config.local.json"
fi

echo
echo "Installed ae."
echo "Add this to ~/.zshrc if needed:"
echo 'export PATH="$HOME/bin:$PATH"'
