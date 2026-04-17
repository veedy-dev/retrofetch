# retrofetch
Automated ROM collection filler for retro console emulation

## What is retrofetch?
retrofetch is a CLI tool designed to automate the process of building and maintaining a high-quality ROM collection. Instead of manually hunting for individual files or downloading massive, uncurated sets, it uses popularity signals from major archival sites to identify the "Top N" games for any given console and fetches them automatically.

The tool is built for users who want a representative library of the best games across 178 different systems without the overhead of manual curation. It handles the entire pipeline: identifying the most popular titles, finding reliable download sources, verifying file integrity against industry-standard DAT files, and organizing them into a clean directory structure.

## How It Works
The core of retrofetch is its source-site popularity ranking model. It derives "wantlists" by analyzing download counts from Archive.org and default popularity rankings from sites like romsfun and romsretro. This approach requires zero API keys, zero OAuth tokens, and no user accounts.

Once a wantlist is generated, the tool attempts to fetch files through a fallback chain of HTTP and Torrent sources. Downloaded files are verified using bundled No-Intro and Redump DAT files to ensure CRC32, MD5, or SHA1 hashes match known-good dumps. If a download fails or a source is blocked, the orchestrator automatically moves to the next available provider in the chain.

## Requirements
*   **OS**: Windows 10+ (Primary), Linux/macOS (Secondary)
*   **Python**: `>=3.11, <3.13` (Hard pin for library compatibility)
*   **Disk Space**: ~100 GB recommended (varies significantly by console)
*   **Optional Dependencies**:
    *   `libtorrent`: Required for torrent-based sources (`uv pip install libtorrent`)
    *   `unrar`: Binary on PATH required for .rar extraction (available at rarlab.com)
    *   **Windows Long Paths**: Must be enabled in the registry for deep directory structures

## Installation
The following steps assume a Windows environment using PowerShell.

```powershell
git clone https://github.com/user/retrofetch D:\retrofetch
cd D:\retrofetch

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install in editable mode (uv preferred, pip fallback)
uv pip install -e .    # or: pip install -e .

# Verify installation
retrofetch --version   # should print "retrofetch 0.1.0"
```

<details>
<summary>Linux / macOS Fallback</summary>

```bash
git clone https://github.com/user/retrofetch ~/retrofetch
cd ~/retrofetch
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
retrofetch --version
```
</details>

## First Run
Follow this sequence to initialize the tool and perform a safe test run.

```powershell
# 1. Generate default configuration and bootstrap DAT files
retrofetch init

# 2. Perform a dry-run for a small console to see the wantlist
retrofetch download --console virtualboy --limit 3 --dry-run

# 3. Execute the actual download
retrofetch download --console virtualboy --limit 3

# 4. Verify the downloaded files against DATs
retrofetch verify --console virtualboy

# 5. Generate a coverage report
retrofetch report
```

## Commands

### init
Creates `config.yml`, `overrides.yml`, and bootstraps the `dats/` directory.

| Option | Meaning |
|---|---|
| `--force` | Overwrite existing configuration files |

### download
The primary command for fetching ROMs.

| Option | Type | Default | Meaning |
|---|---|---|---|
| `--console` | TEXT | all 178 | Single console shortname (e.g. `nes`, `psx`) |
| `--limit` | INT | 75 | Max games per console (overrides config) |
| `--dry-run` | FLAG | off | Print wantlist without downloading |
| `--no-torrent` | FLAG | off | Skip libtorrent sources |
| `--config` | PATH | `config.yml` | Path to configuration file |

### verify
Rescans existing ROM files and updates local state with verification results.

| Option | Type | Default | Meaning |
|---|---|---|---|
| `--console` | TEXT | all | Single console shortname |
| `--config` | PATH | `config.yml` | Path to configuration file |

### report
Generates a `coverage.md` report showing collection progress.

| Option | Type | Default | Meaning |
|---|---|---|---|
| `--config` | PATH | `config.yml` | Path to configuration file |
| `--output` | PATH | `coverage.md` | Target path for the report |

## Configuration

### config.yml
The global configuration file defines your ROM root, region preferences, and source priorities.

```yaml
roms_root: "D:/Projects/retrofetch/ROMs"  # Target directory for ROMs
cache_dir: ".cache"                       # DAT and HTTP cache location
log_file: "retrofetch.log"                # Application log path
default_limit: 75                         # Default top-N games per console
region_priority:                          # Preferred region order
  - USA
  - World
  - Europe
  - Japan
exclude_keywords:                         # Skip titles containing these strings
  - "(Beta)"
  - "(Proto)"
  - "(Demo)"
max_game_size_gb: null                    # Size cap per file (null = no limit)
max_concurrent_downloads: 3               # Parallel workers per console
source_fallback_by_class:                 # Download source order per class
  A: [archive_org, minerva_http, minerva_torrent, romsfun]
  B: [minerva_torrent, minerva_http, archive_org, romsretro]
  C: [romsfun, romsretro, archive_org]
ranking_sources_by_class:                 # Popularity ranking sources
  A: [romsfun, romsretro, archive_org]
  B: [archive_org, romsretro]
  C: [romsfun, romsretro]
```

### overrides.yml
Use this file to force-include specific titles or set custom limits per console.

```yaml
consoles:
  nes:
    include:
      - Chrono Trigger             # Always download this title
    exclude:
      - "E.T. the Extra-Terrestrial" # Never download this title
    limit: 100                     # Custom limit for NES
    region_priority:               # Custom region order for NES
      - USA
      - Japan
```

Note: `consoles.yml` in the repo root is the authoritative classification for all 178 systems. Do not modify it unless you are adding support for a new system.

## Console Classes
retrofetch categorizes systems into classes based on their distribution model and metadata availability.

| Class | Count | Support | Description |
|---|---|---|---|
| A | 64 | Full | Cartridge consoles with No-Intro DATs (NES, SNES, GB, etc.) |
| B | 20 | Full | Disc-based consoles with Redump DATs (PSX, Saturn, CD, etc.) |
| C | 5 | Best-effort | Modern consoles (PS3, Vita, Wii U, Switch, 3DS) |
| D | 20 | Skipped | Arcade romsets (MAME, FBNeo, CPS) |
| E | 54 | Skipped | Home computers / engines / ports (Amiga, DOS, Steam) |
| F | 15 | Skipped | Fantasy / homebrew / mobile (PICO-8, J2ME) |

## Output Layout
```
<roms_root>/
├── <shortname>/
│   ├── Game Title (USA).ext          # Verified ROM file
│   ├── .retrofetch-state.json        # Per-console resume state
│   └── ...
retrofetch.log                         # Rotating application log
coverage.md                            # Collection status report
.cache/                                # Temporary metadata caches
```

## Troubleshooting

### Empty wantlist for a console
The ranker could not reach any configured sources or the collection is missing on the provider side. Check `retrofetch.log` for network errors or Cloudflare blocks. Retry after a delay.

### Windows long-path errors
Windows has a 260-character path limit by default. Enable long paths in the registry:
`HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled = 1`
Alternatively, move your `roms_root` closer to the drive root (e.g., `C:\ROMs`).

### .rar files not extracting
The tool requires the `unrar` binary to be available on your system PATH. Download it from rarlab.com and ensure `unrar.exe` is in your environment variables.

### libtorrent not installed
If you want to use torrent sources, you must install `libtorrent` manually. If installation fails due to missing wheels, use the `--no-torrent` flag to stick to HTTP sources.

### Cloudflare blocked
Sources like romsfun and romsretro use Cloudflare protection. If the log shows persistent 403 errors, the source is temporarily unreachable. The tool will mark it as dead for the session; restart the command later.

### Ctrl+C mid-download
Safe to interrupt. State is preserved in `.retrofetch-state.json` and partial downloads (`.part`) remain on disk. Rerunning the command will resume where it left off.

## Limitations / Non-Goals
*   **No BIOS**: Does not download system BIOS files.
*   **No Conversion**: Does not handle CHD or zstd compression for disc images.
*   **No Patching**: Does not apply IPS, BPS, or XDelta patches.
*   **No Arcade**: Hard-skips MAME/FBNeo due to complex romset versioning.
*   **No Media**: Does not fetch box art, videos, or gamelist.xml metadata.
*   **No GUI**: CLI-only operation; no web or graphical interface.
*   **No Vimm's Lair**: Bulk scraping is discouraged by the site owner and not supported.

## Repository Layout
```
retrofetch/
├── retrofetch/
│   ├── cli.py                 # Typer subcommands and entry points
│   ├── config.py              # YAML loading and validation
│   ├── ranker.py              # Popularity-based wantlist generation
│   ├── state.py               # JSON state management
│   ├── dat.py / dat_fetch.py  # DAT parsing and bootstrapping
│   ├── downloader.py          # HTTP/Torrent download logic
│   ├── extractor.py           # Archive extraction (zip, 7z, rar)
│   ├── organizer.py           # File naming and path sanitization
│   ├── orchestrator.py        # Main execution loop
│   ├── dispatcher.py          # Source fallback management
│   ├── report.py              # coverage.md generation
│   └── sources/               # Site-specific adapters
├── consoles.yml               # 178-console metadata (authoritative)
├── config.yml.example         # Global config template
├── overrides.yml.example      # Per-console override template
├── dats/                      # Bundled DAT file snapshots
└── ROMs/                      # Default target directory
```

## License
MIT License. See `pyproject.toml` for details.
