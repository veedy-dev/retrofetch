from __future__ import annotations

from textual import work  # pyright: ignore[reportMissingImports, reportAttributeAccessIssue]
from textual.app import ComposeResult  # pyright: ignore[reportMissingImports]
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import Vertical  # pyright: ignore[reportMissingImports]
from textual.message import Message  # pyright: ignore[reportMissingImports]
from textual.screen import Screen  # pyright: ignore[reportMissingImports]
from textual.widgets import Footer, Header, Label, OptionList, Static  # pyright: ignore[reportMissingImports]

from retrofetch.qbittorrent import (
    QBITTORRENT_INSTALLER_SHA256,
    QBITTORRENT_INSTALLER_URL,
    QBITTORRENT_PACKAGE_ID,
    QBITTORRENT_PUBLISHER,
    QBITTORRENT_VERSION,
)


def install_qbittorrent_winget() -> object:
    from retrofetch.torrent import install_qbittorrent_winget as install  # pyright: ignore[reportMissingImports]

    return install()


def install_qbittorrent_official() -> object:
    from retrofetch.torrent import install_qbittorrent_official as install  # pyright: ignore[reportMissingImports]

    return install()


class TorrentInstallResult(Message):
    def __init__(self, success: bool, error: str | None = None) -> None:
        self.success = success
        self.error = error
        super().__init__()


class TorrentSetupScreen(Screen[bool]):
    BINDINGS = [
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

    def __init__(self) -> None:
        super().__init__()
        self._installing = False

    def compose(self) -> ComposeResult:
        details = (
            f"Package: qBittorrent {QBITTORRENT_VERSION} ({QBITTORRENT_PACKAGE_ID})\n"
            f"Publisher: {QBITTORRENT_PUBLISHER}\n"
            "License: GNU General Public License v3 (GPL-3.0)\n"
            "WinGet source: winget community repository\n"
            f"Official installer: {QBITTORRENT_INSTALLER_URL}\n"
            f"Installer SHA-256: {QBITTORRENT_INSTALLER_SHA256}"
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
            yield OptionList(
                "Use/install with WinGet (recommended)",
                "Verified official installer fallback (visible installer)",
                "Not now",
                id="torrent-setup-options",
                markup=False,
            )
            yield Label("No installation started.", id="torrent-setup-status")
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
        self._installing = True
        method = "WinGet" if selected == 0 else "official installer"
        self.query_one("#torrent-setup-status", Label).update(
            f"Preparing qBittorrent {QBITTORRENT_VERSION} with {method}..."
        )
        self._install(selected)

    @work(thread=True, exclusive=True, group="torrent-install")
    def _install(self, selected: int) -> None:
        try:
            result = (
                install_qbittorrent_winget()
                if selected == 0
                else install_qbittorrent_official()
            )
            if result is False:
                raise RuntimeError("installer did not complete")
        except Exception as exc:
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
