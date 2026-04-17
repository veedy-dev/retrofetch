from __future__ import annotations

import difflib
import io
from itertools import islice
from pathlib import Path
from time import perf_counter
import sys

from ruamel.yaml import YAML


ROOT = Path(__file__).resolve().parents[2]
YAML_PATHS = {
    "consoles": ROOT / "consoles.yml",
    "commented_config": ROOT / ".sisyphus" / "fixtures" / "commented-config.yml",
    "overrides": ROOT / "overrides.yml.example",
}


def load_ms(yaml: YAML, path: Path) -> float:
    text = path.read_text(encoding="utf-8")
    start = perf_counter()
    yaml.load(text)
    return (perf_counter() - start) * 1000


def round_trip_verdict(yaml: YAML, path: Path) -> tuple[str, list[str]]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.load(fh)

    buf = io.StringIO()
    yaml.dump(data, buf)
    dumped = buf.getvalue().encode("utf-8")
    original = path.read_bytes()

    if original == dumped:
        return "IDENTICAL", []

    diff = difflib.unified_diff(
        original.decode("utf-8").splitlines(),
        dumped.decode("utf-8").splitlines(),
        fromfile=str(path),
        tofile=f"{path} (dumped)",
        lineterm="",
    )
    diff_lines = list(islice(diff, 20))
    if not diff_lines:
        diff_lines = ["--- byte-level difference only"]
    return "DIVERGENT", diff_lines


def main() -> int:
    yaml = YAML(typ="rt", pure=False)
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.representer.add_representer(
        type(None),
        lambda representer, data: representer.represent_scalar(
            "tag:yaml.org,2002:null",
            "null",
        ),
    )

    with YAML_PATHS["consoles"].open("r", encoding="utf-8") as fh:
        yaml.load(fh)

    for label, path in YAML_PATHS.items():
        ms = load_ms(yaml, path)
        status = "PASS" if ms < 100 else "FAIL"
        print(f"load_{label}_ms={ms:.1f} {status}")

    verdict, diff = round_trip_verdict(yaml, YAML_PATHS["commented_config"])
    print(f"ROUND-TRIP: {verdict}")
    if diff:
        for line in diff:
            print(line)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
