import threading

from retrofetch.events import EventBus, GameStartEvent

bus = EventBus()
collected: list = []
bus.subscribe(collected.append)

THREADS = 10
PUBLISHES_PER_THREAD = 100
TOTAL = THREADS * PUBLISHES_PER_THREAD


def worker(n: int) -> None:
    for i in range(PUBLISHES_PER_THREAD):
        bus.publish(GameStartEvent(game=f"g{n}-{i}", source="archive_org", console="nes"))


threads = [threading.Thread(target=worker, args=(n,)) for n in range(THREADS)]
for t in threads:
    t.start()
for t in threads:
    t.join()

assert len(collected) == TOTAL, f"expected {TOTAL} events, got {len(collected)}"
print(f"T7 events thread-safety: OK ({len(collected)} events)")
