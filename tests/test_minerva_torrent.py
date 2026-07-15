from __future__ import annotations

import hashlib

import pytest

from retrofetch.catalog import CatalogEntry, CatalogFile
from retrofetch.sources import SourceUnavailable
from retrofetch.sources import minerva_torrent
from retrofetch.sources.minerva_torrent import MinervaTorrentSource


def _bencode(value: object) -> bytes:
    if isinstance(value, int):
        return b"i" + str(value).encode() + b"e"
    if isinstance(value, bytes):
        return str(len(value)).encode() + b":" + value
    if isinstance(value, list):
        return b"l" + b"".join(_bencode(item) for item in value) + b"e"
    if isinstance(value, dict):
        return (
            b"d"
            + b"".join(
                _bencode(key) + _bencode(item) for key, item in sorted(value.items())
            )
            + b"e"
        )
    raise TypeError(type(value))


def _torrent(*files: dict[bytes, object]) -> tuple[bytes, str]:
    info = {
        b"files": list(files),
        b"name": b"Minerva_Myrient",
        b"piece length": 16_384,
        b"pieces": b"0" * 20,
    }
    return _bencode(
        {b"announce": b"https://tracker.test", b"info": info}
    ), hashlib.sha1(_bencode(info)).hexdigest()


class _Catalog:
    def __init__(
        self,
        entry: CatalogEntry | None,
        root: str = "Redump/Sony - PlayStation Portable",
    ) -> None:
        self.entry = entry
        self.root = root

    def get_entry_with_root(
        self, title: str, region_priority: list[str] | None = None
    ) -> tuple[str, CatalogEntry] | None:
        if self.entry is None or self.entry.title != title:
            return None
        return self.root, self.entry

    def list_popular(
        self, limit: int, region_priority: list[str] | None = None
    ) -> list[str]:
        return [self.entry.title] if self.entry else []


class _FixtureSource(MinervaTorrentSource):
    def __init__(
        self,
        entry: CatalogEntry | None,
        torrent: bytes,
        *,
        root: str = "Redump/Sony - PlayStation Portable",
        console_entry: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            console_entry
            if console_entry is not None
            else {"minerva_path": "Redump/Sony - PlayStation Portable"}
        )
        self._catalog = _Catalog(entry, root)  # type: ignore[assignment]
        self.torrent = torrent
        self.fetch_urls: list[str] = []

    def _fetch_torrent_bytes(self, url: str) -> bytes:
        self.fetch_urls.append(url)
        return self.torrent


def _entry(*paths: str) -> CatalogEntry:
    return CatalogEntry(
        title="Example Game",
        region="USA",
        files=[
            CatalogFile(
                filename=path.rsplit("/", 1)[-1],
                url="https://minerva.test/rom?name=./" + path.replace(" ", "%20"),
                size=None,
            )
            for path in paths
        ],
        source="minerva_http",
        tags=[],
    )


def test_resolves_exact_file_and_caches_collection_metadata() -> None:
    path = "Redump/Sony - PlayStation Portable/Example Game (USA).zip"
    sha1 = bytes.fromhex("11" * 20)
    crc32 = bytes.fromhex("22" * 4)
    md5 = bytes.fromhex("33" * 16)
    torrent, infohash = _torrent(
        {
            b"length": 1_067_861_720,
            b"path": [part.encode() for part in path.split("/")],
            b"sha1": sha1,
            b"crc32": crc32,
            b"md5sum": md5,
        }
    )
    source = _FixtureSource(_entry(path), torrent)

    candidate = source.find_url_for_game("Example Game", ["USA"])
    again = source.find_url_for_game("Example Game", ["USA"])

    assert candidate is not None and again is not None
    assert candidate.url == (
        "https://minerva-archive.org/assets/Minerva_Myrient_v0.3/"
        "Minerva_Myrient%20-%20Redump%20-%20Sony%20-%20PlayStation%20Portable.torrent"
    )
    assert candidate.filename == "Example Game (USA).zip"
    assert candidate.expected_size == 1_067_861_720
    assert candidate.expected_sha1 == "11" * 20
    assert candidate.expected_crc32 == "22" * 4
    assert candidate.extra == {
        "transport": "torrent",
        "torrent_url": candidate.url,
        "torrent_infohash": infohash,
        "torrent_internal_path": path,
        "torrent_file_index": 0,
        "torrent_name": "Minerva_Myrient",
        "torrent_bytes": torrent,
        "minerva_full_path": path,
        "minerva_path": "Redump/Sony - PlayStation Portable",
        "catalog_title": "Example Game",
        "catalog_region": "USA",
        "artifact_md5": "33" * 16,
    }
    assert len(source.fetch_urls) == 1


def test_missing_or_ambiguous_catalog_match_returns_none() -> None:
    path = "Redump/Sony - PlayStation Portable/Example Game (USA).zip"
    torrent, _infohash = _torrent(
        {b"length": 1, b"path": [part.encode() for part in path.split("/")]}
    )

    assert _FixtureSource(None, torrent).find_url_for_game("Example Game") is None
    assert (
        _FixtureSource(
            _entry(path, path.replace("USA", "Europe")), torrent
        ).find_url_for_game("Example Game")
        is None
    )


def test_missing_torrent_path_returns_none() -> None:
    path = "Redump/Sony - PlayStation Portable/Example Game (USA).zip"
    other = "Redump/Sony - PlayStation Portable/Other Game (USA).zip"
    missing, _ = _torrent(
        {b"length": 1, b"path": [part.encode() for part in other.split("/")]}
    )

    assert (
        _FixtureSource(_entry(path), missing).find_url_for_game("Example Game") is None
    )


def test_exact_case_mismatch_returns_none() -> None:
    path = "Redump/Sony - PlayStation Portable/Example Game (USA).zip"
    torrent, _ = _torrent(
        {
            b"length": 1,
            b"path": [part.swapcase().encode() for part in path.split("/")],
        }
    )

    assert _FixtureSource(_entry(path), torrent).find_url_for_game("Example Game") is None


def test_rejects_traversal_in_torrent_metadata() -> None:
    path = "Redump/Sony - PlayStation Portable/Example Game (USA).zip"
    torrent, _ = _torrent(
        {b"length": 1, b"path": [b"Redump", b"..", b"Example Game (USA).zip"]}
    )

    with pytest.raises(SourceUnavailable, match="unsafe torrent path"):
        _FixtureSource(_entry(path), torrent).find_url_for_game("Example Game")


@pytest.mark.parametrize(
    "component",
    ["CON.zip", "lpt9.bin", "game. ", "game.", "game.zip:payload"],
)
def test_rejects_windows_unsafe_torrent_paths(component: str) -> None:
    path = "Redump/Sony - PlayStation Portable/Example Game (USA).zip"
    torrent, _ = _torrent({b"length": 1, b"path": [b"Redump", component.encode()]})

    with pytest.raises(SourceUnavailable, match="unsafe torrent path"):
        _FixtureSource(_entry(path), torrent).find_url_for_game("Example Game")


def test_rejects_case_fold_duplicate_torrent_paths() -> None:
    path = "Redump/Sony - PlayStation Portable/Example Game (USA).zip"
    torrent, _ = _torrent(
        {b"length": 1, b"path": [part.encode() for part in path.split("/")]},
        {
            b"length": 1,
            b"path": [part.swapcase().encode() for part in path.split("/")],
        },
    )

    with pytest.raises(SourceUnavailable, match="case-fold duplicate"):
        _FixtureSource(_entry(path), torrent).find_url_for_game("Example Game")


def test_rejects_oversized_torrent_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    path = "Redump/Sony - PlayStation Portable/Example Game (USA).zip"
    monkeypatch.setattr(minerva_torrent, "_MAX_TORRENT_BYTES", 8)

    with pytest.raises(SourceUnavailable, match="metadata exceeds 8 bytes"):
        _FixtureSource(_entry(path), b"x" * 9).find_url_for_game("Example Game")


def test_download_requires_qbittorrent_coordinator(tmp_path: object) -> None:
    source = _FixtureSource(None, b"")

    with pytest.raises(SourceUnavailable, match="qBittorrent coordinator"):
        source.download(None, tmp_path)  # type: ignore[arg-type]


def test_supplemental_title_uses_its_torrent_root_and_metadata() -> None:
    root = "RetroAchievements/RA - Sony PSP"
    path = f"{root}/Example Game (USA).zip"
    torrent, _ = _torrent(
        {b"length": 123, b"path": [part.encode() for part in path.split("/")]}
    )
    source = _FixtureSource(
        _entry(path),
        torrent,
        root=root,
        console_entry={
            "minerva_path": "Redump/Sony - PlayStation Portable",
            "minerva_paths": [root],
        },
    )

    candidate = source.find_url_for_game("Example Game", ["USA"])

    assert candidate is not None
    assert candidate.url == (
        "https://minerva-archive.org/assets/Minerva_Myrient_v0.3/"
        "Minerva_Myrient%20-%20RetroAchievements%20-%20RA%20-%20Sony%20PSP.torrent"
    )
    assert candidate.extra is not None
    assert candidate.extra["minerva_path"] == root
    assert candidate.extra["torrent_internal_path"] == path
    assert source.fetch_urls == [candidate.url]


def test_selected_root_owns_catalog_containment_check() -> None:
    primary = "Redump/Sony - PlayStation Portable"
    supplement = "RetroAchievements/RA - Sony PSP"
    primary_path = f"{primary}/Example Game (USA).zip"
    torrent, _ = _torrent(
        {
            b"length": 1,
            b"path": [part.encode() for part in primary_path.split("/")],
        }
    )
    source = _FixtureSource(
        _entry(primary_path),
        torrent,
        root=supplement,
        console_entry={"minerva_path": primary, "minerva_paths": [supplement]},
    )

    with pytest.raises(SourceUnavailable, match="escapes its console collection"):
        source.find_url_for_game("Example Game", ["USA"])


def test_duplicate_title_selected_from_primary_does_not_probe_supplement() -> None:
    primary = "Redump/Sony - PlayStation Portable"
    path = f"{primary}/Example Game (USA).zip"
    torrent_without_selected_path, _ = _torrent(
        {
            b"length": 1,
            b"path": [
                part.encode()
                for part in f"{primary}/Other Game (USA).zip".split("/")
            ],
        }
    )
    source = _FixtureSource(
        _entry(path),
        torrent_without_selected_path,
        root=primary,
        console_entry={
            "minerva_path": primary,
            "minerva_paths": ["RetroAchievements/RA - Sony PSP"],
        },
    )

    assert source.find_url_for_game("Example Game", ["USA"]) is None
    assert len(source.fetch_urls) == 1
    assert "Redump%20-%20Sony%20-%20PlayStation%20Portable" in source.fetch_urls[0]


def test_download_re_resolves_current_root_priority() -> None:
    primary = "Redump/Sony - PlayStation Portable"
    supplement = "RetroAchievements/RA - Sony PSP"
    primary_path = f"{primary}/Example Game (USA).zip"
    supplement_path = f"{supplement}/Example Game (USA).zip"
    torrent, _ = _torrent(
        {
            b"length": 1,
            b"path": [part.encode() for part in primary_path.split("/")],
        }
    )
    console_entry = {
        "minerva_path": primary,
        "minerva_paths": [supplement],
    }
    browsed_during_outage = _FixtureSource(
        _entry(supplement_path),
        b"",
        root=supplement,
        console_entry=console_entry,
    )
    source_after_recovery = _FixtureSource(
        _entry(primary_path),
        torrent,
        root=primary,
        console_entry=console_entry,
    )

    assert browsed_during_outage.list_popular(0, ["USA"]) == ["Example Game"]
    candidate = source_after_recovery.find_url_for_game("Example Game", ["USA"])

    assert candidate is not None and candidate.extra is not None
    assert candidate.extra["minerva_path"] == primary
    assert candidate.extra["torrent_internal_path"] == primary_path
    assert "Redump%20-%20Sony%20-%20PlayStation%20Portable" in candidate.url


def test_supplemental_multifile_entry_never_produces_torrent_candidate() -> None:
    root = "T-En Collection/Sony - PlayStation [T-En] Collection"
    source = _FixtureSource(
        _entry(
            f"{root}/Example Game (World) (Disc 1).zip",
            f"{root}/Example Game (World) (Disc 2).zip",
        ),
        b"",
        root=root,
        console_entry={
            "minerva_path": "Redump/Sony - PlayStation",
            "minerva_paths": [root],
        },
    )

    assert source.find_url_for_game("Example Game", ["World"]) is None
    assert source.fetch_urls == []
