"""The Settings page and operations over HTTP."""

from fastapi.testclient import TestClient

from bayle.api.app import create_app
from bayle.api.settings import ApiSettings
from bayle.session import Session
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from bayle.work.prompts import PlanStore
from support import er

TOKEN = "t" * 32


def test_the_page_a_change_and_a_refusal():
    session = Session(JobManager(EventBus(), spawn=lambda run, name=None: run()), plans=PlanStore(), locations=er)
    with TestClient(create_app(ApiSettings(token=TOKEN), session), base_url="http://127.0.0.1") as c:
        c.headers.update({"Authorization": f"Bearer {TOKEN}"})
        page = c.get("/v1/pages/settings").json()
        assert page["game"] == "eldenring" and any(s["key"] == "logo" for s in page["specs"])
        assert c.post("/v1/ops/settings.set", json={"key": "logo", "value": "gold"}).json()["value"] == "gold"
        assert c.get("/v1/pages/settings").json()["logo"] == "gold"
        bad = c.post("/v1/ops/settings.set", json={"key": "logo", "value": "purple"})
        assert bad.status_code == 400 and bad.json()["code"] == "invalid_choice"
