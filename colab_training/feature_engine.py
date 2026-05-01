"""
feature_engine.py — Advanced IPL feature engineering.

New signals beyond the base ipl_features.csv:
  EloSystem          : chronological ELO ratings per team
  add_elo_features   : attach pre-match ELO columns to any feature DataFrame
  add_extended_form  : rolling win-rates at 3 / 5 / 10 / 20-match windows
  add_phase_aggregates: per-phase run-rate aggregates per team per match
  add_recency_venue  : exponentially-weighted venue averages (recent > old)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple


# ── ELO system ────────────────────────────────────────────────────────────────

class EloSystem:
    """
    Standard ELO rating system for IPL teams.

    Usage
    -----
    elo = EloSystem().fit(df)          # df must have match_id, start_date,
                                       #   batting_team, bowling_team, winner
    df  = elo.add_to_df(df)            # adds batting_team_elo, bowling_team_elo,
                                       #   elo_diff, elo_win_prob
    latest = elo.ratings_df()          # current standings
    """

    K: float = 32.0
    BASE: float = 1500.0
    SCALE: float = 400.0

    def __init__(self) -> None:
        self.ratings: Dict[str, float] = defaultdict(lambda: self.BASE)
        self._match_snapshot: Dict[int, Dict[str, float]] = {}

    # ── internals ─────────────────────────────────────────────────────────────

    def _expected(self, ra: float, rb: float) -> float:
        return 1.0 / (1.0 + 10 ** ((rb - ra) / self.SCALE))

    def _update(self, t1: str, t2: str, winner: Optional[str]) -> None:
        r1, r2 = self.ratings[t1], self.ratings[t2]
        e1 = self._expected(r1, r2)
        if winner == t1:
            s1, s2 = 1.0, 0.0
        elif winner == t2:
            s1, s2 = 0.0, 1.0
        else:
            s1, s2 = 0.5, 0.5
        self.ratings[t1] = r1 + self.K * (s1 - e1)
        self.ratings[t2] = r2 + self.K * (s2 - (1.0 - e1))

    # ── public API ────────────────────────────────────────────────────────────

    def fit(self, df: pd.DataFrame) -> "EloSystem":
        """Build ELO timeline from historical match data."""
        matches = (
            df[["match_id", "start_date", "batting_team", "bowling_team", "winner"]]
            .drop_duplicates("match_id")
            .copy()
        )
        matches["start_date"] = pd.to_datetime(matches["start_date"], errors="coerce")
        matches = matches.sort_values(["start_date", "match_id"]).reset_index(drop=True)

        for _, row in matches.iterrows():
            t1, t2 = str(row["batting_team"]), str(row["bowling_team"])
            if t1 == "nan" or t2 == "nan":
                continue
            mid = int(row["match_id"])
            self._match_snapshot[mid] = {
                t1: self.ratings[t1],
                t2: self.ratings[t2],
            }
            self._update(t1, t2, row.get("winner"))
        return self

    def win_prob(self, team: str, opponent: str) -> float:
        """Current ELO-based win probability for `team` against `opponent`."""
        return self._expected(self.ratings[team], self.ratings[opponent])

    def ratings_df(self) -> pd.DataFrame:
        return (
            pd.DataFrame(list(self.ratings.items()), columns=["team", "elo"])
            .sort_values("elo", ascending=False)
            .reset_index(drop=True)
            .round({"elo": 1})
        )

    def add_to_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Attach pre-match ELO columns to a ball-level feature DataFrame.
        Adds: batting_team_elo, bowling_team_elo, elo_diff, elo_win_prob
        """
        df = df.copy()

        def _bat_elo(row):
            snap = self._match_snapshot.get(int(row["match_id"]), {})
            return snap.get(str(row["batting_team"]), self.BASE)

        def _bowl_elo(row):
            snap = self._match_snapshot.get(int(row["match_id"]), {})
            return snap.get(str(row["bowling_team"]), self.BASE)

        df["batting_team_elo"] = df.apply(_bat_elo, axis=1)
        df["bowling_team_elo"] = df.apply(_bowl_elo, axis=1)
        df["elo_diff"] = df["batting_team_elo"] - df["bowling_team_elo"]
        df["elo_win_prob"] = df.apply(
            lambda r: self._expected(r["batting_team_elo"], r["bowling_team_elo"]),
            axis=1,
        )
        return df


# ── extended rolling windows ──────────────────────────────────────────────────

def add_extended_form(
    df: pd.DataFrame,
    windows: List[int] = (3, 5, 10, 20),
) -> pd.DataFrame:
    """
    Rolling team win-rates at multiple window sizes.

    Adds columns:
      bat_form_w3, bat_form_w5, bat_form_w10, bat_form_w20
      bowl_form_w3, bowl_form_w5, bowl_form_w10, bowl_form_w20
    """
    matches = (
        df[["match_id", "start_date", "batting_team", "bowling_team", "winner"]]
        .drop_duplicates("match_id")
        .copy()
    )
    matches["start_date"] = pd.to_datetime(matches["start_date"], errors="coerce")
    matches = matches.sort_values(["start_date", "match_id"]).reset_index(drop=True)

    max_w = max(windows)
    team_hist: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_w))
    rows: List[dict] = []

    for _, row in matches.iterrows():
        t1, t2 = str(row["batting_team"]), str(row["bowling_team"])
        winner = row.get("winner")

        rec: dict = {"match_id": row["match_id"]}
        for w in windows:
            h1 = list(team_hist[t1])[-w:]
            h2 = list(team_hist[t2])[-w:]
            rec[f"bat_form_w{w}"]  = float(np.mean(h1)) if h1 else 0.5
            rec[f"bowl_form_w{w}"] = float(np.mean(h2)) if h2 else 0.5
        rows.append(rec)

        for team in [t1, t2]:
            if not (isinstance(winner, float) and np.isnan(winner)) and winner is not None:
                team_hist[team].append(1.0 if team == str(winner) else 0.0)

    form_df = pd.DataFrame(rows)
    return df.merge(form_df, on="match_id", how="left")


# ── phase run-rate aggregates ─────────────────────────────────────────────────

def add_phase_aggregates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Per-match per-team average run-rates in powerplay / middle / death.

    Adds (6 columns):
      bat_pp_rr, bat_mid_rr, bat_death_rr
      bowl_pp_rr, bowl_mid_rr, bowl_death_rr
    """
    phase_map = {"powerplay": "pp", "middle": "mid", "death": "death"}

    legal = df[df["phase"].isin(phase_map)].copy()
    legal["phase_code"] = legal["phase"].map(phase_map)
    legal["ball_runs"] = legal["runs_last_6_balls"] / 6.0  # approx per-ball

    bat_phase = (
        legal.groupby(["match_id", "batting_team", "phase_code"])["ball_runs"]
        .mean()
        .unstack("phase_code", fill_value=0.0)
        .rename(columns=lambda c: f"bat_{c}_rr")
        .reset_index()
    )
    bowl_phase = (
        legal.groupby(["match_id", "bowling_team", "phase_code"])["ball_runs"]
        .mean()
        .unstack("phase_code", fill_value=0.0)
        .rename(columns=lambda c: f"bowl_{c}_rr")
        .reset_index()
    )

    for col in ["bat_pp_rr", "bat_mid_rr", "bat_death_rr"]:
        if col not in bat_phase.columns:
            bat_phase[col] = 0.0
    for col in ["bowl_pp_rr", "bowl_mid_rr", "bowl_death_rr"]:
        if col not in bowl_phase.columns:
            bowl_phase[col] = 0.0

    df = df.merge(
        bat_phase[["match_id", "batting_team", "bat_pp_rr", "bat_mid_rr", "bat_death_rr"]],
        on=["match_id", "batting_team"],
        how="left",
    )
    df = df.merge(
        bowl_phase[["match_id", "bowling_team", "bowl_pp_rr", "bowl_mid_rr", "bowl_death_rr"]],
        on=["match_id", "bowling_team"],
        how="left",
    )

    for col in ["bat_pp_rr", "bat_mid_rr", "bat_death_rr", "bowl_pp_rr", "bowl_mid_rr", "bowl_death_rr"]:
        df[col] = df[col].fillna(df[col].median())

    return df


# ── recency-weighted venue averages ──────────────────────────────────────────

def add_recency_venue(df: pd.DataFrame, decay: float = 0.92) -> pd.DataFrame:
    """
    Exponentially decay-weighted venue average (recent matches weigh more).
    Adds column: venue_weighted_avg_1st
    """
    match_venue = (
        df[df["innings"] == 1][["match_id", "start_date", "venue", "total_runs"]]
        .drop_duplicates("match_id")
        .dropna(subset=["total_runs"])
        .copy()
    )
    match_venue["start_date"] = pd.to_datetime(match_venue["start_date"], errors="coerce")
    match_venue = match_venue.sort_values(["venue", "start_date"])

    venue_wavg: Dict[str, float] = {}
    for venue, grp in match_venue.groupby("venue"):
        scores = grp["total_runs"].values.astype(float)
        n = len(scores)
        weights = np.array([decay ** (n - 1 - i) for i in range(n)])
        weights /= weights.sum()
        venue_wavg[venue] = float(np.dot(scores, weights))

    df = df.copy()
    df["venue_weighted_avg_1st"] = df["venue"].map(venue_wavg).fillna(df["venue_avg_first_innings"])
    return df


# ── composite feature builder ─────────────────────────────────────────────────

def build_advanced_features(
    df: pd.DataFrame,
    elo: Optional[EloSystem] = None,
    windows: List[int] = (3, 5, 10, 20),
    decay: float = 0.92,
    verbose: bool = True,
) -> Tuple[pd.DataFrame, EloSystem]:
    """
    Run all advanced feature engineering steps in sequence.

    Returns (enriched_df, fitted_elo_system).
    """
    if verbose:
        print(f"Input rows: {len(df):,}")

    if elo is None:
        if verbose:
            print("  Fitting ELO ratings ...")
        elo = EloSystem().fit(df)

    if verbose:
        print("  Adding ELO features ...")
    df = elo.add_to_df(df)

    if verbose:
        print(f"  Adding extended form windows {windows} ...")
    df = add_extended_form(df, windows=list(windows))

    if verbose:
        print("  Adding phase aggregates ...")
    df = add_phase_aggregates(df)

    if verbose:
        print("  Adding recency venue averages ...")
    df = add_recency_venue(df, decay=decay)

    if verbose:
        new_cols = ["batting_team_elo", "bowling_team_elo", "elo_diff", "elo_win_prob",
                    "bat_form_w3", "bat_form_w5", "bowl_form_w3", "bowl_form_w5",
                    "bat_pp_rr", "bat_mid_rr", "bat_death_rr",
                    "bowl_pp_rr", "bowl_mid_rr", "bowl_death_rr",
                    "venue_weighted_avg_1st"]
        added = [c for c in new_cols if c in df.columns]
        print(f"  Added {len(added)} new feature columns.")
        print(f"Final rows: {len(df):,}")

    return df, elo


# ── feature list for advanced models ─────────────────────────────────────────

ADVANCED_NUMERIC_EXTRAS = [
    "batting_team_elo",
    "bowling_team_elo",
    "elo_diff",
    "elo_win_prob",
    "bat_form_w3",
    "bat_form_w5",
    "bat_form_w10",
    "bat_form_w20",
    "bowl_form_w3",
    "bowl_form_w5",
    "bowl_form_w10",
    "bowl_form_w20",
    "bat_pp_rr",
    "bat_mid_rr",
    "bat_death_rr",
    "bowl_pp_rr",
    "bowl_mid_rr",
    "bowl_death_rr",
    "venue_weighted_avg_1st",
]
