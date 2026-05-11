# retrofetch
Automated ROM collection filler for retro console emulation

## What you get
retrofetch builds and maintains a curated ROM library for 178 consoles without
you doing the hunting. It ranks the most popular titles per system, fetches
them from reliable archives, and verifies every file against No-Intro / Redump
hashes.

- A clean ROMs/ tree with resume-on-crash state
- DAT-verified files (no broken dumps)
- A keyboard-driven TUI with live previews and 24h cache

## Quick start (5 minutes)
Follow these steps to get running on Windows with PowerShell.

### Simplest path: use the launcher

If you just want to run it, use the bundled launcher. It creates the venv and installs dependencies on first run, then drops you straight into the TUI.

```powershell
# Windows PowerShell
.\launch.ps1
```

```cmd
:: Windows double-click
launch.bat
```

```bash
# Linux / macOS
./launch.sh
```

Skip the rest of this section if the launcher worked. The manual steps below are for people who want to control each step.

1. Clone and install
```powershell
git clone https://github.com/veedy-dev/retrofetch D:\retrofetch
cd D:\retrofetch
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

2. Verify installation
```powershell
retrofetch --version
```

3. Launch the TUI
```powershell
retrofetch tui
```
If this is your first run, a setup wizard will appear. Press Ctrl+S to save your settings.

4. Try a dry run
```powershell
retrofetch download --console virtualboy --limit 3 --dry-run
```

5. Run a real download
```powershell
retrofetch download --console virtualboy --limit 3
```

6. Check your coverage
```powershell
retrofetch report
```

<details>
<summary>Linux / macOS instructions</summary>

```bash
git clone https://github.com/veedy-dev/retrofetch ~/retrofetch
cd ~/retrofetch
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
retrofetch --version
```
</details>

## The TUI is the friendly path
The Textual-based TUI (`retrofetch tui`) is the easiest way to manage your collection.

### First-run wizard
If `config.yml` is missing, the TUI opens a setup wizard. You can configure:
- ROMs root: Where your files will live.
- Default limit: How many games to fetch per console (1..1000).
- Region priority: Comma-separated list (e.g., USA, World, Europe, Japan).
Press `Ctrl+S` to save your settings or `Esc` to cancel and exit.

### Home screen and live preview
The home screen features a 178-console sidebar. As you scroll through consoles, the right panel auto-fetches and previews the top 20 titles.
- Debounced auto-fetch: Scrolling is smooth because fetches only fire after you stop moving for 400ms.
- Wantlist cache: Wantlists are cached on disk for 24 hours. Cache hits are instant and show `(cached)` in the header.
- Retry: If a fetch fails, a yellow toast appears. Press `Ctrl+R` to invalidate the cache and try again.
- Non-blocking: Opening the Wantlist (`w`) or Download (`d`) screens won't freeze the UI. Data loads in the background while the screen stays responsive.

### Key bindings
| Key | Action |
|---|---|
| q | Quit (exit 0) |
| / | Focus filter input (sidebar) |
| ? | Help modal (key reference) |
| w | Wantlist curation (DataTable, space=include, a/Ctrl+A=include page, x=exclude, s=save) |
| d | Download confirm screen (Enter=save and open progress, c=cancel) |
| s | State browser (read-only .retrofetch-state.json viewer) |
| C | Coverage viewer (async compute, e=export) |
| Ctrl+R | Retry fetch (invalidates cache and re-fetches) |
| Tab | Cycle focus |
| Enter | Select / Activate |
| Esc | Back / Close modal |
| Ctrl+S | Global save (where applicable) |

### Download flow
Pressing `d` on a Class A/B/C console opens the **Download confirm screen**:
- Shows the cached wantlist count and a `Dry run` toggle (Space toggles).
- Press `Enter` to commit the wantlist, dismiss confirm, and open the **Download progress screen**.
- Press `Esc` to return to home without starting.

The **Download progress screen** shows:
- An overall progress block at the top (`X / N games done`).
- The currently active downloads (top section).
- Recently completed entries (scrollable middle section).
- A summary line on completion (`acquired=N, failed=N, unverified=N`).
- Press `Esc` or `c` while running to open the **Cancel confirm modal**; pressing `y` stops the run gracefully (current file finishes, then dismiss).

### Prerequisites
A real terminal is required. The TUI will not launch in MSYS2, PowerShell ISE, or non-TTY pipes.

## CLI reference

### init
Creates `config.yml`, `overrides.yml`, and bootstraps the `dats/` directory.

| Option | Meaning |
|---|---|
| --force | Overwrite existing configuration files |

### download
The primary command for fetching ROMs.

| Option | Type | Default | Meaning |
|---|---|---|---|
| --console | TEXT | all | Single console shortname (e.g. nes, psx) |
| --limit | INT | 75 | Max games per console (overrides config) |
| --verbose / -v | FLAG | off | Emit detailed progress events |
| --dry-run | FLAG | off | Print wantlist without downloading |
| --no-torrent | FLAG | off | Skip libtorrent sources |
| --config | PATH | config.yml | Path to configuration file |

### verify
Rescans existing ROM files and updates local state with verification results.

| Option | Type | Default | Meaning |
|---|---|---|---|
| --console | TEXT | all | Single console shortname |
| --config | PATH | config.yml | Path to configuration file |

### report
Generates a `coverage.md` report showing collection progress.

| Option | Type | Default | Meaning |
|---|---|---|---|
| --config | PATH | config.yml | Path to configuration file |
| --output | PATH | coverage.md | Target path for the report |

### tui
Launches the interactive command center.

| Option | Type | Default | Meaning |
|---|---|---|---|
| --config | PATH | config.yml | Path to configuration file |

## Configuration

### config.yml
Defines global paths, region preferences, and source priorities.

```yaml
roms_root: "D:/Projects/retrofetch/ROMs"
cache_dir: ".cache"
log_file: "retrofetch.log"
default_limit: 75
region_priority:
  - USA
  - World
  - Europe
  - Japan
exclude_keywords:
  - "(Beta)"
  - "(Proto)"
  - "(Demo)"
  - "(Sample)"
  - "(Kiosk)"
  - "(Trade Demo)"
max_game_size_gb: null
max_concurrent_downloads: 3
source_fallback_by_class:
  A: [archive_org, minerva_http, minerva_torrent, romsfun]
  B: [minerva_torrent, minerva_http, archive_org, romsretro]
  C: [romsfun, romsretro, archive_org]
ranking_sources_by_class:
  A: [romsfun, romsretro, archive_org]
  B: [archive_org, romsretro]
  C: [romsfun, romsretro]
```

### overrides.yml
Force-include specific titles or set custom limits per console.

```yaml
consoles:
  nes:
    include:
      - Chrono Trigger
    exclude:
      - "E.T. the Extra-Terrestrial"
    limit: 100
    region_priority:
      - USA
      - Japan
```

## Console classes
retrofetch categorizes systems based on metadata and distribution models.

| Class | Count | Support | Description |
|---|---|---|---|
| A | 64 | Full | Cartridge consoles with No-Intro DATs (NES, SNES, GB, etc.) |
| B | 20 | Full | Disc-based consoles with Redump DATs (PSX, Saturn, CD, etc.) |
| C | 5 | Best-effort | Modern consoles (PS3, Vita, Wii U, Switch, 3DS) |
| D | 20 | Skipped | Arcade romsets (MAME, FBNeo, CPS) |
| E | 54 | Skipped | Home computers / engines / ports (Amiga, DOS, Steam) |
| F | 15 | Skipped | Fantasy / homebrew / mobile (PICO-8, J2ME) |

## Output layout
```
<roms_root>/
|-- <shortname>/
|   |-- Game Title (USA).ext          # Verified ROM file
|   |-- .retrofetch-state.json        # Per-console resume state
|   `-- ...
retrofetch.log                         # Rotating application log
coverage.md                            # Collection status report
.cache/                                # Temporary metadata caches
```

## Troubleshooting

### Empty wantlist
The ranker could not reach sources or the collection is missing on the provider side. Check `retrofetch.log` for network errors or Cloudflare blocks.

### Windows long-path errors
Enable long paths in the registry: `HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled = 1`. Or move `roms_root` closer to the drive root (e.g., `C:\ROMs`).

### .rar files not extracting
Install the `unrar` binary from rarlab.com and ensure `unrar.exe` is on your system PATH.

### libtorrent not installed
Install `libtorrent` manually for torrent support. Use `--no-torrent` to stick to HTTP sources if installation fails.

### Cloudflare blocked
Sources like romsfun use Cloudflare. If you see 403 errors, the source is temporarily unreachable. Restart the command later.

### TUI refuses to launch
Exits with code 2 if the terminal is incompatible. Avoid MSYS2, PowerShell ISE, or non-TTY environments. Use Windows Terminal or a standard shell.

### Ctrl+C mid-download
Safe to interrupt. State is saved in `.retrofetch-state.json`. Rerunning the command will resume from where it stopped.

## Limitations / non-goals
- No BIOS: Does not download system BIOS files.
- No Conversion: Does not handle CHD or zstd compression.
- No Patching: Does not apply IPS, BPS, or XDelta patches.
- No Arcade: Skips MAME/FBNeo due to complex versioning.
- No Media: Does not fetch box art or metadata for frontends.
- No Mouse: TUI is keyboard-only.
- No Vimm's Lair: Bulk scraping is not supported.

## Repository layout
```
retrofetch/
|-- retrofetch/
|   |-- cli.py                 # Typer subcommands and entry points
|   |-- config.py              # YAML loading and validation
|   |-- events.py              # EventBus + typed ProgressEvents
|   |-- ranker.py              # Popularity-based wantlist generation
|   |-- wantlist_cache.py      # 24h disk cache for TUI previews
|   |-- state.py               # JSON state management
|   |-- dat.py / dat_fetch.py  # DAT parsing and bootstrapping
|   |-- downloader.py          # HTTP/Torrent download logic
|   |-- extractor.py           # Archive extraction (zip, 7z, rar)
|   |-- organizer.py           # File naming and path sanitization
|   |-- orchestrator.py        # Main execution loop
|   |-- dispatcher.py          # Source fallback management
|   |-- report.py              # markdown emitter
|   |-- coverage.py            # pure compute_coverage()
|   |-- sources/               # Site-specific adapters
|   `-- tui/                   # Textual command center
|       |-- app.py
|       |-- messages.py
|       |-- styles.tcss
|       |-- screens/
|       |   |-- setup.py             # First-run configuration wizard
|       |   |-- download_confirm.py  # Download confirm screen
|       |   |-- download_progress.py # Download progress screen
|       |   `-- cancel_confirm.py    # Cancel confirm modal
|       |-- widgets/
|       |   `-- wantlist_preview.py # Live preview panel
|       `-- workers/
|-- consoles.yml               # 178-console metadata (authoritative)
|-- config.yml.example         # Global config template
|-- overrides.yml.example      # Per-console override template
|-- dats/                      # Bundled DAT file snapshots
`-- ROMs/                      # Default target directory
```

## License
MIT License. See `pyproject.toml` for details.
