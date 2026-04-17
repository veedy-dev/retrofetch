#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
py_exe="$repo_root/.venv/bin/python"
version="$($py_exe -m retrofetch --version)"

if [ "$version" != "retrofetch 0.1.0" ]; then
  printf 'expected retrofetch 0.1.0, got %s\n' "$version" >&2
  exit 1
fi

printf 'sample version-check: OK\n'
