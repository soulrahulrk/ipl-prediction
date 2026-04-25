from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from ipl_predictor.common import (
    load_support_tables as backend_load_support_tables,
    predict_pre_match as backend_predict_pre_match,
)

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROCESSED_DIR = ROOT / "data" / "processed"
MODELS_DIR    = ROOT / "models"

# ── team metadata ─────────────────────────────────────────────────────────────
TEAM_COLORS: dict[str, str] = {
    "Chennai Super Kings":        "#f5c518",
    "Delhi Capitals":             "#004c97",
    "Gujarat Titans":             "#1b3c5e",
    "Kolkata Knight Riders":      "#3b215d",
    "Lucknow Super Giants":       "#00a3e0",
    "Mumbai Indians":             "#005da0",
    "Punjab Kings":               "#ed1c24",
    "Rajasthan Royals":           "#ea3b94",
    "Royal Challengers Bengaluru":"#c8102e",
    "Sunrisers Hyderabad":        "#f26522",
}
TEAM_SHORT = {
    "Chennai Super Kings":"CSK", "Delhi Capitals":"DC",
    "Gujarat Titans":"GT", "Kolkata Knight Riders":"KKR",
    "Lucknow Super Giants":"LSG", "Mumbai Indians":"MI",
    "Punjab Kings":"PBKS", "Rajasthan Royals":"RR",
    "Royal Challengers Bengaluru":"RCB", "Sunrisers Hyderabad":"SRH",
}
ACTIVE_TEAMS = sorted(TEAM_COLORS.keys())

# ── available models ───────────────────────────────────────────────────────────
PRE_MATCH_SCORE_MODELS = {
    "Pre-Match (Recommended)": ("pre_match_score_model.pkl", "pre_match"),
}
PRE_MATCH_WIN_MODELS = {
    "Pre-Match (Recommended)": ("pre_match_win_model.pkl", "pre_match"),
}


# ── loaders ────────────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def load_model(filename: str):
    import joblib
    p = MODELS_DIR / filename
    if not p.exists():
        return None
    return joblib.load(p)


@st.cache_data(show_spinner=False)
def load_team_form() -> pd.DataFrame:
    p = PROCESSED_DIR / "team_form_latest.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_matchup() -> pd.DataFrame:
    p = PROCESSED_DIR / "matchup_form_latest.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_venue_stats() -> pd.DataFrame:
    p = PROCESSED_DIR / "venue_stats.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_active_teams() -> list[str]:
    p = PROCESSED_DIR / "active_teams_2026.csv"
    if not p.exists():
        return sorted(TEAM_COLORS.keys())

    try:
        df = pd.read_csv(p)
    except Exception:
        return sorted(TEAM_COLORS.keys())

    if df.empty:
        return sorted(TEAM_COLORS.keys())

    if "team" in df.columns:
        values = df["team"].dropna().astype(str).str.strip().tolist()
    else:
        values = df.iloc[:, 0].dropna().astype(str).str.strip().tolist()

    teams = [team for team in values if team]
    return list(dict.fromkeys(teams)) or sorted(TEAM_COLORS.keys())


@st.cache_data(show_spinner=False)
def load_venue_options() -> list[str]:
    venue_df = load_venue_stats()
    if venue_df.empty or "venue" not in venue_df.columns:
        return []

    venues = venue_df["venue"].dropna().astype(str).str.strip().tolist()
    venues = [venue for venue in venues if venue]
    return list(dict.fromkeys(venues))


@st.cache_data(show_spinner=False)
def load_tvf() -> pd.DataFrame:
    p = PROCESSED_DIR / "team_venue_form_latest.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_players() -> pd.DataFrame:
    p = PROCESSED_DIR / "team_player_pool_2026.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_batter_form() -> pd.DataFrame:
    p = PROCESSED_DIR / "batter_form_latest.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_bowler_form() -> pd.DataFrame:
    p = PROCESSED_DIR / "bowler_form_latest.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_playing_xi() -> pd.DataFrame:
    p = PROCESSED_DIR / "match_playing_xi.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_batter_bowler_form() -> pd.DataFrame:
    p = PROCESSED_DIR / "batter_bowler_form_latest.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


def load_report() -> dict:
    p = MODELS_DIR / "all_models_report.json"
    if not p.exists():
        p = MODELS_DIR / "deployment_report.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


# ── prediction helpers ─────────────────────────────────────────────────────────
def predict_pre_match(team1: str, team2: str, venue: str,
                      score_fname: str, win_fname: str) -> tuple[dict | None, str | None]:
    sm = load_model(score_fname)
    wm = load_model(win_fname)
    if sm is None or wm is None:
        return None, "Pre-match model files are missing. Train pre-match models first."

    try:
        raw = backend_predict_pre_match(
            team1=team1,
            team2=team2,
            venue=venue,
            score_model=sm,
            win_model=wm,
            support_tables=backend_load_support_tables(),
        )
    except Exception as exc:
        return None, f"Pre-match prediction failed: {exc}"

    if "error" in raw:
        return None, str(raw["error"])

    try:
        score = float(raw.get("exact_predicted_score", "0"))
    except Exception:
        return None, "Pre-match score could not be parsed from model output."

    try:
        wp = float(raw.get("win_probability_raw", 0.5))
    except Exception:
        return None, "Pre-match win probability could not be parsed from model output."

    return {"score": score, "win_prob": wp}, None


# ── HTML helpers ───────────────────────────────────────────────────────────────
def win_bar_html(prob: float, t1: str, t2: str) -> str:
    c1, c2 = TEAM_COLORS.get(t1, "#4f8ef7"), TEAM_COLORS.get(t2, "#f74f4f")
    p1, p2 = round(prob * 100, 1), round(100 - prob * 100, 1)
    s1, s2 = TEAM_SHORT.get(t1, t1), TEAM_SHORT.get(t2, t2)
    return f"""
<div style="margin:10px 0">
  <div style="display:flex;height:40px;border-radius:8px;overflow:hidden;font-weight:700;font-size:15px">
    <div style="width:{p1}%;background:{c1};display:flex;align-items:center;
                justify-content:center;color:#fff;min-width:60px">{s1} {p1}%</div>
    <div style="width:{p2}%;background:{c2};display:flex;align-items:center;
                justify-content:center;color:#fff;min-width:60px">{p2}% {s2}</div>
  </div>
</div>"""


def form_badge(v: float) -> str:
    pct = round(v * 100)
    c = "#22c55e" if pct >= 60 else ("#f59e0b" if pct >= 40 else "#ef4444")
    return f'<span style="background:{c};color:#fff;padding:2px 8px;border-radius:12px;font-weight:700">{pct}%</span>'


# ── page config ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="IPL Predictor 2026", page_icon="🏏", layout="wide")
st.markdown("""
<style>
.block-container{padding-top:1.2rem}
h1{font-size:1.9rem!important}
.stMetric label{font-size:.78rem!important}
.team-card{border-radius:10px;padding:14px;margin-bottom:6px;color:#fff;
           font-weight:700;font-size:1.05rem;text-align:center}
</style>""", unsafe_allow_html=True)

st.title("🏏 IPL 2026 — Live Match Predictor")

# ── sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Match Setup")
    available_teams = load_active_teams()
    team1_default = available_teams.index("Mumbai Indians") if "Mumbai Indians" in available_teams else 0
    team1 = st.selectbox("Team 1 (batting first)", available_teams, index=team1_default)

    t2_opts = [t for t in available_teams if t != team1]
    team2_default = t2_opts.index("Chennai Super Kings") if "Chennai Super Kings" in t2_opts else 0
    team2 = st.selectbox("Team 2 (bowling first)", t2_opts, index=team2_default)

    venues = load_venue_options()
    venue_default = venues.index("Wankhede Stadium") if "Wankhede Stadium" in venues else 0
    venue = st.selectbox("Venue", venues, index=venue_default if venues else 0)

    toss_w = st.selectbox("Toss winner", ["— unknown —", team1, team2])
    toss_d = "bat"
    if toss_w != "— unknown —":
        toss_d = st.selectbox("Toss decision", ["bat", "field"])

    st.divider()
    st.subheader("Model Selection")
    score_available = [name for name, (fname, _) in PRE_MATCH_SCORE_MODELS.items() if (MODELS_DIR / fname).exists()]
    win_available = [name for name, (fname, _) in PRE_MATCH_WIN_MODELS.items() if (MODELS_DIR / fname).exists()]

    score_options = score_available or list(PRE_MATCH_SCORE_MODELS.keys())
    win_options = win_available or list(PRE_MATCH_WIN_MODELS.keys())

    score_choice = st.selectbox("Score model", score_options)
    win_choice = st.selectbox("Win model", win_options)

    # show which model file is selected
    sf = PRE_MATCH_SCORE_MODELS[score_choice][0]
    wf = PRE_MATCH_WIN_MODELS[win_choice][0]
    st.caption(f"Score file: `{sf}`  {'✅' if (MODELS_DIR/sf).exists() else '❌ missing'}")
    st.caption(f"Win file: `{wf}`    {'✅' if (MODELS_DIR/wf).exists() else '❌ missing'}")

    missing_score = [name for name in PRE_MATCH_SCORE_MODELS if name not in score_available]
    missing_win = [name for name in PRE_MATCH_WIN_MODELS if name not in win_available]
    if missing_score or missing_win:
        st.info("Some model variants are hidden because their files are not available yet.")

    predict_btn = st.button("Predict Match", type="primary", use_container_width=True)

# ── load support data ──────────────────────────────────────────────────────────
tf_df   = load_team_form()
mf_df   = load_matchup()
tvf_df  = load_tvf()
pp_df   = load_players()
bat_df  = load_batter_form()
bow_df  = load_bowler_form()
vs_df   = load_venue_stats()

def get_form(team: str) -> float:
    r = tf_df[tf_df["team"] == team]["team_form"] if not tf_df.empty else pd.Series()
    return float(r.iloc[0]) if not r.empty else 0.5

def get_h2h(t: str, o: str) -> float | None:
    if mf_df.empty: return None
    r = mf_df[(mf_df["team"] == t) & (mf_df["opponent"] == o)]["matchup_form"]
    return float(r.iloc[0]) if not r.empty else None

def get_tvf(t: str, v: str) -> float | None:
    if tvf_df.empty: return None
    r = tvf_df[(tvf_df["team"] == t) & (tvf_df["venue"] == v)]["team_venue_form"]
    return float(r.iloc[0]) if not r.empty else None

def get_venue(v: str) -> dict | None:
    if vs_df.empty: return None
    r = vs_df[vs_df["venue"] == v]
    return r.iloc[0].to_dict() if not r.empty else None

def top_batters(team: str, n: int = 5) -> pd.DataFrame:
    if pp_df.empty or bat_df.empty: return pd.DataFrame()
    pl = pp_df[pp_df["team"] == team]["player"].tolist()
    b  = bat_df[bat_df["batter"].isin(pl) & (bat_df["batter_balls"] >= 20)]
    return b.sort_values("striker_form_sr", ascending=False).head(n)[
        ["batter","striker_form_sr","striker_form_avg","batter_balls"]
    ].rename(columns={"batter":"Player","striker_form_sr":"SR","striker_form_avg":"Avg","batter_balls":"Balls"})

def top_bowlers(team: str, n: int = 5) -> pd.DataFrame:
    if pp_df.empty or bow_df.empty: return pd.DataFrame()
    pl = pp_df[pp_df["team"] == team]["player"].tolist()
    b  = bow_df[bow_df["bowler"].isin(pl) & (bow_df["bowler_balls"] >= 12)]
    return b.sort_values("bowler_form_econ").head(n)[
        ["bowler","bowler_form_econ","bowler_form_strike","bowler_balls"]
    ].rename(columns={"bowler":"Player","bowler_form_econ":"Economy","bowler_form_strike":"SR","bowler_balls":"Balls"})

# ── team header ────────────────────────────────────────────────────────────────
c1, cv, c2 = st.columns([5, 1, 5])
with c1:
    clr = TEAM_COLORS.get(team1, "#333")
    f1  = get_form(team1)
    st.markdown(f'<div class="team-card" style="background:{clr}">{team1}'
                f'<br><small style="font-weight:400;font-size:.85rem">'
                f'Recent form: {round(f1*100)}% wins (last 5)</small></div>',
                unsafe_allow_html=True)
with cv:
    st.markdown("<div style='text-align:center;font-size:1.8rem;font-weight:900;padding-top:8px'>vs</div>",
                unsafe_allow_html=True)
with c2:
    clr = TEAM_COLORS.get(team2, "#333")
    f2  = get_form(team2)
    st.markdown(f'<div class="team-card" style="background:{clr}">{team2}'
                f'<br><small style="font-weight:400;font-size:.85rem">'
                f'Recent form: {round(f2*100)}% wins (last 5)</small></div>',
                unsafe_allow_html=True)
st.divider()

# ── prediction result ──────────────────────────────────────────────────────────
if predict_btn:
    sf_file = PRE_MATCH_SCORE_MODELS[score_choice][0]
    wf_file = PRE_MATCH_WIN_MODELS[win_choice][0]
    with st.spinner("Running prediction…"):
        result, error_msg = predict_pre_match(team1, team2, venue, sf_file, wf_file)

    if result is None:
        st.error(error_msg or "Pre-match prediction failed.")
    else:
        wp     = result["win_prob"]
        score  = result["score"]
        winner = team1 if wp > 0.5 else team2
        wpr    = wp if wp > 0.5 else 1 - wp
        vrow   = get_venue(venue)

        st.subheader(f"Prediction — {score_choice} score model + {win_choice} win model")
        st.markdown(win_bar_html(wp, team1, team2), unsafe_allow_html=True)

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Likely Winner",   TEAM_SHORT.get(winner, winner))
        m2.metric("Win Probability", f"{wpr*100:.1f}%")
        m3.metric(f"{TEAM_SHORT.get(team1,'T1')} Proj. Score",
                  f"{round(score-10)}–{round(score+15)}")
        m4.metric("Venue Avg (1st)", f"{vrow['venue_avg_first_innings']:.0f}" if vrow else "—")
        m5.metric("Bat-First Win%",  f"{vrow['venue_bat_first_win_rate']*100:.1f}%" if vrow else "—")

        if toss_w != "— unknown —" and vrow:
            bfwr = vrow["venue_bat_first_win_rate"]
            if toss_d == "bat":
                st.info(f"🪙 {toss_w} won toss & chose to BAT. "
                        f"Venue bat-first win rate: **{bfwr*100:.0f}%**")
            else:
                st.info(f"🪙 {toss_w} won toss & chose to FIELD. "
                        f"Venue chase win rate: **{(1-bfwr)*100:.0f}%**")

        # Store prediction in session for feedback
        st.session_state["last_pred"] = {
            "batting_team": team1, "bowling_team": team2,
            "venue": venue, "predicted_score": round(score, 1),
            "predicted_winner": winner, "win_prob": round(wp, 4),
        }
        st.divider()

# ── feedback / online learning ─────────────────────────────────────────────────
with st.expander("📥 Submit Actual Result (Online Learning Feedback)", expanded=False):
    st.markdown("""
    After the match ends, submit the actual result here.
    The model will **incrementally update** itself with the new data.
    Over time, this improves prediction accuracy for current teams & conditions.
    """)
    fb_col1, fb_col2 = st.columns(2)
    with fb_col1:
        fb_actual_total  = st.number_input("Actual 1st innings total", min_value=0, max_value=300, value=0, step=1)
        fb_actual_winner = st.selectbox("Actual match winner", ["— select —", team1, team2])
    with fb_col2:
        fb_bt = st.selectbox("Batting team (1st innings)", [team1, team2], key="fb_bt")
        fb_bw = st.selectbox("Bowling team (1st innings)", [t for t in [team1, team2] if t != fb_bt], key="fb_bw")

    fb_submit = st.button("Submit Result & Update Model", type="secondary")
    if fb_submit:
        if fb_actual_winner == "— select —":
            st.warning("Please select the actual winner.")
        else:
            try:
                from ipl_predictor.online_learning import save_feedback, pending_count, fine_tune_models, RETRAIN_THRESHOLD
                payload = {"batting_team": fb_bt, "bowling_team": fb_bw, "venue": venue}
                save_feedback(
                    payload=payload,
                    actual_total=float(fb_actual_total) if fb_actual_total > 0 else None,
                    actual_winner=fb_actual_winner if fb_actual_winner != "— select —" else None,
                )
                n = pending_count()
                st.success(f"Feedback saved. Total pending rows: {n}/{RETRAIN_THRESHOLD}")
                if n >= RETRAIN_THRESHOLD:
                    with st.spinner("Fine-tuning models with new data..."):
                        summary = fine_tune_models()
                    st.success(f"Models updated!  Score: {summary.get('score_update','—')}  "
                               f"Win: {summary.get('win_update','—')}")
                    st.cache_resource.clear()
                else:
                    st.info(f"Models will auto-update after {RETRAIN_THRESHOLD - n} more feedback rows.")
            except Exception as exc:
                st.error(f"Feedback error: {exc}")

    # Show accuracy drift
    try:
        from ipl_predictor.online_learning import get_accuracy_drift
        drift = get_accuracy_drift()
        if drift.get("history"):
            st.markdown("#### Model Accuracy Over Time (feedback updates)")
            hist_df = pd.DataFrame(drift["history"])
            hist_df["timestamp"] = pd.to_datetime(hist_df["timestamp"])
            st.line_chart(hist_df.set_index("timestamp")["accuracy"], height=180)
            st.caption(f"Total feedback rows collected: {drift.get('total_feedback', 0)}")
    except Exception:
        pass

# ── main tabs ──────────────────────────────────────────────────────────────────
tab_xi, tab_team, tab_h2h, tab_venue, tab_players, tab_models = st.tabs([
    "🏏 Playing XI", "📊 Team Form", "⚔️ Head-to-Head", "🏟️ Venue", "👤 Players", "🤖 Model Comparison"
])

with tab_xi:
    xi_df  = load_playing_xi()
    bat_df_xi = load_batter_form()
    bow_df_xi = load_bowler_form()
    bb_df     = load_batter_bowler_form()

    st.markdown("### Playing XI — Match History & Current Form")
    st.caption("Showing actual playing XIs from recorded matches. "
               "Select a specific match below, or view the latest XI for each team.")

    if xi_df.empty:
        st.warning("Playing XI data not found. It should have been extracted automatically.")
    else:
        # ── Match selector ────────────────────────────────────────────────────
        xi_t1 = xi_df[xi_df["team"] == team1]
        xi_t2 = xi_df[xi_df["team"] == team2]

        # Find matches where both teams played each other
        both_matches = xi_df[xi_df["team"].isin([team1, team2])].groupby("match_id").filter(
            lambda g: set(g["team"].unique()) == {team1, team2}
        )
        both_matches = both_matches.copy()
        both_matches["date"] = pd.to_datetime(both_matches["date"], errors="coerce")
        match_list = (both_matches.drop_duplicates("match_id")
                      .sort_values("date", ascending=False)
                      [["match_id", "date", "winner"]])

        sel_label: str | None = None
        sel_xi = pd.DataFrame()
        if not match_list.empty:
            match_options = {
                f"{row['date'].strftime('%d %b %Y')} — winner: {row['winner'] or 'N/A'}": row["match_id"]
                for _, row in match_list.iterrows()
            }
            sel_label = st.selectbox(
                f"Select a {TEAM_SHORT.get(team1,'T1')} vs {TEAM_SHORT.get(team2,'T2')} match",
                list(match_options.keys())
            )
            sel_mid = match_options[sel_label]
            sel_xi  = both_matches[both_matches["match_id"] == sel_mid]
        else:
            st.info(f"No recorded head-to-head matches found for {team1} vs {team2} in dataset.")

        # ── Latest XI per team ────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("#### Latest Known Playing XI per team (most recent match)")

        def get_latest_xi(team: str) -> pd.DataFrame:
            t_xi = xi_df[xi_df["team"] == team].copy()
            t_xi["date"] = pd.to_datetime(t_xi["date"], errors="coerce")
            t_xi = t_xi.sort_values("date", ascending=False)
            if t_xi.empty:
                return pd.DataFrame()
            last_mid = t_xi["match_id"].iloc[0]
            return t_xi[t_xi["match_id"] == last_mid][["player", "date"]].drop_duplicates()

        def enrich_xi(players: list[str]) -> pd.DataFrame:
            """Merge bat + bowl stats for given player list."""
            rows: list[dict[str, object]] = []
            for p in players:
                row: dict[str, object] = {"Player": p}
                # batting
                b = bat_df_xi[bat_df_xi["batter"] == p]
                if not b.empty:
                    row["Bat SR"]      = round(float(b["striker_form_sr"].iloc[0]), 1)
                    row["Bat Avg"]     = round(float(b["striker_form_avg"].iloc[0]), 1)
                    row["Balls Faced"] = int(b["batter_balls"].iloc[0])
                else:
                    row["Bat SR"] = row["Bat Avg"] = row["Balls Faced"] = "—"
                # bowling
                bw = bow_df_xi[bow_df_xi["bowler"] == p]
                if not bw.empty:
                    row["Bowl Econ"] = round(float(bw["bowler_form_econ"].iloc[0]), 2)
                    row["Bowl SR"]   = round(float(bw["bowler_form_strike"].iloc[0]), 1)
                    row["Wickets"]   = int(bw["bowler_wickets"].iloc[0])
                else:
                    row["Bowl Econ"] = row["Bowl SR"] = row["Wickets"] = "—"
                rows.append(row)
            out = pd.DataFrame(rows)
            if out.empty:
                return out

            # Keep display columns Arrow-safe by using a consistent string type.
            num_cols = ["Bat SR", "Bat Avg", "Balls Faced", "Bowl Econ", "Bowl SR", "Wickets"]
            for col in num_cols:
                out[col] = out[col].astype(str)

            return out

        lxi1 = get_latest_xi(team1)
        lxi2 = get_latest_xi(team2)

        xc1, xc2 = st.columns(2)
        with xc1:
            clr = TEAM_COLORS.get(team1, "#333")
            st.markdown(f'<div style="background:{clr};color:#fff;padding:8px 12px;'
                        f'border-radius:6px;font-weight:700">{team1}</div>',
                        unsafe_allow_html=True)
            if not lxi1.empty:
                last_date1 = lxi1["date"].iloc[0]
                st.caption(f"Last match: {pd.to_datetime(last_date1).strftime('%d %b %Y')}")
                enriched1 = enrich_xi(lxi1["player"].tolist())
                st.dataframe(enriched1, use_container_width=True, hide_index=True)
            else:
                st.caption("No XI data found.")

        with xc2:
            clr = TEAM_COLORS.get(team2, "#333")
            st.markdown(f'<div style="background:{clr};color:#fff;padding:8px 12px;'
                        f'border-radius:6px;font-weight:700">{team2}</div>',
                        unsafe_allow_html=True)
            if not lxi2.empty:
                last_date2 = lxi2["date"].iloc[0]
                st.caption(f"Last match: {pd.to_datetime(last_date2).strftime('%d %b %Y')}")
                enriched2 = enrich_xi(lxi2["player"].tolist())
                st.dataframe(enriched2, use_container_width=True, hide_index=True)
            else:
                st.caption("No XI data found.")

        # ── Head-to-head match XI ─────────────────────────────────────────────
        if not sel_xi.empty and sel_label is not None:
            st.markdown(f"---")
            st.markdown(f"#### XI from selected H2H match — {sel_label}")
            hc1, hc2 = st.columns(2)
            for col, team in zip([hc1, hc2], [team1, team2]):
                with col:
                    clr = TEAM_COLORS.get(team, "#333")
                    st.markdown(f'<div style="background:{clr};color:#fff;padding:6px 12px;'
                                f'border-radius:6px;font-weight:700">{team}</div>',
                                unsafe_allow_html=True)
                    t_xi = sel_xi[sel_xi["team"] == team]["player"].tolist()
                    enriched = enrich_xi(t_xi)
                    st.dataframe(enriched, use_container_width=True, hide_index=True)

        # ── Key batter vs bowler matchups ─────────────────────────────────────
        if not bb_df.empty and not lxi1.empty and not lxi2.empty:
            st.markdown("---")
            st.markdown("#### Key Batter vs Bowler Matchups")
            st.caption("Batters from Team 1 vs bowlers from Team 2, and vice versa")

            batters1  = lxi1["player"].tolist()
            batters2  = lxi2["player"].tolist()
            bowlers1  = [p for p in batters1 if not bow_df_xi[bow_df_xi["bowler"]==p].empty]
            bowlers2  = [p for p in batters2 if not bow_df_xi[bow_df_xi["bowler"]==p].empty]

            def matchup_table(batters: list, bowlers: list) -> pd.DataFrame:
                rows = []
                for b in batters:
                    for bw in bowlers:
                        r = bb_df[(bb_df["batter"]==b) & (bb_df["bowler"]==bw)]
                        if not r.empty and int(r["batter_vs_bowler_balls"].iloc[0]) >= 6:
                            rows.append({
                                "Batter": b, "Bowler": bw,
                                "Balls": int(r["batter_vs_bowler_balls"].iloc[0]),
                                "Runs":  int(r["batter_vs_bowler_runs"].iloc[0]),
                                "SR":    round(float(r["batter_vs_bowler_sr"].iloc[0]), 1),
                            })
                if not rows:
                    return pd.DataFrame()
                return pd.DataFrame(rows).sort_values("Balls", ascending=False).head(10)

            mc1, mc2 = st.columns(2)
            with mc1:
                st.markdown(f"**{TEAM_SHORT.get(team1,'T1')} batters vs {TEAM_SHORT.get(team2,'T2')} bowlers**")
                mt1 = matchup_table(batters1, bowlers2)
                if mt1.empty:
                    st.caption("Not enough balls faced in this matchup combination.")
                else:
                    st.dataframe(mt1, use_container_width=True, hide_index=True)
            with mc2:
                st.markdown(f"**{TEAM_SHORT.get(team2,'T2')} batters vs {TEAM_SHORT.get(team1,'T1')} bowlers**")
                mt2 = matchup_table(batters2, bowlers1)
                if mt2.empty:
                    st.caption("Not enough balls faced in this matchup combination.")
                else:
                    st.dataframe(mt2, use_container_width=True, hide_index=True)

with tab_team:
    cl1, cl2 = st.columns(2)
    with cl1:
        st.markdown(f"#### {team1}")
        st.markdown(f"Recent form: {form_badge(f1)}", unsafe_allow_html=True)
        tv1 = get_tvf(team1, venue)
        if tv1 is not None:
            st.markdown(f"At **{venue}**: {form_badge(tv1)}", unsafe_allow_html=True)
    with cl2:
        st.markdown(f"#### {team2}")
        st.markdown(f"Recent form: {form_badge(f2)}", unsafe_allow_html=True)
        tv2 = get_tvf(team2, venue)
        if tv2 is not None:
            st.markdown(f"At **{venue}**: {form_badge(tv2)}", unsafe_allow_html=True)

    if not tf_df.empty:
        active_tf = tf_df[tf_df["team"].isin(ACTIVE_TEAMS)].copy()
        active_tf["Win %"] = (active_tf["team_form"] * 100).round(0)
        active_tf = active_tf.sort_values("Win %", ascending=False)
        st.bar_chart(active_tf.set_index("team")["Win %"], height=250)

with tab_h2h:
    h1 = get_h2h(team1, team2)
    h2 = get_h2h(team2, team1)
    if h1 is not None and h2 is not None:
        a, b = st.columns(2)
        a.metric(f"{TEAM_SHORT.get(team1,'T1')} win rate vs {TEAM_SHORT.get(team2,'T2')}",
                 f"{h1*100:.0f}%")
        b.metric(f"{TEAM_SHORT.get(team2,'T2')} win rate vs {TEAM_SHORT.get(team1,'T1')}",
                 f"{h2*100:.0f}%")
        h2h_bar = pd.DataFrame({
            "Team": [TEAM_SHORT.get(team1, team1), TEAM_SHORT.get(team2, team2)],
            "H2H Win %": [round(h1*100), round(h2*100)],
        }).set_index("Team")
        st.bar_chart(h2h_bar, height=200)

    if not mf_df.empty:
        both = mf_df[
            ((mf_df["team"] == team1) | (mf_df["team"] == team2)) &
            ((mf_df["opponent"] == team1) | (mf_df["opponent"] == team2))
        ].copy()
        both["Win %"] = (both["matchup_form"] * 100).round(0).astype(int).astype(str) + "%"
        st.dataframe(both[["team","opponent","Win %","window"]], use_container_width=True, hide_index=True)

with tab_venue:
    vrow = get_venue(venue)
    if vrow:
        v1, v2, v3 = st.columns(3)
        v1.metric("Avg 1st Innings", f"{vrow['venue_avg_first_innings']:.1f}")
        v2.metric("Avg 2nd Innings", f"{vrow['venue_avg_second_innings']:.1f}")
        v3.metric("Bat-First Win Rate", f"{vrow['venue_bat_first_win_rate']*100:.1f}%")

    if not vs_df.empty:
        top15 = vs_df.sort_values("venue_avg_first_innings", ascending=False).head(15)
        st.bar_chart(top15.set_index("venue")["venue_avg_first_innings"], height=280)

    if not tvf_df.empty:
        ven_teams = tvf_df[(tvf_df["venue"] == venue) & tvf_df["team"].isin(ACTIVE_TEAMS)].copy()
        if not ven_teams.empty:
            ven_teams["Win % at venue"] = (ven_teams["team_venue_form"] * 100).round(0)
            st.markdown(f"##### Team win rates at {venue}")
            st.bar_chart(ven_teams.sort_values("Win % at venue", ascending=False).set_index("team")["Win % at venue"], height=220)

with tab_players:
    pc1, pc2 = st.columns(2)
    with pc1:
        st.markdown(f"#### {team1} — Top Batters")
        bt1 = top_batters(team1)
        if not bt1.empty:
            st.dataframe(bt1.style.format({"SR":"{:.1f}","Avg":"{:.1f}"}),
                         use_container_width=True, hide_index=True)
        st.markdown(f"#### {team1} — Top Bowlers")
        bw1 = top_bowlers(team1)
        if not bw1.empty:
            st.dataframe(bw1.style.format({"Economy":"{:.2f}","SR":"{:.1f}"}),
                         use_container_width=True, hide_index=True)
        if not pp_df.empty:
            sq = pp_df[pp_df["team"] == team1][["player","appearances"]].sort_values("appearances", ascending=False)
            with st.expander(f"Full squad — {team1}"):
                st.dataframe(sq, use_container_width=True, hide_index=True)
    with pc2:
        st.markdown(f"#### {team2} — Top Batters")
        bt2 = top_batters(team2)
        if not bt2.empty:
            st.dataframe(bt2.style.format({"SR":"{:.1f}","Avg":"{:.1f}"}),
                         use_container_width=True, hide_index=True)
        st.markdown(f"#### {team2} — Top Bowlers")
        bw2 = top_bowlers(team2)
        if not bw2.empty:
            st.dataframe(bw2.style.format({"Economy":"{:.2f}","SR":"{:.1f}"}),
                         use_container_width=True, hide_index=True)
        if not pp_df.empty:
            sq = pp_df[pp_df["team"] == team2][["player","appearances"]].sort_values("appearances", ascending=False)
            with st.expander(f"Full squad — {team2}"):
                st.dataframe(sq, use_container_width=True, hide_index=True)

with tab_models:
    st.markdown("#### Trained Model Comparison (2026 test holdout)")
    report = load_report()

    if report:
        st.caption(f"Trained at: {report.get('trained_at','—')}  |  "
                   f"Test season: {report.get('test_season','—')}  |  "
                   f"Promoted: score={report.get('promoted',{}).get('score','—')}  "
                   f"win={report.get('promoted',{}).get('win','—')}")

        sc_rows = report.get("score_models", [])
        wn_rows = report.get("win_models", [])

        if sc_rows:
            sc_df = pd.DataFrame(sc_rows)[["model","test_mae","test_rmse","val_mae","train_secs"]]
            sc_df = sc_df.sort_values("test_rmse").reset_index(drop=True)
            sc_df.columns = ["Model","Test MAE","Test RMSE","Val MAE","Time (s)"]
            st.markdown("##### Score Models (lower RMSE = better)")
            st.dataframe(sc_df, use_container_width=True, hide_index=True)
            st.bar_chart(sc_df.set_index("Model")["Test RMSE"], height=220)

        if wn_rows:
            wn_df = pd.DataFrame(wn_rows)[["model","test_accuracy","test_log_loss","test_brier","train_secs"]]
            wn_df = wn_df.sort_values("test_accuracy", ascending=False).reset_index(drop=True)
            wn_df.columns = ["Model","Accuracy","Log Loss","Brier","Time (s)"]
            st.markdown("##### Win Models (higher accuracy = better)")
            st.dataframe(wn_df, use_container_width=True, hide_index=True)
            st.bar_chart(wn_df.set_index("Model")["Accuracy"], height=220)
    else:
        st.info("No model comparison report found yet.  "
                "Run `python scripts/train_all_models.py` to train all models and generate the report.")
        st.code("python scripts/train_all_models.py\n"
                "# Fast test (HGB only):\n"
                "python scripts/train_all_models.py --quick\n"
                "# Skip deep learning:\n"
                "python scripts/train_all_models.py --skip-dl")

    # How to improve section
    with st.expander("💡 How to improve model accuracy"):
        st.markdown("""
### Ways to improve model accuracy

#### 1. Retrain with fresh data (most impactful)
```bash
# Download latest Cricsheet data, then:
python scripts/preprocess_ipl.py
python scripts/train_all_models.py
```

#### 2. Submit real match results (Online Learning)
Use the feedback panel above. After 20 submissions,
models auto-fine-tune on the new real data.

#### 3. Switch models
Different models excel at different conditions.
Try CatBoost for win prediction, XGBoost for score.
Select in the sidebar → Model Selection.

#### 4. Feature ideas for even better accuracy
- Add player auction prices (proxy for team strength)
- Add IPL points table standings (current season rank)
- Add pitch report (batting/bowling friendly)
- Add days-since-last-match (player fatigue)
- Add home vs away indicator (some teams play home matches)

#### 5. Hyperparameter tuning
```bash
pip install optuna
# Then modify train_all_models.py to add optuna search
```

#### Why NOT Reinforcement Learning here?
RL needs a live environment where it takes actions and gets rewards
in real time. For match prediction, the "environment" is the match
itself — you'd need streaming ball-by-ball data during the match.
The online learning feedback above is the practical equivalent:
supervised fine-tuning with real labels as they arrive.
        """)

# ── footer ─────────────────────────────────────────────────────────────────────
st.divider()
st.caption("Data: Cricsheet IPL 2007–2026 (1,189 matches).  "
           "Models trained on 61 ball-by-ball features.  "
           "Test holdout: 2026 season.  "
           "Pre-match models use team × venue features only.  "
           "For live in-match predictions: `python web_app.py`")
