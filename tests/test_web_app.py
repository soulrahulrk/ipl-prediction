from __future__ import annotations

import pytest

from ipl_predictor.common import SCORE_MODEL_PATH, WIN_MODEL_PATH


pytestmark = pytest.mark.skipif(
    not SCORE_MODEL_PATH.exists() or not WIN_MODEL_PATH.exists(),
    reason="Live model artifacts are not available in this workspace",
)


def test_api_predict_route_returns_prediction():
    from web_app import app

    client = app.test_client()
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
    assert "prediction" in payload
    assert "predicted_total" in payload["prediction"]


def test_api_predict_route_validates_bad_input():
    from web_app import app

    client = app.test_client()
    response = client.post("/api/predict", json={"season": "2026"})

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["errors"]


def test_api_monitoring_route_returns_report():
    from web_app import app

    client = app.test_client()
    response = client.get("/api/monitoring")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert "monitoring" in payload
    assert "status" in payload["monitoring"]


def test_api_monitoring_outcome_route_accepts_payload():
    from web_app import app

    client = app.test_client()
    response = client.post(
        "/api/monitoring/outcome",
        json={
            "actual_total": 184,
            "actual_win": 1,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert "outcome" in payload
    assert "monitoring" in payload
