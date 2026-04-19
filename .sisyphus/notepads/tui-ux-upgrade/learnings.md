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


## [2026-04-18 session] U4 findings (recorded by orchestrator; subagent stalled mid-task)

- The visual-engineering subagent stalled mid-task and corrupted `retrofetch/cli.py` (replaced `download` command body with TUI launch code, lost the `tui` command entirely, duplicated `_try_load_config`). Orchestrator reverted cli.py and applied the surgical edits directly.
- Clean artifacts the subagent DID produce correctly: `retrofetch/tui/screens/setup.py`, `retrofetch/tui/app.py` (first_run flag + on_mount branch + _on_setup_done callback), the three QA scripts under `.sisyphus/qa/wave5-task4-*.py`.
- Textual API gotchas discovered (future subagents beware):
  - `Label.renderable` does NOT exist in this Textual version. Use `str(label.render())` when reading label text.
  - `App[int].exit(2)` sets `app.return_value = 2` (the ReturnType result), NOT `app.return_code` (OS exit code). Tests on cancel path must assert `app.return_value == 2`. `cli.py` then propagates it via `typer.Exit(return_code if return_code is not None else 0)`.
  - `App.run_test()` teardown: inside a validation-error test, call `app.exit(0)` before exiting the context so the pilot cleans up without hanging.
- `.sisyphus/` is in `.git/info/exclude` (local excludes). Any commit including QA scripts / evidence under `.sisyphus/` MUST use `git add -f` explicitly. Plain `git add` silently skips them with a warning.
- For future Wave 3/4/5 delegations: ALWAYS include the "git add -f for .sisyphus paths" instruction explicitly in the prompt. Recommend subagents `git diff --staged --stat` before committing to verify artifacts actually made it in.
- `RetrofetchApp.on_mount` now branches on `self._first_run`. Home-screen callers unchanged (default `first_run=False`).
- `cli.py::tui` flow (post-U4): consoles.yml + overrides load first, then `_try_load_config` decides wizard vs direct HomeScreen. On cancel (`return_value == 2`), CLI prints "Setup cancelled..." and exits 2. Cleanroom TTY-guard still exits 2 before wizard logic when stdout is not a TTY (wave3-task12 regression still passes).


## [2026-04-18 session] U5 findings (orchestrator implemented directly)

- CRITICAL Textual gotcha: Static widgets parse Rich markup by default. Any text containing `[x]`/`[w]`/`[d]` etc. will be interpreted as markup style tags and stripped. Mitigation: wrap body text in `rich.text.Text(...)` before passing to `Static.update()`. That bypasses markup entirely.
- Do NOT override a method called `_render` on a Widget subclass — `Widget._render()` is a built-in zero-arg method called by layout. My first draft used `_render(body)` and Textual blew up with a TypeError during layout. Renamed to `_set_body(body)` as the internal helper.
- Static exposes the last-set renderable via `self.renderable`? NO — on this Textual version, Static does NOT expose a `renderable` attribute (the attribute returns None). Use `str(widget.render())` in tests, or keep a module-local cache. For the U5 QA I used `getattr(widget, 'renderable', None)` with fallback to `widget.render()`.
- Action hints string `[w] wantlist  [d] download  [s] state  [C] coverage  [?] help  [q] quit` is always rendered at the bottom of the panel across ALL four modes. Centralize in module constant `_HINTS`.
- State snapshot display keys matched per plan/U6 spec: `acquired`, `failed`, `pending` (state.py also defines `unverified` but plan only surfaces the three). Widget accepts the full dict and shows the three plan-specified counts.
- Truncation beyond 20 titles shows `... (N more)` marker line.

## 2026-04-19 19:45:17 tui-retry-and-pagesize-fix
- DataTable.add_row accepts rich.text.Text cells, which bypass Rich markup parsing for bracketed labels like [x] and [ ].
- Same escape pattern as Static.update(Text(...)).
