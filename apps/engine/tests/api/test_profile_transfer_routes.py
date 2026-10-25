"""The Profile transfer page and operations over HTTP, on a session whose Profile transfer service is the real one.
Invented profiles in the test's own folders; every request goes through JSON, a job comes back as an id, a malformed
body is 422 and never 500, an engine refusal is its code."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bayle.api.app import create_app
from bayle.api.settings import ApiSettings
from bayle.modules.mods.profile_transfer import ProfileTransferService
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from support import er

TOKEN = "t" * 32
PROFILE = (
    'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n\n[[packages]]\nid = "flora"\npath = \'mod/flora\'\n'
)


class Env:
    def __init__(self, tmp_path, client):
        self.tmp, self.client = tmp_path, client
        (tmp_path / "me" / "mod" / "flora").mkdir(parents=True)
        (tmp_path / "me" / "mod" / "flora" / "a.dcx").write_text("flora")
        self.profile = tmp_path / "me" / "my.me3"
        self.profile.write_text(PROFILE)

    def post(self, name, body=None):
        return self.client.post(f"/v1/{name.replace('.', '/')}", json=body or {})

    def job(self, started):
        """A started job's id from the response (200), and what GET /v1/jobs/{id} says of it."""
        assert started.status_code == 200, started.text
        body = started.json()
        assert list(body) == ["job_id"]
        got = self.client.get(f"/v1/jobs/{body['job_id']}")
        assert got.status_code == 200
        return got.json()

    def export_list(self):
        done = self.job(
            self.post(
                "profile_transfer.export", dict(profile=str(self.profile), name="Mine", folder=str(self.tmp / "out"))
            )
        )
        assert done["state"] == "done"
        return done["result"]["path"]


@pytest.fixture
def env(tmp_path):
    jobs = JobManager(EventBus(), spawn=lambda run, name=None: run())
    service = ProfileTransferService(jobs, er)
    services = {"profile_transfer": service}
    with TestClient(
        create_app(ApiSettings(token=TOKEN), jobs=jobs, services=services), base_url="http://127.0.0.1"
    ) as c:
        c.headers.update({"Authorization": f"Bearer {TOKEN}"})
        yield Env(tmp_path, c)


def test_the_page_lists_the_mods_an_export_holds(env):
    got = env.client.get("/v1/profile_transfer", params={"profile": str(env.profile)})
    assert got.status_code == 200
    [mod] = got.json()["mods"]
    assert mod["name"] and mod["size"] == 5 and mod["enabled"] is True


def test_an_export_returns_a_job_id_and_the_job_holds_the_result(env):
    done = env.job(
        env.post(
            "profile_transfer.export",
            dict(profile=str(env.profile), name="Mine", folder=str(env.tmp / "out"), with_configs=False),
        )
    )
    assert done["state"] == "done"
    out = Path(done["result"]["path"])
    assert (
        json.loads(out.read_text(encoding="utf-8"))["name"] == "Mine" and done["result"]["size"] == out.stat().st_size
    )


def test_a_failed_export_job_carries_its_code_and_details(env):
    done = env.job(
        env.post(
            "profile_transfer.export", dict(profile=str(env.profile), kind="full", name="P", folder=str(env.tmp / "o"))
        )
    )
    assert done["state"] == "failed" and done["error"]["code"] == "export_failed"
    assert done["error"]["details"]["name"] == "P"


def test_the_check_and_the_start_of_a_big_export_over_json(env, monkeypatch):
    monkeypatch.setattr("bayle.modules.mods.profile_transfer.LARGE_EXPORT", 1)
    key = env.client.get("/v1/profile_transfer", params={"profile": str(env.profile)}).json()["mods"][0]["key"]
    body = dict(profile=str(env.profile), kind="full", chosen=[key])
    checked = env.post("profile_transfer.check_export", body)
    assert checked.status_code == 200 and checked.json() == {"size": 5, "big": True}
    start = dict(body, name="Pack", folder=str(env.tmp / "o"))
    stale = env.post("profile_transfer.export", {**start, "expect": 6})
    assert stale.status_code == 409 and stale.json()["code"] == "stale"
    assert env.job(env.post("profile_transfer.export", {**start, "expect": 5}))["state"] == "done"


def test_open_preview_import_and_discard_over_http(env):
    out = env.export_list()
    dst = env.tmp / "b"
    (dst / "mod" / "flora").mkdir(parents=True)
    (dst / "mod" / "flora" / "a.dcx").write_text("flora")
    off = PROFILE.replace("path =", "enabled = false\npath =")  # the share list turns it on
    (dst / "my.me3").write_text(off)
    opened = env.post("profile_transfer.open_file", {"path": out})
    assert opened.status_code == 200 and opened.json()["kind"] == "json"
    resource = opened.json()["resource"]
    early = env.post("profile_transfer.import", {"resource": resource})
    assert early.status_code in (400, 409) and early.json()["code"] == "no_preview"
    pre = env.post("profile_transfer.preview", {"resource": resource, "profile": str(dst / "my.me3")})
    assert pre.status_code == 200 and pre.json()["serial"] == 1 and pre.json()["ok"] is True
    stale = env.post("profile_transfer.import", {"resource": resource, "expect": 7})
    assert stale.json()["code"] == "stale"
    assert env.job(env.post("profile_transfer.import", {"resource": resource, "expect": 1}))["state"] == "done"
    assert env.post("profile_transfer.discard", {"resource": resource}).json() == {"found": False}


def test_a_resource_that_is_gone_is_not_found(env):
    got = env.post("profile_transfer.preview", {"resource": "t404", "profile": str(env.profile)})
    assert got.status_code in (400, 404) and got.json()["code"] == "not_found"


@pytest.mark.parametrize(
    "name,body",
    [
        ("profile_transfer.export", {}),
        ("profile_transfer.export", {"profile": "p", "name": "n"}),
        ("profile_transfer.export", {"profile": "p", "name": "n", "folder": "f", "chosen": "all"}),
        ("profile_transfer.export", {"profile": "p", "name": "n", "folder": "f", "expect": "big"}),
        ("profile_transfer.export", {"profile": "p", "name": "n", "folder": "f", "extra": 1}),
        ("profile_transfer.check_export", {}),
        ("profile_transfer.check_export", {"profile": "p", "chosen": 3}),
        ("profile_transfer.open_file", {}),
        ("profile_transfer.open_bundled", {"unpacked": "u", "profiles": "x"}),
        ("profile_transfer.preview", {"resource": "t1"}),
        ("profile_transfer.preview", {"resource": "t1", "profile": "p", "choices": ["a"]}),
        ("profile_transfer.preview", {"resource": "t1", "profile": "p", "which": "first"}),
        ("profile_transfer.import", {}),
        ("profile_transfer.import", {"resource": "t1", "skip": "a"}),
        ("profile_transfer.import", {"resource": "t1", "expect": "latest"}),
        ("profile_transfer.discard", {}),
    ],
)
def test_bad_params_are_422_not_500(env, name, body):
    got = env.post(name, body)
    assert got.status_code == 422 and got.json()["code"] == "invalid_params"
