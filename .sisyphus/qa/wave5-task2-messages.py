from __future__ import annotations
from pathlib import Path
from retrofetch.tui.messages import (
    WantlistReady, WantlistFailed, SetupComplete,
    GameStart, GameBytes, GameDone, GameFailed, SourceDead, RateLimit,
    CloudflareBlock, DatLoadStart, DatLoadDone, ExtractionStart, ExtractionDone,
    DownloadComplete, DownloadCrashed, CoverageReady,
    EventBusBridge, wire_event_bus,
)

# WantlistReady
m1 = WantlistReady(console="nes", titles=["Alpha", "Beta"], from_cache=True)
assert m1.console == "nes"
assert m1.titles == ["Alpha", "Beta"]
assert m1.from_cache is True

# WantlistFailed
m2 = WantlistFailed(console="snes", reason="network down")
assert m2.console == "snes"
assert m2.reason == "network down"

# SetupComplete
p = Path("config.yml")
m3 = SetupComplete(config_path=p)
assert m3.config_path == p

out = "ux-task-2 messages OK\n"
evidence = Path(".sisyphus/evidence/ux-task-2-messages.txt")
evidence.parent.mkdir(parents=True, exist_ok=True)
evidence.write_text(out, encoding="utf-8")
print(out.strip())
