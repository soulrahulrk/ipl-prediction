from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from ipl_predictor.common import (
    MODEL_FEATURES,
    PRE_MATCH_SCORE_MODEL_PATH,
    PRE_MATCH_WIN_MODEL_PATH,
    SCORE_MODEL_PATH,
    WIN_MODEL_PATH,
    SupportTables,
    build_feature_frame,
    load_models,
    load_pre_match_models,
    normalize_team,
    normalize_venue,
    parse_overs,
    predict_pre_match,
    predict_match_state,
)
from scripts.preprocess_ipl import build_historical_venue_stats


class DummyScoreModel:
    def predict(self, X: pd.DataFrame):
        row = X.iloc[0]
        projected = float(row["runs"]) + (float(row["balls_left"]) / 6.0) * 8.0
        return np.array([projected])


class DummyWinModel:
    def predict_proba(self, X: pd.DataFrame):
        row = X.iloc[0]
        base = 0.50 + 0.002 * float(row["runs_vs_par"])
        p1 = min(0.99, max(0.01, base))
        return np.array([[1.0 - p1, p1]])


@pytest.fixture
def support_tables() -> SupportTables:
    return SupportTables(
        venue_stats={
            "Wankhede Stadium": {
                "venue_avg_first_innings": 172.0,
                "venue_avg_second_innings": 160.0,
                "venue_bat_first_win_rate": 0.55,
            }
        },
        team_form_map={
            "Mumbai Indians": 0.62,
            "Chennai Super Kings": 0.58,
        },
        team_venue_form_map={
            ("Mumbai Indians", "Wankhede Stadium"): 0.64,
            ("Chennai Super Kings", "Wankhede Stadium"): 0.56,
        },
        matchup_form_map={
            ("Mumbai Indians", "Chennai Super Kings"): 0.52,
            ("Chennai Super Kings", "Mumbai Indians"): 0.48,
        },
        batter_form_map={
            "Rohit Sharma": {"striker_form_sr": 132.0, "striker_form_avg": 31.0}
        },
        bowler_form_map={
            "Jasprit Bumrah": {"bowler_form_econ": 7.2, "bowler_form_strike": 18.0}
        },
        batter_bowler_map={
            ("Rohit Sharma", "Jasprit Bumrah"): {
                "batter_vs_bowler_sr": 121.0,
                "batter_vs_bowler_balls": 44.0,
            }
        },
    )


@pytest.fixture
def valid_payload() -> dict[str, object]:
    return {
        "season": "2025",
        "venue": "Wankhede Stadium",
        "batting_team": "Mumbai Indians",
        "bowling_team": "Chennai Super Kings",
        "striker": "Rohit Sharma",
        "bowler": "Jasprit Bumrah",
        "innings": 1,
        "runs": 92,
        "wickets": 2,
        "overs": "10.2",
        "runs_last_5": 41,
        "wickets_last_5": 1,
        "use_live_weather": False,
    }


def test_alias_normalization():
    assert normalize_team("Delhi Daredevils") == "Delhi Capitals"
    assert normalize_team("Royal Challengers Bangalore") == "Royal Challengers Bengaluru"
    assert normalize_venue("Wankhede Stadium, Mumbai") == "Wankhede Stadium"


def test_parse_overs_valid_and_invalid():
    assert parse_overs("0.0") == 0
    assert parse_overs("12.3") == 75
    with pytest.raises(ValueError):
        parse_overs("14.7")


def test_input_validation_required_fields(support_tables: SupportTables, valid_payload: dict[str, object]):
    payload = dict(valid_payload)
    payload["season"] = ""
    _, errors = build_feature_frame(payload, support_tables)
    assert any("Season is required" in err for err in errors)


def test_feature_frame_columns_are_consistent(support_tables: SupportTables, valid_payload: dict[str, object]):
    features, errors = build_feature_frame(valid_payload, support_tables)
    assert not errors
    assert list(features.columns) == MODEL_FEATURES


def test_second_innings_requires_first_innings_total(
    support_tables: SupportTables,
    valid_payload: dict[str, object],
):
    payload = dict(valid_payload)
    payload["innings"] = 2
    features, errors = build_feature_frame(payload, support_tables)
    assert features.empty
    assert any("First innings total is required" in err for err in errors)


def test_predict_match_state_smoke(support_tables: SupportTables, valid_payload: dict[str, object]):
    prediction, errors = predict_match_state(
        valid_payload,
        support_tables=support_tables,
        score_model=DummyScoreModel(),
        win_model=DummyWinModel(),
    )
    assert not errors
    assert prediction is not None
    assert "predicted_total" in prediction
    assert "projected_range" in prediction
    assert "collapse_risk_pct" in prediction
    assert "win_prob_pct" in prediction


def test_venue_snapshot_is_leakage_safe():
    summaries = [
        {
            "match_id": 1,
            "match_path": "dummy1.csv",
            "match_date": date(2020, 1, 1),
            "venue": "Wankhede Stadium",
            "innings_totals": {1: 150.0, 2: 140.0},
            "batting_first_team": "Mumbai Indians",
            "winner": "Mumbai Indians",
        },
        {
            "match_id": 2,
            "match_path": "dummy2.csv",
            "match_date": date(2020, 1, 10),
            "venue": "Wankhede Stadium",
            "innings_totals": {1: 180.0, 2: 170.0},
            "batting_first_team": "Chennai Super Kings",
            "winner": "Chennai Super Kings",
        },
    ]

    match_venue_stats, _ = build_historical_venue_stats(summaries)

    # First match sees no prior venue history.
    assert match_venue_stats[1]["venue_avg_first_innings"] == 0.0

    # Second match must only use match 1 prior history, not its own totals.
    assert match_venue_stats[2]["venue_avg_first_innings"] == 150.0
    assert match_venue_stats[2]["venue_avg_second_innings"] == 140.0


def test_model_loading_when_artifacts_exist():
    if not SCORE_MODEL_PATH.exists() or not WIN_MODEL_PATH.exists():
        pytest.skip("Model artifacts are not available in this workspace")

    score_model, win_model = load_models()
    assert hasattr(score_model, "predict")
    assert hasattr(win_model, "predict_proba")


def test_real_saved_models_can_run_live_prediction():
    if not SCORE_MODEL_PATH.exists() or not WIN_MODEL_PATH.exists():
        pytest.skip("Live model artifacts are not available in this workspace")

    score_model, win_model = load_models()
    support_tables = SupportTables(
        venue_stats={},
        team_form_map={},
        team_venue_form_map={},
        matchup_form_map={},
        batter_form_map={},
        bowler_form_map={},
        batter_bowler_map={},
    )
    payload = {
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
    }

    prediction, errors = predict_match_state(payload, support_tables, score_model, win_model)
    assert not errors
    assert prediction is not None
    assert float(prediction["predicted_total"]) >= float(payload["runs"])
    assert 0.0 <= float(prediction["win_prob"]) <= 1.0


def test_real_saved_models_can_run_pre_match_prediction():
    if not PRE_MATCH_SCORE_MODEL_PATH.exists() or not PRE_MATCH_WIN_MODEL_PATH.exists():
        pytest.skip("Pre-match model artifacts are not available in this workspace")

    score_model, win_model = load_pre_match_models()
    prediction = predict_pre_match(
        team1="Mumbai Indians",
        team2="Chennai Super Kings",
        venue="Wankhede Stadium",
        score_model=score_model,
        win_model=win_model,
    )
    assert "error" not in prediction
    assert prediction["likely_winner"] in {"Mumbai Indians", "Chennai Super Kings"}
    assert prediction["team1"] == "Mumbai Indians"
    assert prediction["team2"] == "Chennai Super Kings"
