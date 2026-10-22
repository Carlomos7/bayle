import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import ValidationError

from bayle import __version__
from bayle.api.app import create_app
from bayle.api.models import CONTRACT_VERSION
from bayle.api.settings import ApiSettings
from bayle.services.errors import Busy, OperationError

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "t" * 32
AUTH = {"Authorization": f"Bearer {TOKEN}"}
ORIGINS = ["http://tauri.localhost", "https://tauri.localhost", "tauri://localhost"]


def test_health(client):
    r = client.get("/v1/health", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"app_version": __version__, "contract_version": CONTRACT_VERSION, "ready": True}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic " + TOKEN}])
def test_bad_token_is_401(client, headers):
    assert client.get("/v1/health", headers=headers).status_code == 401


def test_non_ascii_token_is_401_not_500(client):
    r = client.get("/v1/health", headers={"Authorization": "Bearer ñandú".encode("latin-1")})
    assert r.status_code == 401


def test_every_route_requires_token(app):
    """A router added later without the app-level dependency would 200 here."""
    app.include_router(_extra_router())
    with TestClient(app, base_url="http://127.0.0.1") as c:
        for route in app.routes:
            path = getattr(route, "path", None)
            if path:
                assert c.get(path).status_code in (401, 405), path


def _extra_router():
    r = APIRouter()
    r.add_api_route("/v1/extra", lambda: {}, methods=["GET"])
    return r


def test_docs_and_spec_routes_are_off(client):
    for p in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(p, headers=AUTH).status_code == 404


@pytest.mark.parametrize("origin", ORIGINS)
def test_cors_allowed_origin(client, origin):
    r = client.get("/v1/health", headers={**AUTH, "Origin": origin})
    assert r.headers["access-control-allow-origin"] == origin
    assert "access-control-allow-credentials" not in r.headers


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "http://localhost", "http://tauri.localhost:1"])
def test_cors_rejected_origin(client, origin):
    r = client.options("/v1/health", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
    assert r.status_code == 400
    assert "access-control-allow-origin" not in r.headers


def test_vite_origin_only_in_dev():
    for dev, expected in ((False, None), (True, "http://localhost:1420")):
        app = create_app(ApiSettings(token=TOKEN, dev=dev))
        with TestClient(app, base_url="http://127.0.0.1") as c:
            r = c.get("/v1/health", headers={**AUTH, "Origin": "http://localhost:1420"})
            assert r.headers.get("access-control-allow-origin") == expected


def test_bad_host_is_400(app):
    with TestClient(app, base_url="http://evil.example") as c:
        assert c.get("/v1/health", headers=AUTH).status_code == 400


def test_settings_require_token(monkeypatch):
    monkeypatch.delenv("BAYLE_API_TOKEN", raising=False)
    with pytest.raises(ValidationError):
        ApiSettings()


@pytest.mark.parametrize(
    ("error", "status"),
    [(Busy("Game running.", {"pid": 4}), 409), (OperationError("bad_input", "Nope."), 400)],
)
def test_operation_error_maps_to_problem(app, error, status):
    def boom():
        raise error

    r = APIRouter()
    r.add_api_route("/v1/boom", boom, methods=["GET"])
    app.include_router(r)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        resp = c.get("/v1/boom", headers=AUTH)
    assert resp.status_code == status
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.json() == {"code": error.code, "message": error.message, "details": error.details}


def test_openapi_snapshot_is_current():
    r = subprocess.run(
        [sys.executable, "scripts/export_openapi.py", "--check"], cwd=ROOT, capture_output=True, text=True
    )
    assert r.returncode == 0, r.stderr


def _spawn(env_extra):
    env = {k: v for k, v in os.environ.items() if k != "BAYLE_API_TOKEN"} | env_extra
    return subprocess.Popen(
        [sys.executable, "-m", "bayle", "--backend"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=ROOT,
    )


def test_backend_handshake_and_stdin_eof_exit():
    proc = _spawn({"BAYLE_API_TOKEN": TOKEN})
    try:
        hs = json.loads(proc.stdout.readline())
        assert hs["version"] == __version__ and hs["contract"] == CONTRACT_VERSION and hs["port"] > 0
        import httpx

        r = httpx.get(f"http://127.0.0.1:{hs['port']}/v1/health", headers=AUTH)
        assert r.status_code == 200
        proc.stdin.close()
        assert proc.wait(timeout=15) == 0
        assert proc.stdout.read() == b""
    finally:
        proc.kill()
        for f in (proc.stdin, proc.stdout, proc.stderr):
            f.close()


def test_backend_without_token_fails_fast():
    proc = _spawn({})
    out, _ = proc.communicate(timeout=30)
    assert proc.returncode != 0 and out == b""


def test_api_imports_no_qt():
    code = (
        "import sys, bayle.api.server; sys.exit(any(m.split('.')[0] in ('PySide6','shiboken6') for m in sys.modules))"
    )
    assert subprocess.run([sys.executable, "-c", code], cwd=ROOT).returncode == 0
