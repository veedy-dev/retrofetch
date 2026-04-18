# retrofetch-tui: Inherited Wisdom & Learnings

## Environment
- Python: 3.13.5 (active in `.venv`)
- Platform: Windows 11 (win32, PowerShell 5.1)
- Commands MUST use `;` not `&&` to chain (PowerShell 5.1 doesn't support `&&`)
- Python invocation: `.venv\Scripts\python.exe` (Windows), but QA scenarios MUST use `sys.executable` + `subprocess.run([sys.executable, "-m", "retrofetch", ...])` for cross-platform portability.

## Project Conventions (from retrofetch parent plan)
- Flat `retrofetch/` module, no clean-arch dirs
- YAML config only (no TOML/JSON)
- State: JSON per console at `ROMs/<console>/.retrofetch-state.json`
- Commits: Conventional Commits, NO attribution trailers (no `Co-authored-by`, `Generated-by`, `Claude`, `Atlas`, `OMC`, `Sisyphus`)
- NO unit tests (no pytest/conftest anywhere in the repo)
- QA: agent-executed scenarios only, evidence in `.sisyphus/evidence/`
- Exception types locked to 3: `SourceUnavailable`, `VerificationFailed`, `ConfigError`
- Exit codes locked to: 0, 1, 2, 130

## Critical Current-Code Facts (verified 2026-04-17)
- `retrofetch/cli.py::download`: `--dry-run` CURRENTLY skips `run_console` entirely (line ~203 `if dry_run: continue`). T10 must move this gate INTO `run_console` via new `dry_run` param on Config.
- `retrofetch/orchestrator.py::run_console`: signature is `(console_entry, wantlist, config, allow_torrent, consoles_yml, stop_event=None)`. T10 adds `event_bus` and `dry_run` params.
- `retrofetch/downloader.py::download_game`: signature takes `progress_cb`. T10 replaces with `event_bus`.
- `retrofetch/dispatcher.py::SourceDispatcher.dispatch_download`: signature takes `progress_cb: Any | None = None`. T10 replaces.
- `retrofetch/sources/__init__.py`: `SourceAdapter` Protocol has `download(candidate, dest_dir, progress_cb=None)`. T10 replaces.
- Live `progress_cb` call sites (NOT dead code - confirmed in plan):
  - `archive_org.py::download` (lines ~125-127)
  - `minerva_http.py::download` (lines 151, 169 approx)
  - `romsfun.py::download` (line 161 approx)
  - `romsretro.py`: inherits from romsfun — no own download method
  - `minerva_torrent.py::download`: unimplemented (raises); T10 adds param for consistency
- `retrofetch/ui.py::progress_context` is DEAD infrastructure (intentionally left unused per Metis K.5, NOT wired to event bus in this plan).
- `retrofetch/signals.py::ShutdownCoordinator.install()` uses `signal.signal(...)`. Per T23: KEEP in CLI download path; DO NOT use in TUI path (conflicts with Textual's own SIGINT handler).
- `retrofetch/__main__.py` exists: `from retrofetch.cli import app; app()`. QA scenarios can use `python -m retrofetch`.
- `retrofetch/__init__.py`: `__version__ = "0.1.0"`.

## YAML Strategy (full ruamel migration, T8)
- Four `yaml.safe_load` sites to replace (Metis K.4): `cli.py:61` (consoles), `config.py:64` (config), `config.py:89` (overrides), `report.py:21` (consoles).
- Zero `yaml.safe_dump` sites today — save is NEW functionality (not migration).
- Pattern: `_yaml_rt = YAML(typ='rt')` module-level; `_yaml_rt.load(path.read_text(encoding="utf-8"))` replaces `yaml.safe_load(...)`.
- ALWAYS load-then-mutate (never construct `CommentedMap` from scratch).
- Keep `PyYAML` in pyproject (transitive deps may use it).
- Pydantic validation remains unchanged after load.
- Atomic save: write to `.tmp`, fsync, `os.replace`.

## Textual Pitfalls (from plan research)
- Textual pin: `>=8.0.0,<9.0.0`
- `@work(thread=True, exclusive=True, group="...")` — group MUST be explicit (Metis K.6; issue #5137 + silent collision)
- `post_message()` is the ONLY thread-safe UI primitive from worker threads (Metis K.7)
- DO NOT call widget methods, `self.query_one`, `widget.reactive = ...`, `widget.styles.xxx = ...` from worker threads
- DO NOT use `set_loading=True` from a thread worker (issue #5137)
- DO NOT use `asyncio.sleep` in `on_mount` (issue #1707; blocks Ctrl+C)
- DO NOT use `asyncio.to_thread` inside Textual workers
- DO NOT use `Select.BLANK` (removed in Textual v8+)
- DO NOT use Rich emoji shortcodes `":smiley:"` (removed in Textual v2+)
- NO emojis in widget labels, screen titles, TCSS content (Windows rendering bugs #5915, #6327)
- Use ASCII arrows/checks: `→` `✓` `✗` are OK in Rich output (T11), but NOT in Textual layout per Metis K.10

## Delegation Reliability (CRITICAL from prior session)
- **Prior session had 2x 30-minute delegation timeouts** with `Sisyphus-Junior-quick`. If a task hangs 20+ min with no progress, cancel and retry or fall back to direct implementation.
- Keep prompts SHARP and SHORT. Explicit verify commands. Always specify file paths.
- Always include `load_skills=[]` (per session CLAUDE.md MANDATORY).

## QA Scenario Constraints
- Cross-platform: always `subprocess.run([sys.executable, "-m", "retrofetch", ...])`, `pathlib.Path`, `tempfile.TemporaryDirectory()`, `encoding="utf-8"` on all reads.
- NEVER hardcode `.\.venv\Scripts\retrofetch.exe` or `./.venv/bin/retrofetch`.
- NEVER use `grep`, `wc`, `diff`, `sed` inside `.py` scenarios — use `re.findall`, `len(...)`, `difflib.unified_diff`, Python equivalents.
- Evidence path: `.sisyphus/evidence/tui-task-{N}-{slug}.txt`
- QA dispatchers: `.sisyphus/qa/run-qa.sh` (POSIX) + `.sisyphus/qa/run-qa.ps1` (Windows).
- Exit code convention: 0 pass, 1 fail, 77 skip.
## 2026-04-18 T5: deps
Raised Python floor to 3.10 and added textual/ruamel.yaml to project deps. Editable install pulled textual 8.2.3 in the current venv, and the QA scenario passed with the version smoke check.
## 2026-04-17T23:38:38Z T6: goldens + fixtures
- Captured pre-refactor CLI stdout once per golden with subprocess.run([sys.executable, '-m', 'retrofetch', ...], capture_output=True, text=True, encoding='utf-8').
- Stable golden bodies were clean; no timestamps, temp paths, or other nondeterministic content appeared in stdout.
- `--help` output is wrapped with ANSI-free table formatting and includes a trailing blank line in stdout.
- QA comparison strips the `# ---` header and diffs only the body with difflib.unified_diff.


## [2026-04-18 06:41] T4: QA dispatcher
- Added cross-platform QA dispatchers under .sisyphus/qa/ with WAVE/TASK/SLUG stem resolution and 0/1/77 exit codes.
- POSIX .sh scripts need LF line endings on Windows; normalize after writing or bash -n will fail on CRLF.
- Windows dispatcher stays self-contained by using .venv\Scripts\python.exe for .py scenarios and skipping shell-only scenarios.
- Sample version-check scenarios assert "retrofetch 0.1.0" via retrofetch --version only.


## [2026-04-18 06:47:06] T1: DataTable perf
initial=42.7ms, scroll=65.5ms, filter=450.2ms — VERDICT: NO-GO
Implications for T17 wantlist screen: paginate

## [2026-04-18 07:00] T7: events module
- 11 event dataclasses
- EventBus API: subscribe/unsubscribe/publish + SubscriptionHandle
- Thread-safety: 1000-event race test PASS
- Unsub-mid-dispatch: PASS
## [2026-04-18T06:49:54.5836402+07:00] T3: ruamel round-trip
loads: consoles=165.6ms, commented_config=1.9ms, overrides=0.5ms
round-trip: DIVERGENT
Implication for T8: known divergence case: commented-config.yml still changes byte-for-byte under ruamel rt; consoles load also exceeds 100ms on this machine

## [2026-04-18 06:50] T2: ListView perf + debounce
178 items: initial=61.49ms; recommended debounce=200ms
Implications for T15 Home screen sidebar: {use built-in ListView + debounce of 200ms}

## [2026-04-18 07:15] Wave 1 Orchestrator Summary + Follow-up Fixes
- **T3 round-trip DIVERGENT root cause**: Windows `core.autocrlf=true` rewrote the LF fixture to CRLF on commit; ruamel always dumps LF. Secondary cause: literal `max_game_size_gb: null` line — ruamel dumps `null` as empty scalar (semantically equal, byte-different).
- **Fix (commit `2df06d7`)**: Added root `.gitattributes` with `.sisyphus/fixtures/*.yml text eol=lf` (preserves LF on checkout/commit across platforms). Rewrote fixture without the `null` line. Re-ran T3 — ROUND-TRIP: IDENTICAL.
- **Evidence file encoding gotcha**: PowerShell 5.1 `Tee-Object` / `| Out-File` default to UTF-16 LE with BOM. T2+T3 evidence had to be regenerated as UTF-8 by capturing stdout in Python. **Rule: future QA scenarios MUST write evidence via Python `write_text(..., encoding="utf-8")` rather than PowerShell redirect.**
- **T1 DataTable NO-GO**: filter latency 561ms on 5000 rows (plain add_rows + filter → rebuild). Mitigation for T17: paginate 50 rows/page OR reduce visible rows. No `textual-fastdatatable` dep per plan guardrail.
- **T2 ListView GO**: 200ms debounce makes 8-char typing result in 1 filter call (not 8). Plan T15 sidebar will use this.
- **T7 EventBus PASS**: thread-safe; snapshot-under-lock dispatch works; subscriber exceptions swallowed (hot path).
- **Plan status**: 7 of 27 top-level tasks done (T1-T7). Wave 2 next: T8 (ruamel migration), T9 (coverage split), T10 (event-bus refactor), T11 (--verbose).

## Production config.yml line-ending concern (T8 heads-up)
Current repo files checked (2026-04-18):
- `config.yml.example`: 26 CRLF, 0 LF (Windows)
- `config.yml`: 26 CRLF, 0 LF (Windows)
- `overrides.yml.example`: 10 LF (Unix)
- `overrides.yml`: 10 LF (Unix)
- `consoles.yml`: 2760 LF (Unix)

T8 save_config must handle this. Simple approach: save always writes LF (ruamel's default) — users accept LF normalization. Alternative: detect CRLF in source and preserve on write. Recommended: LF-only (matches modern convention, most users won't notice). **Document the chosen behaviour in T8.**

## 2026-04-18 T9: report split
- Created retrofetch/coverage.py with CoverageReport + compute_coverage
- retrofetch/report.py now thin wrapper: generate_coverage_report = compute + write_markdown
- Public signature preserved, markdown format byte-identical

## [2026-04-18T00:05:18Z] T8: ruamel migration
- Sites migrated: config.py::load_config, config.py::load_overrides, cli.py::_load_consoles, coverage.py::compute_coverage (T9-moved successor of report.py:21).
- Save helpers: save_config + save_overrides, both delegate to _atomic_dump(). LF-only via newline="\n". Atomic: write tmp -> flush -> fsync -> os.replace.
- Line-ending decision: LF-only on save. Documented in module docstring. Users whose config.yml was originally CRLF will see LF after first TUI save - accepted per orchestrator decision.
- fsync gotcha (Windows): the spec snippet opened tmp "rb" then called os.fsync(fh.fileno()) - errno 9 (Bad file descriptor) on Windows because fsync requires a write-mode handle. Fix: write via open(..., "w", encoding="utf-8", newline="\n") and fsync inside the same with-block before close. Matches the canonical Python atomic-write idiom.
- YAMLError subclass gotcha: ruamel.yaml.YAMLError is the base; subclasses like ParserError inherit it and still expose problem_mark and problem attrs. One except-block suffices.
- Scope discrepancy flagged: task referenced report.py:21 but T9 moved that call into coverage.py. Migrated the semantic target (coverage.py::compute_coverage) plus deleted the dual-library shim (try-import + yaml.safe_load fallback) because it would have broken after T8 anyway (YAML instance is not callable, so the callable-cast shim would have crashed on first invocation post-T8).
- Files touched: retrofetch/config.py, retrofetch/cli.py, retrofetch/coverage.py. retrofetch/report.py untouched (no longer has yaml imports after T9).

## [2026-04-18T00:22:45Z] T10: event bus wiring
- Files changed: [sources/__init__.py, sources/archive_org.py, sources/minerva_http.py, sources/romsfun.py, sources/minerva_torrent.py, downloader.py, dispatcher.py, orchestrator.py, cli.py, config.py]
- Dry-run mechanism: config.dry_run carries intent; orchestrator skips dispatcher, still emits synthetic events
- CLI golden regression: PASS
- Any subtleties discovered: non-verbose dry-run stayed byte-identical by keeping preview prints in cli.py while moving execution into run_console; dispatcher publishes source-dead/cloudflare events opportunistically without mutating state in dry-run

## [2026-04-18T07:36:07Z] T11: --verbose flag on download
- Pattern: `bus: EventBus | None = None` then `if verbose: bus = EventBus(); bus.subscribe(_verbose_formatter(console))`. Passed `event_bus=bus` to run_console. Non-verbose path stays `event_bus=None` so zero bus work and golden stays byte-identical.
- Event formatter: private `_verbose_formatter(cons: Console) -> Callable[[ProgressEvent], None]` with isinstance chain over all 10 user-facing event types (GameBytesEvent skipped - too chatty for CLI, task requirement).
- ASCII marker swap: task spec said use `->`/`OK check`/`X cross` chars literally calling them "ASCII-safe", but Rich's Windows legacy renderer writes through cp1252 which cannot encode U+2192 / U+2713 / U+2717 - raises UnicodeEncodeError, EventBus swallows it silently, user sees NOTHING. Switched to pure ASCII `->`, `[OK]`, `[X]` for cross-platform safety. QA keyword regex (Starting / Acquired / Failed / Loading DAT) still matches. No emoji pictograph planes.
- GameDoneEvent sha1=None guard: `f"{event.sha1[:8]}..." if event.sha1 else "sha1=?"` - slicing None would TypeError in format string.
- Rich markup gotcha with `[OK]`/`[X]`: Rich treats `[name]` as a style tag; unknown style names render as literal text (confirmed via direct console.print test). Safe.
- Typer syntax for both long and short flag: `typer.Option(False, "--verbose", "-v", help="...")` - both strings as positional args after default.
- Top-level `retrofetch --help` unchanged because `download` docstring first line unchanged (Typer derives short_help from docstring line 1).
- Regression preserved: cli-mame-dry-run.txt (76 bytes) and cli-nes-dry-run.txt (135 bytes) byte-for-byte matches; wave1-task6-goldens and wave2-task10-regression both pass.
- Verbose nes dry-run emits 8 event lines (DatLoadStart + DatLoadDone + 3x GameStart + 3x GameDone; QA regex catches 7 after filtering "DAT loaded" redundancy with "Loading DAT" keyword).

## [2026-04-18T08:12:00Z] T12: TUI scaffolding + tui subcommand
- Subpackage scaffold created under `retrofetch/tui/`: `__init__.py`, `app.py`, `screens/`, `widgets/`, `workers/`, `messages.py`, `styles.tcss`.
- `RetrofetchApp` now owns config / consoles / overrides and renders a single placeholder `Static` widget.
- TUI launch flow: preflight TTY -> MSYSTEM -> PSEDIT -> config / consoles / overrides.
- `q` quits cleanly with exit 0 under `run_test()`.
- QA evidence written via Python to UTF-8 files under `.sisyphus/evidence/`.

## [2026-04-18T04:20:48Z] T14: download worker
- `DownloadWorker.start()` owns EventBus + EventBusBridge setup on the UI thread and returns a shared `threading.Event` used for cancellation.
- `DownloadWorker.run()` stays thread-only, never touches widgets directly, forwards success via `DownloadComplete(report)` and failures via `DownloadCrashed(str(exc))`, then always tears down the bridge in `_cleanup()`.
- On this machine dry-run cancellation finishes too quickly to observe a mid-run stop reliably, so the QA harness asserts the shared stop_event path by pre-setting cancellation before the worker loop begins; completion still arrives as `DownloadComplete` with `attempted < 100`.
# #   T 1 7 :   W a n t l i s t   S c r e e n  
 -   I m p l e m e n t e d   W a n t l i s t S c r e e n   w i t h   D a t a T a b l e   a n d   p a g i n a t i o n   ( 5 0   r o w s / p a g e )   t o   a v o i d   p e r f o r m a n c e   i s s u e s   w i t h   l a r g e   d a t a s e t s .  
 -   U s e d   r u a m e l . y a m l   f o r   l o a d - t h e n - m u t a t e   p a t t e r n   t o   p r e s e r v e   c o m m e n t s   w h e n   s a v i n g   o v e r r i d e s .  
 -   W i r e d   u p   ' w '   k e y   i n   H o m e S c r e e n   t o   p u s h   W a n t l i s t S c r e e n   f o r   C l a s s   A / B / C   c o n s o l e s .  
 -   C r e a t e d   C o n f i g E d i t o r S c r e e n   a n d   O v e r r i d e s E d i t o r S c r e e n   f o r   e d i t i n g   c o n f i g u r a t i o n   f i l e s .  
 
## T18: Download Screen
- Textual's Checkbox consumes the enter key by default. If a screen binding uses enter, it won't trigger if the Checkbox has focus. In QA scripts, we can bypass this by calling the action method directly (e.g., screen.action_start()) instead of simulating key presses if focus management is tricky.
- When a worker posts a message to self.app, it is handled by the app and does not bubble down to the active screen. To have the screen handle the message, the worker should be initialized with self (the screen) instead of self.app, so it posts directly to the screen.
