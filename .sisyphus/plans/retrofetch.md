# retrofetch - Automated ROM Collection Filler

## TL;DR

> **Quick Summary**: Build a Python 3.12 CLI (`retrofetch`) that automatically fills 178 pre-existing console folders at `D:\Projects\retrofetch\ROMs\` with top 50-100 IGDB-rated games per console, pulling from Archive.org + Minerva Archive (HTTP + torrent) + cloudscraper-bypassed scraping sites, with DAT-based verification, auto-extraction, and resume/progress tracking.
>
> **Deliverables**:
> - `retrofetch/` Python package with `download`, `verify`, `init`, `report` subcommands
> - `consoles.yml` - authoritative 178-console classification artifact (Class A-F)
> - `config.yml` + `overrides.yml` + `.env.example` schemas for user configuration
> - Source adapters: Archive.org, Minerva HTTP, Minerva Torrent, romsfun (CF), romsretro (CF)
> - DAT parser + hash verifier (No-Intro + Redump Logiqx XML)
> - Rich TUI progress + markdown coverage report
> - Per-console JSON state for cross-session resume
>
> **Estimated Effort**: Large (~18 implementation tasks across 3 waves + 4 final reviews)
> **Parallel Execution**: YES - 3 waves with 5-6 concurrent tasks each
> **Critical Path**: T1 (bootstrap) → T3 (config) → T7 (DAT parser) → T10 (download orch) → T12 (CLI) → T16 (dispatcher) → F1-F4

---

## Context

### Original Request

User has 178 pre-created console folders at `D:\Projects\retrofetch\ROMs\` (RetroBat/ES-DE naming convention). They want to automate ROM downloading across all consoles because "manually takes ages". They prefer quantity to "play blindly like first experience." Sources mentioned: Vimm's Lair, romsfun, romsretro, r-roms. Scraping allowed. Windows environment.

### Interview Summary

**Key Decisions**:
- **Scale**: Top 50-100 games per console (curated, not complete sets)
- **Tech Stack**: Python
- **Console Coverage**: All 178 folders attempted (with classification-based skips)
- **Curation**: Hybrid - IGDB primary + hand-curated overrides YAML
- **Sources**: User confirmed Myrient is dead (shut down March 31, 2026). Full torrent + HTTP dual support; scrape romsfun/romsretro as fallback
- **Processing**: Auto-extract archives + delete originals
- **Verification**: DAT-based (No-Intro + Redump), rename to canonical
- **Test Strategy**: No unit tests - Agent-executed QA scenarios only

### Research Findings

**CRITICAL**: Myrient (390TB gold standard) shut down March 31, 2026.

**Source Landscape (post-Myrient)**:
- **Minerva Archive** (minerva-archive.org) - 385TB torrent-based successor, same folder structure, web UI + API
- **Archive.org** - Use `internetarchive` Python library (2K stars, active), stable fallback
- **romsfun/romsretro** - Cloudflare-protected, expiring tokens, use `cloudscraper` v3.8.4 (has AI CAPTCHA solving)
- **Vimm's Lair** - EXCLUDED (owner discourages bulk, incomplete sets)
- **r-roms.github.io** - Dead links post-Myrient, only useful for naming reference
- **RGSX** (318 stars, Python) - Closest existing tool; architectural reference only

**Stack Confirmed**:
- Python 3.12 (libtorrent-python wheel availability confirmed for 3.11/3.12; NOT pinned 3.13+)
- `httpx` (async, HTTP/2, Range resume)
- `selectolax` (fast HTML parsing)
- `cloudscraper` (Cloudflare bypass primary)
- `curl-cffi` (TLS impersonation fallback)
- `internetarchive` (Archive.org official lib)
- `libtorrent` (PyPI, arvidn builds) for Minerva torrents
- `archivey` (unified zip/7z/rar/tar extraction)
- `rich` + `typer` (TUI/CLI)
- `uv` as package manager

### Metis Review

Metis identified **18 critical gaps and guardrails**. Key insights incorporated:

**STRUCTURAL INSIGHT**: Only ~73 of 178 folders fit the "top 100 + DAT" model. The rest require different handling or must be hard-skipped.

**Console Classification** (authoritative via `consoles.yml`):
- **Class A**: Cartridge consoles (~55) - No-Intro DAT, small files, perfect fit
- **Class B**: Disc consoles (~18) - Redump DAT, large files, CHD candidates
- **Class C**: Modern consoles (~5) - `switch`, `ps3`, `psvita`, `wiiu`, `n3ds` - best-effort, lower targets
- **Class D**: Arcade (~15) - `arcade`, `mame`, `fbneo`, `cps*`, `naomi*`, `model*`, `atomiswave`, etc. - HARD SKIP (romset versioning is different project)
- **Class E**: Home computers / engines / ports (~35) - `amiga*`, `dos`, `msx*`, `zxspectrum`, `c64`, `macintosh`, `windows*`, `scummvm`, `doom`, `quake`, `openbor`, `easyrpg`, `ports`, `steam`, `epic`, `emulators` - HARD SKIP (not applicable to ROM model)
- **Class F**: Homebrew/fantasy/mobile (~10) - `pico8`, `tic80`, `wasm4`, `arduboy`, `androidapps`, `ngage`, `palm`, `symbian`, `j2me`, `flash` - HARD SKIP (different ecosystems)

Regional duplicates (`snesna`, `saturnjp`, `megadrivejp`, etc.) alias to parent console with region filter override.

**Phased Execution** (from Metis):
- Phase 1 (Wave 1): Skeleton + Classification (no network)
- Phase 2 (Wave 2): Single-source E2E (Archive.org + virtualboy)
- Phase 3 (Wave 3): Multi-source + scale

---

## Work Objectives

### Core Objective
Deliver a working Python CLI tool that reliably downloads, verifies, extracts, and organizes retro ROMs into pre-existing console folders with minimal user intervention after initial configuration.

### Concrete Deliverables
- `pyproject.toml` with locked dependency versions and Python >=3.11,<3.13 pin
- `retrofetch/` package (flat module layout - no clean-architecture layers)
  - `retrofetch/__init__.py` (version string)
  - `retrofetch/cli.py` (typer entry with subcommands)
  - `retrofetch/config.py` (YAML loading + schema validation)
  - `retrofetch/state.py` (per-console JSON state read/write)
  - `retrofetch/dat.py` (Logiqx XML parser + hash verifier)
  - `retrofetch/igdb.py` (OAuth + wantlist generation)
  - `retrofetch/downloader.py` (HTTP download with resume, .part files)
  - `retrofetch/extractor.py` (archivey wrapper + cleanup)
  - `retrofetch/organizer.py` (filename sanitize, long-path, collision)
  - `retrofetch/report.py` (coverage markdown generator)
  - `retrofetch/sources/archive_org.py`
  - `retrofetch/sources/minerva_http.py`
  - `retrofetch/sources/minerva_torrent.py`
  - `retrofetch/sources/romsfun.py`
  - `retrofetch/sources/romsretro.py`
  - `retrofetch/dispatcher.py` (fallback chain logic)
- `consoles.yml` - 178-entry classification artifact (class, sources, DAT platform, IGDB platform ID, extensions, region priority)
- `config.yml.example` - user config template
- `overrides.yml.example` - hand-curated override template
- `.env.example` - IGDB_CLIENT_ID + IGDB_CLIENT_SECRET template
- `dats/` - bundled DAT snapshot (No-Intro + Redump as of plan date)
- `README.md` - install, IGDB setup, usage, troubleshooting
- Coverage report format: `coverage.md` at project root

### Definition of Done
- [ ] `uv pip install -e .` succeeds on Windows Python 3.12 venv
- [ ] `retrofetch --version` returns `retrofetch X.Y.Z` with exit code 0
- [ ] `retrofetch init` creates all config files and 178-entry consoles.yml
- [ ] All 18 QA scenarios (QA-1 through QA-18) pass with evidence files
- [ ] `retrofetch download --console virtualboy --limit 3` completes end-to-end producing >=1 acquired ROM
- [ ] Ctrl+C mid-download preserves state and doesn't corrupt files
- [ ] Class D/E/F consoles are logged-skipped, not errored

### Must Have
- Python pinned >=3.11,<3.13 in pyproject.toml (libtorrent wheel availability)
- `consoles.yml` with all 178 folders classified A/B/C/D/E/F
- Per-console JSON state file at `ROMs/<console>/.retrofetch-state.json`
- Multi-disc games counted as ONE unit toward top-N limit
- Default region priority: `["USA", "World", "Europe", "Japan"]`
- Default exclusions: beta, proto, demo, sample, kiosk, trade-demo
- Pre-flight disk-space check (fail-closed if estimate > free)
- DAT verification with `unverified` status after N=3 failures across M=2+ sources (no infinite retry)
- Ctrl+C → save state, close torrents cleanly, `.part` files preserved for resume
- Windows filename sanitization: replace `<>:"/\|?*` → `-`, truncate to 240 chars
- Windows long-path awareness (fail loudly if not enabled)
- IGDB credentials via env vars `IGDB_CLIENT_ID` / `IGDB_CLIENT_SECRET`
- IGDB response cache at `.cache/igdb/<platform_id>.json` (never auto-expire)
- Log file at `retrofetch.log`, rolled at >10MB, human-readable
- Flat single-level `rich` progress (no nested 4-level bars)
- Exit codes: 0=success, 2=config error, 130=SIGINT, 1=other

### Must NOT Have (Guardrails)

**Scope Exclusions**:
- NO GUI, web UI, HTTP API, or daemon mode
- NO CHD/zstd conversion (even tempting for disc systems)
- NO gamelist.xml, screenscraper output, box-art, videos, or ES-DE metadata
- NO BIOS discovery/download (existing `BIOS/` folder is out of scope - don't touch)
- NO patch application (IPS/BPS/XDelta), ROM hacks, or translations
- NO MAME/FBNeo arcade romset version management (Class D hard-skipped)
- NO home-computer/engine/mobile downloads (Class E/F hard-skipped)
- NO save-state or savegame handling
- NO Windows service / scheduled task integration
- NO RomM / HyperSpin / LaunchBox integration
- NO multi-user / remote storage
- NO Vimm's Lair adapter (explicitly excluded)
- NO auto-update, telemetry, crash reporting
- NO vendored binaries (unrar, 7z, chdman - document install requirement)
- NO modifications to files outside `D:\Projects\retrofetch\`

**Code Quality Guardrails (AI-Slop Prevention)**:
- NO `AbstractSourceBase(ABC)` hierarchy - concrete classes + one optional `Protocol`
- NO Pydantic for internal data structures (allowed only for user-config validation at load)
- NO async beyond httpx HTTP concurrency (libtorrent/archivey/DAT parsing stay sync)
- NO clean-architecture layers (`domain/application/infrastructure/adapters/ports`) - flat `retrofetch/` module
- NO exception hierarchy explosion - max 3 concrete exceptions: `SourceUnavailable`, `VerificationFailed`, `ConfigError`
- NO typer subcommand sprawl beyond: `download`, `verify`, `init`, `report`
- NO nested 4-level progress bars - flat per-console + global counter
- NO YAML+TOML+JSON+env config format variety - YAML only
- NO custom retry/backoff/circuit-breaker machinery - `tenacity` OR inline 15-line retry
- NO logging ceremony (custom formatters, JSON logs, trace IDs) - `logging.basicConfig` + one file handler
- NO IGDB cache with TTL/invalidation - dump to JSON, manual delete to refresh
- NO separate `NoIntroDATParser` and `RedumpDATParser` classes - both use Logiqx, one parser
- NO SQLite state with 12 tables - one JSON file per console
- NO unit tests, pytest fixtures, conftest.py, mocking frameworks
- NO `mypy --strict` with ignore comments - pragmatic typing only
- NO unused source adapters "for future" (GameFAQs, MobyGames, Vimm's)
- NO defensive over-validation after trusted parse points
- NO ROM header normalization (SMC/iNES) - document limitation, mark `unverified`
- NO source-site credential management beyond IGDB

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: NO (fresh Python project)
- **Automated tests**: NONE (Agent-executed QA scenarios are the ONLY verification)
- **Framework**: N/A
- **Why**: Personal tool; Agent QA scenarios verify actual behavior end-to-end, which is more valuable than unit test coverage.

### QA Policy
Every task MUST include agent-executed QA scenarios matching the 18 QA specifications from Metis review. Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **CLI**: Use `interactive_bash` (tmux) - Run `retrofetch` commands, assert stdout patterns, check exit codes
- **Filesystem**: Use `Bash` (PowerShell) - Verify file existence, path structure, content
- **JSON/YAML**: Use `Bash` (python -c inline) - Parse and assert structure/values
- **Network mocks**: Use Python http.server or recorded fixtures in `.sisyphus/fixtures/`
- **Evidence capture**: Command output, file listings, state JSON dumps

---

## Execution Strategy

### Parallel Execution Waves

> 3 phases, ~6 tasks per wave, max parallelism within each wave.
> Each wave MUST fully complete + pass its QA scenarios before the next begins.

```
Wave 1 - FOUNDATION (no network, pure offline) — 6 parallel tasks:
├── T1: Project bootstrap (pyproject.toml, structure, .gitignore, README skeleton)
├── T2: consoles.yml artifact (178 entries, class A-F, source paths, IGDB IDs)
├── T3: Config schemas + YAML loader + validator (config.yml, overrides.yml, .env)
├── T4: State persistence + logging setup + rich console wrapper
├── T5: Filename sanitization + Windows long-path utilities
└── T6: DAT acquisition + bundled DAT snapshot (fetch-on-first-run or repo bundle)

Wave 2 - SINGLE-SOURCE E2E (Archive.org + virtualboy only) — 6 tasks:
├── T7: DAT parser (Logiqx XML) + hash verifier (depends: T3, T5)
├── T8: IGDB OAuth + wantlist generator + override merge (depends: T3)
├── T9: Archive.org source adapter (depends: T3)
├── T10: Download orchestrator (resume, .part, archive extraction) (depends: T4, T5, T7)
├── T11: Organizer + coverage report generator (depends: T4, T5)
└── T12: CLI entry (download/verify/init/report subcommands) (depends: T3, T4, T8, T9, T10, T11)

Wave 3 - MULTI-SOURCE + SCALE — 6 tasks:
├── T13: Minerva Archive HTTP adapter (depends: T9 pattern)
├── T14: Minerva Archive torrent adapter (libtorrent-python) (depends: T10)
├── T15: Cloudscraper base + romsfun + romsretro adapters (depends: T9 pattern)
├── T16: Source dispatcher (fallback chain per console class) (depends: T13, T14, T15)
├── T17: Concurrency + disk preflight + multi-disc handling (depends: T10, T16)
└── T18: Signal handler + scraper graceful degradation (depends: T10, T15)

Final Verification Wave (after all implementation) — 4 parallel reviews:
├── F1: Plan compliance audit (oracle)
├── F2: Code quality review (unspecified-high)
├── F3: Real manual QA - run 18 QA scenarios (unspecified-high)
└── F4: Scope fidelity check (deep)
→ Present results → Get explicit user okay

Critical Path: T1 → T3 → T7 → T10 → T12 → T16 → T17 → F1-F4
Parallel Speedup: ~55% vs sequential
Max Concurrent: 6 per wave
```

### Dependency Matrix

- **T1** (bootstrap): deps=none; blocks=T2,T3,T4,T5,T6
- **T2** (consoles.yml): deps=T1; blocks=T8,T9,T12
- **T3** (config): deps=T1; blocks=T7,T8,T9,T12
- **T4** (state+logging): deps=T1; blocks=T10,T11,T12
- **T5** (sanitization): deps=T1; blocks=T7,T10,T11
- **T6** (DAT bundle): deps=T1; blocks=T7
- **T7** (DAT parser): deps=T3,T5,T6; blocks=T10
- **T8** (IGDB): deps=T2,T3; blocks=T12
- **T9** (Archive.org): deps=T2,T3; blocks=T10,T13,T15
- **T10** (downloader): deps=T4,T5,T7; blocks=T12,T14,T17,T18
- **T11** (organizer+report): deps=T4,T5; blocks=T12
- **T12** (CLI): deps=T3,T4,T8,T9,T10,T11; blocks=Wave3
- **T13** (Minerva HTTP): deps=T9-pattern; blocks=T16
- **T14** (Minerva torrent): deps=T10; blocks=T16
- **T15** (CF scrapers): deps=T9-pattern; blocks=T16,T18
- **T16** (dispatcher): deps=T13,T14,T15; blocks=T17
- **T17** (concurrency+preflight): deps=T10,T16; blocks=F1-F4
- **T18** (signal+degradation): deps=T10,T15; blocks=F1-F4

### Agent Dispatch Summary

- **Wave 1 (6 tasks)**: T1,T3,T4,T5,T6 → `quick`; T2 → `unspecified-high` (large YAML + classification research)
- **Wave 2 (6 tasks)**: T7,T10 → `deep` (parsing + orchestration); T8 → `deep` (OAuth complexity); T9,T11,T12 → `unspecified-high`
- **Wave 3 (6 tasks)**: T13,T14,T15,T16,T17 → `deep` (network + concurrency); T18 → `unspecified-high`
- **Final (4 reviews)**: F1 → `oracle`; F2,F3 → `unspecified-high`; F4 → `deep`

---

## TODOs

- [x] 1. Project Bootstrap (pyproject.toml + package scaffold)

  **What to do**:
  - Create `pyproject.toml` using hatchling or setuptools backend
  - Pin Python: `requires-python = ">=3.11,<3.13"` (libtorrent wheel constraint)
  - Dependencies: `httpx[http2]>=0.27`, `selectolax>=0.3`, `cloudscraper>=3.0`, `curl-cffi>=0.7`, `internetarchive>=5.0`, `libtorrent>=2.0`, `archivey>=0.1`, `rich>=13.0`, `typer>=0.12`, `PyYAML>=6.0`, `tenacity>=8.2`
  - Version in `retrofetch/__init__.py` as `__version__ = "0.1.0"`
  - Create module skeleton files (empty stubs): all files listed in "Concrete Deliverables"
  - `.gitignore`: `.venv/`, `__pycache__/`, `*.egg-info/`, `.cache/`, `*.log`, `ROMs/*/.retrofetch-state.json`, `dist/`, `build/`, `.env`
  - `README.md` skeleton: Overview, Install, IGDB Setup, Usage, Troubleshooting
  - `git init` + first commit

  **Must NOT do**:
  - Do NOT add pytest, mypy, ruff as runtime deps (agent QA only)
  - Do NOT create `domain/`, `application/`, `infrastructure/` directories
  - Do NOT use poetry or pipenv (use `uv` + pip-compatible pyproject)
  - Do NOT include Python 3.13 in requires-python range

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Pure scaffolding task, well-defined file list, no domain reasoning required
  - **Skills**: []
    - No specific skills needed; scaffold follows Python packaging standards

  **Parallelization**:
  - **Can Run In Parallel**: NO (foundation for everything)
  - **Parallel Group**: Wave 1 start
  - **Blocks**: T2, T3, T4, T5, T6
  - **Blocked By**: None

  **References**:

  **Pattern References**:
  - `https://packaging.python.org/en/latest/guides/writing-pyproject-toml/` - Official pyproject.toml spec

  **External References**:
  - `https://docs.astral.sh/uv/` - uv package manager docs
  - `https://hatch.pypa.io/latest/config/metadata/` - Hatchling config reference

  **WHY Each Reference Matters**:
  - uv docs: user prefers `uv` over pip for install speed; pyproject must be uv-compatible
  - PEP 621 pyproject: ensure metadata format is standard, not poetry-specific

  **Acceptance Criteria**:
  - [ ] `uv pip install -e .` completes with no errors on Windows Python 3.12
  - [ ] `python -c "import retrofetch; print(retrofetch.__version__)"` outputs `0.1.0`
  - [ ] All 15 module skeleton files exist as empty stubs
  - [ ] `git log` shows initial commit with conventional commit format
  - [ ] `.gitignore` prevents committing `.venv/` and `.cache/`

  **QA Scenarios** (MANDATORY):

  ```
  Scenario: Fresh install succeeds (happy path)
    Tool: Bash (PowerShell)
    Preconditions: Clean Python 3.12 venv active, cwd = D:\Projects\retrofetch
    Steps:
      1. Run: uv pip install -e .
      2. Run: retrofetch --version
      3. Run: python -c "import retrofetch; print(retrofetch.__version__)"
    Expected Result:
      - Install exits 0, no compile errors
      - `retrofetch --version` prints string matching regex ^retrofetch \d+\.\d+\.\d+$ and exits 0
      - Python import prints 0.1.0
    Failure Indicators: pip error, ModuleNotFoundError, version mismatch
    Evidence: .sisyphus/evidence/task-1-fresh-install.log

  Scenario: Python 3.13 rejection (negative path)
    Tool: Bash (PowerShell)
    Preconditions: Python 3.13 venv active
    Steps:
      1. Run: uv pip install -e .
    Expected Result: Install fails with message mentioning requires-python constraint
    Evidence: .sisyphus/evidence/task-1-py313-reject.log
  ```

  **Evidence to Capture**:
  - [ ] task-1-fresh-install.log (install + version verification)
  - [ ] task-1-py313-reject.log (constraint enforcement)

  **Commit**: YES
  - Message: `chore(init): scaffold retrofetch Python project with pyproject.toml and package layout`
  - Files: `pyproject.toml`, `retrofetch/__init__.py`, `retrofetch/*.py` (stubs), `.gitignore`, `README.md`
  - Pre-commit: `uv pip install -e . && retrofetch --version`

- [x] 2. Console Classification Artifact (consoles.yml - 178 entries)

  **What to do**:
  - Create `consoles.yml` at repo root with 178 entries, one per folder in `ROMs/`
  - Schema per entry:
    ```yaml
    - shortname: nes  # matches ROMs/ folder name
      display_name: Nintendo Entertainment System
      class: A  # A|B|C|D|E|F
      igdb_platform_id: 18  # null for skip classes
      dat_system: "Nintendo - Nintendo Entertainment System"  # null for skip
      archive_org_identifier: "no-intro_nintendo_entertainment_system"  # or null
      minerva_path: "No-Intro/Nintendo - Nintendo Entertainment System"
      romsfun_slug: "nes"  # or null
      romsretro_slug: "nes"  # or null
      extensions: [".nes"]
      cd_based: false
      region_alias_of: null  # "nes" for snesna alias cases
      region_filter: null  # ["NA"] for snesna
      skip_reason: null  # required for D/E/F: "arcade romset model - out of scope" etc.
    ```
  - Classify ALL 178 folders per Metis's breakdown (Class A-F)
  - Class D reasons: "Arcade romset-versioning model out of scope for v1"
  - Class E reasons: "Home computer / engine / port - ROM download model not applicable"
  - Class F reasons: "Fantasy/homebrew/mobile platform - different distribution ecosystem"
  - Regional duplicates (snesna, saturnjp, megadrivejp, sega32xjp, sega32xna, megacdjp, neogeocdjp) - use `region_alias_of` + `region_filter`
  - Use research output (see `.sisyphus/drafts/retrofetch.md`) for Myrient→shortname mapping
  - Validate YAML parses with no duplicates

  **Must NOT do**:
  - Do NOT include consoles not in the 178 folder list
  - Do NOT classify any obvious Class D/E/F as Class A-C "hoping it works"
  - Do NOT leave `skip_reason` empty for D/E/F entries

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Research-heavy; requires cross-referencing 178 consoles with No-Intro/Redump/IGDB naming + classifying each; substantial YAML authoring
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (depends only on T1 repo existing)
  - **Parallel Group**: Wave 1
  - **Blocks**: T8 (IGDB platform_id lookup), T9 (Archive.org identifier), T12 (CLI needs console list)
  - **Blocked By**: T1

  **References**:
  - `D:\Projects\retrofetch\ROMs\systems.txt` - 178-entry list of shortnames + display names (source of truth)
  - `.sisyphus/drafts/retrofetch.md` - Myrient→shortname + IGDB platform ID mapping from research
  - `https://www.igdb.com/api/v4/platforms` (via API) - IGDB platform IDs
  - `https://datomatic.no-intro.org/index.php?page=systems` - No-Intro system naming
  - `http://redump.org/downloads/` - Redump per-system dat packages

  **Acceptance Criteria**:
  - [ ] `consoles.yml` exists at repo root
  - [ ] Python parse: `len(yaml.safe_load(open('consoles.yml'))['consoles']) == 178`
  - [ ] Exactly one entry per shortname in ROMs/ directory listing
  - [ ] All Class D/E/F entries have non-null `skip_reason`
  - [ ] All Class A/B entries have non-null `igdb_platform_id` and `dat_system`
  - [ ] Regional dupes have `region_alias_of` pointing to existing entry

  **QA Scenarios** (MANDATORY):

  ```
  Scenario: Full 178-entry validation
    Tool: Bash (python -c)
    Preconditions: consoles.yml exists at repo root
    Steps:
      1. Run: python -c "import yaml; d=yaml.safe_load(open('consoles.yml')); cs=d['consoles']; from collections import Counter; kc=Counter(c['class'] for c in cs); print(f'total={len(cs)} classes={dict(kc)}')"
    Expected Result: output contains "total=178" and classes dict has keys A,B,C,D,E,F all non-zero
    Evidence: .sisyphus/evidence/task-2-classification.log

  Scenario: Skip-class completeness (failure detection)
    Tool: Bash (python -c)
    Steps:
      1. Run script that asserts every class-D/E/F entry has non-null skip_reason
    Expected Result: assertion passes
    Failure: prints shortnames with missing skip_reason + exit 1
    Evidence: .sisyphus/evidence/task-2-skip-reason.log

  Scenario: ROMs folder coverage check
    Tool: Bash (python -c)
    Steps:
      1. List ROMs/ directory entries (excluding systems.txt, .nomedia)
      2. Assert every one has matching consoles.yml entry
    Expected Result: zero unmatched folders
    Evidence: .sisyphus/evidence/task-2-folder-coverage.log
  ```

  **Commit**: YES
  - Message: `feat(consoles): add 178-console classification artifact with class A-F`
  - Files: `consoles.yml`
  - Pre-commit: yaml validation + 178-entry count

- [x] 3. Config Schemas + YAML Loader + Validator

  **What to do**:
  - `retrofetch/config.py`: loaders for `config.yml`, `overrides.yml`, `.env`
  - `config.yml` schema (validate at load):
    ```yaml
    roms_root: "D:/Projects/retrofetch/ROMs"
    cache_dir: ".cache"
    log_file: "retrofetch.log"
    default_limit: 75  # top-N per console
    region_priority: ["USA", "World", "Europe", "Japan"]
    exclude_keywords: ["(Beta)", "(Proto)", "(Demo)", "(Sample)", "(Kiosk)", "(Trade Demo)"]
    max_game_size_gb: null  # null=no cap
    max_concurrent_downloads: 3
    source_fallback_by_class:
      A: ["archive_org", "minerva_http", "minerva_torrent", "romsfun"]
      B: ["minerva_torrent", "minerva_http", "archive_org", "romsretro"]
      C: ["romsfun", "romsretro", "archive_org"]
    ```
  - `overrides.yml` schema (per-console):
    ```yaml
    consoles:
      nes:
        include: ["Chrono Trigger"]  # force-include beyond top-N
        exclude: ["E.T. the Extra-Terrestrial"]  # never download
        limit: 100  # override default_limit
        region_priority: ["Japan", "USA"]  # override global
    ```
  - `.env.example`:
    ```
    IGDB_CLIENT_ID=your_twitch_client_id
    IGDB_CLIENT_SECRET=your_twitch_client_secret
    ```
  - Use Pydantic v2 ONLY for load-time validation of these 3 files (allowed per guardrails)
  - Expose `load_config() -> Config`, `load_overrides() -> dict[str, ConsoleOverride]`, `load_env() -> IgdbCreds`
  - Graceful errors with file:line on YAML parse fail
  - Fail-closed on schema violation with clear field-level message

  **Must NOT do**:
  - Do NOT add TOML, JSON, CLI-override-config support - YAML only
  - Do NOT use Pydantic for internal data structures beyond these 3 config files
  - Do NOT add config merge precedence system (env > user > default) - just load user file or default
  - Do NOT add runtime config mutation

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Standard config loader with Pydantic validation; well-understood pattern
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: T7, T8, T9, T12
  - **Blocked By**: T1

  **References**:
  - `https://docs.pydantic.dev/latest/concepts/models/` - Pydantic v2 model usage
  - `https://pyyaml.org/wiki/PyYAMLDocumentation` - yaml.safe_load
  - `https://12factor.net/config` - env var config pattern

  **Acceptance Criteria**:
  - [ ] `retrofetch/config.py` exports `load_config`, `load_overrides`, `load_env`, `Config`, `ConsoleOverride`, `IgdbCreds` classes
  - [ ] `config.yml.example`, `overrides.yml.example`, `.env.example` exist at repo root
  - [ ] Loading valid config returns typed objects
  - [ ] Loading malformed YAML raises `ConfigError` with file path and line number
  - [ ] Missing required field raises `ConfigError` with field name

  **QA Scenarios** (MANDATORY):

  ```
  Scenario: Happy path config load
    Tool: Bash (python -c)
    Steps:
      1. Copy config.yml.example to config.yml
      2. Run: python -c "from retrofetch.config import load_config; c=load_config(); print(c.default_limit)"
    Expected: prints 75, exit 0
    Evidence: .sisyphus/evidence/task-3-config-load.log

  Scenario: Malformed YAML rejection
    Tool: Bash (python -c)
    Steps:
      1. Write invalid YAML to test_bad.yml (unclosed quote)
      2. Load via python script
    Expected: ConfigError raised with message mentioning file path + line
    Evidence: .sisyphus/evidence/task-3-config-malformed.log

  Scenario: Missing required field
    Tool: Bash (python -c)
    Steps:
      1. Write config.yml missing `roms_root`
      2. Load
    Expected: ConfigError mentions "roms_root" field
    Evidence: .sisyphus/evidence/task-3-config-missing-field.log
  ```

  **Commit**: YES
  - Message: `feat(config): add YAML config loader with schema validation`
  - Files: `retrofetch/config.py`, `config.yml.example`, `overrides.yml.example`, `.env.example`

- [x] 4. State Persistence + Logging + Rich Console

  **What to do**:
  - `retrofetch/state.py`:
    - Schema: per-console `ROMs/<console>/.retrofetch-state.json`:
      ```json
      {"version": 1, "console": "virtualboy", "last_run": "2026-04-17T...",
       "games": [{"title":"Mario Clash","status":"acquired","source":"archive_org",
                  "filename":"Mario Clash (USA).vb","sha1":"abc...","size_bytes":524288,
                  "attempts":[{"source":"archive_org","result":"success","ts":"..."}]}]}
      ```
    - Functions: `load_state(console: str) -> State`, `save_state(state: State) -> None`, `update_game(state, title, **fields) -> State`
    - Atomic write: write to `.tmp` + os.replace
    - Corruption recovery: on parse fail, move to `.corrupt.<ts>` and return empty state with warning log
  - `retrofetch/logging_setup.py`:
    - `setup_logging(log_file: Path, level: str) -> None` using `logging.basicConfig` + one `RotatingFileHandler` (maxBytes=10MB, backupCount=3)
    - Human-readable format: `%(asctime)s %(levelname)s %(name)s: %(message)s`
    - Rich console for user-facing output via `rich.console.Console()` global instance
  - `retrofetch/ui.py`:
    - Flat `Progress` with columns: BarColumn, TextColumn(console), TextColumn(game), DownloadColumn, TransferSpeedColumn
    - `progress_context()` context manager that yields Progress

  **Must NOT do**:
  - NO JSON-structured logs, trace IDs, or custom formatters
  - NO nested 4-level progress hierarchies
  - NO `rich.live.Live` shows with animated ASCII art
  - NO SQLite or any database for state - JSON per console only
  - NO state migration framework - version=1 hard-coded

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Standard stdlib usage, well-defined schemas
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: T10, T11, T12
  - **Blocked By**: T1

  **References**:
  - `https://docs.python.org/3/library/logging.handlers.html#logging.handlers.RotatingFileHandler` - rotating file log
  - `https://rich.readthedocs.io/en/stable/progress.html` - rich Progress API
  - `https://docs.python.org/3/library/os.html#os.replace` - atomic rename semantics

  **Acceptance Criteria**:
  - [ ] State JSON round-trip: load → modify → save → load returns equivalent data
  - [ ] Atomic write: kill process mid-save → state file never corrupted (either old or new, not partial)
  - [ ] Log rotation: write >10MB → rotates to `.1`, `.2`, `.3`
  - [ ] Progress renders without crashes in Windows Terminal

  **QA Scenarios** (MANDATORY):

  ```
  Scenario: State round-trip
    Tool: Bash (python -c)
    Steps:
      1. Call save_state with test data to temp dir
      2. Call load_state, assert equality
    Expected: data matches
    Evidence: .sisyphus/evidence/task-4-state-roundtrip.log

  Scenario: Corrupt state recovery
    Tool: Bash (python -c)
    Steps:
      1. Write invalid JSON to .retrofetch-state.json
      2. Call load_state
    Expected: returns empty State, moves corrupt file to .corrupt.<ts>, logs warning
    Evidence: .sisyphus/evidence/task-4-state-corrupt.log

  Scenario: Log rotation
    Tool: Bash (python -c)
    Steps:
      1. Write >12MB of log messages
      2. Verify .log + .log.1 exist, .log.1 is the older content
    Expected: rotation happens
    Evidence: .sisyphus/evidence/task-4-log-rotation.log
  ```

  **Commit**: YES (grouped with T5, T6)
  - Message: `feat(core): state persistence, logging, rich console wrappers`
  - Files: `retrofetch/state.py`, `retrofetch/logging_setup.py`, `retrofetch/ui.py`

- [x] 5. Filename Sanitization + Windows Long-Path Utilities

  **What to do**:
  - `retrofetch/sanitize.py`:
    - `sanitize_filename(name: str) -> str`:
      - Replace each of `<>:"/\|?*` → `-`
      - Strip trailing dots and spaces (Windows silently strips these)
      - Collapse runs of `-` → single `-`
      - Truncate to 240 chars (preserve extension)
      - Reject reserved names: `CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9` (prepend `_`)
    - `ensure_long_path_enabled() -> bool`: check Windows registry `HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled`, return True/False
    - `make_long_path(path: Path) -> Path`: prepend `\\?\` if path > 240 chars and running on Windows
    - `sanitize_dos_components(path_parts: list[str]) -> list[str]`: apply sanitize to each segment
  - Unit test replacements via embedded doctest strings (allowed in-place docs, but no pytest files)

  **Must NOT do**:
  - NO complex filesystem abstraction layer
  - NO attempt to fix illegal Unicode characters (keep them, they work on NTFS)
  - NO hard-coded replacements for other OS (Windows is target)

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Single file, pure function logic, no external deps
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: T7, T10, T11
  - **Blocked By**: T1

  **References**:
  - `https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file` - Windows naming rules
  - `https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation` - MAX_PATH + `\\?\`

  **Acceptance Criteria**:
  - [ ] `sanitize_filename("Phoenix Wright: Ace Attorney")` returns `"Phoenix Wright - Ace Attorney"`
  - [ ] `sanitize_filename("CON.nes")` returns `"_CON.nes"`
  - [ ] `sanitize_filename("a"*300 + ".zip")` length <= 240
  - [ ] `make_long_path(Path("a"*250))` on Windows returns `\\?\...` prefixed path
  - [ ] Trailing dots/spaces removed: `sanitize_filename("foo...")` → `"foo"`

  **QA Scenarios** (MANDATORY):

  ```
  Scenario: Forbidden char substitution
    Tool: Bash (python -c)
    Steps:
      1. from retrofetch.sanitize import sanitize_filename
      2. assert sanitize_filename('Phoenix Wright: Ace Attorney') == 'Phoenix Wright - Ace Attorney'
    Expected: assertion passes
    Evidence: .sisyphus/evidence/task-5-sanitize-forbidden.log

  Scenario: Reserved name handling
    Tool: Bash (python -c)
    Steps:
      1. Test all reserved names get _ prefix
    Expected: all pass
    Evidence: .sisyphus/evidence/task-5-sanitize-reserved.log

  Scenario: Actual file creation with long path
    Tool: Bash (PowerShell)
    Steps:
      1. Create file at 260-char path via make_long_path helper
      2. Verify os.path.exists
    Expected: file exists (or graceful error if long-path not enabled)
    Evidence: .sisyphus/evidence/task-5-longpath-create.log
  ```

  **Commit**: YES (grouped with T4, T6)
  - Files: `retrofetch/sanitize.py`

- [x] 6. DAT Acquisition + Bundled Snapshot

  **What to do**:
  - `retrofetch/dat_fetch.py`:
    - `bootstrap_dats(dats_dir: Path) -> None`: one-time fetch of No-Intro + Redump DAT bundles
    - Strategy: download a pinned-date snapshot from a reliable mirror (Archive.org hosts No-Intro DAT collections)
    - URLs pinned in constant:
      - No-Intro bundle: `https://archive.org/download/no-intro_romsets/<pinned>.zip` (check live URL at plan-build time)
      - Redump bundle: `https://archive.org/download/redump_datfiles_<date>/<pinned>.zip`
    - Verify SHA256 of downloaded bundle against pinned hashes in constants
    - Extract into `dats/no-intro/<system>.dat` and `dats/redump/<system>.dat`
    - `find_dat_for_console(console_shortname: str, consoles_yml: dict) -> Path | None` - uses `dat_system` field to locate file
  - Bundle DAT snapshot: include `dats/` directory in the repo (pinned date: commit date) to allow offline-first-run
  - If bundled DATs present, skip fetch; user can `--refresh-dats` manually later (future flag, not in v1)
  - Document DAT snapshot date in `dats/MANIFEST.md`

  **Must NOT do**:
  - NO automatic DAT refresh / TTL / update check
  - NO scraping datomatic.no-intro.org (has anti-bot)
  - NO building DAT merge tool (clrmamepro-style operations)
  - NO support for DAT formats other than Logiqx XML

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Download + extract + verify; straightforward
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: T7
  - **Blocked By**: T1

  **References**:
  - `https://archive.org/details/no-intro_romsets` - No-Intro DAT mirror on Archive.org
  - `https://archive.org/details/redump_datfiles` - Redump DAT mirror

  **Acceptance Criteria**:
  - [ ] `dats/` directory contains DAT files for all Class A+B consoles in `consoles.yml`
  - [ ] Each DAT is valid Logiqx XML (parses via ElementTree)
  - [ ] `dats/MANIFEST.md` lists snapshot date and source URLs
  - [ ] Post-install, `find_dat_for_console("nes", ...)` returns valid Path

  **QA Scenarios** (MANDATORY):

  ```
  Scenario: DAT files present after bootstrap
    Tool: Bash (python -c)
    Steps:
      1. from retrofetch.dat_fetch import find_dat_for_console
      2. import yaml; cy = yaml.safe_load(open('consoles.yml'))
      3. for c in cy['consoles'] if c['class'] in ('A','B'): assert find_dat_for_console(c['shortname'], cy).exists()
    Expected: all Class A+B consoles resolve to existing DAT files
    Evidence: .sisyphus/evidence/task-6-dat-coverage.log

  Scenario: DAT XML parses
    Tool: Bash (python -c)
    Steps:
      1. Parse dats/no-intro/nes.dat via xml.etree.ElementTree
      2. Assert root tag in (datafile, mamelist)
      3. Assert >100 <game> elements
    Expected: all pass
    Evidence: .sisyphus/evidence/task-6-dat-parse.log
  ```

  **Commit**: YES (grouped with T4, T5)
  - Files: `retrofetch/dat_fetch.py`, `dats/` directory, `dats/MANIFEST.md`

- [x] 7. DAT Parser (Logiqx XML) + Hash Verifier

  **What to do**:
  - `retrofetch/dat.py`:
    - `parse_dat(dat_path: Path) -> DatEntry` where DatEntry wraps dict[canonical_name, GameEntry]
    - GameEntry fields: `name`, `description`, `roms` (list of `Rom(name, size, crc32, md5, sha1)`)
    - Use `xml.etree.ElementTree.iterparse` (streaming) for memory efficiency (some DATs are 50MB+)
    - Handle both No-Intro and Redump schemas (both Logiqx variants):
      - No-Intro: `<game><rom name="..." size="..." crc="..." sha1="..."/></game>`
      - Redump: same schema, may have multiple `<rom>` per `<game>` (multi-track CDs)
    - `verify_file(file: Path, expected: Rom) -> VerifyResult`:
      - Compute CRC32 (zlib.crc32), MD5, SHA1 via `hashlib`
      - Stream read 1MB chunks
      - Return `VerifyResult(matched: bool, reason: str | None)`
    - `find_game_by_title(dat: DatEntry, title: str, region_priority: list[str]) -> GameEntry | None`:
      - Fuzzy match title against `description` (strip region/language brackets)
      - Apply region priority: try USA, then World, etc., exclude Beta/Proto/Demo/Sample/Kiosk

  **Must NOT do**:
  - NO separate NoIntroDATParser + RedumpDATParser classes - one parser handles both
  - NO header normalization (SMC/iNES header stripping) - return `unverified` on mismatch, document
  - NO DAT merge/conversion/rebuild features
  - NO whole-document DOM load (use iterparse)

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: XML parsing nuance, streaming memory model, fuzzy matching algorithm, Logiqx schema variants
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: T10 (download orchestrator needs verifier)
  - **Blocked By**: T3, T5, T6

  **References**:
  - `https://datomatic.no-intro.org/stuff/schema_nointro_datfile_v3.xsd` - Logiqx schema
  - `https://docs.python.org/3/library/xml.etree.elementtree.html#xml.etree.ElementTree.iterparse` - streaming XML
  - `https://docs.python.org/3/library/hashlib.html` - hash computation
  - `https://docs.python.org/3/library/zlib.html#zlib.crc32` - CRC32

  **Acceptance Criteria**:
  - [ ] `parse_dat("dats/no-intro/nes.dat")` returns DatEntry with >100 games
  - [ ] `verify_file` on a known-good NES ROM returns `matched=True`
  - [ ] `verify_file` on random bytes returns `matched=False`
  - [ ] `find_game_by_title(dat, "Super Mario Bros.", ["USA"])` returns the USA variant
  - [ ] Memory usage stays <500MB when parsing large DAT (use iterparse)

  **QA Scenarios** (MANDATORY):

  ```
  Scenario: Parse + find happy path
    Tool: Bash (python -c)
    Steps:
      1. Parse nes.dat
      2. Find "Super Mario Bros." with USA priority
      3. Assert returned entry has .name containing "(USA)"
    Evidence: .sisyphus/evidence/task-7-dat-parse-find.log

  Scenario: Hash verify pass
    Tool: Bash (python -c)
    Steps:
      1. Create file with known content
      2. Compute SHA1 externally
      3. Call verify_file with Rom(sha1=known)
    Expected: matched=True
    Evidence: .sisyphus/evidence/task-7-verify-pass.log

  Scenario: Hash verify fail
    Tool: Bash (python -c)
    Steps:
      1. Create random bytes file
      2. Call verify_file with Rom(sha1="deadbeef...")
    Expected: matched=False, reason includes "expected ... got ..."
    Evidence: .sisyphus/evidence/task-7-verify-fail.log

  Scenario: Large DAT memory
    Tool: Bash (PowerShell + python -c with psutil)
    Steps:
      1. Parse largest DAT file
      2. Track peak memory via psutil
    Expected: peak < 500MB
    Evidence: .sisyphus/evidence/task-7-dat-memory.log
  ```

  **Commit**: YES (grouped with T8)
  - Files: `retrofetch/dat.py`

- [x] 8. IGDB OAuth + Wantlist Generator

  **What to do**:
  - `retrofetch/igdb.py`:
    - `get_twitch_token(client_id, client_secret) -> OAuthToken`:
      - POST to `https://id.twitch.tv/oauth2/token` with `grant_type=client_credentials`
      - Cache token to `.cache/igdb/token.json` with `expires_at`
      - Refresh if <60s remain on expiry
    - `fetch_platform_games(platform_id: int, limit: int = 500) -> list[IgdbGame]`:
      - POST to `https://api.igdb.com/v4/games` with Client-ID + Authorization headers
      - Query body (apicalypse): `fields name,total_rating,total_rating_count,first_release_date,category; where platforms = [<id>] & category = (0,2,4) & total_rating != null; sort total_rating desc; limit <limit>;`
      - category=0 (main), 2 (expansion), 4 (standalone DLC); exclude ports (11), remakes (8) - user wants originals
      - Rate limit: 4 req/sec; use `tenacity` with wait_fixed(0.26)
      - Cache result to `.cache/igdb/<platform_id>.json` (never auto-expire)
    - `build_wantlist(console: Console, overrides: ConsoleOverride, limit: int) -> list[str]`:
      - Load cached IGDB games for console.igdb_platform_id
      - Sort by total_rating desc (fallback aggregated_rating, then release year desc)
      - Apply overrides: prepend `overrides.include`, remove `overrides.exclude`
      - Return top-N titles
    - Graceful: if IGDB has <limit games, return all available with log warning

  **Must NOT do**:
  - NO interactive OAuth flow - credentials via env vars only
  - NO storing credentials in plain text config file (env only)
  - NO scraping IGDB website - official API only
  - NO cache TTL/expiry - manual delete only
  - NO fallback to MobyGames/GameFAQs if IGDB fails (v1 scope)

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: OAuth flow, apicalypse query language, rate limiting, cache strategy
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: T12
  - **Blocked By**: T2, T3

  **References**:
  - `https://api-docs.igdb.com/#getting-started` - IGDB API overview + Twitch OAuth
  - `https://api-docs.igdb.com/#game` - game endpoint + field schema
  - `https://api-docs.igdb.com/#apicalypse` - query language
  - `https://api-docs.igdb.com/#platform` - platform IDs list
  - `https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/` - Twitch app token

  **Acceptance Criteria**:
  - [ ] With valid credentials, `get_twitch_token` returns token with expires_in >= 3600
  - [ ] `fetch_platform_games(18)` (NES) returns >=100 games sorted by rating desc
  - [ ] Cached results load without re-hitting network
  - [ ] Missing credentials raises `ConfigError` with Twitch dev portal URL in message
  - [ ] Rate limiter: 10 back-to-back calls take >=2.5 seconds

  **QA Scenarios** (MANDATORY):

  ```
  Scenario: Token acquisition happy path
    Tool: Bash (python -c)
    Preconditions: IGDB_CLIENT_ID and IGDB_CLIENT_SECRET set to valid creds
    Steps:
      1. Call get_twitch_token
      2. Assert token.access_token truthy, expires_in > 3600
    Evidence: .sisyphus/evidence/task-8-igdb-oauth.log

  Scenario: Missing creds error
    Tool: Bash (python -c)
    Steps:
      1. Unset IGDB_CLIENT_ID
      2. Call fetch_platform_games(18)
    Expected: ConfigError with message containing "IGDB_CLIENT_ID" and "dev.twitch.tv"
    Evidence: .sisyphus/evidence/task-8-igdb-no-creds.log

  Scenario: Wantlist build with override
    Tool: Bash (python -c)
    Steps:
      1. Load NES IGDB cache (ensure >=50 entries)
      2. Apply override: include=["Chrono Trigger"], exclude=["E.T."]
      3. Build wantlist limit=10
    Expected: "Chrono Trigger" in result, "E.T." not in result, length=10
    Evidence: .sisyphus/evidence/task-8-wantlist.log

  Scenario: Rate limit compliance
    Tool: Bash (python -c with time)
    Steps:
      1. Make 10 fetch_platform_games calls in a row (use different platform_ids)
      2. Measure total time
    Expected: time >= 2.5 seconds (rate limit enforced)
    Evidence: .sisyphus/evidence/task-8-rate-limit.log
  ```

  **Commit**: YES (grouped with T7)
  - Message: `feat(data): DAT parser and IGDB wantlist generation`
  - Files: `retrofetch/igdb.py`

- [x] 9. Archive.org Source Adapter

  **What to do**:
  - `retrofetch/sources/archive_org.py`:
    - `class ArchiveOrgSource`:
      - `__init__(console: Console, dat: DatEntry)`
      - `find_url_for_game(game_title: str) -> DownloadCandidate | None`:
        - Use `internetarchive` library: `ia.search_items(f'collection:{console.archive_org_identifier} AND title:"{game_title}"')`
        - Prefer items with filenames matching `dat_system` prefix
        - Return `DownloadCandidate(url, expected_sha1, expected_size, filename)`
      - `download(candidate: DownloadCandidate, dest: Path, progress_cb) -> Path`:
        - Use `internetarchive.download(identifier, files=[filename], destdir=dest_parent)` which handles resume natively
        - Report progress via callback (bytes_downloaded)
    - Handle `internetarchive` errors: 403 (locked item), 404 (deleted), network
    - Respect rate limit: max 10 req/sec (internetarchive library already does this)

  **Must NOT do**:
  - NO raw HTTP scraping of archive.org HTML - use the `internetarchive` library
  - NO upload/write operations (read-only)
  - NO metadata-only fetches without download path
  - NO manifest_version handling - use library defaults

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Wrapping third-party library with error handling; moderate complexity
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: T10 (downloader uses source), T13/T15 (pattern template)
  - **Blocked By**: T2, T3

  **References**:
  - `https://archive.org/developers/internetarchive/` - library docs
  - `https://archive.org/advancedsearch.php` - search query syntax
  - `https://archive.org/services/docs/api/` - IA API reference

  **Acceptance Criteria**:
  - [ ] `find_url_for_game` returns non-None for known NES games on a known IA collection
  - [ ] `download` produces file with correct size matching candidate
  - [ ] Resume works: kill mid-download, rerun → continues from offset
  - [ ] 404/403 raises `SourceUnavailable` with reason

  **QA Scenarios** (MANDATORY):

  ```
  Scenario: Find + download known game
    Tool: Bash (python -c)
    Preconditions: network available, archive.org up
    Steps:
      1. Instantiate ArchiveOrgSource for virtualboy
      2. find_url_for_game("Mario Clash") returns candidate
      3. download(candidate, temp_dir)
    Expected: file exists at temp_dir, size == candidate.expected_size
    Evidence: .sisyphus/evidence/task-9-archive-org-download.log

  Scenario: Missing item graceful failure
    Tool: Bash (python -c)
    Steps:
      1. find_url_for_game("Nonexistent Game 9999")
    Expected: returns None, logs warning, no exception
    Evidence: .sisyphus/evidence/task-9-archive-org-missing.log

  Scenario: Resume interrupted download
    Tool: Bash (PowerShell with background Python process kill)
    Steps:
      1. Start download of a 10MB file
      2. After 2 seconds, kill process
      3. Restart download
    Expected: second run detects .part file, resumes; final size correct
    Evidence: .sisyphus/evidence/task-9-archive-org-resume.log
  ```

  **Commit**: YES (grouped with T10, T11)
  - Files: `retrofetch/sources/archive_org.py`

- [x] 10. Download Orchestrator (Resume, .part, Extraction)

  **What to do**:
  - `retrofetch/downloader.py`:
    - `class Downloader`:
      - `download_game(source, candidate, dest_dir, state) -> DownloadResult`:
        - Construct dest path: `<dest_dir>/<sanitized_filename>.part`
        - Delegate to source.download; report progress
        - On completion, rename `.part` → actual name
        - Call verifier (from T7) against DAT entry
        - If verified: update state game status to `acquired`, call extractor
        - If hash mismatch: retry count++; after 3 failures, mark `unverified` and KEEP file
      - Retry logic: up to 3 attempts per source with tenacity exponential backoff (1s, 4s, 10s)
  - `retrofetch/extractor.py`:
    - `extract_archive(archive_path: Path, dest_dir: Path) -> list[Path]`:
      - Use `archivey` for zip/7z/rar/tar unified API
      - Handle split archives (.7z.001 etc.): require all parts present or skip
      - Return list of extracted files
      - On success: delete original archive
      - On failure: keep archive, raise `ExtractionError`
    - Skip archives containing only readme.txt / nfo files (no ROM payload)
    - Sanitize extracted filenames via T5 sanitize

  **Must NOT do**:
  - NO aria2 subprocess - use httpx/internetarchive only for v1
  - NO recursive archive extraction (one level only)
  - NO password-protected archive handling
  - NO custom retry/backoff library - tenacity only

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Download state machine, retry logic, extraction coordination, hash verification flow
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: T12, T14, T17, T18
  - **Blocked By**: T4, T5, T7

  **References**:
  - `https://github.com/archivey/archivey` - archivey unified API (inspect README for exact function names)
  - `https://tenacity.readthedocs.io/en/latest/` - retry library
  - `https://www.python-httpx.org/async/` - httpx async with Range headers

  **Acceptance Criteria**:
  - [ ] Full download → verify → extract → rename pipeline works for a zip file
  - [ ] Resume from .part file continues from last byte
  - [ ] Hash mismatch after 3 attempts sets status=`unverified`, keeps file
  - [ ] Corrupt archive raises ExtractionError, keeps archive, marks status=`failed`
  - [ ] Progress callback fires at least every 1s

  **QA Scenarios** (MANDATORY):

  ```
  Scenario: Full pipeline happy path
    Tool: Bash (python -c)
    Steps:
      1. Point source to a known Archive.org item
      2. Call download_game
      3. Assert: file extracted with canonical DAT name, no .part, no archive, state=acquired
    Evidence: .sisyphus/evidence/task-10-download-happy.log

  Scenario: Hash mismatch no infinite retry
    Tool: Bash (python -c with mock source)
    Steps:
      1. Mock source to always return file with wrong hash
      2. Call download_game
    Expected: exactly 3 attempts, final state=unverified, file kept, no 4th attempt
    Evidence: .sisyphus/evidence/task-10-mismatch-no-retry.log

  Scenario: Corrupt archive handling
    Tool: Bash (python -c)
    Steps:
      1. Write random bytes to file.zip in dest_dir
      2. Call extract_archive
    Expected: ExtractionError raised, file.zip still exists on disk
    Evidence: .sisyphus/evidence/task-10-corrupt-archive.log
  ```

  **Commit**: YES (grouped with T9, T11)
  - Files: `retrofetch/downloader.py`, `retrofetch/extractor.py`

- [x] 11. Organizer + Coverage Report Generator

  **What to do**:
  - `retrofetch/organizer.py`:
    - `place_file(extracted: Path, target_dir: Path, canonical_name: str, state: State) -> PlaceResult`:
      - Sanitize canonical_name via T5
      - Compute final path: `target_dir / canonical_name`
      - Handle collisions:
        - If path exists + same hash: skip (return `already_present`)
        - If path exists + different hash: suffix with `(2)`, log warning
      - Use `make_long_path` for >240 char paths
      - Move file atomically (shutil.move; on Windows same-drive = fast)
    - Multi-disc: group by base title (strip `(Disc N)`), count as 1 toward limit
  - `retrofetch/report.py`:
    - `generate_coverage_report(consoles_yml, roms_root) -> Path`:
      - Walk `consoles.yml`; for each, load state file
      - Compute per-console: Target, Acquired, Unverified, Failed, Skipped
      - For skipped classes, Target=0 and note the skip_reason
      - Generate markdown matching exact format in QA-15 spec
      - Write to `coverage.md` at project root
      - Include timestamp, summary, per-console table, failed games list

  **Must NOT do**:
  - NO gamelist.xml generation
  - NO box-art or media download
  - NO HTML/PDF/JSON report formats - markdown only
  - NO automatic collision resolution that deletes user files

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: File manipulation logic + report templating; medium complexity
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: T12
  - **Blocked By**: T4, T5

  **References**:
  - `https://docs.python.org/3/library/shutil.html#shutil.move` - atomic move
  - Exact report format defined in this plan under QA-15

  **Acceptance Criteria**:
  - [ ] `place_file` moves extracted file into target dir with canonical name
  - [ ] Collision with same hash: skipped gracefully, no overwrite
  - [ ] Collision with different hash: renamed with (2) suffix, warning logged
  - [ ] Multi-disc grouping: 3 discs of FF7 count as 1 game in report
  - [ ] `coverage.md` matches exact format specified in QA-15

  **QA Scenarios** (MANDATORY):

  ```
  Scenario: Place file simple case
    Tool: Bash (python -c)
    Steps:
      1. Create temp file "foo.zip.extracted"
      2. place_file(src, target_dir, "Super Mario Bros. (USA).nes")
    Expected: file exists at target_dir / "Super Mario Bros. (USA).nes", src gone
    Evidence: .sisyphus/evidence/task-11-place-simple.log

  Scenario: Collision with same hash
    Tool: Bash (python -c)
    Steps:
      1. Place file
      2. Place identical file again
    Expected: second call returns already_present, no file duplication
    Evidence: .sisyphus/evidence/task-11-collision-same.log

  Scenario: Coverage report format
    Tool: Bash (python -c)
    Steps:
      1. Set up state files for nes (10 acquired) + mame (skipped) + ps2 (5 failed)
      2. Call generate_coverage_report
      3. Read coverage.md, assert regex patterns per QA-15
    Expected: file matches specified structure
    Evidence: .sisyphus/evidence/task-11-coverage-format.log
  ```

  **Commit**: YES (grouped with T9, T10)
  - Files: `retrofetch/organizer.py`, `retrofetch/report.py`

- [x] 12. CLI Entry (typer subcommands)

  **What to do**:
  - `retrofetch/cli.py`:
    - Typer app with 4 subcommands:
      - `init`: create config.yml/overrides.yml/.env.example + consoles.yml copy + dats/ bootstrap
      - `download [--console N] [--limit N] [--dry-run] [--resume]`: main pipeline
      - `verify [--console N]`: scan existing files, hash-match against DAT, update state
      - `report`: regenerate coverage.md from state files
    - Pipeline in `download` command:
      1. Load config, overrides, consoles.yml
      2. Pre-flight disk space check (fail if insufficient)
      3. Select consoles (--console filter or all with class in A/B/C)
      4. Log skip for class D/E/F
      5. For each console: build wantlist (IGDB + override), dispatch to sources (via T16 dispatcher), download each game through T10
      6. Write state after each game
      7. At end: regenerate coverage.md
    - `--dry-run`: print wantlist + estimated sizes, don't download
    - Exit codes: 0=success, 2=ConfigError, 130=SIGINT, 1=other
  - Entry point in pyproject.toml: `[project.scripts] retrofetch = "retrofetch.cli:app"`

  **Must NOT do**:
  - NO subcommands beyond: init, download, verify, report
  - NO interactive menus / prompts during normal run (only init first-run)
  - NO global flags beyond --verbose, --quiet, --config-path
  - NO shell completion files (stretch goal)
  - NO sub-subcommands (e.g., `download add`, `config set`) - edit YAML directly

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: CLI assembly requires wiring all other modules; moderate size
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO (depends on most Wave 2 tasks)
  - **Parallel Group**: Wave 2 (last)
  - **Blocks**: Wave 3 (needs functional CLI to test source adapters)
  - **Blocked By**: T3, T4, T8, T9, T10, T11

  **References**:
  - `https://typer.tiangolo.com/` - Typer docs
  - `https://typer.tiangolo.com/tutorial/subcommands/` - subcommand pattern

  **Acceptance Criteria**:
  - [ ] `retrofetch --help` lists exactly 4 subcommands
  - [ ] `retrofetch init` creates expected files in cwd
  - [ ] `retrofetch download --console virtualboy --limit 3 --dry-run` prints wantlist and sizes, exits 0
  - [ ] `retrofetch download --console mame` prints `SKIPPED: mame` and exits 0
  - [ ] Missing IGDB creds → exit code 2 + clear error pointing to Twitch dev portal
  - [ ] `retrofetch verify --console virtualboy` updates state JSON

  **QA Scenarios** (MANDATORY):

  Covers QA-1 through QA-6, QA-15, QA-16, QA-17 from Metis specification.

  ```
  Scenario: Init creates all expected files (QA-2)
    Tool: Bash (PowerShell)
    Steps:
      1. Clean cwd
      2. Run: retrofetch init
      3. Assert: config.yml, overrides.yml, .env.example, consoles.yml all exist
    Evidence: .sisyphus/evidence/task-12-init.log

  Scenario: Dry run for Class A (QA-6)
    Tool: Bash (PowerShell)
    Steps:
      1. Run: retrofetch download --console virtualboy --limit 10 --dry-run
    Expected: stdout contains "Console: virtualboy (Class A)", lists games, total size estimate
    Evidence: .sisyphus/evidence/task-12-dryrun.log

  Scenario: Missing creds exit 2 (QA-17)
    Tool: Bash (PowerShell)
    Steps:
      1. Unset IGDB_CLIENT_ID
      2. Run: retrofetch download --console nes --limit 5
    Expected: stderr mentions "IGDB credentials missing", exit code 2
    Evidence: .sisyphus/evidence/task-12-no-creds.log

  Scenario: Class E skip (QA-4)
    Tool: Bash (PowerShell)
    Steps:
      1. Run: retrofetch download --console dos --limit 5 --dry-run
    Expected: "SKIPPED: dos" with reason, exit 0, ROMs/dos unchanged
    Evidence: .sisyphus/evidence/task-12-class-e-skip.log

  Scenario: Class D skip (QA-5)
    Tool: Bash (PowerShell)
    Steps:
      1. Run: retrofetch download --console mame --limit 5 --dry-run
    Expected: "SKIPPED: mame" with reason matching arcade/romset
    Evidence: .sisyphus/evidence/task-12-class-d-skip.log
  ```

  **Commit**: YES
  - Message: `feat(cli): typer subcommands download/verify/init/report`
  - Files: `retrofetch/cli.py`, `pyproject.toml` (entry point addition), README usage section

- [x] 13. Minerva Archive HTTP Adapter

  **What to do**:
  - `retrofetch/sources/minerva_http.py`:
    - `class MinervaHttpSource`:
      - Base URL: `https://minerva-archive.org/browse/` (verify at implementation time)
      - Index page parsing: `selectolax` to extract Apache directory listing links
      - `find_url_for_game(title, region_priority) -> DownloadCandidate | None`:
        - Construct path: `<minerva_path>/` from `consoles.yml` entry
        - Fetch directory listing
        - Filter files matching title (strip extensions, normalize spaces)
        - Apply region priority
        - Return candidate with direct URL
      - `download(candidate, dest, progress_cb) -> Path`:
        - httpx streaming download with Range header resume
        - Chunked read 64KB, report progress
        - Validate final size matches Content-Length
    - Robust to transient 5xx via tenacity (3 attempts)
    - If Minerva web interface is unreachable (server down), raise `SourceUnavailable` immediately (no retry storm)

  **Must NOT do**:
  - NO scraping search/index pages beyond the directory listing we need
  - NO attempt to torrent from this adapter - that's T14
  - NO parallel HTTP downloads from this source (respect Minerva's volunteer bandwidth)

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: HTTP Range resume, selectolax parsing, rate-sensitive source
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: T16
  - **Blocked By**: T9 (pattern reference)

  **References**:
  - `https://minerva-archive.org/browse/` - live URL to verify at build time
  - `https://www.python-httpx.org/async/#streaming-responses` - streaming + Range
  - `https://selectolax.readthedocs.io/` - HTML parsing

  **Acceptance Criteria**:
  - [ ] Directory listing fetched and parsed returns >0 entries for a known console
  - [ ] Download produces file matching Content-Length
  - [ ] Resume: kill mid-download, rerun → finishes with correct size
  - [ ] Server 5xx triggers retry, eventual success
  - [ ] Server down: `SourceUnavailable` raised within 10s, no retry storm

  **QA Scenarios** (MANDATORY):

  ```
  Scenario: Index page parse
    Tool: Bash (python -c)
    Preconditions: minerva-archive.org reachable
    Steps:
      1. Instantiate MinervaHttpSource for nes
      2. Fetch and parse directory listing
      3. Assert: returns list with >=50 filenames containing .nes
    Evidence: .sisyphus/evidence/task-13-minerva-index.log

  Scenario: Download with resume
    Tool: Bash (PowerShell)
    Steps:
      1. Start download of a small ROM (~1MB)
      2. Kill process at ~300KB
      3. Rerun same command
    Expected: final file correct size, resumed from ~300KB (verify via log)
    Evidence: .sisyphus/evidence/task-13-minerva-resume.log

  Scenario: Server unavailable graceful
    Tool: Bash (python -c with mocked network)
    Steps:
      1. Point adapter at unreachable host (e.g., 127.0.0.1:9999)
      2. Call find_url_for_game
    Expected: SourceUnavailable raised within 10s, no long hang
    Evidence: .sisyphus/evidence/task-13-minerva-unavailable.log
  ```

  **Commit**: YES (grouped with T14, T15)
  - Files: `retrofetch/sources/minerva_http.py`

- [x] 14. Minerva Archive Torrent Adapter (libtorrent-python)

  **What to do**:
  - `retrofetch/sources/minerva_torrent.py`:
    - `class MinervaTorrentSource`:
      - Torrent catalog URL pattern from Minerva (verify at impl time; may be per-collection .torrent files)
      - `find_url_for_game(title) -> DownloadCandidate`:
        - Identify which collection torrent contains the game (map via consoles.yml + internal index)
        - Return candidate with magnet/torrent file URL + file index inside torrent
      - `download(candidate, dest, progress_cb) -> Path`:
        - Use `libtorrent` session:
          ```python
          ses = lt.session()
          ses.listen_on(6881, 6891)
          info = lt.torrent_info(torrent_file_path)
          h = ses.add_torrent({'ti': info, 'save_path': str(dest.parent)})
          # SELECTIVE: set file priorities to 0 except for target file index
          h.file_priorities([0]*num_files); h.file_priority(target_idx, 7)
          while not h.status().is_seeding: ... progress_cb(...)
          ```
        - Critical: **selective file download via file_priorities** (NOT whole torrent)
      - Graceful: if no peers after 60s, raise `SourceUnavailable`
      - Config: allow `--no-torrent` to skip this source entirely (CLI flag propagates)
    - Firewall awareness: log if listen_on ports fail (Windows firewall block)

  **Must NOT do**:
  - NO downloading entire torrent (must be selective)
  - NO seeding for extended periods after download complete (stop within 10s of completion)
  - NO DHT bootstrap storms - use conservative settings
  - NO encryption/proxy configuration beyond libtorrent defaults
  - NO trying to connect if `--no-torrent` flag set

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: libtorrent API, selective download, event loop, graceful teardown
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: T16
  - **Blocked By**: T10

  **References**:
  - `https://www.libtorrent.org/python_binding.html` - libtorrent Python API
  - `https://www.libtorrent.org/manual-ref.html#file-priority` - selective download
  - `https://pypi.org/project/libtorrent/` - PyPI wheel availability

  **Acceptance Criteria**:
  - [ ] libtorrent wheel installs on Windows Python 3.12 via pip
  - [ ] Selective file download: only target file hits disk, not whole torrent
  - [ ] No-peer timeout: after 60s with 0 peers, raises SourceUnavailable
  - [ ] Graceful shutdown: process kill → libtorrent cleans up without corrupting partial files
  - [ ] `--no-torrent` flag bypasses this source entirely

  **QA Scenarios** (MANDATORY):

  ```
  Scenario: Selective torrent download
    Tool: Bash (python -c)
    Preconditions: Minerva torrent with known content reachable
    Steps:
      1. Start download via adapter for one specific file
      2. Monitor dest_dir during download
    Expected: only one file grows; other files in torrent have 0 bytes
    Evidence: .sisyphus/evidence/task-14-torrent-selective.log

  Scenario: No-peer timeout
    Tool: Bash (python -c with offline torrent)
    Steps:
      1. Use torrent with known-dead tracker and no DHT peers
      2. Start download
    Expected: after 60s, SourceUnavailable raised, process not stuck
    Evidence: .sisyphus/evidence/task-14-torrent-timeout.log

  Scenario: --no-torrent bypasses
    Tool: Bash (PowerShell)
    Steps:
      1. Run: retrofetch download --console virtualboy --limit 1 --no-torrent
    Expected: MinervaTorrentSource not instantiated / not attempted (verify log absence)
    Evidence: .sisyphus/evidence/task-14-no-torrent-flag.log
  ```

  **Commit**: YES (grouped with T13, T15)
  - Files: `retrofetch/sources/minerva_torrent.py`, CLI flag addition

- [x] 15. Cloudscraper Scrapers (romsfun + romsretro)

  **What to do**:
  - `retrofetch/sources/_cloudflare_base.py`:
    - Shared `CloudflareSession` using `cloudscraper.create_scraper(browser={'custom': 'ScraperBot/1.0'})` with user-agent rotation
    - Fallback: on persistent 403/503, try `curl_cffi.requests.Session(impersonate="chrome120")`
    - If both fail 5 times in a row: mark source dead for rest of session
  - `retrofetch/sources/romsfun.py`:
    - Base URL: `https://romsfun.com/roms/<slug>/`
    - `find_url_for_game(title) -> DownloadCandidate | None`:
      - Fetch console index page, search by title
      - Extract game page URL
      - Fetch game page, extract tokenized download URL (parse HTML via selectolax)
      - Token typically expires in ~1 hour - store timestamp in candidate
      - Return candidate with URL + expiry
    - `download`: httpx GET with token URL; check response is binary (not HTML error page)
    - If token expired (403 on download), re-fetch game page for fresh token
  - `retrofetch/sources/romsretro.py`:
    - Similar pattern to romsfun (slug pattern `https://romsretro.com/roms/<slug>/<game>`)
    - Same Cloudflare + token handling
  - Both sources: detect Cloudflare challenge page in response and log-and-fail (do not try to auto-solve in v1)

  **Must NOT do**:
  - NO CAPTCHA solving (AI-based or otherwise) - if hit CAPTCHA, fail source
  - NO residential proxy integration
  - NO credential/cookie persistence between runs (fresh session each run)
  - NO parallel requests to same domain (rate-limit: 1 req/sec per host)
  - NO attempting sites other than romsfun/romsretro (no scope creep)

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Cloudflare bypass complexity, token lifecycle, HTML parsing, fragile external sites
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: T16, T18
  - **Blocked By**: T9 (pattern template)

  **References**:
  - `https://pypi.org/project/cloudscraper/` - cloudscraper docs
  - `https://github.com/yifeikong/curl_cffi` - curl-cffi TLS impersonation

  **Acceptance Criteria**:
  - [ ] cloudscraper session established successfully against romsfun.com
  - [ ] Game search returns candidate for known title
  - [ ] Download succeeds with valid token
  - [ ] Expired token triggers re-fetch, succeeds on retry
  - [ ] Cloudflare CAPTCHA page detected → source marked failed for session, no hang
  - [ ] 5 consecutive failures mark source dead for session

  **QA Scenarios** (MANDATORY):

  ```
  Scenario: romsfun CF session + search
    Tool: Bash (python -c)
    Preconditions: network available
    Steps:
      1. Instantiate RomsfunSource for nes
      2. find_url_for_game("Super Mario Bros.")
    Expected: returns candidate OR logs "CF-blocked, skipping" without exception
    Evidence: .sisyphus/evidence/task-15-romsfun-search.log

  Scenario: CF block graceful degradation
    Tool: Bash (python -c with mock response returning CF HTML)
    Steps:
      1. Mock response returns Cloudflare challenge HTML
      2. find_url_for_game
    Expected: returns None, logs "cloudflare challenge detected", source marked dead
    Evidence: .sisyphus/evidence/task-15-cf-block.log

  Scenario: 5-failure dead source
    Tool: Bash (python -c)
    Steps:
      1. Force 5 consecutive 403s
      2. 6th call
    Expected: 6th call returns None without network attempt (source dead)
    Evidence: .sisyphus/evidence/task-15-dead-source.log
  ```

  **Commit**: YES (grouped with T13, T14)
  - Message: `feat(sources): Minerva HTTP + torrent + cloudscraper scrapers`
  - Files: `retrofetch/sources/_cloudflare_base.py`, `retrofetch/sources/romsfun.py`, `retrofetch/sources/romsretro.py`

- [x] 16. Source Dispatcher (Fallback Chain per Console Class)

  **What to do**:
  - `retrofetch/dispatcher.py`:
    - `class SourceDispatcher`:
      - `__init__(config: Config, consoles_yml: dict, dat: DatEntry)`
      - Build per-class source list from `config.source_fallback_by_class`
      - Instantiate source adapters lazily (only when first needed)
      - `dispatch_download(console, game_title, dest_dir, state) -> DispatchResult`:
        - For each source in chain:
          - Skip if source marked dead for session (from T15 degradation)
          - Skip if `--no-torrent` and source is torrent-type
          - Call `source.find_url_for_game(title)`; if None → next source
          - Call `downloader.download_game(source, candidate)`; if success → return
          - On source failure (network/403/etc), log + try next
        - If all sources exhausted: return `DispatchResult(status='failed', attempted=<list>)`, update state
    - Track per-source success/fail stats for coverage report

  **Must NOT do**:
  - NO "smart" AI-based source selection - strictly config-driven ordered fallback
  - NO caching/prediction of which source has which game - always try in order
  - NO parallel source attempts for the same game - serial fallback only
  - NO re-attempting a source that already returned None for this title in this session

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Cross-source orchestration, state tracking, many edge cases
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO (needs all sources ready)
  - **Parallel Group**: Wave 3 (late)
  - **Blocks**: T17
  - **Blocked By**: T13, T14, T15

  **References**:
  - Source fallback config in `config.yml` from T3
  - Pattern: chain of responsibility (but keep it simple - a for-loop is fine)

  **Acceptance Criteria**:
  - [ ] Fallback chain: mock source 1 fails → tries source 2 → succeeds
  - [ ] All sources exhausted: returns failed status, updates state
  - [ ] Dead-source tracking: source marked dead doesn't get called again in session
  - [ ] `--no-torrent` flag skips torrent sources
  - [ ] Per-class config respected (Class A tries archive_org first, Class B tries minerva_torrent first)

  **QA Scenarios** (MANDATORY):

  ```
  Scenario: Fallback chain success (QA-14)
    Tool: Bash (python -c with mock sources)
    Steps:
      1. Mock archive_org to return 404
      2. Mock minerva_http to succeed
      3. Call dispatch_download
    Expected: log contains "archive_org failed", then "minerva_http succeeded"; file acquired
    Evidence: .sisyphus/evidence/task-16-fallback-success.log

  Scenario: All sources exhausted
    Tool: Bash (python -c with all mocks failing)
    Steps:
      1. Mock every source to return None
      2. Call dispatch_download
    Expected: DispatchResult(status='failed'), state updated with attempt history
    Evidence: .sisyphus/evidence/task-16-all-fail.log

  Scenario: Class-B uses torrent-first order
    Tool: Bash (python -c)
    Steps:
      1. Use config with Class B order: [minerva_torrent, minerva_http, archive_org]
      2. Dispatch for a psx game
    Expected: log shows minerva_torrent tried first
    Evidence: .sisyphus/evidence/task-16-class-b-order.log
  ```

  **Commit**: YES (grouped with T17, T18)
  - Files: `retrofetch/dispatcher.py`

- [x] 17. Concurrency + Disk Preflight + Multi-Disc Handling

  **What to do**:
  - `retrofetch/orchestrator.py`:
    - `class Orchestrator`:
      - `run(console_filter, limit_override, dry_run) -> RunReport`:
        - Preflight: `shutil.disk_usage(roms_root).free` - estimate total download size
          - Estimate per game: use DAT sizes summed, or conservative defaults (cart=2MB, disc=700MB, DVD=4GB)
          - If estimate > free_space: fail with clear error + required space
        - Use `asyncio.Semaphore(config.max_concurrent_downloads)` for HTTP concurrency (default 3)
        - Per-host rate limit: separate semaphore per domain (1 per host for CF sites, 3 for archive.org)
        - Multi-disc grouping:
          - On wantlist build, dedupe by base title (strip `(Disc N)` suffix)
          - Count as 1 toward limit
          - On dispatch, download all discs associated with canonical game
        - Process consoles serially (one complete before next); games within console concurrent
  - `--dry-run`: print wantlist + disk estimate; don't download

  **Must NOT do**:
  - NO `asyncio` for libtorrent/archivey/DAT (sync only; async only for httpx HTTP)
  - NO `multiprocessing` (threads/asyncio are enough)
  - NO global concurrency beyond semaphore limit
  - NO background retry loop for failed games - in-run only

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Concurrency model, disk math, multi-disc logic, dry-run accounting
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO (depends on dispatcher + downloader)
  - **Parallel Group**: Wave 3 (late)
  - **Blocks**: F1-F4
  - **Blocked By**: T10, T16

  **References**:
  - `https://docs.python.org/3/library/asyncio-sync.html#asyncio.Semaphore` - semaphore
  - `https://docs.python.org/3/library/shutil.html#shutil.disk_usage` - disk check

  **Acceptance Criteria**:
  - [ ] Preflight detects insufficient space before downloading
  - [ ] Max 3 concurrent HTTP downloads enforced (timestamps in log confirm)
  - [ ] Multi-disc: 3 discs of FF7 count as 1 toward limit, all 3 downloaded
  - [ ] Dry-run doesn't modify any files
  - [ ] Per-host rate: CF sites see <=1 req/sec
  - [ ] Consoles processed serially

  **QA Scenarios** (MANDATORY):

  ```
  Scenario: Insufficient disk (QA-16)
    Tool: Bash (python -c with mocked shutil.disk_usage)
    Steps:
      1. Mock disk_usage to return 1GB free
      2. Run: retrofetch download --limit 100
    Expected: exit non-zero; stderr contains "Insufficient disk space"; no partial files
    Evidence: .sisyphus/evidence/task-17-disk-preflight.log

  Scenario: Concurrency limit respected
    Tool: Bash (python -c with concurrent download tracking)
    Steps:
      1. Start run with 10 games
      2. Track active downloads via log timestamps
    Expected: max 3 active at any time
    Evidence: .sisyphus/evidence/task-17-concurrency.log

  Scenario: Multi-disc single count
    Tool: Bash (python -c)
    Steps:
      1. Craft wantlist including "Final Fantasy VII (Disc 1/2/3)"
      2. Set limit=1
      3. Run dispatch
    Expected: all 3 discs downloaded, wantlist counter increments by 1 not 3
    Evidence: .sisyphus/evidence/task-17-multidisc.log
  ```

  **Commit**: YES (grouped with T16, T18)
  - Files: `retrofetch/orchestrator.py`

- [x] 18. Signal Handler + Scraper Graceful Degradation

  **What to do**:
  - `retrofetch/signals.py`:
    - `install_signal_handlers(orchestrator) -> None`:
      - Catch SIGINT (Ctrl+C) and SIGTERM (Windows: CTRL_BREAK_EVENT)
      - Save all open state files
      - Close libtorrent session cleanly (`session.pause(); session = None`)
      - Finalize any `.part` files in consistent state (truncate to last good offset)
      - Set exit code 130
      - Print "Graceful shutdown complete. Resume with same command." via rich
    - Register via `signal.signal(signal.SIGINT, handler)` in CLI main
  - Scraper degradation (integrate with T15):
    - `SourceHealth` singleton tracks consecutive failures per source
    - After 5 failures in a session: source marked dead
    - `SourceDead` check in dispatcher (T16)
    - Log once per source becoming dead; don't spam
  - Track per-source + per-console stats → report generator

  **Must NOT do**:
  - NO attempting recovery from OOMKilled / hard process kill (best-effort only)
  - NO sending crash reports
  - NO auto-restarting on signal
  - NO background threads keeping process alive after signal

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Signal handling + stateful degradation logic; moderate complexity
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: F1-F4
  - **Blocked By**: T10, T15

  **References**:
  - `https://docs.python.org/3/library/signal.html` - signal module
  - `https://docs.python.org/3/library/signal.html#signal.SIGBREAK` - Windows SIGBREAK note

  **Acceptance Criteria**:
  - [ ] SIGINT mid-download: state file saved, .part kept intact, exit 130
  - [ ] Rerun after SIGINT: resumes from saved state, doesn't restart completed games
  - [ ] Source dead detection: 5 failures → marked dead, 6th call bypasses source
  - [ ] Report includes per-source success/fail stats

  **QA Scenarios** (MANDATORY):

  ```
  Scenario: Graceful SIGINT (QA-10)
    Tool: Bash (PowerShell with Ctrl+C simulation)
    Steps:
      1. Start: retrofetch download --console virtualboy --limit 2
      2. After 3 seconds, send Ctrl+C
      3. Check state file + .part files
      4. Restart same command
    Expected: first run exits 130; state consistent; rerun resumes correctly
    Evidence: .sisyphus/evidence/task-18-graceful-sigint.log

  Scenario: Scraper dead-source mark (QA-18)
    Tool: Bash (python -c with forced 403 source)
    Steps:
      1. Inject romsfun that returns CAPTCHA challenge
      2. Run: retrofetch download --console snes --limit 5
    Expected: log contains "romsfun blocked by Cloudflare; skipping source"; continues to next source; exit 0
    Evidence: .sisyphus/evidence/task-18-cf-block.log
  ```

  **Commit**: YES (grouped with T16, T17)
  - Message: `feat(orchestration): dispatcher, concurrency, preflight, graceful shutdown`
  - Files: `retrofetch/signals.py`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
>
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**
> **Never mark F1-F4 as checked before getting user's okay.**

- [x] F1. **Plan Compliance Audit** — `oracle`
  Read plan end-to-end. For each "Must Have": verify implementation exists (read file, run `retrofetch` subcommand, check output). For each "Must NOT Have": search codebase for forbidden patterns (Pydantic internal models, ABC classes, async file I/O, pytest files, CHD code, etc.) — reject with file:line if found. Check evidence files exist in `.sisyphus/evidence/` for all 18 QA scenarios. Compare deliverables list against actual files in repo.
  Output: `Must Have [N/18] | Must NOT Have violations [N] | QA evidence [N/18] | VERDICT: APPROVE/REJECT`

- [x] F2. **Code Quality Review** — `unspecified-high`
  Run `uv pip install -e .` fresh; run `ruff check .` (if installed); review all changed files for: `as any`/`# type: ignore` abuse, empty except, print() in prod code (should be rich.console), commented-out code, unused imports. Check AI slop: excessive comments (user rule: NO comments unless requested), over-abstraction, generic names (`data`, `result`, `item`, `temp`), ABC hierarchies, unused "for future" adapters.
  Output: `Install [PASS/FAIL] | Ruff [N issues] | Files [N clean/N issues] | AI-slop flags [N] | VERDICT`

- [x] F3. **Real Manual QA** — `unspecified-high`
  Start from clean state: delete `.retrofetch-state.json`, clear `.cache/`, fresh venv. Execute ALL 18 QA scenarios (QA-1 through QA-18) from the plan — follow exact steps, capture evidence to `.sisyphus/evidence/final-qa/`. Test cross-task integration: full `retrofetch download --console virtualboy --limit 5` end-to-end with real Archive.org. Test edge cases: missing IGDB creds, corrupted archive, network interruption mid-download. Verify state file integrity after Ctrl+C.
  Output: `QA scenarios [N/18 pass] | E2E [PASS/FAIL] | Edge cases [N tested/N pass] | VERDICT`

- [x] F4. **Scope Fidelity Check** — `deep`
  For each task T1-T18: read "What to do", read actual diff (git log/diff or file inspection). Verify 1:1 — everything in task spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance PER TASK. Detect cross-task contamination: Task N touching Task M's files. Flag unaccounted changes. Specifically hunt for: unit test files, CHD conversion code, gamelist.xml generation, BIOS logic, Vimm's adapter, web server/daemon code, clean-arch layer directories, Pydantic internal models, ABC classes.
  Output: `Tasks [N/18 compliant] | Contamination [CLEAN/N issues] | Scope creep [CLEAN/N items] | VERDICT`

---

## Commit Strategy

Each task in Wave 1 should be its own commit (6 commits). Waves 2 & 3 group related tasks (e.g., T10+T11 single commit since organizer uses downloader). All commits follow Conventional Commits format (no attribution per project rule).

- **T1**: `chore(init): scaffold retrofetch Python project with pyproject.toml and package layout`
  - Files: `pyproject.toml`, `retrofetch/__init__.py`, `.gitignore`, `README.md` (skeleton)
  - Pre-commit: `uv pip install -e . && retrofetch --version`

- **T2**: `feat(consoles): add 178-console classification artifact`
  - Files: `consoles.yml`
  - Pre-commit: YAML validation script

- **T3**: `feat(config): add YAML config loader with schema validation`
  - Files: `retrofetch/config.py`, `config.yml.example`, `overrides.yml.example`, `.env.example`

- **T4-T6**: `feat(core): add state persistence, logging, DAT bundle, sanitization`
  - Files: `retrofetch/state.py`, `retrofetch/logging_setup.py`, `retrofetch/sanitize.py`, `dats/` (pinned snapshot)

- **T7+T8**: `feat(data): DAT parser and IGDB wantlist generation`
  - Files: `retrofetch/dat.py`, `retrofetch/igdb.py`

- **T9+T10+T11**: `feat(pipeline): Archive.org source, downloader, organizer, report`
  - Files: `retrofetch/sources/archive_org.py`, `retrofetch/downloader.py`, `retrofetch/extractor.py`, `retrofetch/organizer.py`, `retrofetch/report.py`

- **T12**: `feat(cli): typer subcommands download/verify/init/report`
  - Files: `retrofetch/cli.py`, README update

- **T13-T15**: `feat(sources): Minerva HTTP + torrent + cloudscraper scrapers`
  - Files: `retrofetch/sources/minerva_http.py`, `retrofetch/sources/minerva_torrent.py`, `retrofetch/sources/romsfun.py`, `retrofetch/sources/romsretro.py`

- **T16+T17+T18**: `feat(orchestration): dispatcher, concurrency, preflight, graceful shutdown`
  - Files: `retrofetch/dispatcher.py`, `retrofetch/orchestrator.py`, `retrofetch/signals.py`

---

## Success Criteria

### Verification Commands
```powershell
# Install
uv pip install -e .
# Expected: install succeeds, no compile errors

retrofetch --version
# Expected: "retrofetch 0.1.0" (or similar) + exit 0

retrofetch init
# Expected: config.yml, overrides.yml, .env.example, consoles.yml created + exit 0

python -c "import yaml; d=yaml.safe_load(open('consoles.yml')); print(len(d['consoles']))"
# Expected: 178

retrofetch download --console mame --dry-run
# Expected: "SKIPPED: mame (Class D: arcade romset, out-of-scope)" + exit 0

retrofetch download --console virtualboy --limit 3
# Expected: 1-3 .vb files in ROMs\virtualboy\, state JSON created + exit 0

retrofetch report
# Expected: coverage.md created with proper structure + exit 0
```

### Final Checklist
- [ ] `pyproject.toml` pins Python `>=3.11,<3.13`
- [ ] `consoles.yml` has exactly 178 entries across classes A-F
- [ ] All Class D/E/F consoles log-skip without error
- [ ] At least 1 Class A console (virtualboy) achieves full E2E acquisition
- [ ] All 18 QA scenarios have evidence in `.sisyphus/evidence/`
- [ ] Zero Pydantic internal models, zero ABC hierarchies, zero unit test files
- [ ] State file survives Ctrl+C; resume works
- [ ] Coverage report generated in documented format
- [ ] Windows filename sanitization verified
- [ ] README documents IGDB setup + install + troubleshooting
