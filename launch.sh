#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_PY="./.venv/bin/python"

if [ ! -x "$VENV_PY" ]; then
    echo "First-run setup: creating .venv and installing retrofetch..."
    python3 -m venv .venv
    "$VENV_PY" -m pip install --upgrade pip
    "$VENV_PY" -m pip install -e .
fi

exec "$VENV_PY" -m retrofetch tui "$@"
