from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, cast

import joblib
import numpy as np
import pandas as pd

from .live_data import fetch_live_weather_context


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
PROCESSED_DIR = DATA_DIR / "processed"
MODELS_DIR = ROOT_DIR / "models"

SCORE_MODEL_PATH = MODELS_DIR / "score_model.pkl"
WIN_MODEL_PATH = MODELS_DIR / "win_model.pkl"
PRE_MATCH_SCORE_MODEL_PATH = MODELS_DIR / "pre_match_score_model.pkl"
PRE_MATCH_WIN_MODEL_PATH = MODELS_DIR / "pre_match_win_model.pkl"
VENUE_STATS_PATH = PROCESSED_DIR / "venue_stats.csv"
TEAM_FORM_PATH = PROCESSED_DIR / "team_form_latest.csv"
TEAM_VENUE_FORM_PATH = PROCESSED_DIR / "team_venue_form_latest.csv"
MATCHUP_FORM_PATH = PROCESSED_DIR / "matchup_form_latest.csv"
BATTER_FORM_PATH = PROCESSED_DIR / "batter_form_latest.csv"
BOWLER_FORM_PATH = PROCESSED_DIR / "bowler_form_latest.csv"
BATTER_BOWLER_FORM_PATH = PROCESSED_DIR / "batter_bowler_form_latest.csv"
SCORE_UNCERTAINTY_PATH = MODELS_DIR / "score_uncertainty.json"
WIN_STABILITY_PROFILE_PATH = MODELS_DIR / "win_stability_profile.json"
ACTIVE_TEAMS_2026_PATH = PROCESSED_DIR / "active_teams_2026.csv"
TEAM_PLAYER_POOL_2026_PATH = PROCESSED_DIR / "team_player_pool_2026.csv"

ACTIVE_IPL_TEAMS_2026 = [
    "Chennai Super Kings",
    "Delhi Capitals",
    "Gujarat Titans",
    "Kolkata Knight Riders",
    "Lucknow Super Giants",
    "Mumbai Indians",
    "Punjab Kings",
    "Rajasthan Royals",
    "Royal Challengers Bengaluru",
    "Sunrisers Hyderabad",
]

TEAM_ALIASES = {
    "Delhi Capitals": "Delhi Capitals",
    "Delhi Daredevils": "Delhi Capitals",
    "Gujarat Lions": "Gujarat Lions",
    "Gujarat Titans": "Gujarat Titans",
    "Kochi Tuskers Kerala": "Kochi Tuskers Kerala",
    "Kings XI Punjab": "Punjab Kings",
    "Lucknow Super Giants": "Lucknow Super Giants",
    "Pune Warriors India": "Pune Warriors India",
    "Pune Warriors": "Pune Warriors India",
    "Rising Pune Supergiant": "Rising Pune Supergiant",
    "Rising Pune Supergiants": "Rising Pune Supergiant",
    "Royal Challengers Bengaluru": "Royal Challengers Bengaluru",
    "Royal Challengers Bangalore": "Royal Challengers Bengaluru",
}

VENUE_ALIASES = {
    "ACA-VDCA Stadium": "ACA-VDCA Stadium",
    "ACA-VDCA Stadium, Visakhapatnam": "ACA-VDCA Stadium",
    "Arun Jaitley Stadium": "Arun Jaitley Stadium",
    "Arun Jaitley Stadium, Delhi": "Arun Jaitley Stadium",
    "Barabati Stadium": "Barabati Stadium",
    "Barabati Stadium, Cuttack": "Barabati Stadium",
    "Bharat Ratna Shri Atal Bihari Vajpayee Ekana Cricket Stadium, Lucknow": "Ekana Cricket Stadium",
    "Brabourne Stadium": "Brabourne Stadium",
    "Brabourne Stadium, Mumbai": "Brabourne Stadium",
    "Dr DY Patil Sports Academy": "DY Patil Stadium",
    "Dr DY Patil Sports Academy, Mumbai": "DY Patil Stadium",
    "Dr. DY Patil Sports Academy": "DY Patil Stadium",
    "Dr. Y.S. Rajasekhara Reddy ACA-VDCA Cricket Stadium": "ACA-VDCA Stadium",
    "Dr. Y.S. Rajasekhara Reddy ACA-VDCA Cricket Stadium, Visakhapatnam": "ACA-VDCA Stadium",
    "Dubai International Cricket Stadium": "Dubai International Cricket Stadium",
    "Dubai International Cricket Stadium, Dubai": "Dubai International Cricket Stadium",
    "DY Patil Stadium, Navi Mumbai": "DY Patil Stadium",
    "Eden Gardens, Kolkata": "Eden Gardens",
    "Ekana Cricket Stadium, Lucknow": "Ekana Cricket Stadium",
    "Ekana International Cricket Stadium, Lucknow": "Ekana Cricket Stadium",
    "Feroz Shah Kotla": "Arun Jaitley Stadium",
    "Green Park": "Green Park",
    "Green Park, Kanpur": "Green Park",
    "Himachal Pradesh Cricket Association Stadium": "HPCA Stadium",
    "Himachal Pradesh Cricket Association Stadium, Dharamsala": "HPCA Stadium",
    "Holkar Cricket Stadium": "Holkar Cricket Stadium",
    "Holkar Cricket Stadium, Indore": "Holkar Cricket Stadium",
    "JSCA International Stadium Complex": "JSCA International Stadium Complex",
    "JSCA International Stadium Complex, Ranchi": "JSCA International Stadium Complex",
    "M. A. Chidambaram Stadium": "MA Chidambaram Stadium",
    "MA Chidambaram Stadium": "MA Chidambaram Stadium",
    "MA Chidambaram Stadium, Chepauk": "MA Chidambaram Stadium",
    "MA Chidambaram Stadium, Chepauk, Chennai": "MA Chidambaram Stadium",
    "MA Chidambaram Stadium, Chennai": "MA Chidambaram Stadium",
    "M. Chinnaswamy Stadium": "M. Chinnaswamy Stadium",
    "M. Chinnaswamy Stadium, Bengaluru": "M. Chinnaswamy Stadium",
    "M Chinnaswamy Stadium": "M. Chinnaswamy Stadium",
    "M Chinnaswamy Stadium, Bengaluru": "M. Chinnaswamy Stadium",
    "Maharashtra Cricket Association Stadium": "Maharashtra Cricket Association Stadium",
    "Maharashtra Cricket Association Stadium, Pune": "Maharashtra Cricket Association Stadium",
    "Motera Stadium": "Narendra Modi Stadium",
    "Narendra Modi Stadium, Ahmedabad": "Narendra Modi Stadium",
    "Punjab Cricket Association IS Bindra Stadium": "Punjab Cricket Association Stadium",
    "Punjab Cricket Association IS Bindra Stadium, Mohali": "Punjab Cricket Association Stadium",
    "Punjab Cricket Association Stadium, Mohali": "Punjab Cricket Association Stadium",
    "Rajiv Gandhi International Stadium": "Rajiv Gandhi International Stadium",
    "Rajiv Gandhi International Stadium, Hyderabad": "Rajiv Gandhi International Stadium",
    "Rajiv Gandhi International Stadium, Uppal": "Rajiv Gandhi International Stadium",
    "Sardar Patel Stadium, Ahmedabad": "Narendra Modi Stadium",
    "Sardar Patel Stadium, Motera": "Narendra Modi Stadium",
    "Saurashtra Cricket Association Stadium": "Saurashtra Cricket Association Stadium",
    "Saurashtra Cricket Association Stadium, Rajkot": "Saurashtra Cricket Association Stadium",
    "Sawai Mansingh Stadium": "Sawai Mansingh Stadium",
    "Sawai Mansingh Stadium, Jaipur": "Sawai Mansingh Stadium",
    "Shaheed Veer Narayan Singh International Stadium, Raipur": "Shaheed Veer Narayan Singh Stadium",
    "Sharjah Cricket Stadium": "Sharjah Cricket Stadium",
    "Sharjah Cricket Stadium, Sharjah": "Sharjah Cricket Stadium",
    "Sheikh Zayed Stadium, Abu Dhabi": "Sheikh Zayed Stadium",
    "Wankhede Stadium, Mumbai": "Wankhede Stadium",
    "Zayed Cricket Stadium": "Sheikh Zayed Stadium",
    "Zayed Cricket Stadium, Abu Dhabi": "Sheikh Zayed Stadium",
}

DEFAULT_VENUE_STRENGTH = {
    "venue_avg_first_innings": 0.0,
    "venue_avg_second_innings": 0.0,
    "venue_bat_first_win_rate": 0.0,
}

CATEGORICAL_FEATURES = [
    "batting_team",
    "bowling_team",
    "venue",
    "season_str",
    "innings",
    "phase",
    "toss_winner",
    "toss_decision",
    "striker",
    "bowler",
]

NUMERIC_FEATURES = [
    "runs",
    "wickets",
    "wickets_left",
    "balls_left",
    "legal_balls_bowled",
    "innings_progress",
    "over_number",
    "ball_in_over",
    "runs_last_5",
    "wickets_last_5",
    "runs_last_6_balls",
    "wickets_last_6_balls",
    "runs_last_12_balls",
    "wickets_last_12_balls",
    "current_run_rate",
    "target",
    "target_remaining",
    "required_run_rate",
    "current_minus_required_rr",
    "required_minus_current_rr",
    "is_powerplay",
    "is_middle",
    "is_death",
    "toss_winner_batting",
    "batting_team_form",
    "bowling_team_form",
    "batting_team_venue_form",
    "bowling_team_venue_form",
    "batting_vs_bowling_form",
    "striker_form_sr",
    "striker_form_avg",
    "bowler_form_econ",
    "bowler_form_strike",
    "batter_vs_bowler_sr",
    "batter_vs_bowler_balls",
    "temperature_c",
    "relative_humidity",
    "wind_kph",
    "dew_risk",
    "runs_vs_par",
    "venue_avg_first_innings",
    "venue_avg_second_innings",
    "venue_bat_first_win_rate",
]

MODEL_FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES

PRE_MATCH_CATEGORICAL_FEATURES = ["batting_team", "bowling_team", "venue"]
PRE_MATCH_NUMERIC_FEATURES = [
    "batting_team_form",
    "bowling_team_form",
    "batting_team_venue_form",
    "bowling_team_venue_form",
    "batting_vs_bowling_form",
    "venue_avg_first_innings",
    "venue_avg_second_innings",
    "venue_bat_first_win_rate",
]
PRE_MATCH_MODEL_FEATURES = PRE_MATCH_CATEGORICAL_FEATURES + PRE_MATCH_NUMERIC_FEATURES


@dataclass(frozen=True)
class SupportTables:
    venue_stats: dict[str, dict[str, float]]
    team_form_map: dict[str, float]
    team_venue_form_map: dict[tuple[str, str], float]
    matchup_form_map: dict[tuple[str, str], float]
    batter_form_map: dict[str, dict[str, float]]
    bowler_form_map: dict[str, dict[str, float]]
    batter_bowler_map: dict[tuple[str, str], dict[str, float]]


def normalize_team(name: str | None) -> str | None:
    if not name:
        return None
    return TEAM_ALIASES.get(name, name)


def normalize_venue(name: str | None) -> str | None:
    if not name:
        return None
    return VENUE_ALIASES.get(name, name)


def season_to_year(season_value: Any) -> int | None:
    if season_value is None:
        return None
    text = str(season_value).strip()
    if not text:
        return None
    first = text.split("/")[0]
    try:
        return int(first)
    except ValueError:
        return None


def parse_overs(overs_text: str) -> int:
    if not overs_text:
        return 0
    parts = overs_text.strip().split(".")
    overs = int(parts[0]) if parts[0] else 0
    balls = int(parts[1]) if len(parts) > 1 and parts[1] else 0
    if balls < 0 or balls > 5:
        raise ValueError("Balls must be between 0 and 5.")
    return overs * 6 + balls


def coerce_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return default
    return float(value)


def _patch_model(model) -> None:
    """Fix SimpleImputer statistics_ dtype=object mismatch from sklearn version changes."""
    from sklearn.impute import SimpleImputer

    seen: set[int] = set()

    def _walk(obj) -> None:
        if id(obj) in seen:
            return
        seen.add(id(obj))

        if isinstance(obj, SimpleImputer):
            if hasattr(obj, "statistics_") and obj.statistics_ is not None:
                if obj.statistics_.dtype == object:
                    try:
                        obj.statistics_ = obj.statistics_.astype(float)
                    except (ValueError, TypeError):
                        pass  # categorical imputer — string fill values are correct
            return

        # Pipeline: .steps list of (name, estimator)
        if hasattr(obj, "steps"):
            for _, step in obj.steps:
                _walk(step)

        # ColumnTransformer: fitted .named_transformers_ dict or .transformers_ list
        if hasattr(obj, "named_transformers_"):
            for step in obj.named_transformers_.values():
                _walk(step)
        elif hasattr(obj, "transformers_"):
            for _, step, _ in obj.transformers_:
                _walk(step)

        # CalibratedClassifierCV: .calibrated_classifiers_ list
        if hasattr(obj, "calibrated_classifiers_"):
            for cc in obj.calibrated_classifiers_:
                _walk(cc)

        # _CalibratedClassifier: .estimator
        if hasattr(obj, "estimator") and obj.estimator is not None:
            _walk(obj.estimator)

    _walk(model)


def load_models():
    score_model = joblib.load(SCORE_MODEL_PATH)
    win_model = joblib.load(WIN_MODEL_PATH)
    _patch_model(score_model)
    _patch_model(win_model)
    return score_model, win_model


def load_pre_match_models():
    if not PRE_MATCH_SCORE_MODEL_PATH.exists() or not PRE_MATCH_WIN_MODEL_PATH.exists():
        return None, None
    score_model = joblib.load(PRE_MATCH_SCORE_MODEL_PATH)
    win_model = joblib.load(PRE_MATCH_WIN_MODEL_PATH)
    _patch_model(score_model)
    _patch_model(win_model)
    return score_model, win_model


def load_score_uncertainty_profile() -> dict[str, float]:
    default_profile = {
        "residual_q10": -16.0,
        "residual_q90": 16.0,
        "residual_std": 13.0,
    }
    if not SCORE_UNCERTAINTY_PATH.exists():
        return default_profile

    try:
        data = json.loads(SCORE_UNCERTAINTY_PATH.read_text(encoding="utf-8"))
        return {
            "residual_q10": float(data.get("residual_q10", default_profile["residual_q10"])),
            "residual_q90": float(data.get("residual_q90", default_profile["residual_q90"])),
            "residual_std": float(data.get("residual_std", default_profile["residual_std"])),
        }
    except Exception:
        return default_profile


def load_win_stability_profile() -> dict[str, float | bool | str]:
    default_profile: dict[str, float | bool | str] = {
        "enabled": False,
        "alpha_death": 0.0,
        "alpha_high_pressure": 0.0,
        "pressure_rr_gap_threshold": 1.25,
        "pressure_balls_left_max": 48.0,
        "source": "default",
    }
    if not WIN_STABILITY_PROFILE_PATH.exists():
        return default_profile

    try:
        data = json.loads(WIN_STABILITY_PROFILE_PATH.read_text(encoding="utf-8"))
        return {
            "enabled": bool(data.get("enabled", default_profile["enabled"])),
            "alpha_death": float(data.get("alpha_death", default_profile["alpha_death"])),
            "alpha_high_pressure": float(data.get("alpha_high_pressure", default_profile["alpha_high_pressure"])),
            "pressure_rr_gap_threshold": float(
                data.get("pressure_rr_gap_threshold", default_profile["pressure_rr_gap_threshold"])
            ),
            "pressure_balls_left_max": float(
                data.get("pressure_balls_left_max", default_profile["pressure_balls_left_max"])
            ),
            "source": str(data.get("source", default_profile["source"])),
        }
    except Exception:
        return default_profile


def _shrink_toward_even(prob: float, alpha: float) -> float:
    clipped = float(np.clip(prob, 1e-6, 1 - 1e-6))
    a = float(np.clip(alpha, 0.0, 0.95))
    return float(np.clip(0.5 + (clipped - 0.5) * (1.0 - a), 1e-6, 1 - 1e-6))


def apply_win_stability_adjustment(
    prob: float,
    row: pd.Series,
    profile: Mapping[str, Any],
) -> tuple[float, list[str]]:
    adjusted = float(np.clip(prob, 1e-6, 1 - 1e-6))
    flags: list[str] = []

    if not bool(profile.get("enabled", False)):
        return adjusted, flags

    phase = str(row.get("phase", "")).lower()
    innings = int(float(row.get("innings", 0))) if not pd.isna(row.get("innings", np.nan)) else 0
    rr_gap = float(row.get("required_minus_current_rr", np.nan))
    balls_left = float(row.get("balls_left", np.nan))

    if phase == "death":
        adjusted = _shrink_toward_even(adjusted, float(profile.get("alpha_death", 0.0)))
        flags.append("death_over")

    rr_threshold = float(profile.get("pressure_rr_gap_threshold", 1.25))
    balls_max = float(profile.get("pressure_balls_left_max", 48.0))
    high_pressure = (
        innings == 2
        and not np.isnan(rr_gap)
        and rr_gap >= rr_threshold
        and not np.isnan(balls_left)
        and balls_left <= balls_max
    )
    if high_pressure:
        adjusted = _shrink_toward_even(adjusted, float(profile.get("alpha_high_pressure", 0.0)))
        flags.append("high_pressure_chase")

    return float(np.clip(adjusted, 1e-6, 1 - 1e-6)), flags


def score_interval(
    predicted_total: float,
    current_runs: float,
    uncertainty_profile: Mapping[str, float],
) -> tuple[float, float]:
    lower = max(current_runs, predicted_total + float(uncertainty_profile["residual_q10"]))
    upper = max(lower, predicted_total + float(uncertainty_profile["residual_q90"]))
    return lower, upper


def simulate_remaining_innings(
    row: pd.Series,
    predicted_total: float,
    win_prob: float,
    uncertainty_profile: Mapping[str, float],
    n_sims: int = 300,
) -> dict[str, float]:
    balls_left = float(row["balls_left"])
    phase = str(row["phase"])
    current_runs = float(row["runs"])

    phase_scale = 1.0
    if phase == "powerplay":
        phase_scale = 1.12
    elif phase == "death":
        phase_scale = 0.84

    sigma = max(
        6.0,
        float(uncertainty_profile["residual_std"]) * (0.55 + 0.9 * (balls_left / 120.0)) * phase_scale,
    )

    seed = 42 + int(float(row["legal_balls_bowled"])) + int(current_runs)
    rng = np.random.default_rng(seed)

    score_samples = rng.normal(loc=predicted_total, scale=sigma, size=n_sims)
    score_samples = np.clip(score_samples, current_runs, current_runs + 260.0)

    win_noise = 0.05 + 0.10 * (balls_left / 120.0)
    win_prob_samples = np.clip(rng.normal(loc=win_prob, scale=win_noise, size=n_sims), 0.01, 0.99)

    p10, p50, p90 = np.quantile(score_samples, [0.10, 0.50, 0.90])
    win_p10, win_p90 = np.quantile(win_prob_samples, [0.10, 0.90])
    collapse_cut = max(current_runs, predicted_total - 20.0)
    finish_cut = predicted_total + 20.0

    return {
        "sim_score_p10": float(p10),
        "sim_score_p50": float(p50),
        "sim_score_p90": float(p90),
        "sim_win_prob_p10": float(win_p10),
        "sim_win_prob_p90": float(win_p90),
        "collapse_risk": float(np.mean(score_samples <= collapse_cut)),
        "big_finish_chance": float(np.mean(score_samples >= finish_cut)),
    }


def load_support_tables() -> SupportTables:
    venue_stats: dict[str, dict[str, float]] = {}
    if VENUE_STATS_PATH.exists():
        venue_stats = cast(
            dict[str, dict[str, float]],
            pd.read_csv(VENUE_STATS_PATH).set_index("venue").to_dict(orient="index"),
        )

    team_form_map: dict[str, float] = {}
    if TEAM_FORM_PATH.exists():
        team_form_map = cast(
            dict[str, float],
            pd.read_csv(TEAM_FORM_PATH).set_index("team")["team_form"].to_dict(),
        )

    team_venue_form_map: dict[tuple[str, str], float] = {}
    if TEAM_VENUE_FORM_PATH.exists():
        team_venue_form_map = cast(
            dict[tuple[str, str], float],
            pd.read_csv(TEAM_VENUE_FORM_PATH)
            .set_index(["team", "venue"])["team_venue_form"]
            .to_dict(),
        )

    matchup_form_map: dict[tuple[str, str], float] = {}
    if MATCHUP_FORM_PATH.exists():
        matchup_form_map = cast(
            dict[tuple[str, str], float],
            pd.read_csv(MATCHUP_FORM_PATH)
            .set_index(["team", "opponent"])["matchup_form"]
            .to_dict(),
        )

    batter_form_map: dict[str, dict[str, float]] = {}
    if BATTER_FORM_PATH.exists():
        batter_form_map = cast(
            dict[str, dict[str, float]],
            pd.read_csv(BATTER_FORM_PATH).set_index("batter").to_dict(orient="index"),
        )

    bowler_form_map: dict[str, dict[str, float]] = {}
    if BOWLER_FORM_PATH.exists():
        bowler_form_map = cast(
            dict[str, dict[str, float]],
            pd.read_csv(BOWLER_FORM_PATH).set_index("bowler").to_dict(orient="index"),
        )

    batter_bowler_map: dict[tuple[str, str], dict[str, float]] = {}
    if BATTER_BOWLER_FORM_PATH.exists():
        batter_bowler_map = cast(
            dict[tuple[str, str], dict[str, float]],
            pd.read_csv(BATTER_BOWLER_FORM_PATH)
            .set_index(["batter", "bowler"])
            .to_dict(orient="index"),
        )

    return SupportTables(
        venue_stats=venue_stats,
        team_form_map=team_form_map,
        team_venue_form_map=team_venue_form_map,
        matchup_form_map=matchup_form_map,
        batter_form_map=batter_form_map,
        bowler_form_map=bowler_form_map,
        batter_bowler_map=batter_bowler_map,
    )


def build_feature_frame(
    payload: Mapping[str, Any],
    support_tables: SupportTables,
) -> tuple[pd.DataFrame, list[str]]:
    errors: list[str] = []

    season = str(payload.get("season", "")).strip()
    venue = normalize_venue(payload.get("venue"))
    batting_team = normalize_team(payload.get("batting_team"))
    bowling_team = normalize_team(payload.get("bowling_team"))
    toss_winner = normalize_team(payload.get("toss_winner"))
    toss_decision_raw = payload.get("toss_decision")
    toss_decision = str(toss_decision_raw).strip().lower() if toss_decision_raw else None
    toss_decision = toss_decision or None
    striker = str(payload.get("striker", "")).strip() or "Unknown"
    bowler = str(payload.get("bowler", "")).strip() or "Unknown"

    if not season:
        errors.append("Season is required.")
    if not venue:
        errors.append("Venue is required.")
    if not batting_team:
        errors.append("Batting team is required.")
    if not bowling_team:
        errors.append("Bowling team is required.")

    try:
        innings = int(payload.get("innings", 0))
    except (TypeError, ValueError):
        innings = 0
    if innings not in (1, 2):
        errors.append("Innings must be 1 or 2.")

    runs = coerce_float(payload.get("runs"))
    wickets = coerce_float(payload.get("wickets"))
    if runs is None or wickets is None:
        errors.append("Runs and wickets are required.")

    try:
        balls_bowled = parse_overs(str(payload.get("overs", "")))
    except ValueError as exc:
        errors.append(str(exc))
        balls_bowled = 0

    runs = runs if runs is not None else 0.0
    wickets = wickets if wickets is not None else 0.0

    balls_left = max(0, 120 - balls_bowled)
    legal_balls_bowled = max(0, min(120, balls_bowled))
    overs_completed = balls_bowled / 6
    current_run_rate = (runs / overs_completed) if overs_completed > 0 else 0.0
    wickets_left = max(0.0, 10.0 - wickets)
    innings_progress = legal_balls_bowled / 120 if legal_balls_bowled > 0 else 0.0
    over_number = min(20.0, float(legal_balls_bowled // 6))
    ball_in_over = float(legal_balls_bowled % 6)
    if legal_balls_bowled <= 36:
        phase = "powerplay"
    elif legal_balls_bowled <= 90:
        phase = "middle"
    else:
        phase = "death"

    runs_last_5_value = coerce_float(payload.get("runs_last_5"), default=0.0)
    wickets_last_5_value = coerce_float(payload.get("wickets_last_5"), default=0.0)
    runs_last_5 = 0.0 if runs_last_5_value is None else runs_last_5_value
    wickets_last_5 = 0.0 if wickets_last_5_value is None else wickets_last_5_value

    runs_last_6_value = coerce_float(payload.get("runs_last_6_balls"), default=runs_last_5 / 5.0)
    wickets_last_6_value = coerce_float(payload.get("wickets_last_6_balls"), default=wickets_last_5 / 5.0)
    runs_last_6_balls = 0.0 if runs_last_6_value is None else runs_last_6_value
    wickets_last_6_balls = 0.0 if wickets_last_6_value is None else wickets_last_6_value

    runs_last_12_value = coerce_float(payload.get("runs_last_12_balls"), default=2.0 * runs_last_6_balls)
    wickets_last_12_value = coerce_float(
        payload.get("wickets_last_12_balls"),
        default=2.0 * wickets_last_6_balls,
    )
    runs_last_12_balls = 0.0 if runs_last_12_value is None else runs_last_12_value
    wickets_last_12_balls = 0.0 if wickets_last_12_value is None else wickets_last_12_value

    target = None
    required_run_rate = None
    if innings == 2:
        first_innings_total = coerce_float(payload.get("first_innings_total"))
        if first_innings_total is None:
            errors.append("First innings total is required for innings 2.")
        else:
            target = first_innings_total + 1
            overs_left = balls_left / 6
            required_run_rate = ((target - runs) / overs_left) if overs_left > 0 else 0.0

    venue_key = venue or ""
    batting_team_key = batting_team or "Unknown"
    bowling_team_key = bowling_team or "Unknown"

    venue_strength = support_tables.venue_stats.get(venue_key, DEFAULT_VENUE_STRENGTH)
    venue_par_total = (
        venue_strength["venue_avg_first_innings"]
        if innings == 1
        else venue_strength["venue_avg_second_innings"]
    )
    expected_runs_by_now = venue_par_total * innings_progress
    runs_vs_par = runs - expected_runs_by_now

    toss_winner_batting = 0.0
    if toss_winner:
        toss_winner_batting = 1.0 if toss_winner == batting_team else 0.0

    default_batting_form = float(support_tables.team_form_map.get(batting_team_key, 0.5))
    default_bowling_form = float(support_tables.team_form_map.get(bowling_team_key, 0.5))
    default_batting_venue_form = float(support_tables.team_venue_form_map.get((batting_team_key, venue_key), 0.5))
    default_bowling_venue_form = float(support_tables.team_venue_form_map.get((bowling_team_key, venue_key), 0.5))
    default_matchup_form = float(support_tables.matchup_form_map.get((batting_team_key, bowling_team_key), 0.5))

    batter_stats = support_tables.batter_form_map.get(striker, {})
    bowler_stats = support_tables.bowler_form_map.get(bowler, {})
    bb_stats = support_tables.batter_bowler_map.get((striker, bowler), {})

    default_striker_form_sr = float(batter_stats.get("striker_form_sr", 115.0))
    default_striker_form_avg = float(batter_stats.get("striker_form_avg", 22.0))
    default_bowler_form_econ = float(bowler_stats.get("bowler_form_econ", 8.5))
    default_bowler_form_strike = float(bowler_stats.get("bowler_form_strike", 20.0))
    default_batter_vs_bowler_sr = float(bb_stats.get("batter_vs_bowler_sr", 110.0))
    default_batter_vs_bowler_balls = float(bb_stats.get("batter_vs_bowler_balls", 0.0))

    batting_team_form = coerce_float(payload.get("batting_team_form"), default_batting_form)
    bowling_team_form = coerce_float(payload.get("bowling_team_form"), default_bowling_form)
    batting_team_venue_form = coerce_float(
        payload.get("batting_team_venue_form"),
        default_batting_venue_form,
    )
    bowling_team_venue_form = coerce_float(
        payload.get("bowling_team_venue_form"),
        default_bowling_venue_form,
    )
    batting_vs_bowling_form = coerce_float(
        payload.get("batting_vs_bowling_form"),
        default_matchup_form,
    )
    striker_form_sr = coerce_float(payload.get("striker_form_sr"), default_striker_form_sr)
    striker_form_avg = coerce_float(payload.get("striker_form_avg"), default_striker_form_avg)
    bowler_form_econ = coerce_float(payload.get("bowler_form_econ"), default_bowler_form_econ)
    bowler_form_strike = coerce_float(payload.get("bowler_form_strike"), default_bowler_form_strike)
    batter_vs_bowler_sr = coerce_float(payload.get("batter_vs_bowler_sr"), default_batter_vs_bowler_sr)
    batter_vs_bowler_balls = coerce_float(
        payload.get("batter_vs_bowler_balls"),
        default_batter_vs_bowler_balls,
    )

    use_live_weather = str(payload.get("use_live_weather", "")).strip().lower() in {"1", "true", "yes", "on"}
    live_weather = fetch_live_weather_context(venue) if use_live_weather and venue else {
        "temperature_c": 28.0,
        "relative_humidity": 60.0,
        "wind_kph": 12.0,
        "dew_risk": 0.5,
    }

    temperature_c = coerce_float(payload.get("temperature_c"), float(live_weather["temperature_c"]))
    relative_humidity = coerce_float(payload.get("relative_humidity"), float(live_weather["relative_humidity"]))
    wind_kph = coerce_float(payload.get("wind_kph"), float(live_weather["wind_kph"]))
    dew_risk = coerce_float(payload.get("dew_risk"), float(live_weather["dew_risk"]))

    target_remaining = None if target is None else max(0.0, target - runs)
    required_minus_current_rr = (
        None if required_run_rate is None else required_run_rate - current_run_rate
    )
    current_minus_required_rr = (
        None if required_run_rate is None else current_run_rate - required_run_rate
    )
    is_powerplay = 1.0 if phase == "powerplay" else 0.0
    is_middle = 1.0 if phase == "middle" else 0.0
    is_death = 1.0 if phase == "death" else 0.0

    if errors:
        return pd.DataFrame(), errors

    target_value = np.nan if target is None else target
    target_remaining_value = np.nan if target_remaining is None else target_remaining
    required_run_rate_value = np.nan if required_run_rate is None else required_run_rate
    required_minus_current_rr_value = (
        np.nan if required_minus_current_rr is None else required_minus_current_rr
    )
    current_minus_required_rr_value = (
        np.nan if current_minus_required_rr is None else current_minus_required_rr
    )

    features = pd.DataFrame(
        [
            {
                "batting_team": batting_team,
                "bowling_team": bowling_team,
                "venue": venue,
                "season_str": season,
                "innings": innings,
                "toss_winner": toss_winner or "Unknown",
                "toss_decision": toss_decision or "Unknown",
                "striker": striker,
                "bowler": bowler,
                "toss_winner_batting": toss_winner_batting,
                "runs": runs,
                "wickets": wickets,
                "wickets_left": wickets_left,
                "balls_left": balls_left,
                "legal_balls_bowled": legal_balls_bowled,
                "innings_progress": innings_progress,
                "over_number": over_number,
                "ball_in_over": ball_in_over,
                "phase": phase,
                "runs_last_5": runs_last_5,
                "wickets_last_5": wickets_last_5,
                "runs_last_6_balls": runs_last_6_balls,
                "wickets_last_6_balls": wickets_last_6_balls,
                "runs_last_12_balls": runs_last_12_balls,
                "wickets_last_12_balls": wickets_last_12_balls,
                "current_run_rate": current_run_rate,
                "target": target_value,
                "target_remaining": target_remaining_value,
                "required_run_rate": required_run_rate_value,
                "current_minus_required_rr": current_minus_required_rr_value,
                "required_minus_current_rr": required_minus_current_rr_value,
                "is_powerplay": is_powerplay,
                "is_middle": is_middle,
                "is_death": is_death,
                "batting_team_form": batting_team_form,
                "bowling_team_form": bowling_team_form,
                "batting_team_venue_form": batting_team_venue_form,
                "bowling_team_venue_form": bowling_team_venue_form,
                "batting_vs_bowling_form": batting_vs_bowling_form,
                "striker_form_sr": striker_form_sr,
                "striker_form_avg": striker_form_avg,
                "bowler_form_econ": bowler_form_econ,
                "bowler_form_strike": bowler_form_strike,
                "batter_vs_bowler_sr": batter_vs_bowler_sr,
                "batter_vs_bowler_balls": batter_vs_bowler_balls,
                "temperature_c": temperature_c,
                "relative_humidity": relative_humidity,
                "wind_kph": wind_kph,
                "dew_risk": dew_risk,
                "runs_vs_par": runs_vs_par,
                "venue_avg_first_innings": venue_strength["venue_avg_first_innings"],
                "venue_avg_second_innings": venue_strength["venue_avg_second_innings"],
                "venue_bat_first_win_rate": venue_strength["venue_bat_first_win_rate"],
            }
        ]
    )

    return features[MODEL_FEATURES], []


def predict_match_state(
    payload: Mapping[str, Any],
    support_tables: SupportTables,
    score_model,
    win_model,
) -> tuple[dict[str, str] | None, list[str]]:
    features, errors = build_feature_frame(payload, support_tables)
    if errors:
        return None, errors

    batting_team = normalize_team(payload.get("batting_team", ""))
    row = features.iloc[0]
    predicted_total = score_model.predict(features)[0]
    raw_win_prob = float(win_model.predict_proba(features)[0][1])
    win_stability_profile = load_win_stability_profile()
    win_prob, stability_flags = apply_win_stability_adjustment(raw_win_prob, row, win_stability_profile)
    uncertainty_profile = load_score_uncertainty_profile()
    lower, upper = score_interval(predicted_total, float(row["runs"]), uncertainty_profile)
    sim = simulate_remaining_innings(row, float(predicted_total), float(win_prob), uncertainty_profile)

    monitoring_event_id = ""

    try:
        from .monitoring import track_prediction_event

        monitoring_event_id = track_prediction_event(
            payload=payload,
            row=row,
            predicted_total=float(predicted_total),
            raw_win_prob=float(raw_win_prob),
            adjusted_win_prob=float(win_prob),
            stability_flags=stability_flags,
            stability_profile_source=str(win_stability_profile.get("source", "default")),
        )
    except Exception:
        # Monitoring must never break inference.
        pass

    return {
        "predicted_total": f"{predicted_total:.1f}",
        "win_prob": f"{win_prob:.3f}",
        "win_prob_raw": f"{raw_win_prob:.3f}",
        "win_prob_pct": f"{100.0 * win_prob:.1f}%",
        "win_prob_band": f"{100.0 * sim['sim_win_prob_p10']:.1f}% - {100.0 * sim['sim_win_prob_p90']:.1f}%",
        "win_stability_flags": ", ".join(stability_flags) if stability_flags else "none",
        "batting_team": batting_team or "",
        "phase": str(row["phase"]).title(),
        "venue_par_score": f"{float(row['venue_avg_first_innings'] if int(row['innings']) == 1 else row['venue_avg_second_innings']):.1f}",
        "runs_vs_par": f"{float(row['runs_vs_par']):+.1f}",
        "projected_range": f"{lower:.0f}-{upper:.0f}",
        "simulated_median": f"{sim['sim_score_p50']:.1f}",
        "simulated_p10": f"{sim['sim_score_p10']:.1f}",
        "simulated_p90": f"{sim['sim_score_p90']:.1f}",
        "collapse_risk_pct": f"{100.0 * sim['collapse_risk']:.1f}%",
        "big_finish_chance_pct": f"{100.0 * sim['big_finish_chance']:.1f}%",
        "model_explanation": "Score uses a regression model with residual quantiles and simulation; win uses calibrated classification probability.",
        "temperature_c": f"{float(row['temperature_c']):.1f}",
        "dew_risk": f"{float(row['dew_risk']):.2f}",
        "target_remaining": "" if pd.isna(row["target_remaining"]) else f"{float(row['target_remaining']):.0f}",
        "current_minus_required_rr": (
            ""
            if pd.isna(row["current_minus_required_rr"])
            else f"{float(row['current_minus_required_rr']):+.2f}"
        ),
        "required_minus_current_rr": (
            ""
            if pd.isna(row["required_minus_current_rr"])
            else f"{float(row['required_minus_current_rr']):+.2f}"
        ),
        "monitoring_event_id": monitoring_event_id,
    }, []


def _build_pre_match_features(team1: str, team2: str, venue: str, support_tables: SupportTables) -> pd.DataFrame:
    batting_team = normalize_team(team1) or team1
    bowling_team = normalize_team(team2) or team2
    venue_name = normalize_venue(venue) or venue

    venue_strength = support_tables.venue_stats.get(venue_name, DEFAULT_VENUE_STRENGTH)

    row = {
        "batting_team": batting_team,
        "bowling_team": bowling_team,
        "venue": venue_name,
        "batting_team_form": float(support_tables.team_form_map.get(batting_team, 0.5)),
        "bowling_team_form": float(support_tables.team_form_map.get(bowling_team, 0.5)),
        "batting_team_venue_form": float(support_tables.team_venue_form_map.get((batting_team, venue_name), 0.5)),
        "bowling_team_venue_form": float(support_tables.team_venue_form_map.get((bowling_team, venue_name), 0.5)),
        "batting_vs_bowling_form": float(support_tables.matchup_form_map.get((batting_team, bowling_team), 0.5)),
        "venue_avg_first_innings": float(venue_strength.get("venue_avg_first_innings", 0.0)),
        "venue_avg_second_innings": float(venue_strength.get("venue_avg_second_innings", 0.0)),
        "venue_bat_first_win_rate": float(venue_strength.get("venue_bat_first_win_rate", 0.0)),
    }
    return pd.DataFrame([row])[PRE_MATCH_MODEL_FEATURES]


def predict_pre_match(
    team1: str,
    team2: str,
    venue: str,
    score_model,
    win_model,
    support_tables: SupportTables | None = None,
) -> dict[str, str | float]:
    """Provides pre-match score and win estimates using dedicated pre-match models."""
    if not score_model or not win_model:
        return {"error": "Pre-match models not found."}

    support = support_tables if support_tables is not None else load_support_tables()
    features = _build_pre_match_features(team1=team1, team2=team2, venue=venue, support_tables=support)

    predicted_score = float(score_model.predict(features)[0])
    win_prob = float(np.clip(win_model.predict_proba(features)[0][1], 1e-6, 1 - 1e-6))

    likely_winner = team1 if win_prob >= 0.5 else team2
    low = max(0.0, predicted_score - 12.0)
    high = predicted_score + 12.0

    return {
        "predicted_score": f"{low:.0f} - {high:.0f}",
        "exact_predicted_score": f"{predicted_score:.1f}",
        "team1": team1,
        "team2": team2,
        "team1_win_prob": f"{win_prob * 100:.1f}%",
        "team2_win_prob": f"{(1 - win_prob) * 100:.1f}%",
        "likely_winner": likely_winner,
        "win_probability_raw": win_prob,
    }
