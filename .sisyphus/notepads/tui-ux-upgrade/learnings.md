# tui-ux-upgrade — Learnings (conventions & patterns)

## Plan-level constraints (copy into every delegation)

### Must Have
- Atomic writes for cache JSON: tmp + fsync + os.replace (mirror `retrofetch/state.py::save_state`)
- Cache TTL = 24 hours, module-level constant `DEFAULT_TTL_HOURS = 24` (no new Config field)
- Cache dir honors `config.cache_dir` (relative paths resolved vs cwd by caller)
- Cache files: one per console shortname, JSON, `ensure_ascii=False`, `indent=2`
- SetupScreen writes new config.yml via `save_config(ruamel round-trip from config.yml.example)` — preserves comments
- All `@work` invocations include explicit `group=` (Metis K.6)
- Failures logged via existing `logging_setup` pipeline

### Must NOT Have (FORBIDDEN — every delegate prompt MUST include these)
- NO mouse handlers
- NO emojis, NO Rich emoji shortcodes (Metis K.10) — plain ASCII only: `[OK] [X] [!] [R]`
- NO network calls from UI thread — every fetch via `@work`
- NO `asyncio.to_thread` inside Textual workers
- NO `signal.signal` anywhere under `retrofetch/tui/`
- NO new exception types (stick to: `SourceUnavailable`, `VerificationFailed`, `ConfigError`)
- NO new exit codes (stick to: 0, 1, 2, 130)
- NO changes to CLI non-verbose stdout — goldens must be byte-identical
- NO pre-fetch of all 178 consoles — only the highlighted one
- NO DAT download in the wizard (keep `retrofetch init` semantics)
- NO auto-detection of Steam/emulator directories
- NO modifications to `retrofetch/events.py` (add Textual Messages only)
- NO additions to `Config` pydantic model (keep YAML schema unchanged)
- NO `@work(exclusive=True)` without `group=` (ALWAYS include group)

## Commit discipline
- One atomic commit per task, Conventional Commits format.
- NO attribution trailers (no "Co-authored-by" / "Generated-by" / etc.) — repo policy.
- Commit only after verification passes.

## QA / evidence rules
- Evidence path: `.sisyphus/evidence/ux-task-{N}-{slug}.txt`
- Evidence written via Python `Path.write_text(..., encoding="utf-8")` — NEVER PowerShell tee.
- QA scripts live under `.sisyphus/qa/wave5-task{N}-{slug}.py`
- Run via `.\.venv\Scripts\python.exe <script>` directly, or via existing dispatcher scripts.
- Pilot harness: `Textual.run_test` async pilot, monkey-patch `ranker.get_wantlist` where needed.

## @work discipline
- `thread=True` for blocking/sync work (network, sleeping)
- `exclusive=True, group="<uniq>"` to prevent overlap per-screen
- Worker body MUST NOT mutate UI directly → use `self.post_message(...)`
- Groups in use (DO NOT collide):
  - `preview` (Home highlight debounced fetch)
  - `wantlist-load` (WantlistScreen mount)
  - `download-load` (DownloadScreen mount)
  - `coverage` (existing, CoverageScreen)

## Messages to be added (U2)
- `WantlistReady(console: str, titles: list[str], from_cache: bool)`
- `WantlistFailed(console: str, reason: str)`
- `SetupComplete(config_path: Path)`

Files:
- `retrofetch/tui/messages.py` — APPEND ONLY. Existing 13 Messages + EventBusBridge + wire_event_bus must stay intact.

## U2 implementation note
- `retrofetch/tui/messages.py` now imports `Path` and appends `WantlistReady`, `WantlistFailed`, and `SetupComplete` after `CoverageReady` without touching the bridge mapping.

## Ordering / critical path
- U1 (cache) + U2 (messages) + U3 (QA smoke) → Wave 1 parallel
- U4 (SetupScreen + cli wiring) → Wave 2 (needs U2)
- U5 (WantlistPreview widget) + U6 (Home changes) → Wave 3 (U6 needs U1,U2,U4,U5)
- U7 (wantlist.py @work) + U8 (download.py @work) → Wave 4 parallel (need U1,U2)
- U9 (consolidated QA + regression) → Wave 5 (needs U1-U8)
- F1-F4 → Final wave (parallel reviewers)

- 2026-04-18: `run-qa.ps1 5 sample noop` resolved to `wave5-sample-noop.py`; dispatcher returned 0 and printed `wave5 sample: OK`.

## [2026-04-18T06:28:31.618458+00:00] Task U1
- Wantlist cache files should mirror config atomic writes: tmp + fsync + os.replace.
- QA scripts under .sisyphus need runtime importlib loading to keep Pyright clean while importing repo modules from an ignored directory.
