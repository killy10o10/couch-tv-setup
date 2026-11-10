#!/bin/sh
# Double-click in Finder to start Couch TV Setup (the first time: right-click, Open).
# It makes a private Python folder for itself the first time, then opens the setup in your browser.
cd "$(dirname "$0")" || exit 1
HOME_DIR="$HOME/Library/Application Support/Couch TV Setup"
VENV="$HOME_DIR/venv"
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys' >/dev/null 2>&1; then
  echo "This Mac needs Apple's developer tools for Python. A window asks to install them:"
  echo "press Install, wait for it to finish, then double-click this file again."
  xcode-select --install 2>/dev/null
  exit 1
fi
if [ ! -x "$VENV/bin/python" ] || ! "$VENV/bin/python" -c 'import adb_shell, certifi' >/dev/null 2>&1; then
  echo "Getting ready (only the first time, about a minute)..."
  mkdir -p "$HOME_DIR"
  python3 -m venv "$VENV" && "$VENV/bin/pip" install -q --disable-pip-version-check -r requirements.txt || {
    echo "Could not get ready. Is this Mac online?"; exit 1; }
fi
exec "$VENV/bin/python" -m couchtv_setup
