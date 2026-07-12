<p align="center">
  <img src="docs/assets/retrofetch-logo.png" alt="Retrofetch cartridge and download arrow logo" width="180">
</p>

<h1 align="center">Retrofetch</h1>

<p align="center">
  <strong>Browse, choose, and organize a retro game library from one friendly TUI.</strong>
</p>

<p align="center">
  <a href="https://github.com/veedy-dev/retrofetch/releases">Windows downloads</a>
  · <a href="#run-from-source">Run from source</a>
  · <a href="#keyboard-shortcuts">Keyboard shortcuts</a>
  · <a href="#development">Development</a>
</p>

<p align="center">
  <img alt="Python 3.10–3.13" src="https://img.shields.io/badge/Python-3.10--3.13-3776AB?logo=python&logoColor=white">
  <img alt="Windows" src="https://img.shields.io/badge/Windows-10%2F11-0078D4?logo=windows11&logoColor=white">
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/License-MIT-2ea44f"></a>
</p>

Retrofetch replaces browser hunting and manual torrent setup with a keyboard-first
workflow. It catalogues **178 systems**, currently exposes browse providers for
**89**, remembers download progress across restarts, and verifies files against
No-Intro or Redump DATs when a matching DAT is available.

> **Bring your own legal access.** Retrofetch includes no games or firmware.
> Download only content you are legally entitled to obtain.

![Retrofetch library browser showing Nintendo 64 titles](docs/assets/screenshot-library.png)

## Get started on Windows

### Installer — recommended

1. Open [Releases](https://github.com/veedy-dev/retrofetch/releases).
2. Download and double-click **`RetrofetchSetup.exe`**.
3. Launch Retrofetch from the desktop or Start menu.
4. Choose your game and BIOS folders in the first-run wizard, then press `Ctrl+S`.

No Python installation or terminal commands are required. The installer is
per-user and does not require administrator access.

> Current builds are unsigned, so Windows SmartScreen may show **Unknown
> publisher**. Download binaries only from this repository's Releases page.

If the Releases page is empty, use the source instructions below until the first
release is published.

### Portable app

Download **`Retrofetch.exe`** from the same Releases page and double-click it.
It uses the same setup wizard and stores settings in
`%LOCALAPPDATA%\Retrofetch\config.yml`.

## What it does

| Browse | Choose | Download safely |
|---|---|---|
| Search provider-backed systems and page through current catalogues. | Pick exact titles, exclude unwanted entries, and edit the queue before starting. | Resume interrupted work, keep partial torrent pieces, and verify against DATs when available. |

- **Fresh sessions:** game selections reset when Retrofetch starts; download state
  and completed history remain.
- **Visible progress:** per-title progress, transferred bytes, speed, ETA, seeds,
  peers, and terminal outcomes are shown in the TUI.
- **Exact torrent files:** collection torrents select only the requested internal
  file rather than downloading the whole archive.
- **Managed qBittorrent:** Windows can install and run an isolated, loopback-only
  qBittorrent profile when torrent transport is first needed.
- **Honest verification:** missing DAT coverage is shown as `unverified`, never as
  a false success.
- **Settings in the app:** press `,` to change game, BIOS, cache, region, limit,
  extraction, and torrent settings.

![Retrofetch live torrent progress with speed, ETA, seeds, and peers](docs/assets/screenshot-download.png)

## Typical workflow

1. Search for a console with `/`.
2. Press `g` to select games, or use the full current list.
3. Press `d`, remove anything you changed your mind about, then press `Enter`.
4. Watch progress or cancel safely with `Esc` / `c`.
5. Reopen Retrofetch later; active and completed download state is preserved.

DAT-backed files are marked verified after hashing. When no DAT exists for a
system, the download remains clearly marked unverified.

## Keyboard shortcuts

| Key | Action |
|---|---|
| `/` | Search consoles or titles |
| `g` | Select games |
| `d` | Review and start downloads |
| `b` | Download BIOS files |
| `,` | Settings |
| `s` | Download state |
| `C` | Coverage report |
| `r` / `Ctrl+R` | Refresh current catalogue |
| `?` | Full in-app help |
| `q` | Quit |

## Support expectations

Retrofetch knows about 178 systems, but a catalogue entry is not the same as a
working download provider. The sidebar shows provider-backed systems in green and
unsupported/skipped systems in grey.

| Class | Current behavior |
|---|---|
| A | Cartridge systems; No-Intro verification where bundled DATs exist |
| B | Disc systems; Redump verification where bundled DATs exist |
| C | Newer systems; best-effort catalogue/download support |
| D–F | Arcade, computer, fantasy, mobile, or unsupported distribution models; skipped |

Provider availability changes. Cloudflare, removed files, dead torrents, and
zero-seed swarms can make an individual title unavailable even when its catalogue
entry exists.

## Run from source

### Windows PowerShell

```powershell
git clone https://github.com/veedy-dev/retrofetch.git
cd retrofetch
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\retrofetch.exe tui
```

### Linux / macOS

```bash
git clone https://github.com/veedy-dev/retrofetch.git
cd retrofetch
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
retrofetch tui
```

The packaged Windows app uses a per-user config automatically. Source installs
can create local config files with:

```bash
retrofetch init
```

See [`config.yml.example`](config.yml.example) and
[`overrides.yml.example`](overrides.yml.example) for advanced options.

## CLI

The TUI is the recommended interface. Automation is still available:

```bash
retrofetch download --console virtualboy --limit 3 --dry-run
retrofetch verify --console psx
retrofetch bios --console ps2
retrofetch report
retrofetch --help
```

Use `--no-torrent` for a single HTTP-only run, or set
`torrent_mode: disabled` in the config.

## Torrent privacy

Managed mode keeps the qBittorrent Web API on `127.0.0.1`, uses a
Retrofetch-owned profile and secret, disables UPnP/NAT-PMP, and never controls
untagged jobs. BitTorrent traffic itself is public peer-to-peer traffic: peers can
see your public IP and may receive uploaded pieces while a transfer is active.

qBittorrent is separate GPL software. Retrofetch displays its publisher, license,
source, installer URL, and checksum before starting installation.

## Troubleshooting

### No titles appear

Refresh with `r`. The provider may be unavailable, blocked, or missing that
system. Check `retrofetch.log` for the provider error.

### Torrent speed changes or stays at zero

Torrent speed depends on active peers, not your internet plan. A swarm with few
seeds can alternate between idle periods and short bursts. The TUI shows seeds,
peers, speed, and ETA so the cause remains visible.

### Windows path is too long

Choose a short library path such as `C:\ROMs`, or enable Windows long-path
support.

### qBittorrent setup is requested

Choose the recommended WinGet option. Retrofetch validates the package, launches
its managed profile, and resumes the original queue automatically. Set
`torrent_mode: disabled` if you do not want torrent support.

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[build]" pytest ruff pyright
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\pyright.exe
```

Build the portable executable and installer:

```powershell
.\packaging\build_windows.ps1 -InstallTools
```

Outputs:

- `dist\Retrofetch.exe`
- `dist\RetrofetchSetup.exe`

Tagged `v*` pushes run the same tests and publish both files through
[`windows-release.yml`](.github/workflows/windows-release.yml). Release tags must
match the version reported by the executable.

## License

[MIT](LICENSE) © 2026 veedy-dev
