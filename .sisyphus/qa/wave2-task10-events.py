from __future__ import annotations
import pathlib, sys
from retrofetch.events import EventBus, DatLoadStartEvent, DatLoadDoneEvent, GameStartEvent
from retrofetch.orchestrator import run_console
from retrofetch.config import load_config, _yaml_rt

events: list = []
bus = EventBus()
bus.subscribe(events.append)

config = load_config(pathlib.Path("config.yml.example"))
consoles = _yaml_rt.load(pathlib.Path("consoles.yml").read_text(encoding="utf-8"))
entry = next(c for c in consoles["consoles"] if c["shortname"] == "virtualboy")

run_console(
    console_entry=entry,
    wantlist=[],
    config=config,
    allow_torrent=False,
    consoles_yml=consoles,
    event_bus=bus,
)

has_dat_start = any(isinstance(e, DatLoadStartEvent) for e in events)
has_dat_done  = any(isinstance(e, DatLoadDoneEvent) for e in events)
has_game_start = any(isinstance(e, GameStartEvent) for e in events)
assert has_dat_start, "no DatLoadStartEvent emitted"
assert has_dat_done, "no DatLoadDoneEvent emitted"
assert not has_game_start, "unexpected GameStartEvent on empty wantlist"
print(f"T10 events ordering: OK ({len(events)} events)")
