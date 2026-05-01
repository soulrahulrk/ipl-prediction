from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
PROCESSED_DIR = DATA_DIR / "processed"
MODELS_DIR = ROOT_DIR / "models"
MONITORING_DIR = DATA_DIR / "monitoring"

EVENT_LOG_PATH = MONITORING_DIR / "prediction_events.jsonl"
OUTCOME_LOG_PATH = MONITORING_DIR / "prediction_outcomes.jsonl"
REFERENCE_PROFILE_PATH = MODELS_DIR / "feature_reference_profile.json"
DRIFT_REPORT_PATH = MODELS_DIR / "production_drift_report.json"
DEPLOYMENT_REPORT_PATH = MODELS_DIR / "deployment_report.json"

FEATURE_Z_WARNING = 2.5
FEATURE_Z_CRITICAL = 3.5
SLICE_DELTA_WARNING = 0.10
SLICE_DELTA_CRITICAL = 0.18

SCORE_MAE_DEGRADE_WARNING = 0.15
SCORE_MAE_DEGRADE_CRITICAL = 0.30
SCORE_RMSE_DEGRADE_WARNING = 0.15
SCORE_RMSE_DEGRADE_CRITICAL = 0.30
WIN_LOGLOSS_DEGRADE_WARNING = 0.12
WIN_LOGLOSS_DEGRADE_CRITICAL = 0.25
WIN_BRIER_DEGRADE_WARNING = 0.12
WIN_BRIER_DEGRADE_CRITICAL = 0.25
WIN_ACCURACY_DROP_WARNING = 0.05
WIN_ACCURACY_DROP_CRITICAL = 0.10

MONITORED_FEATURES = [
    "runs",
    "wickets",
    "balls_left",
    "current_run_rate",
    "required_minus_current_rr",
    "dew_risk",
    "runs_vs_par",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any, default: float = np.nan) -> float:
    try:
        if value is None:
            return float(default)
        if isinstance(value, str) and not value.strip():
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        if isinstance(value, str) and not value.strip():
            return int(default)
        return int(value)
    except Exception:
        return int(default)


def _metric_baseline() -> dict[str, float]:
    baseline = {
        "score_mae": 18.0,
        "score_rmse": 24.0,
        "win_log_loss": 0.60,
        "win_brier": 0.22,
        "win_accuracy": 0.60,
    }
    if not DEPLOYMENT_REPORT_PATH.exists():
        return baseline

    try:
        report = json.loads(DEPLOYMENT_REPORT_PATH.read_text(encoding="utf-8"))
        score = report.get("deployment_score_metrics_test", {})
        win = report.get("deployment_win_metrics_test", {})
        baseline["score_mae"] = float(score.get("mae", baseline["score_mae"]))
        baseline["score_rmse"] = float(score.get("rmse", baseline["score_rmse"]))
        baseline["win_log_loss"] = float(win.get("log_loss", baseline["win_log_loss"]))
        baseline["win_brier"] = float(win.get("brier", baseline["win_brier"]))
        baseline["win_accuracy"] = float(win.get("accuracy", baseline["win_accuracy"]))
    except Exception:
        return baseline

    return baseline


def _hash_event_id(event: Mapping[str, Any]) -> str:
    base = "|".join(
        [
            str(event.get("timestamp_utc", "")),
            str(event.get("season", "")),
            str(event.get("venue", "")),
            str(event.get("batting_team", "")),
            str(event.get("bowling_team", "")),
            str(event.get("innings", "")),
            str(event.get("phase", "")),
            str(event.get("predicted_total", "")),
            str(event.get("adjusted_win_prob", "")),
        ]
    )
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()
    return f"ev_{digest[:16]}"


def _ensure_dirs() -> None:
    MONITORING_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)


def _db_enabled() -> bool:
    backend = os.getenv("MONITORING_STORAGE", "database").strip().lower()
    database_url = os.getenv("DATABASE_URL", "").strip()
    return backend == "database" and bool(database_url)


def _feature_stats(series: pd.Series) -> dict[str, float]:
    clean = pd.to_numeric(series, errors="coerce")
    return {
        "mean": float(clean.mean()),
        "std": float(clean.std(ddof=0)) if float(clean.std(ddof=0)) > 1e-9 else 1.0,
        "p50": float(clean.quantile(0.50)),
        "p90": float(clean.quantile(0.90)),
        "rows": int(clean.notna().sum()),
    }


def _build_reference_profile_from_processed() -> dict[str, Any]:
    features_path = PROCESSED_DIR / "ipl_features.csv"
    if not features_path.exists():
        return {
            "created_at": _utc_now_iso(),
            "source": "missing_processed_file",
            "features": {f: {"mean": 0.0, "std": 1.0, "p50": 0.0, "p90": 0.0, "rows": 0} for f in MONITORED_FEATURES},
            "slice_rates": {"death_over": 0.0, "high_pressure_chase": 0.0},
        }

    header_cols = pd.read_csv(features_path, nrows=0).columns.tolist()
    use_cols = ["phase", "innings", "required_minus_current_rr", "balls_left"] + MONITORED_FEATURES
    use_cols = [c for c in sorted(set(use_cols)) if c in header_cols]
    df = pd.read_csv(features_path, usecols=use_cols, low_memory=False)

    features = {}
    for col in MONITORED_FEATURES:
        if col in df.columns:
            features[col] = _feature_stats(df[col])
        else:
            features[col] = {"mean": 0.0, "std": 1.0, "p50": 0.0, "p90": 0.0, "rows": 0}

    phase = df["phase"].astype(str).str.lower() if "phase" in df.columns else pd.Series([], dtype=str)
    innings = pd.to_numeric(df.get("innings", np.nan), errors="coerce")
    rr_gap = pd.to_numeric(df.get("required_minus_current_rr", np.nan), errors="coerce")
    balls_left = pd.to_numeric(df.get("balls_left", np.nan), errors="coerce")

    death_rate = float(phase.eq("death").mean()) if len(phase) else 0.0
    pressure_rate = float(
        (
            innings.eq(2)
            & rr_gap.notna()
            & (rr_gap >= 1.25)
            & balls_left.notna()
            & (balls_left <= 48)
        ).mean()
    ) if len(df) else 0.0

    return {
        "created_at": _utc_now_iso(),
        "source": "data/processed/ipl_features.csv",
        "features": features,
        "slice_rates": {
            "death_over": death_rate,
            "high_pressure_chase": pressure_rate,
        },
    }


def load_or_create_reference_profile() -> dict[str, Any]:
    _ensure_dirs()
    if REFERENCE_PROFILE_PATH.exists():
        try:
            return json.loads(REFERENCE_PROFILE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    profile = _build_reference_profile_from_processed()
    REFERENCE_PROFILE_PATH.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    return profile


def _append_event(event: Mapping[str, Any]) -> None:
    if _db_enabled():
        try:
            from .db import get_db_session
            from .models import MonitoringEvent

            db_session = get_db_session()
            existing = db_session.query(MonitoringEvent).filter(MonitoringEvent.event_id == str(event.get("event_id", ""))).one_or_none()
            if existing is None:
                db_session.add(MonitoringEvent(event_id=str(event.get("event_id", "")), event_payload=dict(event)))
                db_session.commit()
            return
        except Exception:
            pass
    with EVENT_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(event), ensure_ascii=True) + "\n")


def _append_outcome(outcome: Mapping[str, Any]) -> None:
    if _db_enabled():
        try:
            from .db import get_db_session
            from .models import MonitoringOutcome

            db_session = get_db_session()
            canonical = json.dumps(dict(outcome), sort_keys=True, ensure_ascii=True)
            payload_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            existing = (
                db_session.query(MonitoringOutcome)
                .filter(MonitoringOutcome.payload_hash == payload_hash)
                .one_or_none()
            )
            if existing is None:
                db_session.add(
                    MonitoringOutcome(
                        event_id=str(outcome.get("event_id", "")).strip() or None,
                        payload_hash=payload_hash,
                        outcome_payload=dict(outcome),
                    )
                )
                db_session.commit()
            return
        except Exception:
            pass
    with OUTCOME_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(outcome), ensure_ascii=True) + "\n")


def _read_recent_events(window: int = 500) -> list[dict[str, Any]]:
    if _db_enabled():
        try:
            from .db import get_db_session
            from .models import MonitoringEvent

            db_session = get_db_session()
            rows = (
                db_session.query(MonitoringEvent)
                .order_by(MonitoringEvent.created_at.desc())
                .limit(window)
                .all()
            )
            return [dict(row.event_payload) for row in reversed(rows)]
        except Exception:
            pass

    if not EVENT_LOG_PATH.exists():
        return []

    lines = EVENT_LOG_PATH.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    for raw in lines[-window:]:
        try:
            out.append(json.loads(raw))
        except Exception:
            continue
    return out


def _find_event_by_id(event_id: str, search_window: int = 5000) -> dict[str, Any] | None:
    if _db_enabled():
        try:
            from .db import get_db_session
            from .models import MonitoringEvent

            db_session = get_db_session()
            row = db_session.query(MonitoringEvent).filter(MonitoringEvent.event_id == str(event_id)).one_or_none()
            return dict(row.event_payload) if row else None
        except Exception:
            pass

    for event in reversed(_read_recent_events(window=search_window)):
        if str(event.get("event_id", "")) == str(event_id):
            return event
    return None


def _read_recent_outcomes(window: int = 500) -> list[dict[str, Any]]:
    if _db_enabled():
        try:
            from .db import get_db_session
            from .models import MonitoringOutcome, PredictionOutcome, Prediction

            db_session = get_db_session()
            outcome_rows = (
                db_session.query(MonitoringOutcome)
                .order_by(MonitoringOutcome.created_at.desc())
                .limit(window)
                .all()
            )
            if outcome_rows:
                return [dict(row.outcome_payload) for row in reversed(outcome_rows)]

            rows = (
                db_session.query(PredictionOutcome, Prediction)
                .join(Prediction, Prediction.id == PredictionOutcome.prediction_id)
                .order_by(PredictionOutcome.resolved_at.desc())
                .limit(window)
                .all()
            )
            out: list[dict[str, Any]] = []
            for outcome, prediction in rows:
                output_payload = prediction.output_payload or {}
                out.append(
                    {
                        "timestamp_utc": outcome.resolved_at.isoformat() if outcome.resolved_at else "",
                        "event_id": prediction.monitoring_event_id or "",
                        "match_id": str(prediction.match_id or ""),
                        "actual_total": outcome.actual_total,
                        "actual_win": outcome.actual_win,
                        "predicted_total": output_payload.get("predicted_total"),
                        "adjusted_win_prob": output_payload.get("win_prob"),
                    }
                )
            return list(reversed(out))
        except Exception:
            pass

    if not OUTCOME_LOG_PATH.exists():
        return []

    lines = OUTCOME_LOG_PATH.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    for raw in lines[-window:]:
        try:
            out.append(json.loads(raw))
        except Exception:
            continue
    return out


def track_prediction_event(
    payload: Mapping[str, Any],
    row: pd.Series,
    predicted_total: float,
    raw_win_prob: float,
    adjusted_win_prob: float,
    stability_flags: list[str],
    stability_profile_source: str,
) -> str:
    _ensure_dirs()
    load_or_create_reference_profile()

    event = {
        "timestamp_utc": _utc_now_iso(),
        "season": str(payload.get("season", "")),
        "venue": str(payload.get("venue", "")),
        "batting_team": str(payload.get("batting_team", "")),
        "bowling_team": str(payload.get("bowling_team", "")),
        "phase": str(row.get("phase", "")),
        "innings": int(_safe_float(row.get("innings", 0.0), 0.0)),
        "predicted_total": float(predicted_total),
        "raw_win_prob": float(raw_win_prob),
        "adjusted_win_prob": float(adjusted_win_prob),
        "stability_flags": list(stability_flags),
        "stability_profile_source": str(stability_profile_source),
    }

    for feat in MONITORED_FEATURES:
        event[feat] = _safe_float(row.get(feat, np.nan))

    event_id = _hash_event_id(event)
    event["event_id"] = event_id

    _append_event(event)

    recent = _read_recent_events(window=25)
    if len(recent) >= 25:
        update_drift_report(window=500, min_events=100, min_outcomes=40)

    return event_id


def _slice_rate(events_df: pd.DataFrame, flag: str) -> float:
    if events_df.empty or "stability_flags" not in events_df.columns:
        return 0.0
    return float(events_df["stability_flags"].apply(lambda flags: flag in (flags or [])).mean())


def record_prediction_outcome(
    *,
    actual_total: float | None,
    actual_win: int | None,
    event_id: str | None = None,
    predicted_total: float | None = None,
    adjusted_win_prob: float | None = None,
    match_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _ensure_dirs()

    linked_event = _find_event_by_id(event_id) if event_id else None
    pred_total = predicted_total if predicted_total is not None else (
        _safe_float(linked_event.get("predicted_total", np.nan)) if linked_event else np.nan
    )
    adj_prob = adjusted_win_prob if adjusted_win_prob is not None else (
        _safe_float(linked_event.get("adjusted_win_prob", np.nan)) if linked_event else np.nan
    )

    outcome: dict[str, Any] = {
        "timestamp_utc": _utc_now_iso(),
        "event_id": event_id or "",
        "match_id": str(match_id or ""),
        "actual_total": None if actual_total is None else float(actual_total),
        "actual_win": None if actual_win is None else int(actual_win),
        "predicted_total": None if np.isnan(pred_total) else float(pred_total),
        "adjusted_win_prob": None if np.isnan(adj_prob) else float(np.clip(adj_prob, 1e-6, 1 - 1e-6)),
        "linked": bool(linked_event is not None),
    }

    if linked_event:
        outcome["season"] = str(linked_event.get("season", ""))
        outcome["venue"] = str(linked_event.get("venue", ""))
        outcome["batting_team"] = str(linked_event.get("batting_team", ""))
        outcome["bowling_team"] = str(linked_event.get("bowling_team", ""))

    _append_outcome(outcome)
    report = update_drift_report(window=500, min_events=100, min_outcomes=40)
    return outcome, report


def update_drift_report(window: int = 500, min_events: int = 100, min_outcomes: int = 40) -> dict[str, Any]:
    profile = load_or_create_reference_profile()
    events = _read_recent_events(window=window)
    outcomes = _read_recent_outcomes(window=window)
    baseline_metrics = _metric_baseline()

    report: dict[str, Any] = {
        "updated_at": _utc_now_iso(),
        "window": int(window),
        "events_used": int(len(events)),
        "outcomes_used": int(len(outcomes)),
        "status": "insufficient_data",
        "feature_drift": {},
        "slice_drift": {},
        "outcome_drift": {
            "status": "insufficient_data",
            "metrics": {},
            "baseline": baseline_metrics,
            "warnings": [],
            "critical": [],
        },
        "trigger_retrain": False,
        "trigger_reasons": [],
        "recommended_action": "Collect more events and outcomes before taking action.",
    }

    warning_flags = 0
    critical_flags = 0
    trigger_reasons: list[str] = []

    enough_events = len(events) >= min_events
    if enough_events:
        events_df = pd.DataFrame(events)

        for feat in MONITORED_FEATURES:
            baseline = profile.get("features", {}).get(feat, {})
            ref_mean = _safe_float(baseline.get("mean", 0.0), 0.0)
            ref_std = max(1e-6, _safe_float(baseline.get("std", 1.0), 1.0))
            recent = pd.to_numeric(events_df.get(feat, np.nan), errors="coerce")
            recent_mean = float(recent.mean()) if recent.notna().any() else 0.0
            z_score = float(abs(recent_mean - ref_mean) / ref_std)

            severity = "stable"
            if z_score >= FEATURE_Z_CRITICAL:
                severity = "critical"
                critical_flags += 1
                trigger_reasons.append(f"feature:{feat}:critical")
            elif z_score >= FEATURE_Z_WARNING:
                severity = "warning"
                warning_flags += 1
                trigger_reasons.append(f"feature:{feat}:warning")

            report["feature_drift"][feat] = {
                "reference_mean": ref_mean,
                "recent_mean": recent_mean,
                "z_score": z_score,
                "severity": severity,
            }

        base_slice = profile.get("slice_rates", {})
        death_recent = _slice_rate(events_df, "death_over")
        pressure_recent = _slice_rate(events_df, "high_pressure_chase")
        death_delta = float(abs(death_recent - _safe_float(base_slice.get("death_over", 0.0), 0.0)))
        pressure_delta = float(abs(pressure_recent - _safe_float(base_slice.get("high_pressure_chase", 0.0), 0.0)))

        death_severity = "stable"
        if death_delta >= SLICE_DELTA_CRITICAL:
            death_severity = "critical"
            critical_flags += 1
            trigger_reasons.append("slice:death_over:critical")
        elif death_delta >= SLICE_DELTA_WARNING:
            death_severity = "warning"
            warning_flags += 1
            trigger_reasons.append("slice:death_over:warning")

        pressure_severity = "stable"
        if pressure_delta >= SLICE_DELTA_CRITICAL:
            pressure_severity = "critical"
            critical_flags += 1
            trigger_reasons.append("slice:high_pressure_chase:critical")
        elif pressure_delta >= SLICE_DELTA_WARNING:
            pressure_severity = "warning"
            warning_flags += 1
            trigger_reasons.append("slice:high_pressure_chase:warning")

        report["slice_drift"] = {
            "death_over": {
                "reference_rate": _safe_float(base_slice.get("death_over", 0.0), 0.0),
                "recent_rate": death_recent,
                "abs_delta": death_delta,
                "severity": death_severity,
            },
            "high_pressure_chase": {
                "reference_rate": _safe_float(base_slice.get("high_pressure_chase", 0.0), 0.0),
                "recent_rate": pressure_recent,
                "abs_delta": pressure_delta,
                "severity": pressure_severity,
            },
        }

    enough_outcomes = len(outcomes) >= min_outcomes
    if enough_outcomes:
        outcomes_df = pd.DataFrame(outcomes)
        outcome_metrics: dict[str, float] = {}
        outcome_warnings: list[str] = []
        outcome_critical: list[str] = []

        score_df = outcomes_df.dropna(subset=["actual_total", "predicted_total"]).copy()
        if not score_df.empty:
            score_err = pd.to_numeric(score_df["predicted_total"], errors="coerce") - pd.to_numeric(
                score_df["actual_total"], errors="coerce"
            )
            mae = float(np.mean(np.abs(score_err)))
            rmse = float(np.sqrt(np.mean(score_err ** 2)))
            outcome_metrics["score_mae"] = mae
            outcome_metrics["score_rmse"] = rmse

            if mae > baseline_metrics["score_mae"] * (1.0 + SCORE_MAE_DEGRADE_CRITICAL):
                outcome_critical.append("score_mae")
            elif mae > baseline_metrics["score_mae"] * (1.0 + SCORE_MAE_DEGRADE_WARNING):
                outcome_warnings.append("score_mae")

            if rmse > baseline_metrics["score_rmse"] * (1.0 + SCORE_RMSE_DEGRADE_CRITICAL):
                outcome_critical.append("score_rmse")
            elif rmse > baseline_metrics["score_rmse"] * (1.0 + SCORE_RMSE_DEGRADE_WARNING):
                outcome_warnings.append("score_rmse")

        win_df = outcomes_df.dropna(subset=["actual_win", "adjusted_win_prob"]).copy()
        if not win_df.empty:
            y_true = pd.to_numeric(win_df["actual_win"], errors="coerce").astype(float)
            probs = np.clip(pd.to_numeric(win_df["adjusted_win_prob"], errors="coerce").to_numpy(dtype=float), 1e-6, 1 - 1e-6)
            preds = (probs >= 0.5).astype(int)

            logloss = float(log_loss(y_true, probs, labels=[0, 1]))
            brier = float(brier_score_loss(y_true, probs))
            accuracy = float(accuracy_score(y_true, preds))

            outcome_metrics["win_log_loss"] = logloss
            outcome_metrics["win_brier"] = brier
            outcome_metrics["win_accuracy"] = accuracy

            if logloss > baseline_metrics["win_log_loss"] * (1.0 + WIN_LOGLOSS_DEGRADE_CRITICAL):
                outcome_critical.append("win_log_loss")
            elif logloss > baseline_metrics["win_log_loss"] * (1.0 + WIN_LOGLOSS_DEGRADE_WARNING):
                outcome_warnings.append("win_log_loss")

            if brier > baseline_metrics["win_brier"] * (1.0 + WIN_BRIER_DEGRADE_CRITICAL):
                outcome_critical.append("win_brier")
            elif brier > baseline_metrics["win_brier"] * (1.0 + WIN_BRIER_DEGRADE_WARNING):
                outcome_warnings.append("win_brier")

            if accuracy < baseline_metrics["win_accuracy"] * (1.0 - WIN_ACCURACY_DROP_CRITICAL):
                outcome_critical.append("win_accuracy")
            elif accuracy < baseline_metrics["win_accuracy"] * (1.0 - WIN_ACCURACY_DROP_WARNING):
                outcome_warnings.append("win_accuracy")

        warning_flags += len(outcome_warnings)
        critical_flags += len(outcome_critical)
        trigger_reasons.extend([f"outcome:{name}:warning" for name in outcome_warnings])
        trigger_reasons.extend([f"outcome:{name}:critical" for name in outcome_critical])

        outcome_status = "stable"
        if outcome_critical:
            outcome_status = "critical"
        elif outcome_warnings:
            outcome_status = "warning"

        report["outcome_drift"] = {
            "status": outcome_status,
            "metrics": outcome_metrics,
            "baseline": baseline_metrics,
            "warnings": sorted(set(outcome_warnings)),
            "critical": sorted(set(outcome_critical)),
        }

    if critical_flags > 0:
        report["status"] = "critical"
    elif warning_flags >= 2:
        report["status"] = "warning"
    elif enough_events or enough_outcomes:
        report["status"] = "stable"
    else:
        report["status"] = "insufficient_data"

    unique_reasons = sorted(set(trigger_reasons))
    report["trigger_reasons"] = unique_reasons
    report["trigger_retrain"] = bool(report["status"] == "critical" or len(unique_reasons) >= 4)

    if report["trigger_retrain"]:
        report["recommended_action"] = (
            "Run scripts/retrain_and_register.py --skip-update and review deployment_report.json before promotion."
        )
    elif report["status"] == "warning":
        report["recommended_action"] = (
            "Inspect warning fields, increase monitoring frequency, and retrain if warnings persist for multiple windows."
        )
    elif report["status"] == "stable":
        report["recommended_action"] = "No action needed; continue periodic monitoring."

    DRIFT_REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def get_latest_drift_report() -> dict[str, Any]:
    if not DRIFT_REPORT_PATH.exists():
        return update_drift_report(window=500, min_events=100, min_outcomes=40)
    try:
        return json.loads(DRIFT_REPORT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return update_drift_report(window=500, min_events=100, min_outcomes=40)
