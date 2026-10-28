"""Games, profiles and Play over HTTP, on a session whose Launch service is the real one. The machine is invented:
profiles live in a temporary me3 folder, the game is never started (job_play* are replaced by recorders) and the
settings file is the test's own (tests/conftest.py)."""

import time

import pytest
from fastapi.testclient import TestClient

from bayle.api.app import create_app
from bayle.api.settings import ApiSettings
from bayle.modules.games import catalog
from bayle.modules.games import ports as game_ports
from bayle.modules.games.locate import Locations, Overrides
from bayle.modules.launch import play as play_service
from bayle.modules.launch.service import LaunchService
from bayle.modules.mods import rebuild as mod_merge
from bayle.modules.settings.service import load_settings, save_settings
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager

TOKEN = "t" * 32


class Machine:
    """What the routes run on: the current game, who switched it, and the launches that would have happened."""

    def __init__(self, tmp_path, monkeypatch, threaded=False):
        (tmp_path / "profiles").mkdir()
        me3 = tmp_path / "me3.exe"
        me3.write_bytes(b"not me3")
        self.loc = Locations(catalog.ELDEN_RING, Overrides(me3_exe=str(me3), profiles_dir=str(tmp_path / "profiles")))
        self.running, self.launched, self.switched = False, [], []
        monkeypatch.setattr(Locations, "game_running", lambda loc: self.running)
        monkeypatch.setattr(Locations, "game_dir", lambda loc: tmp_path)
        monkeypatch.setattr(game_ports, "installed_dir", lambda game: None)
        monkeypatch.setattr(mod_merge, "play_check", lambda profile, loc: None)
        for name in ("job_play", "job_play_offline", "job_play_vanilla"):
            monkeypatch.setattr(play_service, name, lambda *a, _n=name, **k: self.launched.append(_n))
        self.jobs = JobManager(EventBus(), spawn=None if threaded else lambda run, name=None: run())
        self.service = LaunchService(self.jobs, lambda: self.loc, self.select)

    def select(self, game):
        self.switched.append(game.key)
        self.loc = Locations(game, self.loc.overrides)
        return self.loc


def client_for(machine):
    app = create_app(ApiSettings(token=TOKEN), jobs=machine.jobs, services={"launch": machine.service})
    with TestClient(app, base_url="http://127.0.0.1") as c:
        c.headers.update({"Authorization": f"Bearer {TOKEN}"})
        yield c


@pytest.fixture
def machine(tmp_path, monkeypatch):
    return Machine(tmp_path, monkeypatch)


@pytest.fixture
def client(machine):
    yield from client_for(machine)


@pytest.fixture
def slow_client(tmp_path, monkeypatch):
    """Jobs on real threads, for a job that waits for an answer."""
    m = Machine(tmp_path, monkeypatch, threaded=True)
    m.client = next(client_for(m))
    return m


def new_profile(client, name="Mine") -> str:
    return client.post("/v1/launch/create_profile", json={"name": name}).json()["profile"]


def wait_for(done):
    for _ in range(100):
        if done():
            return
        time.sleep(0.05)
    raise AssertionError("timed out")


def test_games_are_listed_and_one_is_selected_and_remembered(client, machine):
    got = client.get("/v1/games").json()["games"]
    assert [g["key"] for g in got][:2] == ["eldenring", "nightreign"] and got[0]["current"] and not got[1]["current"]
    after = client.post("/v1/games/select", json={"key": "nr"}).json()["games"]
    assert [g["key"] for g in after if g["current"]] == ["nightreign"] and machine.switched == ["nightreign"]
    assert load_settings().game == "nightreign"
    bad = client.post("/v1/games/select", json={"key": "pong"})
    assert bad.status_code == 400 and bad.json()["code"] == "unknown_game" and machine.switched == ["nightreign"]


def test_a_profile_is_created_listed_and_remembered(client):
    path = new_profile(client)
    listed = client.get("/v1/launch/profiles").json()["profiles"]
    assert [(p["profile"], p["active"]) for p in listed] == [(path, False)]
    chosen = client.post("/v1/launch/set_profile", json={"source": listed[0]["source"]}).json()["profiles"]
    assert chosen[0]["active"] and chosen[0]["problems"] == []
    assert client.post("/v1/launch/set_profile", json={"source": ""}).json()["profiles"][0]["active"] is False
    gone = client.post("/v1/launch/set_profile", json={"source": path + ".missing"})
    assert gone.status_code == 404 and gone.json()["code"] == "not_found"
    blank = client.post("/v1/launch/create_profile", json={"name": "  "})
    assert blank.status_code == 400 and blank.json()["code"] == "invalid_value"


def test_play_starts_the_launch_job_for_each_way_of_playing(client, machine):
    source = new_profile(client)
    for mode, called in (("profile", "job_play"), ("vanilla", "job_play_vanilla")):
        started = client.post("/v1/launch/play", json={"mode": mode, "source": source}).json()
        job = client.get(f"/v1/jobs/{started['job_id']}").json()
        assert job["state"] == "done" and job["result"] == {"mode": mode} and machine.launched[-1] == called
    save_settings(offline_skip_confirm=True)
    started = client.post("/v1/launch/play", json={"mode": "offline", "source": source}).json()
    assert client.get(f"/v1/jobs/{started['job_id']}").json()["state"] == "done"
    assert machine.launched == ["job_play", "job_play_vanilla", "job_play_offline"]


def test_play_is_refused_with_the_reason(client, machine):
    source = new_profile(client)
    checked = client.post("/v1/launch/check", json={"mode": "profile", "source": source}).json()
    assert checked["problems"] == [] and checked["installed"] and not checked["game_running"]
    machine.running = True
    refused = client.post("/v1/launch/play", json={"mode": "profile", "source": source})
    assert refused.status_code == 409 and refused.json()["code"] == "cannot_launch"
    assert refused.json()["details"]["reason"] == "game_running"
    machine.running = False
    missing = client.post("/v1/launch/check", json={"mode": "profile", "source": source + ".missing"})
    assert missing.status_code == 404
    assert client.post("/v1/launch/check", json={"mode": "hover"}).status_code == 422
    assert machine.launched == []


def test_offline_asks_first_and_cancel_stops_it_before_the_game_starts(slow_client):
    m = slow_client
    save_settings(offline_skip_confirm=False)
    source = new_profile(m.client)
    started = m.client.post("/v1/launch/play", json={"mode": "offline", "source": source}).json()
    wait_for(lambda: m.jobs.prompts.pending() == 1)
    assert m.jobs.prompts.words("q1").code == "offline_confirm"
    assert m.client.post("/v1/prompts/q1", json={"choice": "cancel"}).status_code == 200
    wait_for(lambda: m.jobs.get(started["job_id"]).state != "running")
    assert m.jobs.get(started["job_id"]).state == "cancelled" and m.launched == []
    again = m.client.post("/v1/launch/play", json={"mode": "offline", "source": source}).json()
    wait_for(lambda: m.jobs.prompts.pending() == 1)
    m.client.post("/v1/prompts/q2", json={"choice": "go"})
    wait_for(lambda: m.jobs.get(again["job_id"]).state != "running")
    assert m.jobs.get(again["job_id"]).state == "done" and m.launched == ["job_play_offline"]
