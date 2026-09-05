from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from textual.app import App
from textual.widgets import Label, Static

from retrofetch.qbittorrent import (
    QBITTORRENT_DOWNLOAD_URL,
    QBITTORRENT_INSTALLER_SHA256,
    QBITTORRENT_INSTALLER_URL,
    QBITTORRENT_PACKAGE_ID,
    QBITTORRENT_PUBLISHER,
    QBITTORRENT_VERSION,
)
from retrofetch.tui.screens import torrent_setup
from retrofetch.tui.screens.torrent_setup import TorrentSetupScreen


class _SetupApp(App[None]):
    def __init__(self, screen: TorrentSetupScreen) -> None:
        super().__init__()
        self.setup_screen = screen
        self.results: list[bool | None] = []

    async def on_mount(self) -> None:
        await self.push_screen(self.setup_screen, self.results.append)


def _status(screen: TorrentSetupScreen) -> str:
    return str(screen.query_one("#torrent-setup-status", Label).content)


async def _wait_for_result(pilot, app: _SetupApp) -> None:
    for _ in range(100):
        if app.results:
            return
        await pilot.pause(0.02)


def test_setup_discloses_exact_package_and_not_now_has_no_side_effect(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        torrent_setup, "install_qbittorrent_winget", lambda: calls.append("winget")
    )
    monkeypatch.setattr(
        torrent_setup,
        "install_qbittorrent_official",
        lambda: calls.append("official"),
    )
    screen = TorrentSetupScreen(platform_name="windows")
    app = _SetupApp(screen)

    async def run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            details = str(
                screen.query_one("#torrent-setup-details", Static).content
            )
            disclosure = str(
                screen.query_one("#torrent-setup-disclosure", Static).content
            )
            assert QBITTORRENT_VERSION in details
            assert QBITTORRENT_PACKAGE_ID in details
            assert QBITTORRENT_PUBLISHER in details
            assert "GPL-3.0" in details
            assert "winget community repository" in details
            assert QBITTORRENT_INSTALLER_URL in details
            assert QBITTORRENT_INSTALLER_SHA256 in details
            assert "public IP address" in disclosure
            assert "upload pieces" in disclosure
            assert "legal right" in disclosure
            assert calls == []

            await pilot.press("down", "down", "enter")
            await _wait_for_result(pilot, app)
            assert app.results == [False]
            assert calls == []

    asyncio.run(run())


def test_winget_install_is_threaded_and_dismisses_only_after_success(monkeypatch) -> None:
    started = threading.Event()
    release = threading.Event()

    def install() -> Path:
        started.set()
        release.wait(2)
        return Path("qbittorrent.exe")

    monkeypatch.setattr(torrent_setup, "install_qbittorrent_winget", install)
    screen = TorrentSetupScreen(platform_name="windows")
    app = _SetupApp(screen)

    async def run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert not started.is_set()
            await pilot.press("enter")
            for _ in range(50):
                if started.is_set():
                    break
                await pilot.pause(0.02)
            assert started.is_set()
            assert app.results == []
            assert "Preparing" in _status(screen)
            release.set()
            await _wait_for_result(pilot, app)
            assert app.results == [True]

    asyncio.run(run())


def test_official_installer_failure_stays_open_and_can_decline(monkeypatch) -> None:
    calls: list[str] = []

    def fail() -> None:
        calls.append("official")
        raise RuntimeError("verified installer failed")

    monkeypatch.setattr(torrent_setup, "install_qbittorrent_official", fail)
    screen = TorrentSetupScreen(platform_name="windows")
    app = _SetupApp(screen)

    async def run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down", "enter")
            for _ in range(100):
                if "failed" in _status(screen).casefold():
                    break
                await pilot.pause(0.02)
            assert calls == ["official"]
            assert "verified installer failed" in _status(screen)
            assert app.results == []

            await pilot.press("escape")
            await _wait_for_result(pilot, app)
            assert app.results == [False]

    asyncio.run(run())


def test_linux_setup_opens_official_page_then_retries_detection(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        torrent_setup,
        "open_qbittorrent_downloads",
        lambda: calls.append("open") or True,
    )
    monkeypatch.setattr(
        torrent_setup,
        "find_qbittorrent",
        lambda _: calls.append("find") or Path("/usr/bin/qbittorrent"),
    )
    screen = TorrentSetupScreen(platform_name="linux")
    app = _SetupApp(screen)

    async def run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            details = str(screen.query_one("#torrent-setup-details", Static).content)
            assert QBITTORRENT_DOWNLOAD_URL in details
            assert "WinGet" not in details

            await pilot.press("enter")
            assert calls == ["open"]
            assert app.results == []
            assert "choose Retry" in _status(screen)

            await pilot.press("down", "enter")
            await _wait_for_result(pilot, app)
            assert calls == ["open", "find"]
            assert app.results == [True]

    asyncio.run(run())
