from __future__ import annotations

from pathlib import Path

from internetarchive import search_items
from retrofetch.config import _yaml_rt


def probe(identifier: str, sample_limit: int = 3) -> tuple[str, int | None, list[str]]:
    search = search_items(
        f"collection:{identifier}",
        fields=["title"],
        sorts=["downloads desc"],
        params={"rows": max(sample_limit * 2, 8)},
    )
    titles: list[str] = []
    for row in search:
        title = row.get("title") if isinstance(row, dict) else None
        if title and title not in titles:
            titles.append(title)
        if len(titles) >= sample_limit:
            break
    return "ok" if titles else "empty", getattr(search, "num_found", None), titles


def main() -> int:
    consoles = _yaml_rt.load(Path("consoles.yml").read_text(encoding="utf-8"))["consoles"]
    print("shortname|display_name|class|identifier|status|num_found|sample_titles")
    for entry in consoles:
        identifier = entry.get("archive_org_identifier")
        if not identifier:
            continue
        status, num_found, titles = probe(str(identifier))
        print(
            f"{entry.get('shortname')}|{entry.get('display_name')}|{entry.get('class')}|{identifier}|{status}|{num_found}|{'; '.join(titles)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())