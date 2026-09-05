<p align="center">
  <img src="docs/assets/retrofetch-logo.png" alt="Retrofetch logo" width="112">
</p>

<h1 align="center">Retrofetch</h1>

<p align="center">
  A keyboard-first retro game browser, downloader, and verifier.
</p>

<p align="center">
  <a href="#download">Download</a>
  &middot; <a href="#quick-start">Quick start</a>
  &middot; <a href="#development">Contribute</a>
</p>

![Browsing games and building a queue in Retrofetch](docs/assets/screenshot-library.png)

## Download

Get the [latest release](https://github.com/veedy-dev/retrofetch/releases/latest). Packaged builds include Python—just download, extract or install, and open.

| Platform | Download | Launch |
|---|---|---|
| Windows | [Installer](https://github.com/veedy-dev/retrofetch/releases/latest/download/RetrofetchSetup.exe) · [Portable](https://github.com/veedy-dev/retrofetch/releases/latest/download/Retrofetch.exe) | Run the installer, or open the portable EXE. |
| Linux x86-64 | [Archive](https://github.com/veedy-dev/retrofetch/releases/latest/download/Retrofetch-linux-x86_64.tar.gz) | Extract, then run `./run-retrofetch.sh`. |
| macOS | [Apple Silicon](https://github.com/veedy-dev/retrofetch/releases/latest/download/Retrofetch-macos-arm64.tar.gz) · [Intel](https://github.com/veedy-dev/retrofetch/releases/latest/download/Retrofetch-macos-x86_64.tar.gz) | Extract, then Control-click `Retrofetch.command` and choose **Open**. |

On first launch, choose your library folders. Torrent downloads need qBittorrent; Retrofetch offers setup when it is missing.

Builds are unsigned, so Windows or macOS may ask you to confirm the first launch. Download only from this repository.

## Quick start

1. **Browse.** Search consoles with `/`, then open one with `Enter` from the results.
2. **Queue.** Press `Space` on games you want. `Ctrl+A` queues all matching results.
3. **Download.** Press `Enter` to review the queue, then `Enter` again to start.
4. **Keep browsing.** `Esc` leaves progress without stopping downloads; `F6` brings it back.

Keep Retrofetch open while downloading. Quitting asks to stop active transfers safely.

## Download progress

![Completed, active, and queued downloads in Retrofetch](docs/assets/screenshot-download.png)

*Screenshots use demonstration data.*

- Downloaded and already-present files leave the queue. Failed or cancelled items stay for retry.
- Download history is saved; your selection queue starts fresh when you reopen the app.
- **Not checked** means no matching DAT verification—not a failed download and not verified success.
- Archives are kept by default. Extraction and BIOS downloads are separate opt-ins.

## Keyboard shortcuts

| Key | Action |
|---|---|
| `/` | Search consoles or games |
| `Space` | Add or remove a game from the queue |
| `Ctrl+A` / `Ctrl+U` | Queue or remove all matching results |
| `F6` | Open current downloads |
| `Esc` | Go back |
| `?` | Show contextual help |
| `q` / `Ctrl+Q` | Quit |

The footer lists the shortcuts available on each screen. In search fields, `Enter` focuses the results.

## Development

[Issues](https://github.com/veedy-dev/retrofetch/issues) and pull requests are welcome.

<details>
<summary>Run from source, test, or build</summary>

Use Python **3.10–3.13**.

```bash
git clone https://github.com/veedy-dev/retrofetch.git
cd retrofetch
python -m venv .venv
```

Activate with `. .venv/bin/activate` on Linux/macOS, or `.\.venv\Scripts\Activate.ps1` in Windows PowerShell. Then:

```bash
python -m pip install -e ".[build]" pytest ruff==0.16.6 pyright
python -m retrofetch --help
python -m retrofetch tui
```

Release verification gates:

```bash
python -m pytest -q
python -m ruff check .
pyright
```

Build a portable app for the current platform:

```bash
python -m PyInstaller --clean --noconfirm packaging/retrofetch.spec
```

Build the Windows installer:

```powershell
.\packaging\build_windows.ps1 -InstallTools
```

</details>

Retrofetch prepares your library; it is not an emulator. Games and firmware are not bundled. Use authorized content and respect source terms.

## License

[MIT](LICENSE) &copy; 2026 veedy-dev

*Tip: [Automate Android handheld setup with an AI agent](docs/handheld-setup.md).*
