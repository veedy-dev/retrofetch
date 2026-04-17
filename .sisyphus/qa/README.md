# QA dispatcher protocol

Use `run-qa.sh` on POSIX and `run-qa.ps1` on Windows.

## Naming

- `wave{N}-task{M}-{slug}.py`
- `wave{N}-task{M}-{slug}.sh`
- sample scenarios use `wave{N}-sample-{slug}.py`
- sample scenarios use `wave{N}-sample-{slug}.sh`

The dispatcher looks for the matching stem from `WAVE TASK SLUG`.
If `TASK` is `sample`, it resolves to `wave{WAVE}-sample-{SLUG}`.
Otherwise it resolves to `wave{WAVE}-task{TASK}-{SLUG}`.

## Variant selection

### POSIX (`run-qa.sh`)

1. Build the scenario stem.
2. Check for matching `.sh` and `.py` files.
3. If both exist and `tmux` is available, run `.sh`.
4. If both exist and `tmux` is not available, run `.py`.
5. If only `.sh` exists and `tmux` is not available, exit 77.
6. If only `.py` exists, run it.

### Windows (`run-qa.ps1`)

1. Build the scenario stem.
2. Check for matching `.py` first.
3. Run `.py` with `.venv\Scripts\python.exe`.
4. If only `.sh` exists, skip with exit 77.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | pass |
| 1 | fail |
| 77 | skipped, usually because `tmux` is required |

## Skip semantics

`77` means the scenario was not executed, not that it failed.
Use it when a shell-only scenario needs `tmux` and `tmux` is unavailable.

## Python runtime

Do not rely on ambient `python` resolution.
Use the repo venv interpreter:

- POSIX: `.venv/bin/python`
- Windows: `.venv\Scripts\python.exe`

## Example

```powershell
.\.sisyphus\qa\run-qa.ps1 1 sample version-check
```
