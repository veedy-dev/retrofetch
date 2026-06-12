from __future__ import annotations

from typing import Any

from retrofetch.sources.archive_org import ArchiveOrgSource


class _FixtureArchive(ArchiveOrgSource):
    def __init__(self, metadata: dict[str, Any]) -> None:
        super().__init__(
            {
                "archive_org_identifier": "demo item",
                "extensions": [".zip"],
                "exclude_keywords": ["(Beta)"],
            }
        )
        self.metadata = metadata

    def _fetch_metadata(self) -> dict[str, Any]:
        return self.metadata


def test_archive_metadata_catalog_filters_artifacts_and_resolves_exact_url() -> None:
    source = _FixtureArchive(
        {
            "files": [
                {
                    "name": "Good Game (Europe) (Rev 9).zip",
                    "size": "20",
                    "sha1": "e" * 40,
                },
                {
                    "name": "Good Game (USA).zip",
                    "size": "10",
                    "sha1": "a" * 40,
                    "crc32": "1234abcd",
                },
                {"name": "Good Game (USA) (Beta).zip", "size": "5"},
                {"name": "demo item_files.xml", "size": "1"},
                {"name": "demo item_archive.torrent", "size": "1"},
            ]
        }
    )

    titles = source.list_popular(limit=0, region_priority=["USA", "Europe"])
    candidate = source.find_url_for_game("Good Game", ["USA", "Europe"])

    assert titles == ["Good Game"]
    assert candidate is not None
    assert candidate.filename == "Good Game (USA).zip"
    assert candidate.expected_size == 10
    assert candidate.expected_sha1 == "a" * 40
    assert candidate.expected_crc32 == "1234abcd"
    assert candidate.url == (
        "https://archive.org/download/demo%20item/"
        "Good%20Game%20%28USA%29.zip"
    )


def test_archive_metadata_groups_multidisc_candidate_metadata() -> None:
    source = _FixtureArchive(
        {
            "files": [
                {"name": "Mega RPG (USA) (Disc 2).zip", "size": "2"},
                {"name": "Mega RPG (USA) (Disc 1).zip", "size": "1"},
            ]
        }
    )

    candidate = source.find_url_for_game("Mega RPG", ["USA"])

    assert candidate is not None
    assert candidate.filename == "Mega RPG (USA) (Disc 1).zip"
    assert candidate.extra is not None
    files = candidate.extra["catalog_files"]
    assert isinstance(files, list)
    assert [item["filename"] for item in files] == [
        "Mega RPG (USA) (Disc 1).zip",
        "Mega RPG (USA) (Disc 2).zip",
    ]


def test_archive_empty_metadata_is_empty_catalog() -> None:
    source = _FixtureArchive({"files": []})

    assert source.list_popular(limit=0, region_priority=["USA"]) == []
    assert source.find_url_for_game("Missing", ["USA"]) is None
