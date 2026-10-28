"""The Merge page's build routes over HTTP, on the real BuildsService: a profile of two mods that ship the same game
file, rebuilt by the launcher's combine, then read back as the file-level report."""

import pytest
from fakegame import bnd, dcx
from fastapi.testclient import TestClient
from test_param_merge import vanilla

from bayle.adapters.games import discovery
from bayle.adapters.games import paths as common
from bayle.api.app import create_app
from bayle.api.settings import ApiSettings
from bayle.modules.mods import rebuild as merge
from bayle.modules.mods.builds import BuildsService, family_of
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from support import er

TOKEN = "t" * 32
REL = "menu/hi/01_common.sblytbnd.dcx"
GAME = {"SB_KG.layout": b"xbox buttons", "SB_Marker.layout": b"white marker", "SB_Map.layout": b"map"}


@pytest.fixture
def prof(tmp_path, monkeypatch):
    import fakegame

    game = tmp_path / "Game"
    game.mkdir()
    (game / "regulation.bin").write_bytes(vanilla())
    monkeypatch.setattr(discovery, "installed_dir", lambda _game: game)
    monkeypatch.setattr(common, "exe_running", lambda _exe: False)
    fakegame.game(monkeypatch, {REL: dcx(bnd(GAME))})
    base = tmp_path / "p"
    for name, change in (
        ("buttons", {"SB_KG.layout": b"ps5 buttons", "SB_Map.layout": b"big map"}),
        ("marker", {"SB_Marker.layout": b"blue marker", "SB_Map.layout": b"small map"}),
    ):
        (base / "mod" / name / "menu/hi").mkdir(parents=True)
        (base / "mod" / name / REL).write_bytes(dcx(bnd({**GAME, **change})))
    p = base / "p.me3"
    p.write_text(
        "[[packages]]\nid = \"buttons\"\npath = 'mod/buttons'\n\n[[packages]]\nid = \"marker\"\npath = 'mod/marker'\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def client():
    jobs = JobManager(EventBus(), spawn=lambda run, name=None: run())
    app = create_app(ApiSettings(token=TOKEN), jobs=jobs, services={"builds": BuildsService(jobs, er)})
    with TestClient(app, base_url="http://127.0.0.1") as c:
        c.headers.update({"Authorization": f"Bearer {TOKEN}"})
        yield c


def get(client, prof):
    got = client.get("/v1/builds", params={"profile": str(prof)})
    assert got.status_code == 200, got.text
    return got.json()


def test_families_come_from_the_path():
    assert [family_of(p) for p in ("regulation.bin", "msg/engus/item.msgbnd.dcx", "chr/c1.anibnd.dcx", REL)] == [
        "params",
        "text",
        "animations",
        "other",
    ]


def test_before_a_build_the_shared_file_is_a_reason_to_rebuild(client, prof):
    body = get(client, prof)
    assert body["state"] in ("stacked", "single")
    assert [m["name"] for m in body["mods"]] == ["buttons", "marker"] and body["files"] == []
    assert any("can be merged" in r for r in body["reasons"]) and body["built_on"] == ""
    plan = client.post("/v1/builds/preview", json={"profile": str(prof)}).json()
    assert plan["files"] == [REL] and plan["packs"] == [] and plan["blocked"] == ""


def test_after_a_rebuild_the_file_lists_its_mods_and_where_they_met(client, prof):
    merge.rebuild(prof, lambda s: None, loc=er())
    body = get(client, prof)
    assert body["state"] == "current" and body["reasons"] == [] and body["built_on"]
    assert [m["name"] for m in body["mods"]] == ["buttons", "marker"]  # the combined package is not a mod
    (f,) = body["files"]
    ids = [m["index"] for m in body["mods"]]
    assert (f["path"], f["family"], f["merged"], f["mods"]) == (REL, "other", True, ids)
    assert [(c["part"], c["mods"]) for c in f["clashes"]] == [("n:/gr/data/sb_map.layout", ids)]  # the last one wins it
    assert body["dropped"] == []


def test_a_file_that_cannot_be_merged_drops_the_earlier_copies_and_accepting_is_kept(client, prof, monkeypatch):
    import fakegame

    fakegame.game(monkeypatch, {})  # the game has no such file: nothing to compare with
    merge.rebuild(prof, lambda s: None, combine=True, loc=er())
    (d,) = get(client, prof)["dropped"]
    assert (d["file"], d["kind"], d["accepted"]) == (REL, "whole_copy", False) and "nothing to compare" in d["detail"]
    ok = client.post(f"/v1/builds/dropped/{d['id']}/accept", json={"profile": str(prof)})
    assert ok.status_code == 200 and ok.json() == {"id": d["id"]}
    assert get(client, prof)["dropped"][0]["accepted"] is True
    assert get(client, prof)["dropped"][0]["id"] == d["id"]  # stable
    none = client.post("/v1/builds/dropped/nope/accept", json={"profile": str(prof)})
    assert none.status_code == 404 and none.json()["code"] == "not_found"


def test_a_profile_that_is_not_there_is_not_found(client, tmp_path):
    for got in (
        client.get("/v1/builds", params={"profile": str(tmp_path / "x.me3")}),
        client.post("/v1/builds/preview", json={"profile": str(tmp_path / "x.me3")}),
    ):
        assert got.status_code == 404 and got.json()["code"] == "not_found"
