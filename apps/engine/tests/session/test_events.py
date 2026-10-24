from bayle.work.events import EventBus


def types(sub):
    out = []
    while (e := sub.get(0)) is not None:
        out.append(e)
    return out


def test_events_arrive_in_publish_order_with_increasing_seq():
    bus = EventBus()
    sub = bus.subscribe()
    for i in range(3):
        bus.publish("progress", {"i": i}, "j1")
    got = types(sub)
    assert [e.seq for e in got] == [1, 2, 3]
    assert [e.data["i"] for e in got] == [0, 1, 2]


def test_full_queue_drops_oldest_progress_but_keeps_everything_else():
    bus = EventBus()
    sub = bus.subscribe(maxsize=3)
    bus.publish("started", job_id="j1")
    bus.publish("prompt", {"ask": "?"}, "j1")
    for i in range(5):
        bus.publish("progress", {"i": i}, "j1")
    bus.publish("finished", job_id="j1")
    got = types(sub)
    kinds = [e.type for e in got]
    assert kinds[:2] == ["started", "prompt"] and kinds[-1] == "finished"
    assert [
        e.data["i"] for e in got if e.type == "progress"
    ] == []  # protected events fill the queue: all progress goes


def test_terminal_events_survive_a_flood_of_progress():
    bus = EventBus()
    sub = bus.subscribe(maxsize=4)
    bus.publish("started", job_id="j1")
    for i in range(50):
        bus.publish("progress", {"i": i}, "j1")
    bus.publish("failed", job_id="j1")
    kinds = [e.type for e in types(sub)]
    assert kinds[0] == "started" and kinds[-1] == "failed"
    assert len(kinds) == 4  # started, two newest progress, failed


def test_replay_from_seq_gives_exactly_the_later_events_then_live_ones():
    bus = EventBus()
    for _ in range(5):
        bus.publish("progress")
    sub = bus.subscribe(since=3)
    bus.publish("finished")
    assert [e.seq for e in types(sub)] == [4, 5, 6]


def test_asking_for_a_seq_the_ring_lost_starts_with_resync():
    bus = EventBus(buffer=3)
    for _ in range(10):
        bus.publish("progress")
    got = types(bus.subscribe(since=2))
    assert got[0].type == "resync" and got[0].data == {"requested": 2, "oldest": 8, "seq": 10}
    assert [e.seq for e in got[1:]] == [8, 9, 10]


def test_a_client_from_before_a_restart_gets_resync():
    bus = EventBus()
    bus.publish("progress")
    assert types(bus.subscribe(since=99))[0].type == "resync"


def test_closed_subscription_gets_nothing_more():
    bus = EventBus()
    sub = bus.subscribe()
    sub.close()
    bus.publish("progress")
    assert sub.get(0) is None and sub.closed


def test_notify_is_called_for_each_event():
    bus = EventBus()
    calls = []
    bus.subscribe(notify=lambda: calls.append(1))
    bus.publish("progress")
    bus.publish("progress")
    assert len(calls) == 2
