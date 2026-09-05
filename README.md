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

Downloads continue when you leave the progress screen, while Retrofetch remains open. Press `F6` to return to them. Quitting asks to stop active downloads safely; saved download history remains available after reopening. If a provider needs qBittorrent, the app explains what is needed and guides you through setup.

## Features

- Game listings from multiple supported providers.
- Search and selection without opening several websites.
- A download list you can review before starting.
- Clear progress, speed, remaining time, seeds, and peers.
- Background downloads while you browse games, with completion notifications.
- File verification when matching verification data is available.

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
| `x` | Exclude or restore a game in the browser; remove it in the queue |
| `Enter` | Review the queue from game results; start from the queue |
| `d` | Review the highlighted console’s queue from Home |
| `F6` | Open current downloads |
| `Esc` | Go back without stopping downloads |
| `c` | Ask to cancel remaining downloads from the progress screen |
| `v` / `h` | Show progress details or open download History |
| `,` | Open settings from Home |
| `?` | Open contextual keyboard help |
| `q` / `Ctrl+Q` / `Ctrl+C` | Quit, with confirmation for active downloads |

Available controls appear at the bottom of each screen. In search, `Enter` focuses results and `Esc` returns to results before going back.

Successfully downloaded and already-present files leave the pending queue automatically. Failed or cancelled games stay queued for retry. Verification status remains in progress Details and History: **Not checked** means no matching DAT verification was performed, not a failed download or verified success.

## Switch archive providers

`romsim` and `romslab` support Nintendo Switch catalogs and standalone base-game downloads:

- **ROMsIM:** current Buzzheavier single-file links and Buffdrive links.
- **RomsLab:** Filekeeper base-game links and explicitly identified base-game mirrors. A mirror labeled “Mirror 2” can be an update; Retrofetch checks file identity before accepting it.

New configurations include both providers in the Class C order, after Minerva/Internet Archive and before Romsfun/Romsretro. They do not make requests for other consoles. Existing configurations with explicit provider lists are not rewritten: add `romsim, romslab` to the **C** list under both `ranking_sources_by_class` and `source_fallback_by_class`, keeping your preferred order. See `config.yml.example`. Press `r` in the game selector to refresh an existing cached catalog after changing providers.

Updates, DLC, demos, and multipart downloads are not selected as base games. GoFile, legacy Buzzheavier folder links, Datanodes, and links requiring a CAPTCHA/password are not automatically resolved; unavailable links fall through to supported mirrors or the next configured provider. Not every listed title has a usable download mirror. Catalog ordering comes from the provider, not independent popularity research.

Archives are kept unless extraction is explicitly enabled. Downloads remain **unverified** without matching DAT data; a working download link is not verification.

## Notes

- Some games may disappear when a provider removes a file or becomes unavailable.
- Large arcade and bulk archive collections are not enabled yet because they need separate handling.
- Torrent speed depends on the people sharing that file, not only your internet speed.
- Game selections are session-only. Reopening starts a fresh queue and retains saved download history.
- Files are marked verified only when matching verification data is available.

## Android handheld setup

Use the [end-to-end Android handheld agent prompt](docs/handheld-setup.md): connect and authorize the device, then let the agent choose suitable consoles, research a fresh game shortlist from independent user reviews and substantial rating/popularity evidence, install/configure emulators, acquire authorized content through suitable providers, arrange artwork, and verify gameplay. Provider catalog order and fixed title lists are not treated as popularity rankings. The agent adapts to the hardware, keeps source-backed curation and progress checkpoints, and performs app UI work rather than handing routine setup steps back to the user.

With Android platform-tools (`adb`) installed and debugging authorized:

```sh
retrofetch handheld inspect --serial SERIAL
retrofetch handheld audit ./prepared-ROMs
retrofetch handheld transfer ./prepared-ROMs --serial SERIAL --destination /storage/CARD_UUID/ROMs
```

Replace `SERIAL` and `CARD_UUID` with the discovered device values. Transfer previews by default; add `--apply` only after reviewing its JSON report. It skips identical files by SHA-256, refuses conflicting files, and reserves 5 GiB by default. Use one writer at a time. Reruns skip completed files but do not resume an interrupted file byte-by-byte. The offline audit checks playlist dependencies and readiness warnings; it does not verify game authenticity.

The commands above are building blocks, not a standalone universal setup engine: they do not download games, delete existing files, or clone private emulator configs. The agent combines them with existing Retrofetch downloads and adaptive ADB/UI automation as detailed in the prompt. It needs terminal/ADB and image-inspection access; initial authorization, purchases/sign-ins, and missing private files may require the user. Only supply authorized content. For source checkouts, activate the supported Python 3.10–3.13 environment and use `python -m retrofetch handheld` if the `retrofetch` executable is not on PATH.

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
