from __future__ import annotations

from pathlib import Path

from retrofetch.sources.coolrom import CoolROMSource

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / ".sisyphus" / "evidence" / "ux-p3-coolrom.txt"

HTML = """
<center><font size="2" color="#FFFFFF"><b>Top 25 Sega Genesis ROMs</b></font></center><br>
<center><a href="/roms/genesis/1283/Sonic_the_Hedgehog.php" title="Sonic the Hedgehog"><img src="x"><div class="info"><font size="1">Sonic the Hedgehog</font></div></a></center>
<center><a href="/roms/genesis/1255/Sonic_the_Hedgehog_2.php" title="Sonic the Hedgehog 2"><img src="x"><div class="info"><font size="1">Sonic the Hedgehog 2</font></div></a></center>
<div class="info">&raquo; <a href="/roms/genesis/1271/Sonic_the_Hedgehog_3.php" title="Sonic the Hedgehog 3"><font size="1">Sonic the Hedgehog 3</font></a></div>
<div class="info">&raquo; <a href="/roms/genesis/1213/Streets_of_Rage.php" title="Streets of Rage"><font size="1">Streets of Rage</font></a></div>
<div class="info">&raquo; <a href="/roms/genesis/1213/Streets_of_Rage.php" title="Streets of Rage"><font size="1">Streets of Rage</font></a></div>
</font></td></tr></table>
""".strip()


def main() -> int:
    source = CoolROMSource({"coolrom_slug": "genesis", "extensions": [".bin"]})

    def fake_get(path: str, *, allow_missing: bool = False) -> str | None:
        if path == "/roms/genesis/":
            return HTML
        return None

    source._get = fake_get  # type: ignore[method-assign]
    titles = source.list_popular(10)
    expected = [
        "Sonic the Hedgehog",
        "Sonic the Hedgehog 2",
        "Sonic the Hedgehog 3",
        "Streets of Rage",
    ]
    assert titles == expected, titles

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(
        "\n".join(["wave6-p3-coolrom: OK", *titles]) + "\n",
        encoding="utf-8",
    )
    print("wave6-p3-coolrom: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
