from retrofetch.events import EventBus, GameStartEvent

bus = EventBus()
a_received: list = []
b_received: list = []

handle_a = None


def cb_a(evt):
    a_received.append(evt)
    if handle_a is not None:
        bus.unsubscribe(handle_a)


def cb_b(evt):
    b_received.append(evt)


handle_a = bus.subscribe(cb_a)
bus.subscribe(cb_b)

for i in range(5):
    bus.publish(GameStartEvent(game=f"g{i}", source="x", console="nes"))

assert len(a_received) == 1, f"A should receive only 1 event (self-unsub), got {len(a_received)}"
assert len(b_received) == 5, f"B should receive all 5, got {len(b_received)}"
print("T7 unsubscribe-mid-dispatch: OK")
