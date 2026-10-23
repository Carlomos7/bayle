"""The shell over HTTP: its page snapshot, its operations, the Launch flow's questions answered by id, and the push
events on the stream. A Shell over fakes: no game, no me3."""

import pytest
from fastapi.testclient import TestClient

from bayle.api.app import create_app
from bayle.api.settings import ApiSettings
from bayle.session import ops as _ops  # noqa: F401  registers the operations
from bayle.session.shell.service import Shell
from bayle.views.common import Choice, Choose
from support import FakeShellContext, InlineBackground

TOKEN = "t" * 32


@pytest.fixture
def shell(tmp_path):
    s = Shell(FakeShellContext(tmp_path, spawn=lambda run, name=None: run()), background=InlineBackground())
    yield s


@pytest.fixture
def client(shell):
    with TestClient(create_app(ApiSettings(token=TOKEN), shell.session), base_url="http://127.0.0.1") as c:
        c.headers.update({"Authorization": f"Bearer {TOKEN}"})
        yield c


def test_the_top_bar_is_a_page(client):
    body = client.get("/v1/pages/shell").json()
    assert body["game"] == "eldenring" and body["pill"]["mode"] == "profile" and body["status"]["text"]
    assert [g["key"] for g in body["games"] if g["checked"]] == ["eldenring"]


def test_an_operation_changes_the_shell_and_the_page_follows(client):
    assert client.post("/v1/ops/shell.set_mode", json={"mode": "vanilla"}).json() == {"mode": "vanilla"}
    assert client.get("/v1/pages/shell").json()["pill"]["mode"] == "vanilla"
    assert client.post("/v1/ops/shell.set_mode", json={"mode": "nope"}).status_code == 422


def test_a_launch_that_cannot_start_is_a_conflict_with_the_reason(client, shell):
    shell._on_running(True)
    got = client.post("/v1/ops/shell.launch", json={})
    assert got.status_code == 409 and got.json()["code"] == "cannot_launch"


def test_a_question_is_answered_by_id(client, shell):
    answers = []
    prompt_id = shell.jobs.prompts.ask(Choose("Retry?", (), (Choice("retry", "Retry"),)), answers.append)
    assert client.post(f"/v1/prompts/{prompt_id}", json={"choice": "retry"}).json() == {"ok": True}
    assert answers == ["retry"]
    gone = client.post(f"/v1/prompts/{prompt_id}", json={"choice": "retry"})
    assert gone.status_code == 404 and gone.json()["code"] == "unknown_prompt"
