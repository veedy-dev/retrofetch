from __future__ import annotations

import logging
import sys
import webbrowser
from pathlib import Path
from typing import ClassVar

from textual import (
    work,  # pyright: ignore[reportMissingImports, reportAttributeAccessIssue]
)
from textual.app import ComposeResult  # pyright: ignore[reportMissingImports]
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import Vertical  # pyright: ignore[reportMissingImports]
from textual.message import Message  # pyright: ignore[reportMissingImports]
from textual.screen import Screen  # pyright: ignore[reportMissingImports]
from textual.widgets import (  # pyright: ignore[reportMissingImports]
    Footer,
    Header,
    Label,
    OptionList,
    Static,
)

from retrofetch.qbittorrent import (
    QBITTORRENT_DOWNLOAD_URL,
    QBITTORRENT_INSTALLER_SHA256,
    QBITTORRENT_INSTALLER_URL,
    QBITTORRENT_PACKAGE_ID,
    QBITTORRENT_PUBLISHER,
    QBITTORRENT_VERSION,
    discover_qbittorrent,
)

logger = logging.getLogger(__name__)


def install_qbittorrent_winget() -> object:
    from retrofetch.torrent import (
        install_qbittorrent_winget as install,  # pyright: ignore[reportMissingImports]
    )

    return install()


def install_qbittorrent_official() -> object:
    from retrofetch.torrent import (
        install_qbittorrent_official as install,  # pyright: ignore[reportMissingImports]
    )

    return install()


def install_qbittorrent_appimage() -> object:
    from retrofetch.torrent import (
        install_qbittorrent_appimage as install,  # pyright: ignore[reportMissingImports]
    )

    return install()


def find_qbittorrent(executable: Path | None = None) -> Path | None:
    return discover_qbittorrent(executable)


def open_qbittorrent_downloads() -> bool:
    return webbrowser.open(QBITTORRENT_DOWNLOAD_URL)



class TorrentInstallResult(Message):
    def __init__(self, success: bool, error: str | None = None) -> None:
        self.success = success
        self.error = error
        super().__init__()


class TorrentSetupScreen(Screen[bool]):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("enter", "select", "Select", show=True, priority=True),
        Binding("escape", "not_now", "Not now", show=True),
        Binding("q", "not_now", "Not now", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    TorrentSetupScreen #torrent-setup-body { padding: 1 2; }
    TorrentSetupScreen #torrent-setup-details { margin-top: 1; }
    TorrentSetupScreen #torrent-setup-disclosure { margin: 1 0; color: $warning; }
    TorrentSetupScreen #torrent-setup-options { height: 7; border: round $primary; }
    TorrentSetupScreen #torrent-setup-status { margin-top: 1; }
    """

    def __init__(
        self,
        *,
        platform_name: str | None = None,
        qbittorrent_path: Path | None = None,
    ) -> None:
        super().__init__()
        raw_platform = sys.platform if platform_name is None else platform_name
        self._platform = (
            "windows"
            if raw_platform.startswith("win") or raw_platform == "windows"
            else "macos"
            if raw_platform in {"darwin", "macos"}
            else "linux"
        )
        self._qbittorrent_path = qbittorrent_path
        self._installing = False

    def compose(self) -> ComposeResult:
        if self._platform == "windows":
            details = (
                f"Package: qBittorrent {QBITTORRENT_VERSION} ({QBITTORRENT_PACKAGE_ID})\n"
                f"Publisher: {QBITTORRENT_PUBLISHER}\n"
                "License: GNU General Public License v3 (GPL-3.0)\n"
                "WinGet source: winget community repository\n"
                f"Official installer: {QBITTORRENT_INSTALLER_URL}\n"
                f"Installer SHA-256: {QBITTORRENT_INSTALLER_SHA256}"
            )
            options = (
                "Use/install with WinGet (recommended)",
                "Verified official installer fallback (visible installer)",
                "Not now",
            )
        else:
            details = (
                f"Package: qBittorrent {QBITTORRENT_VERSION}\n"
                f"Publisher: {QBITTORRENT_PUBLISHER}\n"
                "License: GNU General Public License v3 (GPL-3.0)\n"
                f"Official downloads: {QBITTORRENT_DOWNLOAD_URL}"
            )
            options = (
                "Open the official qBittorrent download page",
                "Retry after installing qBittorrent",
                "Not now",
            )
        disclosure = (
            "BitTorrent is peer-to-peer: peers can see your public IP address, and "
            "qBittorrent may upload pieces while downloading. Download only content "
            "you have the legal right to obtain. qBittorrent is separate GPL software."
        )
        yield Header(show_clock=False)
        with Vertical(id="torrent-setup-body"):
            yield Static("Torrent setup", id="torrent-setup-title")
            yield Static(details, id="torrent-setup-details", markup=False)
            yield Static(disclosure, id="torrent-setup-disclosure", markup=False)
            yield OptionList(*options, id="torrent-setup-options", markup=False)
            yield Label("No installation started.", id="torrent-setup-status", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        options = self.query_one("#torrent-setup-options", OptionList)
        options.highlighted = 0
        options.focus()

    def action_select(self) -> None:
        if self._installing:
            return
        selected = self.query_one("#torrent-setup-options", OptionList).highlighted
        if selected == 2:
            self.dismiss(False)
            return
        if selected not in (0, 1):
            return
        if self._platform != "windows" and selected == 0:
            opened = open_qbittorrent_downloads()
            self.query_one("#torrent-setup-status", Label).update(
                "Official download page opened. Install qBittorrent, then choose Retry."
                if opened
                else f"Open {QBITTORRENT_DOWNLOAD_URL}, install qBittorrent, then choose Retry."
            )
            return
        self._installing = True
        method = (
            "WinGet"
            if selected == 0
            else "official installer"
            if self._platform == "windows"
            else "installed applications"
        )
        self.query_one("#torrent-setup-status", Label).update(
            f"Preparing qBittorrent {QBITTORRENT_VERSION} with {method}..."
        )
        self._install(selected)

    @work(thread=True, exclusive=True, group="torrent-install")
    def _install(self, selected: int) -> None:
        try:
            if self._platform == "windows":
                result = (
                    install_qbittorrent_winget()
                    if selected == 0
                    else install_qbittorrent_official()
                )
            else:
                result = find_qbittorrent(self._qbittorrent_path)
                if result is None and self._platform == "linux":
                    result = install_qbittorrent_appimage()
            if result is False:
                raise RuntimeError("installer did not complete")
            if result is None:
                raise RuntimeError(
                    "qBittorrent 5.2.x was not found. Install it, then try again."
                )
        except Exception as exc:
            # Installer backends must not crash the UI or expose raw tracebacks.
            logger.exception(
                "Torrent installation failed: %s", type(exc).__name__, exc_info=False
            )
            self.post_message(TorrentInstallResult(False, str(exc)))
            return
        self.post_message(TorrentInstallResult(True))

    def on_torrent_install_result(self, message: TorrentInstallResult) -> None:
        if message.success:
            self.query_one("#torrent-setup-status", Label).update(
                "qBittorrent is ready."
            )
            self.dismiss(True)
            return
        self._installing = False
        self.query_one("#torrent-setup-status", Label).update(
            f"Installation failed: {message.error or 'unknown error'}"
        )

    def action_not_now(self) -> None:
        if self._installing:
            self.query_one("#torrent-setup-status", Label).update(
                "Installation is running; wait for it to finish."
            )
            return
        self.dismiss(False)
