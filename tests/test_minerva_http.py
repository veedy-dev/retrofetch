from __future__ import annotations

import pytest

from retrofetch.sources import SourceUnavailable
from retrofetch.sources.minerva_http import MinervaHttpSource


class _FixtureMinerva(MinervaHttpSource):
    def __init__(self, pages: dict[str, str]) -> None:
        super().__init__(
            {
                "minerva_path": "Redump/PSP",
                "extensions": [".zip"],
                "exclude_keywords": ["(Beta)"],
            },
            base_url="https://minerva.test/browse/",
        )
        self.pages = pages

    def _fetch_text(self, url: str) -> str:
        return self.pages[url]


def test_minerva_catalog_parses_rom_links_sizes_and_one_subdir() -> None:
    root = "https://minerva.test/browse/Redump/PSP/"
    subdir = "https://minerva.test/browse/Redump/PSP/Hacks/"
    source = _FixtureMinerva(
        {
            root: """
            <table>
              <tr><td><a href="/rom?name=Redump/PSP/Burnout%20Dominator%20(USA).zip">Burnout Dominator (USA).zip</a></td><td>1.5 GiB</td></tr>
              <tr><td><a href="/rom?name=Redump/PSP/Burnout%20Dominator%20(Europe).zip">Burnout Dominator (Europe).zip</a></td><td>1.4 GiB</td></tr>
              <tr><td><a href="/rom?name=Redump/PSP/Prototype%20(USA)%20(Beta).zip">Prototype (USA) (Beta).zip</a></td><td>7 MiB</td></tr>
              <tr><td><a href="Hacks/">Hacks/</a></td></tr>
            </table>
            """,
            subdir: """
            <ul>
              <li><a href="/rom?name=Redump/PSP/Hacks/Ridge%20Racer%20(World).zip">Ridge Racer (World).zip</a> 700 MiB</li>
            </ul>
            """,
        }
    )

    titles = source.list_popular(limit=0, region_priority=["USA", "World", "Europe"])
    candidate = source.find_url_for_game("Burnout Dominator", ["USA", "Europe"])
    entry = source.get_entry("Burnout Dominator", ["USA", "Europe"])

    assert titles == ["Burnout Dominator", "Ridge Racer"]
    assert candidate is None
    assert entry is not None
    assert entry.files[0].filename == "Burnout Dominator (USA).zip"
    assert entry.files[0].size == 1_610_612_736
    assert entry.files[0].url == (
        "https://minerva.test/rom?name=Redump/PSP/"
        "Burnout%20Dominator%20%28USA%29.zip"
    )


def test_minerva_limit_caps_titles_after_catalog_build() -> None:
    root = "https://minerva.test/browse/Redump/PSP/"
    source = _FixtureMinerva(
        {
            root: """
            <a href="/rom?name=Redump/PSP/A%20Game%20(USA).zip">A Game (USA).zip</a>
            <a href="/rom?name=Redump/PSP/B%20Game%20(USA).zip">B Game (USA).zip</a>
            """
        }
    )

    assert source.list_popular(limit=1, region_priority=["USA"]) == ["A Game"]


def test_minerva_limit_none_and_zero_are_unlimited() -> None:
    root = "https://minerva.test/browse/Redump/PSP/"
    source = _FixtureMinerva(
        {
            root: """
            <a href="/rom?name=Redump/PSP/A%20Game%20(USA).zip">A Game (USA).zip</a>
            <a href="/rom?name=Redump/PSP/B%20Game%20(USA).zip">B Game (USA).zip</a>
            """
        }
    )

    assert source.list_popular(limit=0, region_priority=["USA"]) == ["A Game", "B Game"]
    assert source.list_popular(limit=None, region_priority=["USA"]) == ["A Game", "B Game"]  # type: ignore[arg-type]


def test_minerva_unavailable_bubbles_source_unavailable() -> None:
    class _UnavailableMinerva(_FixtureMinerva):
        def _fetch_text(self, url: str) -> str:
            raise SourceUnavailable("minerva index not found")

    with pytest.raises(SourceUnavailable, match="not found"):
        _UnavailableMinerva({}).list_popular(limit=0, region_priority=["USA"])
