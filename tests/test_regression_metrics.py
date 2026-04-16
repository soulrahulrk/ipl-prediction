from __future__ import annotations

import json
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT_DIR / "models"
DEPLOYMENT_REPORT_PATH = MODELS_DIR / "deployment_report.json"
BEST_SEARCH_REPORT_PATH = MODELS_DIR / "best_model_search_report.json"
PRE_MATCH_REPORT_PATH = MODELS_DIR / "pre_match_model_report.json"
WIN_STABILITY_PROFILE_PATH = MODELS_DIR / "win_stability_profile.json"


LIVE_SCORE_MAE_MAX = 17.5
LIVE_SCORE_RMSE_MAX = 22.0
LIVE_WIN_LOG_LOSS_MAX = 0.56
LIVE_WIN_BRIER_MAX = 0.19
LIVE_WIN_ACCURACY_MIN = 0.64


pytestmark = pytest.mark.skipif(
    not DEPLOYMENT_REPORT_PATH.exists(),
    reason="Deployment report is not available in this workspace",
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_live_deployment_metrics_regression_guard() -> None:
    report = _load_json(DEPLOYMENT_REPORT_PATH)
    score = report.get("deployment_score_metrics_test", {})
    win = report.get("deployment_win_metrics_test", {})

    assert score.get("mae") is not None, "deployment_score_metrics_test.mae is missing"
    assert score.get("rmse") is not None, "deployment_score_metrics_test.rmse is missing"
    assert win.get("log_loss") is not None, "deployment_win_metrics_test.log_loss is missing"
    assert win.get("brier") is not None, "deployment_win_metrics_test.brier is missing"
    assert win.get("accuracy") is not None, "deployment_win_metrics_test.accuracy is missing"

    assert float(score["mae"]) <= LIVE_SCORE_MAE_MAX, "Live score MAE degraded beyond guardrail"
    assert float(score["rmse"]) <= LIVE_SCORE_RMSE_MAX, "Live score RMSE degraded beyond guardrail"
    assert float(win["log_loss"]) <= LIVE_WIN_LOG_LOSS_MAX, "Live win log loss degraded beyond guardrail"
    assert float(win["brier"]) <= LIVE_WIN_BRIER_MAX, "Live win Brier degraded beyond guardrail"
    assert float(win["accuracy"]) >= LIVE_WIN_ACCURACY_MIN, "Live win accuracy degraded beyond guardrail"


def test_difficult_slice_regression_guard() -> None:
    if not BEST_SEARCH_REPORT_PATH.exists():
        pytest.skip("best_model_search_report.json is not available")

    report = _load_json(BEST_SEARCH_REPORT_PATH)
    stability = report.get("selected_win_stability", {})
    slices_after = stability.get("test_slice_metrics_after", {})

    assert slices_after, (
        "selected_win_stability.test_slice_metrics_after is missing; "
        "run scripts/train_best_model_search.py to refresh difficult-slice metrics"
    )

    death = slices_after.get("death_over", {})
    pressure = slices_after.get("high_pressure_chase", {})

    if int(death.get("rows", 0)) >= 50:
        assert float(death.get("log_loss", 99.0)) <= 0.95, "Death-over slice log loss degraded"
        assert float(death.get("brier", 99.0)) <= 0.35, "Death-over slice Brier degraded"

    if int(pressure.get("rows", 0)) >= 50:
        assert float(pressure.get("log_loss", 99.0)) <= 1.10, "High-pressure chase slice log loss degraded"
        assert float(pressure.get("brier", 99.0)) <= 0.40, "High-pressure chase slice Brier degraded"


def test_win_stability_artifact_exists_and_is_valid() -> None:
    if not WIN_STABILITY_PROFILE_PATH.exists():
        pytest.skip("win_stability_profile.json is not available")

    profile = _load_json(WIN_STABILITY_PROFILE_PATH)
    required_keys = {
        "enabled",
        "alpha_death",
        "alpha_high_pressure",
        "pressure_rr_gap_threshold",
        "pressure_balls_left_max",
        "source",
    }
    missing = sorted(required_keys - set(profile.keys()))
    assert not missing, f"Missing keys in win stability profile: {missing}"

    assert 0.0 <= float(profile["alpha_death"]) <= 0.95
    assert 0.0 <= float(profile["alpha_high_pressure"]) <= 0.95


def test_pre_match_holdout_metrics_exist() -> None:
    if not PRE_MATCH_REPORT_PATH.exists():
        pytest.skip("pre_match_model_report.json is not available")

    report = _load_json(PRE_MATCH_REPORT_PATH)
    assert "split" in report, "Pre-match split summary missing"
    assert "score_metrics" in report and "test" in report["score_metrics"], "Pre-match score hold-out metrics missing"
    assert "win_metrics" in report and "test" in report["win_metrics"], "Pre-match win hold-out metrics missing"
