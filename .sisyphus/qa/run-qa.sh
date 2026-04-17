#!/usr/bin/env bash
set -euo pipefail

qa_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$qa_dir/../.." && pwd)"

if [ "$#" -ne 3 ]; then
  printf 'usage: %s WAVE TASK SLUG\n' "$0" >&2
  exit 2
fi

wave="$1"
task="$2"
slug="$3"

if [ "$task" = "sample" ]; then
  stem="wave${wave}-sample-${slug}"
else
  stem="wave${wave}-task${task}-${slug}"
fi

sh_file="$qa_dir/$stem.sh"
py_file="$qa_dir/$stem.py"
py_exe="$repo_root/.venv/bin/python"
has_tmux=0

run_python() {
  "$py_exe" "$py_file"
}

if command -v tmux >/dev/null 2>&1; then
  has_tmux=1
fi

if [ -f "$sh_file" ] && [ -f "$py_file" ]; then
  if [ "$has_tmux" -eq 1 ]; then
    bash "$sh_file"
  else
    run_python
  fi
  exit $?
fi

if [ -f "$sh_file" ]; then
  if [ "$has_tmux" -eq 1 ]; then
    bash "$sh_file"
    exit $?
  fi
  printf 'skipped: tmux required\n' >&2
  exit 77
fi

if [ -f "$py_file" ]; then
  run_python
  exit $?
fi

printf 'no scenario at %s.(py|sh)\n' "$stem" >&2
exit 1
