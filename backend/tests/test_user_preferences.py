from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api import settings_routes
from app.api.deps import get_current_user
from app.api.settings_routes import router
from app.models.knowledge import UserSetting
from app.models.user import User


def _client(monkeypatch, engine):
    monkeypatch.setattr(settings_routes, "engine", engine)
    app = FastAPI()
    app.include_router(router)
    user = User(id=1, email="user@example.com", hashed_password="hash")
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_preferences_default_and_persist_per_user(monkeypatch, engine):
    client = _client(monkeypatch, engine)

    initial = client.get("/api/settings/preferences")
    assert initial.status_code == 200
    assert initial.json()["reading"]["gloss"]["auto_speak"] is False

    saved = client.put("/api/settings/preferences", json={"reading": {"gloss": {"auto_speak": True}}})
    assert saved.status_code == 200
    assert saved.json()["reading"]["gloss"]["auto_speak"] is True

    with Session(engine) as session:
        row = session.get(UserSetting, "user:1:preferences")
        assert row is not None
        assert '"auto_speak":true' in row.value_json

    loaded = client.get("/api/settings/preferences")
    assert loaded.json()["reading"]["gloss"]["auto_speak"] is True


def test_preferences_ignore_unknown_shape_and_keep_defaults(monkeypatch, engine):
    client = _client(monkeypatch, engine)
    response = client.put(
        "/api/settings/preferences",
        json={"reading": {"future": {"value": True}}, "unknown": {"value": True}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reading"]["gloss"]["auto_speak"] is False
    assert body["reading"]["future"] == {"value": True}
    assert body["unknown"] == {"value": True}

    with Session(engine) as session:
        row = session.get(UserSetting, "user:1:preferences")
        assert row is not None
        assert '"unknown"' in row.value_json
