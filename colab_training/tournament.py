"""
tournament.py — IPL 2026 upcoming match predictions & tournament simulation.

MatchPredictor      : predict one match at a time with rich output card
TournamentSimulator : Monte Carlo simulation of remaining tournament
UPCOMING_2026       : hardcoded remaining IPL 2026 fixture list (edit as needed)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple


# ── IPL 2026 team metadata ────────────────────────────────────────────────────

TEAMS = [
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

SHORT = {
    "Chennai Super Kings":         "CSK",
    "Delhi Capitals":              "DC",
    "Gujarat Titans":              "GT",
    "Kolkata Knight Riders":       "KKR",
    "Lucknow Super Giants":        "LSG",
    "Mumbai Indians":              "MI",
    "Punjab Kings":                "PBKS",
    "Rajasthan Royals":            "RR",
    "Royal Challengers Bengaluru": "RCB",
    "Sunrisers Hyderabad":         "SRH",
}

TEAM_COLORS = {
    "CSK": "#F9CD05",  "DC": "#0078BC",  "GT": "#1C1C1C",
    "KKR": "#3A225D",  "LSG": "#A8D3F1",  "MI": "#004BA0",
    "PBKS": "#ED1B24",  "RR": "#EA1A85",  "RCB": "#EC1C24",
    "SRH": "#F7A721",
}

HOME_VENUES = {
    "Chennai Super Kings":         "MA Chidambaram Stadium",
    "Delhi Capitals":              "Arun Jaitley Stadium",
    "Gujarat Titans":              "Narendra Modi Stadium",
    "Kolkata Knight Riders":       "Eden Gardens",
    "Lucknow Super Giants":        "Ekana Cricket Stadium",
    "Mumbai Indians":              "Wankhede Stadium",
    "Punjab Kings":                "PCA Stadium Mullanpur",
    "Rajasthan Royals":            "Sawai Mansingh Stadium",
    "Royal Challengers Bengaluru": "M. Chinnaswamy Stadium",
    "Sunrisers Hyderabad":         "Rajiv Gandhi International Cricket Stadium",
}

# ── UPCOMING IPL 2026 MATCHES ─────────────────────────────────────────────────
# Format: (date_str YYYY-MM-DD, team1, team2, venue)
# UPDATE THIS LIST with actual remaining fixtures.
# If date/venue unknown, use "TBD".
UPCOMING_2026: List[Tuple[str, str, str, str]] = [
    # ── Remaining league stage (examples — replace with actual schedule) ──
    ("2026-05-02", "Kolkata Knight Riders",       "Sunrisers Hyderabad",         "Eden Gardens"),
    ("2026-05-03", "Punjab Kings",                "Rajasthan Royals",             "PCA Stadium Mullanpur"),
    ("2026-05-04", "Mumbai Indians",              "Delhi Capitals",               "Wankhede Stadium"),
    ("2026-05-05", "Chennai Super Kings",         "Gujarat Titans",               "MA Chidambaram Stadium"),
    ("2026-05-06", "Lucknow Super Giants",        "Royal Challengers Bengaluru",  "Ekana Cricket Stadium"),
    ("2026-05-07", "Rajasthan Royals",            "Mumbai Indians",               "Sawai Mansingh Stadium"),
    ("2026-05-08", "Sunrisers Hyderabad",         "Punjab Kings",                 "Rajiv Gandhi International Cricket Stadium"),
    ("2026-05-09", "Delhi Capitals",              "Kolkata Knight Riders",        "Arun Jaitley Stadium"),
    ("2026-05-10", "Gujarat Titans",              "Lucknow Super Giants",         "Narendra Modi Stadium"),
    ("2026-05-11", "Royal Challengers Bengaluru", "Chennai Super Kings",          "M. Chinnaswamy Stadium"),
    # ── Playoffs (adjust teams when top-4 is known) ──────────────────────
    ("2026-05-20", "TBD (1st vs 2nd)",            "TBD (1st vs 2nd)",             "Narendra Modi Stadium"),
    ("2026-05-21", "TBD (3rd vs 4th)",            "TBD (3rd vs 4th)",             "Narendra Modi Stadium"),
    ("2026-05-23", "TBD Qualifier 2",             "TBD Qualifier 2",              "Narendra Modi Stadium"),
    ("2026-05-25", "TBD Final Team A",            "TBD Final Team B",             "Narendra Modi Stadium"),
]


# ── MatchPredictor ────────────────────────────────────────────────────────────

class MatchPredictor:
    """
    Rich pre-match prediction card for one IPL match.

    Combines:
    - ELO win probability
    - Team form (recent 5 matches)
    - H2H head-to-head record
    - Venue advantage
    - Toss impact

    Parameters
    ----------
    elo           : fitted EloSystem
    df_features   : the full ipl_features DataFrame (for form/H2H lookups)
    win_model     : trained win model (sklearn-compatible, has predict_proba)
    score_model   : trained score model (sklearn-compatible, has predict)
    feat_cols     : list of feature column names for the models
    """

    def __init__(
        self,
        elo,
        df_features: pd.DataFrame,
        win_model=None,
        score_model=None,
        feat_cols: Optional[List[str]] = None,
    ) -> None:
        self.elo = elo
        self.df = df_features
        self.win_model = win_model
        self.score_model = score_model
        self.feat_cols = feat_cols
        self._build_h2h_cache()
        self._build_form_cache()
        self._build_venue_cache()

    def _build_h2h_cache(self) -> None:
        matches = (
            self.df[["match_id", "start_date", "batting_team", "bowling_team", "winner"]]
            .drop_duplicates("match_id")
        )
        h2h: Dict[Tuple[str, str], List[int]] = {}
        for _, row in matches.sort_values("start_date").iterrows():
            t1, t2 = str(row["batting_team"]), str(row["bowling_team"])
            winner = str(row["winner"]) if pd.notna(row["winner"]) else None
            key = tuple(sorted([t1, t2]))
            if key not in h2h:
                h2h[key] = {t1: 0, t2: 0, "total": 0}
            h2h[key]["total"] += 1
            if winner in (t1, t2):
                h2h[key][winner] = h2h[key].get(winner, 0) + 1
        self._h2h = h2h

    def _build_form_cache(self, window: int = 5) -> None:
        from collections import deque
        matches = (
            self.df[["match_id", "start_date", "batting_team", "bowling_team", "winner"]]
            .drop_duplicates("match_id")
            .sort_values("start_date")
        )
        hist = {}
        form = {}
        for _, row in matches.iterrows():
            t1, t2 = str(row["batting_team"]), str(row["bowling_team"])
            winner = str(row["winner"]) if pd.notna(row["winner"]) else None
            for t in [t1, t2]:
                if t not in hist:
                    hist[t] = []
            for t in [t1, t2]:
                if winner:
                    hist[t].append(1 if t == winner else 0)
            for t in [t1, t2]:
                recent = hist[t][-window:]
                form[t] = sum(recent) / len(recent) if recent else 0.5
        self._form = form
        self._full_form_history = hist

    def _build_venue_cache(self) -> None:
        venue_wins = (
            self.df[self.df["innings"] == 1]
            .drop_duplicates("match_id")
            .groupby(["venue", "batting_team"])
            .agg(wins=("win", "sum"), total=("win", "count"))
            .reset_index()
        )
        venue_wins["venue_win_rate"] = venue_wins["wins"] / venue_wins["total"].clip(1)
        self._venue_wins = venue_wins

    def h2h_record(self, team1: str, team2: str) -> Dict:
        key = tuple(sorted([team1, team2]))
        rec = self._h2h.get(key, {team1: 0, team2: 0, "total": 0})
        total = rec["total"]
        return {
            "team1_wins": rec.get(team1, 0),
            "team2_wins": rec.get(team2, 0),
            "total": total,
            "team1_h2h_pct": round(rec.get(team1, 0) / max(total, 1) * 100, 1),
        }

    def venue_record(self, team: str, venue: str) -> Dict:
        rows = self._venue_wins[
            (self._venue_wins["batting_team"] == team) &
            (self._venue_wins["venue"] == venue)
        ]
        if rows.empty:
            return {"matches": 0, "win_rate": 0.5}
        return {
            "matches": int(rows["total"].iloc[0]),
            "win_rate": round(float(rows["venue_win_rate"].iloc[0]), 3),
        }

    def predict(
        self,
        team1: str,
        team2: str,
        venue: str,
        date: str = "2026-05-02",
        toss_winner: Optional[str] = None,
        toss_decision: str = "bat",
        print_card: bool = True,
    ) -> Dict:
        s1 = SHORT.get(team1, team1[:3])
        s2 = SHORT.get(team2, team2[:3])

        elo_p1 = self.elo.win_prob(team1, team2)
        elo_p2 = 1.0 - elo_p1

        form1 = self._form.get(team1, 0.5)
        form2 = self._form.get(team2, 0.5)
        form_p1_raw = form1 / (form1 + form2 + 1e-9)

        h2h = self.h2h_record(team1, team2)
        v1 = self.venue_record(team1, venue)
        v2 = self.venue_record(team2, venue)
        venue_p1 = v1["win_rate"] / (v1["win_rate"] + v2["win_rate"] + 1e-9)

        # Weighted blend: 50% ELO + 25% form + 15% H2H + 10% venue
        h2h_p1 = h2h["team1_h2h_pct"] / 100.0
        blend_p1 = (
            0.50 * elo_p1 +
            0.25 * form_p1_raw +
            0.15 * h2h_p1 +
            0.10 * venue_p1
        )

        result = {
            "date":           date,
            "match":          f"{s1} vs {s2}",
            "team1":          team1,
            "team2":          team2,
            "venue":          venue,
            "elo_t1":         round(self.elo.ratings.get(team1, 1500), 1),
            "elo_t2":         round(self.elo.ratings.get(team2, 1500), 1),
            "elo_win_p1":     round(elo_p1 * 100, 1),
            "elo_win_p2":     round(elo_p2 * 100, 1),
            "form5_t1":       round(form1 * 100, 1),
            "form5_t2":       round(form2 * 100, 1),
            "h2h_t1_wins":    h2h["team1_wins"],
            "h2h_t2_wins":    h2h["team2_wins"],
            "h2h_total":      h2h["total"],
            "venue_wr_t1":    round(v1["win_rate"] * 100, 1),
            "venue_wr_t2":    round(v2["win_rate"] * 100, 1),
            "blend_win_p1":   round(blend_p1 * 100, 1),
            "blend_win_p2":   round((1 - blend_p1) * 100, 1),
            "predicted_winner": team1 if blend_p1 >= 0.5 else team2,
            "confidence":     round(max(blend_p1, 1 - blend_p1) * 100, 1),
        }

        if print_card:
            self._print_card(result, s1, s2)

        return result

    def _print_card(self, r: Dict, s1: str, s2: str) -> None:
        winner = r["predicted_winner"]
        w_short = s1 if winner == r["team1"] else s2
        print(f"\n{'='*58}")
        print(f"  📅 {r['date']}   🏟️  {r['venue']}")
        print(f"  {s1:>6}  vs  {s2:<6}")
        print(f"{'='*58}")
        print(f"  ELO          : {s1} {r['elo_t1']:.0f}  vs  {r['elo_t2']:.0f} {s2}")
        print(f"  ELO win prob : {s1} {r['elo_win_p1']}%   vs  {r['elo_win_p2']}% {s2}")
        print(f"  Last-5 form  : {s1} {r['form5_t1']}%   vs  {r['form5_t2']}% {s2}")
        print(f"  H2H (all)    : {s1} {r['h2h_t1_wins']}W – {r['h2h_t2_wins']}W  ({r['h2h_total']} games)")
        print(f"  Venue W-rate : {s1} {r['venue_wr_t1']}%   vs  {r['venue_wr_t2']}% {s2}")
        print(f"  ─────────────────────────────────────────────────")
        print(f"  PREDICTION   : 🏆 {w_short} wins  ({r['confidence']}% confidence)")
        print(f"  Blend prob   : {s1} {r['blend_win_p1']}%   vs  {r['blend_win_p2']}% {s2}")
        print(f"{'='*58}\n")


# ── TournamentSimulator ───────────────────────────────────────────────────────

class TournamentSimulator:
    """
    Monte Carlo simulation of remaining IPL 2026 matches.

    For each remaining fixture, simulates N times using each team's
    current blended win probability, accumulating points.
    """

    def __init__(
        self,
        predictor: MatchPredictor,
        current_points: Optional[Dict[str, int]] = None,
        n_simulations: int = 10_000,
        seed: int = 42,
    ) -> None:
        self.predictor = predictor
        self.current_points = current_points or {t: 0 for t in TEAMS}
        self.n = n_simulations
        self.rng = np.random.default_rng(seed)

    def simulate_all(
        self,
        fixtures: List[Tuple[str, str, str, str]],
        top_n: int = 4,
    ) -> pd.DataFrame:
        """
        Simulate remaining fixtures N times each.
        Returns a DataFrame of qualification probabilities (top-N finish).
        """
        valid_fixtures = [f for f in fixtures if "TBD" not in f[1] and "TBD" not in f[2]]
        if not valid_fixtures:
            print("No valid (non-TBD) fixtures to simulate.")
            return pd.DataFrame()

        # Initialise point tallies
        qual_counts = {t: 0 for t in TEAMS}

        for sim in range(self.n):
            points = dict(self.current_points)

            for date, t1, t2, venue in valid_fixtures:
                p1 = self.predictor.predict(t1, t2, venue, print_card=False)["blend_win_p1"] / 100.0
                # Add noise to capture uncertainty
                p1_noisy = float(np.clip(
                    p1 + self.rng.normal(0, 0.05),
                    0.05, 0.95
                ))
                winner = t1 if self.rng.random() < p1_noisy else t2
                points[winner] = points.get(winner, 0) + 2

            # Determine top-N
            sorted_teams = sorted(points, key=points.get, reverse=True)
            for t in sorted_teams[:top_n]:
                qual_counts[t] += 1

        results = pd.DataFrame([
            {
                "team": t,
                "short": SHORT.get(t, t[:3]),
                "current_pts": self.current_points.get(t, 0),
                f"top{top_n}_prob_pct": round(qual_counts[t] / self.n * 100, 1),
                "elo": round(self.predictor.elo.ratings.get(t, 1500), 1),
            }
            for t in TEAMS
        ]).sort_values(f"top{top_n}_prob_pct", ascending=False).reset_index(drop=True)

        return results

    def simulate_single_match(self, team1: str, team2: str, venue: str, n: int = 10_000) -> Dict:
        """Full Monte Carlo for one match, return probability distribution."""
        result = self.predictor.predict(team1, team2, venue, print_card=False)
        p1 = result["blend_win_p1"] / 100.0

        outcomes = self.rng.random(n) < p1
        t1_wins = int(outcomes.sum())
        t2_wins = n - t1_wins

        return {
            "team1":         team1,
            "team2":         team2,
            "venue":         venue,
            "team1_win_pct": round(t1_wins / n * 100, 2),
            "team2_win_pct": round(t2_wins / n * 100, 2),
            "n_simulations": n,
            "predicted_winner": team1 if t1_wins > t2_wins else team2,
        }


# ── utilities ─────────────────────────────────────────────────────────────────

def predict_all_upcoming(
    predictor: MatchPredictor,
    fixtures: Optional[List[Tuple]] = None,
) -> pd.DataFrame:
    """
    Run MatchPredictor on every match in UPCOMING_2026 (or a custom list).
    Returns a summary DataFrame.
    """
    fixtures = fixtures or UPCOMING_2026
    rows = []
    for item in fixtures:
        if len(item) == 4:
            date, t1, t2, venue = item
        else:
            t1, t2, venue = item[0], item[1], item[2] if len(item) > 2 else "TBD"
            date = "2026"

        if "TBD" in t1 or "TBD" in t2:
            continue
        r = predictor.predict(t1, t2, venue, date=date, print_card=True)
        rows.append(r)

    return pd.DataFrame(rows) if rows else pd.DataFrame()
