from __future__ import annotations

from pathlib import Path

from retrofetch.config import Config, _yaml_rt
from retrofetch.ranker import _SOURCE_FACTORIES, get_wantlist

ROOT = Path(__file__).resolve().parents[2]
CONSOLES_YML = ROOT / "consoles.yml"
CONFIG_EXAMPLE = ROOT / "config.yml.example"
EVIDENCE = ROOT / ".sisyphus" / "evidence" / "ux-p4-integration.txt"
TARGETS = ["gba", "atari2600", "nes"]


def main() -> int:
    consoles = _yaml_rt.load(CONSOLES_YML.read_text(encoding="utf-8"))["consoles"]
    config = Config(**_yaml_rt.load(CONFIG_EXAMPLE.read_text(encoding="utf-8")))
    by_shortname = {entry["shortname"]: entry for entry in consoles}

    lines = ["wave6-p4-integration: OK"]
    for shortname in TARGETS:
        entry = by_shortname[shortname]
        source_order = config.ranking_sources_by_class[str(entry["class"])]
        source_hits: list[str] = []
        for source_name in source_order:
            factory = _SOURCE_FACTORIES.get(source_name)
            if factory is None:
                continue
            try:
                titles = factory(entry).list_popular(limit=5, region_priority=config.region_priority)
            except Exception as exc:
                lines.append(f"{shortname}|{source_name}|error|{exc}")
                continue
            if len(titles) >= 3:
                source_hits.append(f"{source_name}:{len(titles)}")
                lines.append(f"{shortname}|{source_name}|titles|{'; '.join(titles[:5])}")
        wantlist = get_wantlist(entry, None, config, 5)
        assert wantlist, f"empty wantlist for {shortname}"
        assert source_hits, f"no adapter returned >=3 titles for {shortname}"
        lines.append(f"{shortname}|wantlist|{'; '.join(wantlist)}")

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wave6-p4-integration: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
