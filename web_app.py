from __future__ import annotations

import json
import os
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from marshmallow import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ipl_predictor import (
    get_latest_drift_report,
    load_models,
    load_or_create_reference_profile,
    load_pre_match_models,
    load_support_tables,
    predict_match_state,
    predict_pre_match,
    record_prediction_outcome,
    update_drift_report,
)
from ipl_predictor.auth import AuthUser, hash_password, verify_password
from ipl_predictor.config import get_settings
from ipl_predictor.db import SessionLocal, get_db_session, init_db, init_engine
from ipl_predictor.models import Match, ModelVersion, Prediction, PredictionOutcome, User
from ipl_predictor.schemas import OutcomeRequestSchema, PredictRequestSchema


predict_schema = PredictRequestSchema()
outcome_schema = OutcomeRequestSchema()

try:
    from sklearn.exceptions import InconsistentVersionWarning as _InconsistentVersionWarning
except Exception:
    _InconsistentVersionWarning = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_error(status_code: int, message: str, details: list[str] | None = None):
    payload = {
        "ok": False,
        "error": {
            "code": status_code,
            "message": message,
            "details": details or [],
        },
    }
    return jsonify(payload), status_code


def _is_pickle_version_warning(warning_obj) -> bool:
    message = str(warning_obj.message)
    if _InconsistentVersionWarning is not None and isinstance(warning_obj.message, _InconsistentVersionWarning):
        return True
    if "InconsistentVersionWarning" in warning_obj.category.__name__:
        return True
    return "Trying to unpickle estimator" in message and "when using version" in message


def _warn_pickle_version_mismatch(app: Flask, warnings_found: list[str], model_group: str) -> None:
    if not warnings_found:
        return
    unique_warnings = sorted(set(warnings_found))
    try:
        import sklearn
        sklearn_version = sklearn.__version__
    except Exception:
        sklearn_version = "unknown"
    app.logger.warning(
        "Model pickle version mismatch detected while loading %s. "
        "Installed scikit-learn=%s. Warnings=%d.",
        model_group, sklearn_version, len(unique_warnings),
    )


def _get_or_create_guest_user(db_session) -> int:
    guest = db_session.query(User).filter(User.email == "guest@ipl-predictor.local").one_or_none()
    if not guest:
        guest = User(
            email="guest@ipl-predictor.local",
            password_hash=hash_password(os.urandom(32).hex()),
            is_admin=False,
            is_active=True,
        )
        db_session.add(guest)
        db_session.commit()
    return guest.id


def _safe_model_version(db_session, model_name: str, fallback_version: str) -> int | None:
    version = (
        db_session.query(ModelVersion)
        .filter(ModelVersion.model_name == model_name, ModelVersion.version == fallback_version)
        .one_or_none()
    )
    if version:
        return version.id
    created = ModelVersion(
        model_name=model_name,
        version=fallback_version,
        artifact_uri=None,
        metadata_json={},
    )
    db_session.add(created)
    db_session.flush()
    return created.id


def _resolve_match(db_session, payload: dict[str, Any]) -> Match:
    season = str(payload.get("season", "")).strip() or None
    venue = str(payload.get("venue", "")).strip() or None
    batting_team = str(payload.get("batting_team", "")).strip() or None
    bowling_team = str(payload.get("bowling_team", "")).strip() or None
    external_match_id = str(payload.get("match_id", "")).strip() or None

    if external_match_id:
        existing = db_session.query(Match).filter(Match.external_match_id == external_match_id).one_or_none()
        if existing:
            return existing

    match = Match(
        external_match_id=external_match_id,
        season=season,
        venue=venue,
        batting_team=batting_team,
        bowling_team=bowling_team,
    )
    db_session.add(match)
    db_session.flush()
    return match


def create_app() -> Flask:
    settings = get_settings()
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=settings.secret_key,
        SESSION_COOKIE_SECURE=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=settings.permanent_session_lifetime,
        WTF_CSRF_ENABLED=False,
    )

    init_engine(settings.database_url)
    init_db()

    login_manager = LoginManager()
    login_manager.login_view = "login"
    login_manager.init_app(app)

    limiter_kwargs: dict[str, Any] = {
        "app": app,
        "default_limits": [settings.rate_limit_default],
    }
    if settings.rate_limit_storage_uri:
        limiter_kwargs["storage_uri"] = settings.rate_limit_storage_uri
    limiter = Limiter(get_remote_address, **limiter_kwargs)

    try:
        with warnings.catch_warnings(record=True) as caught_main:
            warnings.simplefilter("always")
            score_model, win_model = load_models()
        mismatch_messages = [str(w.message) for w in caught_main if _is_pickle_version_warning(w)]
        _warn_pickle_version_mismatch(app, mismatch_messages, "score/win models")
    except Exception:
        score_model, win_model = None, None

    try:
        with warnings.catch_warnings(record=True) as caught_pre:
            warnings.simplefilter("always")
            pre_match_score_model, pre_match_win_model = load_pre_match_models()
        mismatch_messages = [str(w.message) for w in caught_pre if _is_pickle_version_warning(w)]
        _warn_pickle_version_mismatch(app, mismatch_messages, "pre-match models")
    except Exception:
        pre_match_score_model, pre_match_win_model = None, None

    support_tables = load_support_tables()
    load_or_create_reference_profile()

    # Create guest user once so DB foreign key on predictions is always satisfied
    with app.app_context():
        db_session = get_db_session()
        guest_user_id = _get_or_create_guest_user(db_session)

    def _request_payload() -> dict[str, Any]:
        if request.is_json:
            data = request.get_json(silent=True)
            if isinstance(data, dict):
                return data
            return {}
        return request.form.to_dict()

    @login_manager.user_loader
    def load_user(user_id: str):
        db_session = get_db_session()
        user = db_session.query(User).filter(User.id == int(user_id), User.is_active.is_(True)).one_or_none()
        if not user:
            return None
        return AuthUser(user.id, user.email, user.is_admin, user.is_active)

    @app.teardown_appcontext
    def _cleanup_session(_exc):
        SessionLocal.remove()

    @app.route("/auth/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("index"))
        if request.method == "POST":
            email = str(request.form.get("email", "")).strip().lower()
            password = str(request.form.get("password", ""))
            db_session = get_db_session()
            user = db_session.query(User).filter(User.email == email, User.is_active.is_(True)).one_or_none()
            if not user or not verify_password(user.password_hash, password):
                flash("Invalid email or password.", "error")
                return render_template("login.html"), 401
            login_user(AuthUser(user.id, user.email, user.is_admin, user.is_active))
            next_url = request.args.get("next")
            return redirect(next_url or url_for("index"))
        return render_template("login.html")

    @app.route("/auth/signup", methods=["GET", "POST"])
    def signup():
        if current_user.is_authenticated:
            return redirect(url_for("index"))
        if request.method == "POST":
            email = str(request.form.get("email", "")).strip().lower()
            password = str(request.form.get("password", ""))
            if not email or not password:
                flash("Email and password are required.", "error")
                return render_template("signup.html"), 400
            db_session = get_db_session()
            if db_session.query(User).filter(User.email == email).one_or_none():
                flash("Email already registered.", "error")
                return render_template("signup.html"), 400
            user = User(email=email, password_hash=hash_password(password), is_admin=False, is_active=True)
            db_session.add(user)
            db_session.commit()
            flash("Account created. Please sign in.", "success")
            return redirect(url_for("login"))
        return render_template("signup.html")

    @app.route("/auth/logout", methods=["POST"])
    def logout():
        logout_user()
        return redirect(url_for("login"))

    @app.errorhandler(ValidationError)
    def _validation_error(err: ValidationError):
        details: list[str] = []
        for field, messages in err.messages.items():
            for message in messages:
                details.append(f"{field}: {message}")
        return _json_error(400, "Validation failed", details)

    @app.errorhandler(404)
    def _not_found(_err):
        if request.path.startswith("/api/"):
            return _json_error(404, "Not found")
        return render_template("error.html", code=404, message="Not found"), 404

    @app.route("/healthz", methods=["GET"])
    def healthz():
        db_session = get_db_session()
        db_ok = True
        try:
            db_session.execute(text("SELECT 1"))
        except Exception:
            db_ok = False
        models_ok = score_model is not None and win_model is not None
        status = "ok" if db_ok and models_ok else "degraded"
        return jsonify({"ok": True, "status": status, "database": db_ok, "models_loaded": models_ok})

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
                        pre_match_error = str(pre_match_prediction["error"])
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

    @app.route("/history", methods=["GET"])
    def history():
        db_session = get_db_session()
        rows = (
            db_session.query(Prediction)
            .order_by(Prediction.created_at.desc())
            .limit(200)
            .all()
        )
        return render_template("history.html", predictions=rows)

    @app.route("/api/predict", methods=["POST"])
    @limiter.limit(settings.write_rate_limit)
    def api_predict():
        if score_model is None or win_model is None:
            return _json_error(503, "Model files missing or not trained yet.")

        payload = _request_payload()
        predict_schema.load(payload)

        prediction, errors = predict_match_state(
            payload,
            support_tables=support_tables,
            score_model=score_model,
            win_model=win_model,
        )
        if errors:
            return _json_error(400, "Validation failed", errors)

        db_session = get_db_session()
        prediction_id = None
        try:
            match = _resolve_match(db_session, payload)
            score_version_id = _safe_model_version(
                db_session,
                model_name="score_model",
                fallback_version=os.getenv("SCORE_MODEL_VERSION", "local-v1"),
            )
            win_version_id = _safe_model_version(
                db_session,
                model_name="win_model",
                fallback_version=os.getenv("WIN_MODEL_VERSION", "local-v1"),
            )
            row = Prediction(
                user_id=guest_user_id,
                match_id=match.id,
                score_model_version_id=score_version_id,
                win_model_version_id=win_version_id,
                input_payload=payload,
                output_payload=prediction or {},
                monitoring_event_id=(prediction or {}).get("monitoring_event_id"),
            )
            db_session.add(row)
            db_session.commit()
            prediction_id = row.id
        except IntegrityError:
            db_session.rollback()

        return jsonify({"ok": True, "prediction": prediction, "prediction_id": prediction_id})

    @app.route("/api/history", methods=["GET"])
    def api_history():
        db_session = get_db_session()
        try:
            limit = int(request.args.get("limit", "50"))
        except (TypeError, ValueError):
            limit = 50
        try:
            offset = int(request.args.get("offset", "0"))
        except (TypeError, ValueError):
            offset = 0
        limit = max(1, min(200, limit))
        offset = max(0, offset)

        base_query = (
            db_session.query(Prediction)
            .order_by(Prediction.created_at.desc())
        )
        total = base_query.count()
        rows = base_query.offset(offset).limit(limit).all()

        items: list[dict[str, Any]] = []
        for row in rows:
            items.append({
                "id": row.id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "match_id": row.match_id,
                "monitoring_event_id": row.monitoring_event_id,
                "input_payload": row.input_payload,
                "output_payload": row.output_payload,
                "outcome": (
                    {
                        "id": row.outcome.id,
                        "actual_total": row.outcome.actual_total,
                        "actual_win": row.outcome.actual_win,
                        "score_abs_error": row.outcome.score_abs_error,
                        "win_brier_error": row.outcome.win_brier_error,
                        "resolved_at": row.outcome.resolved_at.isoformat() if row.outcome.resolved_at else None,
                    }
                    if row.outcome is not None
                    else None
                ),
            })

        return jsonify({
            "ok": True,
            "history": items,
            "pagination": {"limit": limit, "offset": offset, "count": len(items), "total": total},
        })

    @app.route("/api/monitoring", methods=["GET"])
    def api_monitoring():
        refresh = str(request.args.get("refresh", "")).strip().lower() in {"1", "true", "yes", "on"}
        report = update_drift_report(window=500, min_events=100, min_outcomes=40) if refresh else get_latest_drift_report()
        return jsonify({"ok": True, "monitoring": report})

    @app.route("/api/monitoring/outcome", methods=["POST"])
    @limiter.limit(settings.write_rate_limit)
    def api_monitoring_outcome():
        payload = _request_payload()
        valid = outcome_schema.load(payload)

        db_session = get_db_session()
        outcome_row = None
        prediction = None

        prediction_id = valid.get("prediction_id")
        if prediction_id is not None:
            prediction = db_session.query(Prediction).filter(Prediction.id == int(prediction_id)).one_or_none()
            if not prediction:
                return _json_error(404, "prediction_id not found")

        actual_total = valid.get("actual_total")
        actual_win = valid.get("actual_win")

        predicted_total = None
        adjusted_win_prob = None
        if prediction is not None:
            predicted_total = prediction.output_payload.get("predicted_total")
            adjusted_win_prob = prediction.output_payload.get("win_prob")

        try:
            if predicted_total is not None:
                predicted_total = float(predicted_total)
        except (TypeError, ValueError):
            predicted_total = None

        try:
            if adjusted_win_prob is not None:
                adjusted_win_prob = float(adjusted_win_prob)
        except (TypeError, ValueError):
            adjusted_win_prob = None

        score_abs_error = None
        win_brier_error = None
        if actual_total is not None and predicted_total is not None:
            score_abs_error = abs(float(actual_total) - float(predicted_total))
        if actual_win is not None and adjusted_win_prob is not None:
            p = max(0.0, min(1.0, float(adjusted_win_prob)))
            win_brier_error = (float(actual_win) - p) ** 2

        if prediction is not None:
            existing = db_session.query(PredictionOutcome).filter(PredictionOutcome.prediction_id == prediction.id).one_or_none()
            if existing:
                existing.actual_total = actual_total
                existing.actual_win = actual_win
                existing.score_abs_error = score_abs_error
                existing.win_brier_error = win_brier_error
                existing.resolved_at = _utc_now()
                outcome_row = existing
            else:
                outcome_row = PredictionOutcome(
                    prediction_id=prediction.id,
                    actual_total=actual_total,
                    actual_win=actual_win,
                    score_abs_error=score_abs_error,
                    win_brier_error=win_brier_error,
                    resolved_at=_utc_now(),
                )
                db_session.add(outcome_row)

        db_session.commit()

        outcome, report = record_prediction_outcome(
            actual_total=actual_total,
            actual_win=actual_win,
            event_id=valid.get("event_id"),
            predicted_total=predicted_total,
            adjusted_win_prob=adjusted_win_prob,
            match_id=valid.get("match_id"),
        )

        return jsonify({
            "ok": True,
            "outcome": outcome,
            "monitoring": report,
            "prediction_outcome_id": outcome_row.id if outcome_row else None,
        })

    # ── Dashboard ──────────────────────────────────────────────────────────────
    PROCESSED = Path(__file__).parent / "data" / "processed"
    MODELS_DIR = Path(__file__).parent / "models"

    TEAM_COLORS = {
        "Chennai Super Kings": "#f5c518",
        "Delhi Capitals": "#004c97",
        "Gujarat Titans": "#1b3c5e",
        "Kolkata Knight Riders": "#3b215d",
        "Lucknow Super Giants": "#00a3e0",
        "Mumbai Indians": "#005da0",
        "Punjab Kings": "#ed1c24",
        "Rajasthan Royals": "#ea3b94",
        "Royal Challengers Bengaluru": "#c8102e",
        "Sunrisers Hyderabad": "#f26522",
    }
    TEAM_SHORT = {
        "Chennai Super Kings": "CSK", "Delhi Capitals": "DC",
        "Gujarat Titans": "GT", "Kolkata Knight Riders": "KKR",
        "Lucknow Super Giants": "LSG", "Mumbai Indians": "MI",
        "Punjab Kings": "PBKS", "Rajasthan Royals": "RR",
        "Royal Challengers Bengaluru": "RCB", "Sunrisers Hyderabad": "SRH",
    }

    def _read_csv(name: str) -> pd.DataFrame:
        p = PROCESSED / name
        return pd.read_csv(p) if p.exists() else pd.DataFrame()

    @app.route("/dashboard")
    def dashboard():
        return render_template("dashboard.html",
                               team_colors=TEAM_COLORS,
                               team_short=TEAM_SHORT)

    @app.route("/api/dashboard-data")
    def api_dashboard_data():
        team1 = request.args.get("team1", "Mumbai Indians")
        team2 = request.args.get("team2", "Chennai Super Kings")
        venue = request.args.get("venue", "")

        tf  = _read_csv("team_form_latest.csv")
        mf  = _read_csv("matchup_form_latest.csv")
        tvf = _read_csv("team_venue_form_latest.csv")
        vs  = _read_csv("venue_stats.csv")
        pp  = _read_csv("team_player_pool_2026.csv")
        bat = _read_csv("batter_form_latest.csv")
        bow = _read_csv("bowler_form_latest.csv")
        bb  = _read_csv("batter_bowler_form_latest.csv")

        # team form
        def get_form(team):
            if tf.empty or "team" not in tf.columns: return 0.5
            r = tf[tf["team"] == team]["team_form"]
            return float(r.iloc[0]) if not r.empty else 0.5

        f1, f2 = get_form(team1), get_form(team2)

        # all teams form for bar chart
        all_teams_form = []
        if not tf.empty:
            active = list(TEAM_COLORS.keys())
            sub = tf[tf["team"].isin(active)].copy()
            sub["win_pct"] = (sub["team_form"] * 100).round(1)
            all_teams_form = sub.sort_values("win_pct", ascending=False)[["team","win_pct"]].to_dict("records")

        # venue form per team at this venue
        venue_team_form = []
        if not tvf.empty and venue:
            vt = tvf[(tvf["venue"] == venue) & tvf["team"].isin(TEAM_COLORS)].copy()
            vt["win_pct"] = (vt["team_venue_form"] * 100).round(1)
            venue_team_form = vt.sort_values("win_pct", ascending=False)[["team","win_pct"]].to_dict("records")

        def get_tvf_val(team, v):
            if tvf.empty: return None
            r = tvf[(tvf["team"] == team) & (tvf["venue"] == v)]["team_venue_form"]
            return round(float(r.iloc[0]) * 100, 1) if not r.empty else None

        # H2H
        def get_h2h(t, o):
            if mf.empty: return None
            r = mf[(mf["team"] == t) & (mf["opponent"] == o)]["matchup_form"]
            return round(float(r.iloc[0]) * 100, 1) if not r.empty else None

        h1 = get_h2h(team1, team2)
        h2 = get_h2h(team2, team1)

        h2h_table = []
        if not mf.empty:
            both = mf[
                (mf["team"].isin([team1, team2])) & (mf["opponent"].isin([team1, team2]))
            ].copy()
            both["win_pct"] = (both["matchup_form"] * 100).round(0).astype(int).astype(str) + "%"
            h2h_table = both[["team","opponent","win_pct"]].rename(columns={"win_pct":"Win %"}).to_dict("records")

        # venue stats
        venue_row = None
        if not vs.empty and venue:
            r = vs[vs["venue"] == venue]
            if not r.empty:
                row = r.iloc[0]
                venue_row = {
                    "avg_first": round(float(row.get("venue_avg_first_innings", 0)), 1),
                    "avg_second": round(float(row.get("venue_avg_second_innings", 0)), 1),
                    "bat_first_win": round(float(row.get("venue_bat_first_win_rate", 0)) * 100, 1),
                }

        top15_venues = []
        if not vs.empty:
            top15 = vs.sort_values("venue_avg_first_innings", ascending=False).head(15)
            top15_venues = top15[["venue","venue_avg_first_innings"]].rename(
                columns={"venue_avg_first_innings": "avg"}
            ).to_dict("records")

        # players
        def top_batters(team, n=5):
            if pp.empty or bat.empty: return []
            players = pp[pp["team"] == team]["player"].tolist()
            b = bat[bat["batter"].isin(players) & (bat["batter_balls"] >= 20)]
            b = b.sort_values("striker_form_sr", ascending=False).head(n)
            return b[["batter","striker_form_sr","striker_form_avg","batter_balls"]].rename(
                columns={"batter":"Player","striker_form_sr":"SR","striker_form_avg":"Avg","batter_balls":"Balls"}
            ).round(1).to_dict("records")

        def top_bowlers(team, n=5):
            if pp.empty or bow.empty: return []
            players = pp[pp["team"] == team]["player"].tolist()
            b = bow[bow["bowler"].isin(players) & (bow["bowler_balls"] >= 12)]
            b = b.sort_values("bowler_form_econ").head(n)
            return b[["bowler","bowler_form_econ","bowler_form_strike","bowler_balls"]].rename(
                columns={"bowler":"Player","bowler_form_econ":"Economy","bowler_form_strike":"SR","bowler_balls":"Balls"}
            ).round(2).to_dict("records")

        def squad(team):
            if pp.empty: return []
            sq = pp[pp["team"] == team][["player","appearances"]].sort_values("appearances", ascending=False)
            return sq.to_dict("records")

        # batter vs bowler matchups
        def matchup_table(bat_team, bowl_team):
            if pp.empty or bb.empty: return []
            batters = pp[pp["team"] == bat_team]["player"].tolist()
            bowlers = pp[pp["team"] == bowl_team]["player"].tolist()
            rows = []
            for b in batters:
                for bw in bowlers:
                    r = bb[(bb["batter"] == b) & (bb["bowler"] == bw)]
                    if not r.empty and int(r["batter_vs_bowler_balls"].iloc[0]) >= 6:
                        rows.append({
                            "Batter": b, "Bowler": bw,
                            "Balls": int(r["batter_vs_bowler_balls"].iloc[0]),
                            "Runs": int(r["batter_vs_bowler_runs"].iloc[0]),
                            "SR": round(float(r["batter_vs_bowler_sr"].iloc[0]), 1),
                        })
            return sorted(rows, key=lambda x: -x["Balls"])[:10]

        # model report
        model_report: dict = {}
        for fname in ["all_models_report.json", "deployment_report.json"]:
            p = MODELS_DIR / fname
            if p.exists():
                try:
                    model_report = json.loads(p.read_text())
                    break
                except Exception:
                    pass

        return jsonify({
            "ok": True,
            "team1": team1, "team2": team2, "venue": venue,
            "team1_color": TEAM_COLORS.get(team1, "#555"),
            "team2_color": TEAM_COLORS.get(team2, "#555"),
            "team1_short": TEAM_SHORT.get(team1, team1),
            "team2_short": TEAM_SHORT.get(team2, team2),
            "team1_form": round(f1 * 100, 1),
            "team2_form": round(f2 * 100, 1),
            "team1_venue_form": get_tvf_val(team1, venue),
            "team2_venue_form": get_tvf_val(team2, venue),
            "h2h_t1": h1, "h2h_t2": h2,
            "h2h_table": h2h_table,
            "all_teams_form": all_teams_form,
            "venue_row": venue_row,
            "top15_venues": top15_venues,
            "venue_team_form": venue_team_form,
            "batters1": top_batters(team1),
            "batters2": top_batters(team2),
            "bowlers1": top_bowlers(team1),
            "bowlers2": top_bowlers(team2),
            "squad1": squad(team1),
            "squad2": squad(team2),
            "matchups_t1_bat": matchup_table(team1, team2),
            "matchups_t2_bat": matchup_table(team2, team1),
            "model_report": model_report,
        })

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
