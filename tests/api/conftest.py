import pytest
from fastapi.testclient import TestClient

from bayle.api.app import create_app
from bayle.api.settings import ApiSettings

TOKEN = "t" * 32


@pytest.fixture
def app():
    return create_app(ApiSettings(token=TOKEN))


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c
