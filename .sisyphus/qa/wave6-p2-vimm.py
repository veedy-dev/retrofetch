from __future__ import annotations

from pathlib import Path

from retrofetch.sources.vimm import VimmSource

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / ".sisyphus" / "evidence" / "ux-p2-vimm.txt"

INDEX_HTML = """
<div id="topTen" style="display:block">
<tr style="display:block"><td style="width:100%"><a href="834">Super Mario Bros.</a></td></tr>
<tr style="display:block"><td style="width:100%"><a href="836">Super Mario Bros. 3</a></td></tr>
<tr style="display:block"><td style="width:100%"><a href="504">Legend of Zelda, The</a></td></tr>
</tbody></table>
""".strip()

PAGE_2_HTML = """
<tr style="display:block"><td style="width:100%"><a href="558">Metroid</a></td></tr>
<tr style="display:block"><td style="width:100%"><a href="157">Castlevania</a></td></tr>
""".strip()


def main() -> int:
    source = VimmSource({"vimm_slug": "NES", "extensions": [".nes"]})

    def fake_get(path: str, *, allow_missing: bool = False) -> str | None:
        if path == "/vault/NES":
            return INDEX_HTML
        if path == "/vault/ajax/loadTopTen.php?system=NES&page=2":
            return PAGE_2_HTML
        return None

    source._get = fake_get  # type: ignore[method-assign]
    titles = source.list_popular(5)
    expected = [
        "Super Mario Bros.",
        "Super Mario Bros. 3",
        "Legend of Zelda, The",
        "Metroid",
        "Castlevania",
    ]
    assert titles == expected, titles

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(["wave6-p2-vimm: OK", *titles]) + "\n", encoding="utf-8")
    print("wave6-p2-vimm: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
