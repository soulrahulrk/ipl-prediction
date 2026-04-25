import csv
import glob
import sys
from collections import defaultdict, deque
from datetime import date, datetime
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipl_predictor import DATA_DIR, PROCESSED_DIR, normalize_team, normalize_venue
from ipl_predictor import (
    ACTIVE_IPL_TEAMS_2026,
    ACTIVE_TEAMS_2026_PATH,
    TEAM_PLAYER_POOL_2026_PATH,
    season_to_year,
)


RAW_DIR = DATA_DIR / "ipl_csv2"
OUT_DIR = PROCESSED_DIR
OUT_DIR.mkdir(parents=True, exist_ok=True)

TEAM_FORM_WINDOW = 5
DEFAULT_VENUE_STRENGTH = {
    "venue_avg_first_innings": 0.0,
    "venue_avg_second_innings": 0.0,
    "venue_bat_first_win_rate": 0.0,
}
ACTIVE_SQUAD_LOOKBACK_START_YEAR = 2024


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def load_match_metadata() -> dict[int, dict[str, str | None]]:
    metadata: dict[int, dict[str, str | None]] = {}
    for info_path in RAW_DIR.glob("*_info.csv"):
        match_id = int(info_path.stem.replace("_info", ""))
        info = {
            "winner": None,
            "toss_winner": None,
            "toss_decision": None,
            "date": None,
            "venue": None,
            "teams": [],
        }
        result = None
        with open(info_path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) < 3:
                    continue
                if row[0] == "info" and row[1] == "date":
                    parsed = parse_date(row[2])
                    if parsed and (info["date"] is None or parsed < info["date"]):
                        info["date"] = parsed
                if row[0] == "info" and row[1] == "winner":
                    info["winner"] = normalize_team(row[2])
                if row[0] == "info" and row[1] == "result":
                    result = row[2]
                if row[0] == "info" and row[1] == "toss_winner":
                    info["toss_winner"] = normalize_team(row[2])
                if row[0] == "info" and row[1] == "toss_decision":
                    info["toss_decision"] = row[2].strip().lower()
                if row[0] == "info" and row[1] == "venue":
                    info["venue"] = normalize_venue(row[2])
                if row[0] == "info" and row[1] == "team":
                    info["teams"].append(normalize_team(row[2]))
        if result in ("no result", "tie"):
            info["winner"] = None
        if info["teams"]:
            info["teams"] = list(dict.fromkeys(info["teams"]))
        metadata[match_id] = info
    return metadata


def build_team_form_stats(
    metadata: dict[int, dict[str, str | None]],
    window: int = TEAM_FORM_WINDOW,
) -> tuple[dict[int, dict[str, dict[str, float]]], dict[str, float], dict[tuple[str, str], float]]:
    matches: list[tuple[date, int]] = []
    for match_id, info in metadata.items():
        match_date = info.get("date")
        if match_date is None:
            continue
        matches.append((match_date, match_id))

    matches.sort(key=lambda item: (item[0], item[1]))

    team_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=window))
    team_venue_history: dict[tuple[str, str], deque] = defaultdict(lambda: deque(maxlen=window))
    match_forms: dict[int, dict[str, dict[str, float]]] = {}

    for _, match_id in matches:
        info = metadata[match_id]
        teams = info.get("teams") or []
        venue = info.get("venue") or "Unknown"
        match_forms[match_id] = {}

        for team in teams:
            history = team_history[team]
            team_form = sum(history) / len(history) if history else 0.5
            venue_history = team_venue_history[(team, venue)]
            team_venue_form = sum(venue_history) / len(venue_history) if venue_history else 0.5
            match_forms[match_id][team] = {
                "team_form": team_form,
                "team_venue_form": team_venue_form,
            }

        winner = info.get("winner")
        if winner:
            for team in teams:
                result = 1.0 if team == winner else 0.0
                team_history[team].append(result)
                team_venue_history[(team, venue)].append(result)

    latest_team_form = {
        team: (sum(history) / len(history) if history else 0.5)
        for team, history in team_history.items()
    }
    latest_team_venue_form = {
        (team, venue): (sum(history) / len(history) if history else 0.5)
        for (team, venue), history in team_venue_history.items()
    }

    return match_forms, latest_team_form, latest_team_venue_form


def build_matchup_form_stats(
    metadata: dict[int, dict[str, str | None]],
    window: int = TEAM_FORM_WINDOW,
) -> tuple[dict[int, dict[tuple[str, str], float]], dict[tuple[str, str], float]]:
    matches: list[tuple[date, int]] = []
    for match_id, info in metadata.items():
        match_date = info.get("date")
        if match_date is None:
            continue
        matches.append((match_date, match_id))

    matches.sort(key=lambda item: (item[0], item[1]))

    matchup_history: dict[tuple[str, str], deque] = defaultdict(lambda: deque(maxlen=window))
    match_matchups: dict[int, dict[tuple[str, str], float]] = {}

    for _, match_id in matches:
        info = metadata[match_id]
        teams = info.get("teams") or []
        match_matchups[match_id] = {}

        for team in teams:
            for opponent in teams:
                if team == opponent:
                    continue
                history = matchup_history[(team, opponent)]
                match_matchups[match_id][(team, opponent)] = sum(history) / len(history) if history else 0.5

        winner = info.get("winner")
        if winner:
            for team in teams:
                for opponent in teams:
                    if team == opponent:
                        continue
                    matchup_history[(team, opponent)].append(1.0 if team == winner else 0.0)

    latest_matchup_form = {
        key: (sum(history) / len(history) if history else 0.5)
        for key, history in matchup_history.items()
    }
    return match_matchups, latest_matchup_form


def summarize_match(match_path: Path, metadata: dict[int, dict[str, str | None]]) -> dict[str, object]:
    df = pd.read_csv(match_path)
    match_id = int(df["match_id"].iloc[0])
    venue = normalize_venue(df["venue"].iloc[0])

    for col in ["runs_off_bat", "extras"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    innings_totals = (
        df.assign(total_ball_runs=df["runs_off_bat"] + df["extras"])
        .groupby("innings", sort=False)["total_ball_runs"]
        .sum()
        .to_dict()
    )

    batting_first_team = None
    if (df["innings"] == 1).any():
        batting_first_team = normalize_team(df.loc[df["innings"] == 1, "batting_team"].iloc[0])

    return {
        "match_id": match_id,
        "match_path": match_path,
        "match_date": metadata.get(match_id, {}).get("date"),
        "venue": venue,
        "innings_totals": innings_totals,
        "batting_first_team": batting_first_team,
        "winner": metadata.get(match_id, {}).get("winner"),
    }


def derive_venue_strength(stats: dict[str, float]) -> dict[str, float]:
    if not stats:
        return DEFAULT_VENUE_STRENGTH.copy()

    first_count = stats["first_count"] or 1.0
    second_count = stats["second_count"] or 1.0
    bat_first_matches = stats["bat_first_matches"] or 1.0
    return {
        "venue_avg_first_innings": stats["first_sum"] / first_count,
        "venue_avg_second_innings": stats["second_sum"] / second_count,
        "venue_bat_first_win_rate": stats["bat_first_wins"] / bat_first_matches,
    }


def build_historical_venue_stats(
    match_summaries: list[dict[str, object]],
) -> tuple[dict[int, dict[str, float]], dict[str, dict[str, float]]]:
    raw_stats: dict[str, dict[str, float]] = {}
    match_venue_stats: dict[int, dict[str, float]] = {}

    for summary in sorted(
        match_summaries,
        key=lambda item: (item["match_date"] or date.min, item["match_id"]),
    ):
        match_id = int(summary["match_id"])
        venue = str(summary["venue"])
        innings_totals = summary["innings_totals"]
        batting_first_team = summary["batting_first_team"]
        winner = summary["winner"]

        match_venue_stats[match_id] = derive_venue_strength(raw_stats.get(venue, {}))

        venue_stats = raw_stats.setdefault(
            venue,
            {
                "first_sum": 0.0,
                "first_count": 0.0,
                "second_sum": 0.0,
                "second_count": 0.0,
                "bat_first_wins": 0.0,
                "bat_first_matches": 0.0,
            },
        )

        if 1 in innings_totals:
            venue_stats["first_sum"] += float(innings_totals[1])
            venue_stats["first_count"] += 1.0
        if 2 in innings_totals:
            venue_stats["second_sum"] += float(innings_totals[2])
            venue_stats["second_count"] += 1.0

        if winner and batting_first_team:
            venue_stats["bat_first_matches"] += 1.0
            if winner == batting_first_team:
                venue_stats["bat_first_wins"] += 1.0

    latest_venue_stats = {
        venue: derive_venue_strength(stats)
        for venue, stats in raw_stats.items()
    }
    return match_venue_stats, latest_venue_stats


def _safe_player_name(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "Unknown"
    text = str(value).strip()
    return text if text else "Unknown"


def _is_bowler_wicket(wicket_type: str | None) -> bool:
    if not wicket_type:
        return False
    wt = wicket_type.strip().lower()
    return wt not in {
        "run out",
        "retired hurt",
        "retired out",
        "obstructing the field",
        "hit wicket",
    }


def compute_features_for_match(
    match_path: Path,
    metadata: dict[int, dict[str, str | None]],
    match_venue_stats: dict[int, dict[str, float]],
    match_forms: dict[int, dict[str, dict[str, float]]],
    matchup_forms: dict[int, dict[tuple[str, str], float]],
    batter_state: dict[str, dict[str, float]],
    bowler_state: dict[str, dict[str, float]],
    batter_bowler_state: dict[tuple[str, str], dict[str, float]],
) -> list[dict]:
    df = pd.read_csv(match_path)
    match_id = int(df["match_id"].iloc[0])
    match_meta = metadata.get(match_id, {})
    winner = match_meta.get("winner")
    toss_winner = match_meta.get("toss_winner")
    toss_decision = match_meta.get("toss_decision")

    df["batting_team"] = df["batting_team"].apply(normalize_team)
    df["bowling_team"] = df["bowling_team"].apply(normalize_team)
    df["venue"] = df["venue"].apply(normalize_venue)

    for col in ["runs_off_bat", "extras", "wides", "noballs"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    innings_totals = (
        df.assign(total_ball_runs=df["runs_off_bat"] + df["extras"])
        .groupby("innings", sort=False)["total_ball_runs"]
        .sum()
        .to_dict()
    )

    venue_strength = match_venue_stats.get(match_id, DEFAULT_VENUE_STRENGTH)
    team_forms = match_forms.get(match_id, {})
    match_matchups = matchup_forms.get(match_id, {})

    rows: list[dict] = []
    for innings in sorted(df["innings"].unique()):
        if innings > 2:
            continue
        innings_df = df[df["innings"] == innings]

        runs = 0.0
        wickets = 0
        legal_balls = 0
        last_runs = deque()
        last_wickets = deque()
        last_legal_runs: deque[float] = deque(maxlen=12)
        last_legal_wickets: deque[int] = deque(maxlen=12)

        for row in innings_df.itertuples(index=False):
            striker = _safe_player_name(getattr(row, "striker", "Unknown"))
            non_striker = _safe_player_name(getattr(row, "non_striker", "Unknown"))
            bowler = _safe_player_name(getattr(row, "bowler", "Unknown"))

            striker_snapshot = batter_state.get(striker, {"runs": 0.0, "balls": 0.0, "outs": 0.0})
            bowler_snapshot = bowler_state.get(bowler, {"balls": 0.0, "runs": 0.0, "wickets": 0.0})
            bb_snapshot = batter_bowler_state.get((striker, bowler), {"runs": 0.0, "balls": 0.0, "wickets": 0.0})

            striker_form_sr = 100.0 * striker_snapshot["runs"] / max(1.0, striker_snapshot["balls"])
            striker_form_avg = striker_snapshot["runs"] / max(1.0, striker_snapshot["outs"])
            bowler_form_econ = 6.0 * bowler_snapshot["runs"] / max(1.0, bowler_snapshot["balls"])
            bowler_form_strike = bowler_snapshot["balls"] / max(1.0, bowler_snapshot["wickets"])
            batter_vs_bowler_sr = 100.0 * bb_snapshot["runs"] / max(1.0, bb_snapshot["balls"])
            batter_vs_bowler_balls = bb_snapshot["balls"]

            ball_runs = float(row.runs_off_bat) + float(row.extras)
            wicket_count = 0
            wicket_type = str(row.wicket_type).strip() if pd.notna(row.wicket_type) else ""
            other_wicket_type = str(row.other_wicket_type).strip() if pd.notna(row.other_wicket_type) else ""
            if wicket_type:
                wicket_count += 1
            if other_wicket_type:
                wicket_count += 1

            runs += ball_runs
            wickets += wicket_count

            last_runs.append(ball_runs)
            last_wickets.append(wicket_count)
            if len(last_runs) > 30:
                last_runs.popleft()
                last_wickets.popleft()

            is_legal = float(row.wides) == 0 and float(row.noballs) == 0
            if is_legal:
                legal_balls += 1
                last_legal_runs.append(ball_runs)
                last_legal_wickets.append(wicket_count)

            balls_left = max(0, 120 - legal_balls)
            overs_completed = legal_balls / 6
            current_run_rate = (runs / overs_completed) if overs_completed > 0 else 0.0
            wickets_left = max(0, 10 - wickets)
            innings_progress = legal_balls / 120 if legal_balls > 0 else 0.0
            over_number = min(20.0, float(legal_balls // 6))
            ball_in_over = float(legal_balls % 6)
            if legal_balls <= 36:
                phase = "powerplay"
            elif legal_balls <= 90:
                phase = "middle"
            else:
                phase = "death"
            is_powerplay = 1.0 if phase == "powerplay" else 0.0
            is_middle = 1.0 if phase == "middle" else 0.0
            is_death = 1.0 if phase == "death" else 0.0

            last_legal_runs_list = list(last_legal_runs)
            last_legal_wickets_list = list(last_legal_wickets)
            runs_last_6_balls = sum(last_legal_runs_list[-6:]) if last_legal_runs_list else 0.0
            wickets_last_6_balls = sum(last_legal_wickets_list[-6:]) if last_legal_wickets_list else 0
            runs_last_12_balls = sum(last_legal_runs_list[-12:]) if last_legal_runs_list else 0.0
            wickets_last_12_balls = sum(last_legal_wickets_list[-12:]) if last_legal_wickets_list else 0

            target = None
            required_run_rate = None
            target_remaining = None
            required_minus_current_rr = None
            if innings == 2:
                target = innings_totals.get(1, 0) + 1
                overs_left = balls_left / 6
                required_run_rate = ((target - runs) / overs_left) if overs_left > 0 else 0.0
                target_remaining = max(0.0, target - runs)
                required_minus_current_rr = required_run_rate - current_run_rate
            current_minus_required_rr = (
                None if required_run_rate is None else current_run_rate - required_run_rate
            )

            venue_par_total = (
                venue_strength["venue_avg_first_innings"]
                if innings == 1
                else venue_strength["venue_avg_second_innings"]
            )
            runs_vs_par = runs - (venue_par_total * innings_progress)

            total_runs = innings_totals.get(innings, 0)
            win = None if winner is None else int(row.batting_team == winner)
            toss_winner_batting = None
            if toss_winner:
                toss_winner_batting = int(toss_winner == row.batting_team)

            batting_forms = team_forms.get(row.batting_team, {})
            bowling_forms = team_forms.get(row.bowling_team, {})
            batting_team_form = batting_forms.get("team_form", 0.5)
            bowling_team_form = bowling_forms.get("team_form", 0.5)
            batting_team_venue_form = batting_forms.get("team_venue_form", 0.5)
            bowling_team_venue_form = bowling_forms.get("team_venue_form", 0.5)
            batting_vs_bowling_form = match_matchups.get((row.batting_team, row.bowling_team), 0.5)

            rows.append(
                {
                    "match_id": match_id,
                    "season": row.season,
                    "season_str": str(row.season),
                    "start_date": row.start_date,
                    "venue": row.venue,
                    "innings": innings,
                    "ball": row.ball,
                    "batting_team": row.batting_team,
                    "bowling_team": row.bowling_team,
                    "striker": striker,
                    "non_striker": non_striker,
                    "bowler": bowler,
                    "toss_winner": toss_winner,
                    "toss_decision": toss_decision,
                    "toss_winner_batting": toss_winner_batting,
                    "runs": runs,
                    "wickets": wickets,
                    "wickets_left": wickets_left,
                    "balls_left": balls_left,
                    "legal_balls_bowled": legal_balls,
                    "innings_progress": innings_progress,
                    "over_number": over_number,
                    "ball_in_over": ball_in_over,
                    "phase": phase,
                    "is_powerplay": is_powerplay,
                    "is_middle": is_middle,
                    "is_death": is_death,
                    "runs_last_5": sum(last_runs),
                    "wickets_last_5": sum(last_wickets),
                    "runs_last_6_balls": runs_last_6_balls,
                    "wickets_last_6_balls": wickets_last_6_balls,
                    "runs_last_12_balls": runs_last_12_balls,
                    "wickets_last_12_balls": wickets_last_12_balls,
                    "current_run_rate": current_run_rate,
                    "target": target,
                    "target_remaining": target_remaining,
                    "required_run_rate": required_run_rate,
                    "current_minus_required_rr": current_minus_required_rr,
                    "required_minus_current_rr": required_minus_current_rr,
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
                    "temperature_c": 28.0,
                    "relative_humidity": 60.0,
                    "wind_kph": 12.0,
                    "dew_risk": 0.5,
                    "runs_vs_par": runs_vs_par,
                    "venue_avg_first_innings": venue_strength["venue_avg_first_innings"],
                    "venue_avg_second_innings": venue_strength["venue_avg_second_innings"],
                    "venue_bat_first_win_rate": venue_strength["venue_bat_first_win_rate"],
                    "total_runs": total_runs,
                    "winner": winner,
                    "win": win,
                }
            )

            # Update running global player states after snapshotting pre-ball form.
            batter_rec = batter_state.setdefault(striker, {"runs": 0.0, "balls": 0.0, "outs": 0.0})
            batter_rec["runs"] += float(row.runs_off_bat)
            if is_legal:
                batter_rec["balls"] += 1.0

            player_dismissed = str(getattr(row, "player_dismissed", "")).strip()
            if wicket_type and player_dismissed == striker:
                batter_rec["outs"] += 1.0

            bowler_rec = bowler_state.setdefault(bowler, {"balls": 0.0, "runs": 0.0, "wickets": 0.0})
            if is_legal:
                bowler_rec["balls"] += 1.0
            bowler_rec["runs"] += ball_runs
            if _is_bowler_wicket(wicket_type):
                bowler_rec["wickets"] += 1.0

            bb_rec = batter_bowler_state.setdefault((striker, bowler), {"runs": 0.0, "balls": 0.0, "wickets": 0.0})
            bb_rec["runs"] += float(row.runs_off_bat)
            if is_legal:
                bb_rec["balls"] += 1.0
            if wicket_type and player_dismissed == striker and _is_bowler_wicket(wicket_type):
                bb_rec["wickets"] += 1.0

    return rows


def build_active_team_player_pool(
    features_df: pd.DataFrame,
    active_teams: list[str],
    min_season_year: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    scoped = features_df.copy()
    scoped["season_key"] = scoped["season"].apply(season_to_year)
    scoped = scoped[scoped["season_key"].notna()].copy()
    scoped["season_key"] = scoped["season_key"].astype(int)
    scoped = scoped[scoped["season_key"] >= min_season_year]
    scoped = scoped[
        scoped["batting_team"].isin(active_teams)
        & scoped["bowling_team"].isin(active_teams)
    ]

    player_events = pd.concat(
        [
            scoped[["batting_team", "striker", "season_key"]].rename(
                columns={"batting_team": "team", "striker": "player"}
            ),
            scoped[["batting_team", "non_striker", "season_key"]].rename(
                columns={"batting_team": "team", "non_striker": "player"}
            ),
            scoped[["bowling_team", "bowler", "season_key"]].rename(
                columns={"bowling_team": "team", "bowler": "player"}
            ),
        ],
        ignore_index=True,
    )

    player_events["player"] = player_events["player"].astype(str).str.strip()
    player_events = player_events[
        (player_events["player"] != "")
        & (player_events["player"] != "Unknown")
        & (player_events["player"] != "nan")
    ]

    pool = (
        player_events.groupby(["team", "player"], as_index=False)
        .agg(appearances=("player", "size"), latest_season=("season_key", "max"))
        .sort_values(
            by=["team", "latest_season", "appearances", "player"],
            ascending=[True, False, False, True],
        )
    )

    # Keep a practical squad-sized pool per team for UI dropdowns.
    pool = pool.groupby("team", as_index=False, group_keys=False).head(24).reset_index(drop=True)
    active_teams_df = pd.DataFrame({"team": active_teams})
    return active_teams_df, pool


def main() -> None:
    metadata = load_match_metadata()
    match_paths = [Path(p) for p in glob.glob(str(RAW_DIR / "*.csv")) if not p.endswith("_info.csv")]
    match_summaries = [summarize_match(match_path, metadata) for match_path in match_paths]
    ordered_match_paths = [
        Path(summary["match_path"])
        for summary in sorted(match_summaries, key=lambda item: (item["match_date"] or date.min, item["match_id"]))
    ]

    match_forms, team_form_latest, team_venue_form_latest = build_team_form_stats(metadata)
    matchup_forms, matchup_form_latest = build_matchup_form_stats(metadata)

    team_form_path = OUT_DIR / "team_form_latest.csv"
    pd.DataFrame(
        [
            {"team": team, "team_form": form, "window": TEAM_FORM_WINDOW}
            for team, form in sorted(team_form_latest.items())
        ]
    ).to_csv(team_form_path, index=False)

    team_venue_form_path = OUT_DIR / "team_venue_form_latest.csv"
    pd.DataFrame(
        [
            {
                "team": team,
                "venue": venue,
                "team_venue_form": form,
                "window": TEAM_FORM_WINDOW,
            }
            for (team, venue), form in sorted(team_venue_form_latest.items())
        ]
    ).to_csv(team_venue_form_path, index=False)

    matchup_form_path = OUT_DIR / "matchup_form_latest.csv"
    pd.DataFrame(
        [
            {
                "team": team,
                "opponent": opponent,
                "matchup_form": form,
                "window": TEAM_FORM_WINDOW,
            }
            for (team, opponent), form in sorted(matchup_form_latest.items())
        ]
    ).to_csv(matchup_form_path, index=False)

    match_venue_stats, latest_venue_stats = build_historical_venue_stats(match_summaries)
    venue_stats_path = OUT_DIR / "venue_stats.csv"
    pd.DataFrame.from_dict(latest_venue_stats, orient="index").reset_index().rename(
        columns={"index": "venue"}
    ).to_csv(venue_stats_path, index=False)

    batter_state: dict[str, dict[str, float]] = {}
    bowler_state: dict[str, dict[str, float]] = {}
    batter_bowler_state: dict[tuple[str, str], dict[str, float]] = {}

    all_rows: list[dict] = []
    for match_path in ordered_match_paths:
        all_rows.extend(
            compute_features_for_match(
                match_path,
                metadata,
                match_venue_stats,
                match_forms,
                matchup_forms,
                batter_state,
                bowler_state,
                batter_bowler_state,
            )
        )

    out_path = OUT_DIR / "ipl_features.csv"
    features_df = pd.DataFrame(all_rows)
    features_df.to_csv(out_path, index=False)

    active_teams_df, player_pool_df = build_active_team_player_pool(
        features_df,
        ACTIVE_IPL_TEAMS_2026,
        min_season_year=ACTIVE_SQUAD_LOOKBACK_START_YEAR,
    )
    active_teams_df.to_csv(ACTIVE_TEAMS_2026_PATH, index=False)
    player_pool_df.to_csv(TEAM_PLAYER_POOL_2026_PATH, index=False)

    batter_form_path = OUT_DIR / "batter_form_latest.csv"
    batter_rows = []
    for batter, stats in sorted(batter_state.items()):
        balls = stats["balls"]
        outs = stats["outs"]
        runs = stats["runs"]
        batter_rows.append(
            {
                "batter": batter,
                "batter_balls": balls,
                "batter_runs": runs,
                "striker_form_sr": 100.0 * runs / max(1.0, balls),
                "striker_form_avg": runs / max(1.0, outs),
            }
        )
    pd.DataFrame(batter_rows).to_csv(batter_form_path, index=False)

    bowler_form_path = OUT_DIR / "bowler_form_latest.csv"
    bowler_rows = []
    for bowler, stats in sorted(bowler_state.items()):
        balls = stats["balls"]
        runs = stats["runs"]
        wickets = stats["wickets"]
        bowler_rows.append(
            {
                "bowler": bowler,
                "bowler_balls": balls,
                "bowler_runs": runs,
                "bowler_wickets": wickets,
                "bowler_form_econ": 6.0 * runs / max(1.0, balls),
                "bowler_form_strike": balls / max(1.0, wickets),
            }
        )
    pd.DataFrame(bowler_rows).to_csv(bowler_form_path, index=False)

    bb_form_path = OUT_DIR / "batter_bowler_form_latest.csv"
    bb_rows = []
    for (batter, bowler), stats in sorted(batter_bowler_state.items()):
        balls = stats["balls"]
        runs = stats["runs"]
        bb_rows.append(
            {
                "batter": batter,
                "bowler": bowler,
                "batter_vs_bowler_balls": balls,
                "batter_vs_bowler_runs": runs,
                "batter_vs_bowler_sr": 100.0 * runs / max(1.0, balls),
            }
        )
    pd.DataFrame(bb_rows).to_csv(bb_form_path, index=False)

    print(f"Wrote {len(all_rows)} rows to {out_path}")
    print(f"Wrote venue stats to {venue_stats_path}")
    print(f"Wrote team form stats to {team_form_path}")
    print(f"Wrote team venue form stats to {team_venue_form_path}")
    print(f"Wrote matchup form stats to {matchup_form_path}")
    print(f"Wrote batter form stats to {batter_form_path}")
    print(f"Wrote bowler form stats to {bowler_form_path}")
    print(f"Wrote batter-bowler form stats to {bb_form_path}")
    print(f"Wrote active teams to {ACTIVE_TEAMS_2026_PATH}")
    print(f"Wrote team player pool to {TEAM_PLAYER_POOL_2026_PATH}")


if __name__ == "__main__":
    main()
