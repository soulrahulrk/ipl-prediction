from __future__ import annotations

import os
from typing import Any

from flask import Flask, jsonify, render_template, request

from ipl_predictor import (
    get_latest_drift_report,
    load_or_create_reference_profile,
    load_models,
    load_pre_match_models,
    record_prediction_outcome,
    load_support_tables,
    predict_match_state,
    predict_pre_match,
    update_drift_report,
)


app = Flask(__name__)

score_model, win_model = load_models()
pre_match_score_model, pre_match_win_model = load_pre_match_models()
support_tables = load_support_tables()
load_or_create_reference_profile()


def _request_payload() -> dict[str, Any]:
    if request.is_json:
        data = request.get_json(silent=True)
        if isinstance(data, dict):
            return data
        return {}
    return request.form.to_dict()


@app.route("/", methods=["GET", "POST"])
def index():
    prediction = None
    pre_match_prediction = None
    errors: list[str] = []
    pre_match_error: str | None = None
    form_data: dict[str, Any] = {}
    pre_match_form_data: dict[str, Any] = {}

    if request.method == "POST":
        form_type = request.form.get("form_type", "live")
        if form_type == "pre_match":
            pre_match_form_data = request.form.to_dict()
            team1 = pre_match_form_data.get("team1", "").strip()
            team2 = pre_match_form_data.get("team2", "").strip()
            venue = pre_match_form_data.get("venue", "").strip()
            if not team1 or not team2 or not venue:
                pre_match_error = "Team 1, Team 2, and venue are required."
            elif team1 == team2:
                pre_match_error = "Team 1 and Team 2 must be different."
            else:
                pre_match_prediction = predict_pre_match(
                    team1=team1,
                    team2=team2,
                    venue=venue,
                    score_model=pre_match_score_model,
                    win_model=pre_match_win_model,
                    support_tables=support_tables,
                )
                if "error" in pre_match_prediction:
                    pre_match_error = pre_match_prediction["error"]
                    pre_match_prediction = None
        else:
            form_data = request.form.to_dict()
            prediction, errors = predict_match_state(
                form_data,
                support_tables=support_tables,
                score_model=score_model,
                win_model=win_model,
            )

    return render_template(
        "index.html",
        prediction=prediction,
        pre_match_prediction=pre_match_prediction,
        pre_match_error=pre_match_error,
        errors=errors,
        form_data=form_data,
        pre_match_form_data=pre_match_form_data,
    )


@app.route("/api/predict", methods=["POST"])
def api_predict():
    payload = _request_payload()
    prediction, errors = predict_match_state(
        payload,
        support_tables=support_tables,
        score_model=score_model,
        win_model=win_model,
    )
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400
    return jsonify({"ok": True, "prediction": prediction})


@app.route("/api/monitoring", methods=["GET"])
def api_monitoring():
    refresh = str(request.args.get("refresh", "")).strip().lower() in {"1", "true", "yes", "on"}
    report = update_drift_report(window=500, min_events=100, min_outcomes=40) if refresh else get_latest_drift_report()
    return jsonify({"ok": True, "monitoring": report})


@app.route("/api/monitoring/outcome", methods=["POST"])
def api_monitoring_outcome():
    payload = _request_payload()

    actual_total_raw = payload.get("actual_total")
    actual_win_raw = payload.get("actual_win")
    event_id = str(payload.get("event_id", "")).strip() or None
    match_id = str(payload.get("match_id", "")).strip() or None

    if actual_total_raw is None and actual_win_raw is None:
        return jsonify({"ok": False, "errors": ["Provide at least one of actual_total or actual_win."]}), 400

    actual_total: float | None = None
    if actual_total_raw is not None and str(actual_total_raw).strip() != "":
        try:
            actual_total = float(actual_total_raw)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "errors": ["actual_total must be numeric."]}), 400

    actual_win: int | None = None
    if actual_win_raw is not None and str(actual_win_raw).strip() != "":
        try:
            actual_win = int(actual_win_raw)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "errors": ["actual_win must be 0 or 1."]}), 400
        if actual_win not in {0, 1}:
            return jsonify({"ok": False, "errors": ["actual_win must be 0 or 1."]}), 400

    predicted_total: float | None = None
    adjusted_win_prob: float | None = None

    if payload.get("predicted_total") is not None and str(payload.get("predicted_total", "")).strip() != "":
        try:
            predicted_total = float(payload["predicted_total"])
        except (TypeError, ValueError):
            return jsonify({"ok": False, "errors": ["predicted_total must be numeric when provided."]}), 400

    if payload.get("adjusted_win_prob") is not None and str(payload.get("adjusted_win_prob", "")).strip() != "":
        try:
            adjusted_win_prob = float(payload["adjusted_win_prob"])
        except (TypeError, ValueError):
            return jsonify({"ok": False, "errors": ["adjusted_win_prob must be numeric when provided."]}), 400

    outcome, report = record_prediction_outcome(
        actual_total=actual_total,
        actual_win=actual_win,
        event_id=event_id,
        predicted_total=predicted_total,
        adjusted_win_prob=adjusted_win_prob,
        match_id=match_id,
    )
    return jsonify({"ok": True, "outcome": outcome, "monitoring": report})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
