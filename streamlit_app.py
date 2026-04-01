from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

from ipl_predictor import (
    PROCESSED_DIR,
    TEAM_ALIASES,
    SupportTables,
    build_feature_frame,
    load_models,
    load_support_tables,
    parse_overs,
    predict_match_state,
)


@st.cache_resource(show_spinner=False)
def get_models():
    return load_models()


@st.cache_data(show_spinner=False)
def get_support_tables() -> SupportTables:
    return load_support_tables()


@st.cache_data(show_spinner=False)
def get_player_pool() -> dict[str, list[str]]:
    features_path = PROCESSED_DIR / "ipl_features.csv"
    if not features_path.exists():
        return {}

    df = pd.read_csv(
        features_path,
        usecols=["batting_team", "bowling_team", "striker", "non_striker", "bowler"],
        low_memory=False,
    )

    team_players: dict[str, set[str]] = {}
    for row in df.itertuples(index=False):
        batting_team = str(row.batting_team)
        bowling_team = str(row.bowling_team)

        team_players.setdefault(batting_team, set()).update(
            {str(row.striker), str(row.non_striker)}
        )
        team_players.setdefault(bowling_team, set()).add(str(row.bowler))

    out: dict[str, list[str]] = {}
    for team, players in team_players.items():
        out[team] = sorted([p for p in players if p and p != "nan" and p != "Unknown"])
    return out


@st.cache_data(show_spinner=False)
def get_history_table() -> pd.DataFrame:
    features_path = PROCESSED_DIR / "ipl_features.csv"
    if not features_path.exists():
        return pd.DataFrame()

    cols = ["season", "venue"]
    return pd.read_csv(features_path, usecols=cols, low_memory=False)


def get_team_options(support_tables: SupportTables) -> list[str]:
    from_aliases = set(TEAM_ALIASES.values())
    from_form = set(support_tables.team_form_map.keys())
    return sorted(from_aliases | from_form)


def get_season_options(history_df: pd.DataFrame) -> list[str]:
    if history_df.empty:
        return [str(datetime.now().year)]
    seasons = sorted({str(s) for s in history_df["season"].dropna().astype(str).tolist()})
    return seasons or [str(datetime.now().year)]


def get_venue_options(history_df: pd.DataFrame, support_tables: SupportTables) -> list[str]:
    from_history = set()
    if not history_df.empty:
        from_history = set(history_df["venue"].dropna().astype(str).tolist())
    from_support = set(support_tables.venue_stats.keys())
    venues = sorted(from_history | from_support)
    return venues if venues else ["Wankhede Stadium"]


def estimate_recent_runs(runs: float, overs_text: str) -> float:
    try:
        balls = parse_overs(overs_text)
        overs = max(1.0, balls / 6.0)
        crr = runs / overs
        return max(0.0, min(runs, crr * 5.0))
    except Exception:
        return 0.0


def parse_signed_number(text: str) -> float | None:
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def pressure_status(required_minus_current_rr: str) -> tuple[str, str]:
    value = parse_signed_number(required_minus_current_rr)
    if value is None:
        return "Balanced", "No chase pressure right now."
    if value > 2.0:
        return "High Pressure", "Batting side needs a big push immediately."
    if value > 0.8:
        return "Moderate Pressure", "Batting side is slightly behind the required pace."
    return "In Control", "Batting side is keeping up with or ahead of the chase pace."


st.set_page_config(page_title="IPL Match Predictor", page_icon="cricket", layout="wide")

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700&family=Space+Grotesk:wght@500;700&display=swap');

    .stApp {
      background: radial-gradient(circle at 15% 15%, #fff4d8 0%, #f7fbff 40%, #eef7ff 100%);
    }

    h1, h2, h3 {
      font-family: 'Space Grotesk', sans-serif;
      letter-spacing: 0.2px;
    }

    .hero-box {
      border: 1px solid #e6edf5;
      border-radius: 16px;
      padding: 1rem 1.1rem;
      background: linear-gradient(135deg, #ffffff 0%, #f8fbff 100%);
      box-shadow: 0 10px 24px rgba(17, 24, 39, 0.06);
      margin-bottom: 0.6rem;
    }

    .small-note {
      color: #4b5563;
      font-size: 0.95rem;
      margin-top: 0.25rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero-box">
      <h1 style="margin:0;">IPL Live Match Predictor</h1>
      <p class="small-note">Simple mode: fill only match basics, click one button, and read plain-language output.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.expander("How to use in 3 quick steps", expanded=False):
    st.write("1) Select teams, innings, and current score.")
    st.write("2) Add first-innings score only if it is a chase (innings 2).")
    st.write("3) Click **Get Prediction** to see winner chance, final score range, and pressure.")

support_tables = get_support_tables()
score_model, win_model = get_models()
player_pool = get_player_pool()
history_df = get_history_table()

team_options = get_team_options(support_tables)
if not team_options:
    st.error("No team data found. Please run preprocessing first.")
    st.stop()

season_options = get_season_options(history_df)
venue_options = get_venue_options(history_df, support_tables)

default_batting_idx = team_options.index("Mumbai Indians") if "Mumbai Indians" in team_options else 0
current_season = str(datetime.now().year)
default_season = current_season if current_season in season_options else season_options[-1]

show_detailed_analytics = False

with st.form("quick_predict_form"):
    st.subheader("Match Inputs")

    r1c1, r1c2, r1c3, r1c4 = st.columns(4)
    with r1c1:
        season = st.selectbox("Season", options=season_options, index=season_options.index(default_season))
    with r1c2:
        venue = st.selectbox("Venue", options=venue_options, index=venue_options.index("Wankhede Stadium") if "Wankhede Stadium" in venue_options else 0)
    with r1c3:
        batting_team = st.selectbox("Batting Team", options=team_options, index=default_batting_idx)
    with r1c4:
        bowling_choices = [t for t in team_options if t != batting_team] or team_options
        bowling_team = st.selectbox(
            "Bowling Team",
            options=bowling_choices,
            index=bowling_choices.index("Chennai Super Kings") if "Chennai Super Kings" in bowling_choices else 0,
        )

    r2c1, r2c2, r2c3, r2c4 = st.columns(4)
    with r2c1:
        innings = st.radio("Innings", options=[1, 2], horizontal=True)
    with r2c2:
        runs = st.number_input("Current Runs", min_value=0.0, step=1.0, value=100.0)
    with r2c3:
        wickets = st.number_input("Wickets Lost", min_value=0.0, max_value=10.0, step=1.0, value=3.0)
    with r2c4:
        overs = st.text_input("Overs Bowled", value="12.3", help="Use format like 12.3")

    if innings == 2:
        first_innings_total = st.number_input(
            "First Innings Total",
            min_value=1.0,
            step=1.0,
            value=170.0,
            help="Needed only during chase",
        )
    else:
        first_innings_total = 0.0

    st.subheader("Optional Inputs")
    use_live_weather = st.checkbox("Use live weather", value=True)

    know_current_players = st.checkbox("I know current striker and bowler", value=False)
    striker = "Unknown"
    bowler = "Unknown"
    if know_current_players:
        batting_pool = player_pool.get(batting_team, [])
        bowling_pool = player_pool.get(bowling_team, [])

        p1, p2 = st.columns(2)
        with p1:
            striker = st.selectbox("Striker", options=batting_pool if batting_pool else ["Unknown"])
        with p2:
            bowler = st.selectbox("Bowler", options=bowling_pool if bowling_pool else ["Unknown"])

    add_recent_momentum = st.checkbox("I want to enter last 5 overs details", value=False)
    estimated_runs_last_5 = estimate_recent_runs(runs, overs)
    runs_last_5 = estimated_runs_last_5
    wickets_last_5 = 0.0
    if add_recent_momentum:
        m1, m2 = st.columns(2)
        with m1:
            runs_last_5 = st.number_input("Runs in last 5 overs", min_value=0.0, step=1.0, value=float(round(estimated_runs_last_5, 1)))
        with m2:
            wickets_last_5 = st.number_input("Wickets in last 5 overs", min_value=0.0, step=1.0, value=0.0)

    add_toss_info = st.checkbox("I want to enter toss info", value=False)
    toss_winner = ""
    toss_decision = ""
    if add_toss_info:
        t1, t2 = st.columns(2)
        with t1:
            toss_winner = st.selectbox("Toss winner", options=[""] + team_options)
        with t2:
            toss_decision = st.selectbox("Toss decision", options=["", "bat", "field"])

    show_detailed_analytics = st.checkbox("Show advanced analytics after prediction", value=False)

    submitted = st.form_submit_button("Get Prediction", type="primary")

if submitted:
    payload: dict[str, Any] = {
        "season": season,
        "venue": venue,
        "batting_team": batting_team,
        "bowling_team": bowling_team,
        "innings": innings,
        "runs": runs,
        "wickets": wickets,
        "overs": overs,
        "runs_last_5": runs_last_5,
        "wickets_last_5": wickets_last_5,
        "use_live_weather": use_live_weather,
        "striker": striker,
        "bowler": bowler,
        "toss_winner": toss_winner,
        "toss_decision": toss_decision,
    }
    if innings == 2:
        payload["first_innings_total"] = first_innings_total

    prediction, errors = predict_match_state(
        payload,
        support_tables=support_tables,
        score_model=score_model,
        win_model=win_model,
    )

    if errors:
        for error in errors:
            st.error(error)
        st.stop()

    assert prediction is not None

    batting_win_pct = float(prediction["win_prob"]) * 100.0
    bowling_win_pct = 100.0 - batting_win_pct
    likely_winner = batting_team if batting_win_pct >= 50.0 else bowling_team

    st.success("Prediction ready")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Likely Winner", likely_winner)
    c2.metric(f"{batting_team} win %", f"{batting_win_pct:.1f}%")
    c3.metric("Expected Final Score", prediction["predicted_total"])
    c4.metric("Likely Score Range", prediction["projected_range"])

    st.progress(min(1.0, max(0.0, float(prediction["win_prob"]))))
    st.caption(
        f"Win confidence band: {prediction['win_prob_band']} | "
        f"{bowling_team} win %: {bowling_win_pct:.1f}%"
    )

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Match Phase", prediction["phase"])
    d2.metric("Runs vs Par", prediction["runs_vs_par"])
    d3.metric("Collapse Risk", prediction["collapse_risk_pct"])
    d4.metric("Big Finish Chance", prediction["big_finish_chance_pct"])

    if prediction["target_remaining"]:
        pressure_title, pressure_text = pressure_status(prediction["required_minus_current_rr"])
        p1, p2, p3 = st.columns(3)
        p1.metric("Target Remaining", prediction["target_remaining"])
        p2.metric("Req RR - Current RR", prediction["required_minus_current_rr"])
        p3.metric("Chase Pressure", pressure_title)
        st.info(pressure_text)

    score_band = pd.DataFrame(
        {
            "Quantile": ["P10", "Median", "P90"],
            "Projected Score": [
                float(prediction["simulated_p10"]),
                float(prediction["simulated_median"]),
                float(prediction["simulated_p90"]),
            ],
        }
    )
    st.subheader("Score Distribution Snapshot")
    st.bar_chart(score_band.set_index("Quantile"))

    if show_detailed_analytics:
        st.subheader("Advanced Analytics")
        st.caption(prediction["model_explanation"])

        features, feature_errors = build_feature_frame(payload, support_tables)
        if feature_errors:
            for error in feature_errors:
                st.warning(error)
        else:
            row = features.iloc[0]
            info_df = pd.DataFrame(
                [
                    {"Metric": "Venue par score", "Value": prediction["venue_par_score"]},
                    {"Metric": "Temperature (C)", "Value": prediction["temperature_c"]},
                    {"Metric": "Dew risk", "Value": prediction["dew_risk"]},
                    {"Metric": "Current run rate", "Value": f"{float(row['current_run_rate']):.2f}"},
                    {"Metric": "Balls left", "Value": f"{int(float(row['balls_left']))}"},
                    {"Metric": "Wickets left", "Value": f"{int(float(row['wickets_left']))}"},
                ]
            )
            st.dataframe(info_df, width="stretch", hide_index=True)
