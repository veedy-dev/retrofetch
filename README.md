<p align="center">
  <img src="docs/assets/retrofetch-logo.png" alt="Retrofetch logo" width="180">
</p>

<h1 align="center">Retrofetch</h1>

<p align="center">
  <strong>A keyboard-first retro game browser, downloader, and verifier.</strong>
</p>

<p align="center">
  <a href="https://github.com/veedy-dev/retrofetch/releases">Downloads</a>
  &middot; <a href="#install">Setup guide</a>
  &middot; <a href="#how-it-works">How it works</a>
  &middot; <a href="#development-and-contributing">Develop and contribute</a>
</p>

<p align="center">
  <img alt="Windows" src="https://img.shields.io/badge/Windows-10%2F11-0078D4?logo=windows11&logoColor=white">
  <img alt="Linux" src="https://img.shields.io/badge/Linux-x86__64-FCC624?logo=linux&logoColor=black">
  <img alt="macOS" src="https://img.shields.io/badge/macOS-13%2B-000000?logo=apple&logoColor=white">
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/License-MIT-2ea44f"></a>
</p>

Retrofetch brings game listings from supported archives and online providers into one terminal app. Search for a console, queue the games you want, and keep browsing while downloads run. It prepares your library; it is not an emulator.

Catalogs and download fallbacks follow your configured provider order. No-Intro/Redump naming helps organize listings; a catalog listing alone does not verify a file.

> **Please note:** Retrofetch does not include games or firmware. Downloads come from configured archives and online providers, so availability can change. Only download content you are authorized to obtain, following local laws and each provider's terms.

![Retrofetch library browser](docs/assets/screenshot-library.png)

## Install

Choose a platform asset under **Assets** on the [Releases page](https://github.com/veedy-dev/retrofetch/releases), not the source-code ZIP or tarball. The packaged apps include Python.

### Windows

1. Open the [Releases page](https://github.com/veedy-dev/retrofetch/releases).
2. Download **`RetrofetchSetup.exe`**.
3. Double-click the installer, then open Retrofetch from your desktop or Start menu.
4. Choose where your games and BIOS files should be stored when the app first opens.

No Python installation or terminal commands are needed.

> Current builds are not code-signed yet, so Windows may show an **Unknown publisher** warning. Only download Retrofetch from this repository.

Prefer a portable app? Download **`Retrofetch.exe`** from the same Releases page and double-click it.

### Linux

1. Open the [Releases page](https://github.com/veedy-dev/retrofetch/releases).
2. Download **`Retrofetch-linux-x86_64.tar.gz`** and extract it.
3. Open a terminal in the extracted folder and run:

```bash
./run-retrofetch.sh
```

No Python installation is needed.

### macOS

1. Open the [Releases page](https://github.com/veedy-dev/retrofetch/releases).
2. Download **`Retrofetch-macos-arm64.tar.gz`** for Apple Silicon or **`Retrofetch-macos-x86_64.tar.gz`** for an Intel Mac.
3. Extract it, then Control-click **`Retrofetch.command`** and choose **Open**.

No Python installation is needed. Current builds are unsigned, so macOS may ask you to confirm the first launch.

Torrent downloads need separate qBittorrent software. If it is missing, Retrofetch offers a setup screen: Windows has WinGet and official-installer options; Linux/macOS offer the official download page and a retry after installation. Review the prompt and choose an option—setup is not silent, and the pending download continues only after qBittorrent is ready.

## How it works

1. Press `/` to search consoles, then `Enter` to focus results. Open the highlighted console with `Enter` or `g`.
2. Search its games with `/`, move through results with the arrow keys, and press `Space` to queue individual games. `Ctrl+A` queues matching results; `s` shows only queued games.
3. Press `Enter` from game results to review the queue. Remove unwanted entries with `x`, then press `Enter` to start.
4. Follow progress, or press `Esc` to browse elsewhere. `F6` returns to current downloads.

**Background downloads last only while Retrofetch remains open.** The header shows download status while you browse, and in-app notifications report completion or errors. Quitting asks to stop active downloads safely; it does not leave a downloader running after the app exits. Reopening resets game selections to a fresh queue but retains saved download history.

![Retrofetch download progress](docs/assets/screenshot-download.png)

Progress screen shown with locally generated demonstration data.

## Basic controls

| Key | Action |
|---|---|
| Arrow keys | Move through lists |
| `Enter` / `g` | Browse the highlighted console |
| `/` | Search consoles or games |
| `Space` | Add or remove a game from the queue |
| `Ctrl+A` / `Ctrl+U` | Queue or remove all matching search results |
| `s` | Show queued games in the browser; open History from Home |
| `PageUp` / `PageDown` | Change pages in game results |
| `r` | Refresh the browser catalog |
| `x` | Exclude or restore a game in the browser; remove it in the queue |
| `Enter` | Review the queue from game results; start from the queue |
| `d` | Review the highlighted console’s queue from Home |
| `F6` | Open current downloads |
| `Esc` | Go back without stopping downloads |
| `c` | Ask to cancel remaining downloads from the progress screen |
| `v` / `h` | Show progress details or open download History |
| `,` | Open settings from Home |
| `b` | Open the optional BIOS download screen from Home |
| `?` | Open contextual keyboard help |
| `q` / `Ctrl+Q` / `Ctrl+C` | Quit, with confirmation for active downloads |

Available controls appear at the bottom of each screen. In search, `Enter` focuses results and `Esc` returns to results before going back.

Successfully downloaded and already-present files leave the pending queue automatically. Failed or cancelled games stay queued for retry. Verification status remains in progress Details and History: **Not checked** means no matching DAT verification was performed, not a failed download or verified success.

## Notes

- Some games may disappear when a provider removes a file or becomes unavailable.
- Large arcade and bulk archive collections are not enabled yet because they need separate handling.
- Torrent speed depends on the people sharing that file, not only your internet speed.
- Archives are kept by default; extraction and BIOS downloads are explicit opt-ins.

## Development and contributing

Feature requests, bug reports, and pull requests are welcome. [Open an issue](https://github.com/veedy-dev/retrofetch/issues) to share an idea or report a problem.

To work on Retrofetch locally, use Python **3.10–3.13**:

```bash
git clone https://github.com/veedy-dev/retrofetch.git
cd retrofetch
python -m venv .venv
```

Activate the environment with `.\.venv\Scripts\Activate.ps1` on Windows or `. .venv/bin/activate` on Linux and macOS, then run:

```bash
python -m pip install -e ".[build]" pytest ruff==0.16.6 pyright
python -m retrofetch --help
python -m retrofetch tui
```

Run the same verification gates as release CI:

```bash
python -m pytest -q
python -m ruff check .
pyright
```

Build a portable app for the current operating system with:

```bash
python -m PyInstaller --clean --noconfirm packaging/retrofetch.spec
```

Build the Windows installer with:

```powershell
.\packaging\build_windows.ps1 -InstallTools
```

## License

[MIT](LICENSE) &copy; 2026 veedy-dev

*Tip: [Automate Android handheld setup with an AI agent](docs/handheld-setup.md).*
