import json
import os
import subprocess
import sys

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import ValidationError

from bayle import __version__
from bayle.api.app import create_app
from bayle.api.models import CONTRACT_VERSION
from bayle.api.settings import ApiSettings
from bayle.errors import Busy, OperationError
from support import repo_root

ROOT = repo_root()
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


def _spawn(env_extra, data):
    drop = {"BAYLE_API_TOKEN", "BAYLE_DATA", "ROUNDTABLE_SOULS_DATA"}
    env = {k: v for k, v in os.environ.items() if k not in drop} | {"BAYLE_DATA": str(data)}
    env |= env_extra  # the backend sets up its data folder and logs; keep them out of the repo
    return subprocess.Popen(
        [sys.executable, "-m", "bayle", "--backend"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=ROOT,
    )


def test_backend_handshake_and_stdin_eof_exit(tmp_path):
    proc = _spawn({"BAYLE_API_TOKEN": TOKEN}, tmp_path)
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


@pytest.mark.parametrize("token", [None, "short"], ids=["missing", "under-16-characters"])
def test_backend_with_a_bad_token_says_so_and_exits_2(tmp_path, token):
    proc = _spawn({} if token is None else {"BAYLE_API_TOKEN": token}, tmp_path)
    out, err = proc.communicate(timeout=30)
    assert proc.returncode == 2 and out == b""
    assert b"BAYLE_API_TOKEN" in err and b"Traceback" not in err


def _data_refused(env):
    """Run --backend with this data environment; it must stop before its handshake."""
    drop = {"BAYLE_API_TOKEN", "BAYLE_DATA", "ROUNDTABLE_SOULS_DATA"}
    full = {k: v for k, v in os.environ.items() if k not in drop} | {"BAYLE_API_TOKEN": TOKEN} | env
    r = subprocess.run(
        [sys.executable, "-m", "bayle", "--backend"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        env=full,
        cwd=ROOT,
        timeout=30,
    )
    return r.returncode, r.stdout, r.stderr


def test_backend_without_bayle_data_refuses_to_guess_a_data_folder():
    code, out, err = _data_refused({})
    assert code == 2 and out == b"" and b"BAYLE_DATA" in err


def test_backend_refuses_a_data_folder_inside_the_program_or_repository():
    code, out, err = _data_refused({"BAYLE_DATA": str(ROOT / "bayle-data-here")})
    assert code == 2 and out == b"" and b"program folder" in err
    assert not (ROOT / "bayle-data-here").exists()


def test_backend_refuses_the_qt_apps_data_folder(tmp_path):
    local = tmp_path / "local"
    qt_data = local / "RoundtableSouls"
    env = {"BAYLE_DATA": str(qt_data), "LOCALAPPDATA": str(local), "XDG_DATA_HOME": str(local)}
    code, out, err = _data_refused(env)
    assert code == 2 and out == b"" and b"Qt app's data folder" in err
    assert not qt_data.exists()


def test_backend_whose_parent_closed_stdin_before_it_was_ready_exits_quietly(tmp_path):
    proc = _spawn({"BAYLE_API_TOKEN": TOKEN}, tmp_path)
    out, err = proc.communicate(input=b"", timeout=30)  # stdin closed at once, as by a parent that left
    assert proc.returncode == 0 and out == b""
    assert b"Traceback" not in err


def test_a_second_backend_on_the_same_data_folder_is_refused(tmp_path):
    first = _spawn({"BAYLE_API_TOKEN": TOKEN}, tmp_path)
    try:
        assert json.loads(first.stdout.readline())["port"] > 0
        second = _spawn({"BAYLE_API_TOKEN": TOKEN}, tmp_path)
        out, err = second.communicate(timeout=30)
        assert second.returncode == 3 and out == b""
        assert b"in use" in err
    finally:
        first.stdin.close()
        first.wait(timeout=15)
        for f in (first.stdout, first.stderr):
            f.close()


def test_api_imports_no_qt():
    code = (
        "import sys, bayle.api.server; sys.exit(any(m.split('.')[0] in ('PySide6','shiboken6') for m in sys.modules))"
    )
    assert subprocess.run([sys.executable, "-c", code], cwd=ROOT).returncode == 0
