"""Jobs and the SSE stream, against a real uvicorn in a thread (httpx's ASGI transport buffers streams)."""

import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi import APIRouter

from bayle.api.app import create_app
from bayle.api.settings import ApiSettings
from bayle.session import JobContext

TOKEN = "t" * 32
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class Live:
    def __init__(self):
        self.app = create_app(ApiSettings(token=TOKEN))
        self.release = threading.Event()
        r = APIRouter(prefix="/v1/test")

        @r.post("/job")
        def start(writes: bool = True, steps: int = 1) -> dict:
            def work(ctx: JobContext):
                for i in range(steps):
                    ctx.progress(i + 1, steps, f"step {i + 1}")
                end = time.monotonic() + 10
                while not (self.release.is_set() or ctx.cancelled() or time.monotonic() > end):
                    time.sleep(0.01)  # held open until the test lets go or cancels
                ctx.raise_if_cancelled()
                return {"ok": True}

            return {"id": self.app.state.jobs.start(work, title="demo", writes=writes)}

        self.app.include_router(r)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        self.server = uvicorn.Server(uvicorn.Config(self.app, log_level="error", timeout_graceful_shutdown=1))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [sock]}, daemon=True)
        self.thread.start()
        while not self.server.started:
            time.sleep(0.01)
        self.http = httpx.Client(base_url=self.url, headers=AUTH, timeout=10)

    @property
    def bus(self):
        return self.app.state.jobs.bus

    def start_job(self, **params) -> str:
        return self.http.post("/v1/test/job", params=params).json()["id"]

    def stream(self, last_event_id=None):
        headers = {} if last_event_id is None else {"Last-Event-ID": str(last_event_id)}
        return self.http.stream("GET", "/v1/events", headers=headers)

    def close(self):
        self.release.set()
        self.http.close()
        self.server.should_exit = True
        self.thread.join(10)


@pytest.fixture
def live():
    lv = Live()
    yield lv
    lv.close()


def messages(response, stop_after):
    """SSE messages as dicts, until one of type `stop_after`."""
    msg: dict = {}
    for line in response.iter_lines():
        if line == "":
            if msg and "data" in msg:
                yield msg
                if msg["event"] in stop_after:
                    return
            msg = {}
        elif not line.startswith(":"):
            key, _, value = line.partition(":")
            msg[key] = value.strip()


def wait_for(cond, timeout=5):
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)


def test_events_need_token(live):
    assert httpx.get(live.url + "/v1/events").status_code == 401


def test_stream_orders_events_with_seq_ids(live):
    with live.stream() as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        wait_for(lambda: live.bus.subscribers == 1)
        job = live.start_job(steps=2)
        live.release.set()
        got = list(messages(r, {"finished"}))
    assert [m["event"] for m in got] == ["started", "progress", "progress", "finished"]
    assert [int(m["id"]) for m in got] == sorted(int(m["id"]) for m in got)
    first = json.loads(got[0]["data"])
    assert first == {"seq": int(got[0]["id"]), "job_id": job, "type": "started", "data": {"title": "demo"}}
    assert json.loads(got[-1]["data"])["data"]["result"] == {"ok": True}


def test_last_event_id_replays_only_later_events(live):
    live.release.set()
    live.start_job(steps=0)
    wait_for(lambda: live.bus.seq >= 2)  # started, finished
    with live.stream(last_event_id=1) as r:
        got = list(messages(r, {"finished"}))
    assert [(m["id"], m["event"]) for m in got] == [("2", "finished")]


def test_too_old_last_event_id_gets_resync(live):
    live.bus._ring = type(live.bus._ring)(maxlen=2)  # a tiny ring so the start of history is lost
    for _ in range(5):
        live.bus.publish("progress", {"done": 1, "total": 9, "label": ""})
    with live.stream(last_event_id=1) as r:
        first = next(messages(r, set()))
    assert first["event"] == "resync"
    data = json.loads(first["data"])["data"]
    assert data["requested"] == 1 and data["seq"] == live.bus.seq and data["oldest"] > 2


def test_cancel_while_streaming(live):
    with live.stream() as r:
        wait_for(lambda: live.bus.subscribers == 1)
        job = live.start_job(steps=0)
        assert live.http.post(f"/v1/jobs/{job}/cancel").status_code == 200
        got = list(messages(r, {"cancelled"}))
    assert [m["event"] for m in got] == ["started", "cancelled"]
    snap = live.http.get(f"/v1/jobs/{job}").json()
    assert snap["state"] == "cancelled" and snap["error"]["code"] == "cancelled"


def test_job_snapshot_and_unknown_ids(live):
    live.release.set()
    job = live.start_job()
    wait_for(lambda: live.http.get(f"/v1/jobs/{job}").json()["state"] == "done")
    assert live.http.get(f"/v1/jobs/{job}").json()["result"] == {"ok": True}
    for call in (live.http.get, live.http.post):
        path = "/v1/jobs/nope" + ("/cancel" if call == live.http.post else "")
        r = call(path)
        assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_second_writing_job_is_409_with_reason(live):
    first = live.start_job()
    r = live.http.post("/v1/test/job")
    assert r.status_code == 409
    assert r.json()["details"] == {"reason": "job", "job_id": first}
    assert live.http.post("/v1/test/job", params={"writes": False}).status_code == 200  # reads still start


def test_busy_while_game_running(live):
    live.app.state.jobs._game_running = lambda: True
    r = live.http.post("/v1/test/job")
    assert r.status_code == 409 and r.json()["details"]["reason"] == "game_running"


def test_disconnect_closes_subscription(live):
    with live.stream() as r:
        wait_for(lambda: live.bus.subscribers == 1)
        live.start_job()
        next(messages(r, set()))
    wait_for(lambda: live.bus.subscribers == 0)


def test_subscriber_cap_and_release(live):
    streams = [live.stream() for _ in range(3)]
    for s in streams:
        s.__enter__()
    try:
        wait_for(lambda: live.bus.subscribers == 3)
        r = live.http.get("/v1/events")
        assert r.status_code == 429 and r.json()["code"] == "too_many_subscribers"
    finally:
        for s in streams:
            s.__exit__(None, None, None)
    wait_for(lambda: live.bus.subscribers == 0)
