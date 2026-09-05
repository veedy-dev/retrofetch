<p align="center">
  <img src="docs/assets/retrofetch-logo.png" alt="Retrofetch logo" width="180">
</p>

<h1 align="center">Retrofetch</h1>

<p align="center">
  <strong>Find and download retro games from multiple online providers in one place.</strong>
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

Retrofetch brings game listings from supported archives and online providers into one easy app. Search for a console, choose the games you want, review the list, and follow every download without jumping between websites or setting up each transfer by hand.

For each supported console, Retrofetch checks its main No-Intro or Redump collection first, then verified extra collections for more titles.

> **Please note:** Retrofetch does not host or include games or firmware. Downloads come from independent third-party providers, so availability can change. You are responsible for following local laws and each provider's terms.

![Retrofetch library browser](docs/assets/screenshot-library.png)

## Install

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

When a torrent download needs qBittorrent, Retrofetch opens the official download page. Install qBittorrent, return to Retrofetch, and choose **Retry**; the original download then continues.

## How it works

1. Search for a console.
2. Choose one or more games.
3. Review the download list and remove anything you no longer want.
4. Start the download and follow its progress in the app.

Retrofetch keeps active downloads and completed history when you close and reopen it. If a provider needs qBittorrent, the app explains what is needed and guides you through setup.

## Features

- Game listings from multiple supported providers.
- Search and selection without opening several websites.
- A download list you can review before starting.
- Clear progress, speed, remaining time, seeds, and peers.
- Downloads that can continue after restarting Retrofetch.
- File verification when matching verification data is available.

![Retrofetch download progress](docs/assets/screenshot-download.png)

## Basic controls

| Key | Action |
|---|---|
| Arrow keys | Move through lists |
| `Enter` | Open or confirm |
| `/` | Search |
| `g` | Choose games |
| `d` | Review and start downloads |
| `,` | Open settings |
| `Esc` | Go back or cancel |
| `?` | Open help |
| `q` | Quit |

The available controls are always shown at the bottom of the app.

## Notes

- Some games may disappear when a provider removes a file or becomes unavailable.
- Large arcade and bulk archive collections are not enabled yet because they need separate handling.
- Torrent speed depends on the people sharing that file, not only your internet speed.
- Retrofetch resets game selections when reopened, but keeps active and completed downloads.
- Files are marked verified only when matching verification data is available.

## Android handheld setup

Use the [reusable Nova/Android handheld agent prompt](docs/handheld-setup.md) for the full ES-DE, emulator, controller, artwork, and gameplay-verification workflow. It recommends the latest compatible MrPurple driver, with the tested Nova release recorded only as a reference.

With Android platform-tools (`adb`) installed and debugging authorized:

```sh
retrofetch handheld inspect --serial SERIAL
retrofetch handheld audit ./prepared-ROMs
retrofetch handheld transfer ./prepared-ROMs --serial SERIAL --destination /storage/CARD_UUID/ROMs
```

Replace `SERIAL` and `CARD_UUID` with the discovered device values. Transfer previews by default; add `--apply` only after reviewing its JSON report. It skips identical files by SHA-256, refuses conflicting files, and reserves 5 GiB by default. Use one writer at a time. Reruns skip completed files but do not resume an interrupted file byte-by-byte. The offline audit checks playlist dependencies and readiness warnings; it does not verify game authenticity.

These commands do not download games, delete existing files, or clone private emulator configs. Only supply authorized content. For source checkouts, activate the supported Python 3.10–3.13 environment and use `python -m retrofetch handheld` if the `retrofetch` executable is not on PATH.

## Development and contributing

Feature requests, bug reports, and pull requests are welcome. [Open an issue](https://github.com/veedy-dev/retrofetch/issues) to share an idea or report a problem.

To work on Retrofetch locally:

```bash
git clone https://github.com/veedy-dev/retrofetch.git
cd retrofetch
python -m venv .venv
```

Activate the environment with `.\.venv\Scripts\Activate.ps1` on Windows or `. .venv/bin/activate` on Linux and macOS, then run:

```bash
python -m pip install -e ".[build]" pytest ruff pyright
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
