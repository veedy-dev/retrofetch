# retrofetch-tui: Architectural Decisions

## Carried Over From Plan
- **YAML strategy**: ruamel.yaml FULL migration (not dual-library) - Round 2 decision
- **Progress refactor**: maximal event bus (retrofetch/events.py with typed events) - Round 2 decision
- **Test strategy**: tmux/Pilot agent QA only, no pytest introduction - Round 2 decision
- **MVP size**: full command center in v1 (not incremental) - Round 1 decision
- **Live progress**: in-app from Textual worker, driven by event bus - Round 1 decision
- **Python floor**: `>=3.10,<3.14` (T5) - opens to 3.10 for broader users, caps at 3.14 for safety
- **Textual pin**: `>=8.0.0,<9.0.0` - allow bugfixes, block major
- **Shutdown path in TUI**: Textual-native `action_quit` override (NOT `ShutdownCoordinator.install()`) - T23 decision, resolves Textual issue #1707
- **No singleton EventBus global**: instances are passed explicitly (T7)
- **Dry-run semantics**: carried via `Config.dry_run` field (T10), not a per-command kwarg. CLI `--dry-run` sets `config.dry_run = True` before invoking `run_console`. TUI exposes a Checkbox for per-session dry-run toggle.

## [2026-04-18T08:12:00Z] T12: TUI command baseline
- Added `retrofetch tui` as a new Typer subcommand.
- Updated the CLI help golden to include the new `tui` command.
- Kept the TUI layer as scaffolding only; screens and workers remain future tasks.
