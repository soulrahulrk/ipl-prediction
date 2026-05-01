from __future__ import annotations

import importlib

import pytest

from ipl_predictor.auth import hash_password
from ipl_predictor.db import get_db_session
from ipl_predictor.models import Invite, Prediction, User


@pytest.fixture
def app_client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("CSRF_ENABLED", "false")
    monkeypatch.setenv("MONITORING_STORAGE", "file")

    web_app = importlib.import_module("web_app")

    class DummyScoreModel:
        def predict(self, _features):
            return [184.5]

    class DummyWinModel:
        def predict_proba(self, _features):
            return [[0.35, 0.65]]

    monkeypatch.setattr(web_app, "load_models", lambda: (DummyScoreModel(), DummyWinModel()))
    monkeypatch.setattr(web_app, "load_pre_match_models", lambda: (DummyScoreModel(), DummyWinModel()))

    app = web_app.create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        yield app, client


def _create_user(email: str, password: str, is_admin: bool = False) -> User:
    db_session = get_db_session()
    user = User(email=email, password_hash=hash_password(password), is_admin=is_admin, is_active=True)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _login(client, email: str, password: str):
    return client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=False)


def test_auth_required_for_api_predict(app_client):
    _app, client = app_client
    response = client.post("/api/predict", json={"season": "2026"})
    assert response.status_code == 401


def test_login_and_prediction_persisted(app_client):
    _app, client = app_client
    _create_user("user@example.com", "password123", is_admin=False)

    login_response = _login(client, "user@example.com", "password123")
    assert login_response.status_code in (302, 303)

    response = client.post(
        "/api/predict",
        json={
            "season": "2026",
            "venue": "Wankhede Stadium",
            "batting_team": "Mumbai Indians",
            "bowling_team": "Chennai Super Kings",
            "innings": 1,
            "runs": 92,
            "wickets": 2,
            "overs": "10.2",
            "runs_last_5": 41,
            "wickets_last_5": 1,
            "striker": "Rohit Sharma",
            "bowler": "Matheesha Pathirana",
            "use_live_weather": False,
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload.get("prediction_id")

    db_session = get_db_session()
    row = db_session.query(Prediction).filter(Prediction.id == int(payload["prediction_id"])).one_or_none()
    assert row is not None
    assert row.input_payload["batting_team"] == "Mumbai Indians"


def test_predict_schema_validation_blocks_invalid_values(app_client):
    _app, client = app_client
    _create_user("user2@example.com", "password123", is_admin=False)
    _login(client, "user2@example.com", "password123")

    response = client.post(
        "/api/predict",
        json={
            "season": "2026",
            "venue": "Wankhede Stadium",
            "batting_team": "Mumbai Indians",
            "bowling_team": "Mumbai Indians",
            "innings": 1,
            "runs": -5,
            "wickets": 12,
            "overs": "20.6",
        },
    )
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error"]["details"]


def test_admin_required_for_outcome_endpoint(app_client):
    _app, client = app_client
    _create_user("user3@example.com", "password123", is_admin=False)
    _login(client, "user3@example.com", "password123")

    response = client.post("/api/monitoring/outcome", json={"actual_total": 180})
    assert response.status_code == 403


def test_admin_can_create_invite_and_history_route(app_client):
    _app, client = app_client
    _create_user("admin@example.com", "password123", is_admin=True)
    _login(client, "admin@example.com", "password123")

    invite_response = client.post("/admin/invites", data={"email": "new-user@example.com"}, follow_redirects=True)
    assert invite_response.status_code == 200

    db_session = get_db_session()
    invite = db_session.query(Invite).filter(Invite.email == "new-user@example.com").one_or_none()
    assert invite is not None

    history_response = client.get("/history")
    assert history_response.status_code == 200


def test_history_json_endpoint_returns_prediction_rows(app_client):
    _app, client = app_client
    _create_user("history@example.com", "password123", is_admin=False)
    _login(client, "history@example.com", "password123")

    pred_resp = client.post(
        "/api/predict",
        json={
            "season": "2026",
            "venue": "Wankhede Stadium",
            "batting_team": "Mumbai Indians",
            "bowling_team": "Chennai Super Kings",
            "innings": 1,
            "runs": 80,
            "wickets": 2,
            "overs": "9.3",
        },
    )
    assert pred_resp.status_code == 200

    history_api = client.get("/api/history?limit=10&offset=0")
    assert history_api.status_code == 200
    payload = history_api.get_json()
    assert payload["ok"] is True
    assert payload["pagination"]["count"] >= 1
    assert payload["history"]


def test_healthz_endpoint(app_client):
    _app, client = app_client
    response = client.get("/healthz")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert "database" in payload
