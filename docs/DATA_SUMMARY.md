# IPL Prediction Project — Data Summary

**Last updated:** April 2026  
**Project:** Ball-by-ball IPL match score & win prediction  
**Data source:** [Cricsheet](https://cricsheet.org/) (open-source ball-by-ball IPL data)

---

## Table of Contents

1. [Data Sources](#1-data-sources)
2. [Raw Data — Cricsheet CSV2](#2-raw-data--cricsheet-csv2)
3. [Legacy Dataset — ipl_colab.csv](#3-legacy-dataset--ipl_colabcsv)
4. [Processed / Engineered Datasets](#4-processed--engineered-datasets)
5. [Player Statistics Tables](#5-player-statistics-tables)
6. [Venue & Team Form Tables](#6-venue--team-form-tables)
7. [Model Artifacts](#7-model-artifacts)
8. [Data Pipeline Overview](#8-data-pipeline-overview)
9. [Feature Definitions](#9-feature-definitions)
10. [Teams & Venues Reference](#10-teams--venues-reference)

---

## 1. Data Sources

| Source | Format | Coverage | Size |
|--------|--------|----------|------|
| Cricsheet IPL CSV2 | Ball-by-ball CSVs | IPL 2007–2026 | 1,172 match files |
| ipl_colab.csv | Single flat CSV | IPL 2008–2017 | 76,014 rows |
| Open-Meteo API | Live weather JSON | Real-time (runtime) | Cached snapshot |

### How data was collected

**Cricsheet CSV2 format** was downloaded from [cricsheet.org/downloads](https://cricsheet.org/downloads/).  
Each IPL match comes as a pair of files:
- `{match_id}.csv` — every legal ball in the match
- `{match_id}_info.csv` — match metadata (teams, venue, toss, result, players)

The `ipl_colab.csv` is an older aggregated dataset used for compatibility checking and early EDA.

---

## 2. Raw Data — Cricsheet CSV2

**Location:** `data/ipl_csv2/`  
**Matches:** 1,172 (IPL 2007–2026)  
**Files:** 2,344 (1 ball-by-ball + 1 info per match)

### Ball-by-ball file (`{match_id}.csv`)

Each row = one legal delivery.

| Column | Type | Description |
|--------|------|-------------|
| `match_id` | int | Unique Cricsheet match identifier |
| `season` | str | IPL season year (e.g., "2024") |
| `start_date` | date | Match date (YYYY-MM-DD) |
| `venue` | str | Stadium name (raw, un-normalized) |
| `innings` | int | 1 or 2 |
| `ball` | float | Over.ball notation (e.g., 6.3 = over 6, ball 3) |
| `batting_team` | str | Team currently batting |
| `bowling_team` | str | Team currently bowling |
| `striker` | str | Batter facing the delivery |
| `non_striker` | str | Batter at non-striker end |
| `bowler` | str | Bowler delivering the ball |
| `runs_off_bat` | int | Runs scored off the bat |
| `extras` | int | Total extras on this delivery |
| `wides` | int/NaN | Wide runs (NaN if no wide) |
| `noballs` | int/NaN | No-ball runs (NaN if no no-ball) |
| `byes` | int/NaN | Bye runs (NaN if no byes) |
| `legbyes` | int/NaN | Leg-bye runs (NaN if no leg-byes) |
| `penalty` | int/NaN | Penalty runs (NaN if none) |
| `wicket_type` | str/NaN | How batsman was dismissed (NaN if not out) |
| `player_dismissed` | str/NaN | Name of dismissed batsman |
| `other_wicket_type` | str/NaN | Secondary dismissal type (rare) |
| `other_player_dismissed` | str/NaN | Secondary dismissed player (rare) |

**Notes:**
- Extras columns are sparse (mostly NaN — only populated on that delivery type)
- Wicket columns are ~95% NaN (only a wicket delivery has values)
- `ball` uses Cricsheet notation: `6.3` = 7th over, 4th ball (0-indexed overs)

### Match info file (`{match_id}_info.csv`)

Key-value pair format. Relevant fields extracted:

| Field | Description |
|-------|-------------|
| `date` | Match date |
| `team` | Both team names (2 rows) |
| `venue` | Stadium name |
| `toss_winner` | Team that won the toss |
| `toss_decision` | `bat` or `field` |
| `winner` | Match winner (blank if no result) |
| players | Per-team playing XI (via `players` key) |

---

## 3. Legacy Dataset — ipl_colab.csv

**Location:** `ipl_colab.csv`  
**Shape:** 76,014 rows × 15 columns  
**Coverage:** IPL 2008–2017 (seasons 1–10)

| Column | Type | Description |
|--------|------|-------------|
| `mid` | int | Match ID |
| `date` | date | Match date |
| `venue` | str | Stadium name |
| `batting_team` | str | Batting team name |
| `bowling_team` | str | Bowling team name |
| `batsman` | str | Current batter |
| `bowler` | str | Current bowler |
| `runs` | int | Cumulative runs at this ball |
| `wickets` | int | Wickets fallen so far |
| `overs` | float | Overs bowled (e.g., 6.3) |
| `runs_last_5` | int | Runs in previous 5 overs |
| `wickets_last_5` | int | Wickets in previous 5 overs |
| `striker` | int | 1 = batsman is striker, 0 = non-striker |
| `non-striker` | int | 1 = batsman is non-striker |
| `total` | int | Final innings total (ground truth) |

**Teams in this dataset (14):**
Mumbai Indians, Royal Challengers Bangalore, Kings XI Punjab, Delhi Daredevils, Kolkata Knight Riders, Chennai Super Kings, Rajasthan Royals, Deccan Chargers, Sunrisers Hyderabad, Pune Warriors, Rising Pune Supergiants, Kochi Tuskers Kerala, Gujarat Lions, Rising Pune Supergiant

**Venues covered:** 35 unique stadiums

> This file predates the Cricsheet pipeline. It is used for EDA and backward compatibility. Main training uses `ipl_features.csv`.

---

## 4. Processed / Engineered Datasets

### 4.1 ipl_features.csv — Main Training Dataset

**Location:** `data/processed/ipl_features.csv`  
**Shape:** 278,705 rows × 60 columns  
**Coverage:** IPL 2007–2026 (all seasons)  
**Size:** ~128 MB

This is the primary ML training dataset. Each row represents the match **state at the moment a legal ball is bowled**, enriched with:
- Current game state (runs, wickets, overs)
- Rolling team & player form
- Venue characteristics
- Weather defaults

**Column groups:**

#### Match Metadata (8 cols)
| Column | Type | Description |
|--------|------|-------------|
| `match_id` | int | Cricsheet match ID |
| `season` | int | IPL season year |
| `start_date` | date | Match date |
| `venue` | str | Normalized venue name |
| `innings` | int | 1 or 2 |
| `ball` | float | Cricsheet ball notation |
| `batting_team` | str | Team batting |
| `bowling_team` | str | Team bowling |

#### Players (3 cols)
| Column | Type | Description |
|--------|------|-------------|
| `striker` | str | Batter facing |
| `non_striker` | str | Batter at other end |
| `bowler` | str | Bowler for this delivery |

#### Toss (2 cols + 1 derived)
| Column | Type | Description |
|--------|------|-------------|
| `toss_winner` | str | Team that won toss |
| `toss_decision` | str | `bat` or `field` |
| `toss_winner_batting` | int | 1 if toss winner is currently batting |

#### Match State (8 cols)
| Column | Type | Description |
|--------|------|-------------|
| `runs` | int | Cumulative runs this innings |
| `wickets` | int | Wickets fallen |
| `wickets_left` | int | Wickets remaining (10 - wickets) |
| `balls_left` | int | Balls remaining in innings |
| `legal_balls_bowled` | int | Legal deliveries bowled so far |
| `innings_progress` | float | Fraction of innings completed (0–1) |
| `over_number` | int | Current over (0-indexed) |
| `ball_in_over` | int | Ball number within over (0–5) |

#### Phase (4 cols)
| Column | Type | Description |
|--------|------|-------------|
| `phase` | str | `powerplay` / `middle` / `death` |
| `is_powerplay` | int | 1 if overs 1–6 |
| `is_middle` | int | 1 if overs 7–15 |
| `is_death` | int | 1 if overs 16–20 |

#### Momentum (6 cols)
| Column | Type | Description |
|--------|------|-------------|
| `runs_last_5` | int | Runs in last 5 overs |
| `wickets_last_5` | int | Wickets in last 5 overs |
| `runs_last_6_balls` | int | Runs in last 6 balls |
| `wickets_last_6_balls` | int | Wickets in last 6 balls |
| `runs_last_12_balls` | int | Runs in last 12 balls |
| `wickets_last_12_balls` | int | Wickets in last 12 balls |

#### Rates & Targets (6 cols)
| Column | Type | Description |
|--------|------|-------------|
| `current_run_rate` | float | CRR = runs / overs |
| `target` | float | 2nd innings target (NaN for innings 1) |
| `target_remaining` | float | Runs still needed (NaN for innings 1) |
| `required_run_rate` | float | RRR = target_remaining / overs_left (NaN for innings 1) |
| `current_minus_required_rr` | float | CRR − RRR (positive = batting ahead) |
| `required_minus_current_rr` | float | RRR − CRR (positive = bowling ahead) |

#### Team Form (5 cols) — rolling 5-match window
| Column | Type | Description |
|--------|------|-------------|
| `batting_team_form` | float | Batting team recent win rate |
| `bowling_team_form` | float | Bowling team recent win rate |
| `batting_team_venue_form` | float | Batting team win rate at this venue |
| `bowling_team_venue_form` | float | Bowling team win rate at this venue |
| `batting_vs_bowling_form` | float | Batting team H2H win rate vs bowling team |

#### Player Form (6 cols) — all-time rolling stats
| Column | Type | Description |
|--------|------|-------------|
| `striker_form_sr` | float | Batter's career strike rate |
| `striker_form_avg` | float | Batter's career batting average |
| `bowler_form_econ` | float | Bowler's career economy rate |
| `bowler_form_strike` | float | Bowler's career strike rate (balls per wicket) |
| `batter_vs_bowler_sr` | float | This batter's SR against this bowler |
| `batter_vs_bowler_balls` | float | Total balls faced in this matchup |

#### Weather (4 cols) — placeholder defaults
| Column | Type | Description |
|--------|------|-------------|
| `temperature_c` | float | Temperature in Celsius (default: 28) |
| `relative_humidity` | float | Humidity % (default: 60) |
| `wind_kph` | float | Wind speed km/h (default: 12) |
| `dew_risk` | float | Dew risk score 0–1 (default: 0.5) |

> Weather is fetched live via Open-Meteo API at prediction time; these are training defaults.

#### Venue Strength (4 cols)
| Column | Type | Description |
|--------|------|-------------|
| `venue_avg_first_innings` | float | Historical avg 1st innings at this venue |
| `venue_avg_second_innings` | float | Historical avg 2nd innings at this venue |
| `venue_bat_first_win_rate` | float | Fraction of matches won by team batting first |
| `runs_vs_par` | float | Current innings runs minus expected runs at this over |

#### Target Variables (3 cols)
| Column | Type | Description |
|--------|------|-------------|
| `total_runs` | int | Final innings total (regression target) |
| `winner` | str | Match winner (team name) |
| `win` | float | 1 if batting team wins, 0 otherwise (classification target) |

---

## 5. Player Statistics Tables

### 5.1 batter_form_latest.csv

**Location:** `data/processed/batter_form_latest.csv`  
**Shape:** 710 rows × 5 columns  
**Coverage:** All IPL batters 2007–2026

| Column | Description |
|--------|-------------|
| `batter` | Player name |
| `batter_balls` | Career balls faced |
| `batter_runs` | Career runs scored |
| `striker_form_sr` | Strike rate (runs per 100 balls) |
| `striker_form_avg` | Batting average (runs per dismissal) |

### 5.2 bowler_form_latest.csv

**Location:** `data/processed/bowler_form_latest.csv`  
**Shape:** 557 rows × 6 columns  
**Coverage:** All IPL bowlers 2007–2026

| Column | Description |
|--------|-------------|
| `bowler` | Player name |
| `bowler_balls` | Career balls bowled |
| `bowler_runs` | Career runs conceded |
| `bowler_wickets` | Career wickets taken |
| `bowler_form_econ` | Economy rate (runs per 6 balls) |
| `bowler_form_strike` | Strike rate (balls per wicket) |

### 5.3 batter_bowler_form_latest.csv

**Location:** `data/processed/batter_bowler_form_latest.csv`  
**Shape:** 29,623 rows × 5 columns  
**Coverage:** Every batter-bowler pair that has met in IPL history

| Column | Description |
|--------|-------------|
| `batter` | Batter name |
| `bowler` | Bowler name |
| `batter_vs_bowler_balls` | Balls faced in this matchup |
| `batter_vs_bowler_runs` | Runs scored in this matchup |
| `batter_vs_bowler_sr` | Strike rate in this matchup |

### 5.4 team_player_pool_2026.csv

**Location:** `data/processed/team_player_pool_2026.csv`  
**Shape:** 240 rows × 4 columns  
**Coverage:** 10 active IPL teams × top 24 players (from 2024–2026 data only)

| Column | Description |
|--------|-------------|
| `team` | Team name |
| `player` | Player name |
| `appearances` | Ball-level appearances in 2024–2026 |
| `latest_season` | Most recent season played |

---

## 6. Venue & Team Form Tables

### 6.1 venue_stats.csv

**Location:** `data/processed/venue_stats.csv`  
**Shape:** 41 rows × 4 columns

| Column | Description |
|--------|-------------|
| `venue` | Normalized venue name |
| `venue_avg_first_innings` | Historical average 1st innings score |
| `venue_avg_second_innings` | Historical average 2nd innings score |
| `venue_bat_first_win_rate` | Fraction of matches won by team batting first |

**Key venues:**

| Venue | Avg 1st Inn | Avg 2nd Inn | Bat-First Win% |
|-------|-------------|-------------|----------------|
| M. Chinnaswamy Stadium | 173 | 154 | 43.9% |
| Arun Jaitley Stadium | 172 | 157 | 48.9% |
| Wankhede Stadium | 171 | 160 | 44.8% |
| Eden Gardens | 169 | 154 | 42.4% |
| Narendra Modi Stadium | 169 | 157 | 47.0% |

### 6.2 team_form_latest.csv

**Location:** `data/processed/team_form_latest.csv`  
**Shape:** 15 rows × 3 columns

| Column | Description |
|--------|-------------|
| `team` | Team name |
| `team_form` | Win rate in last 5 matches (0.0–1.0) |
| `window` | Rolling window size (always 5) |

### 6.3 team_venue_form_latest.csv

**Location:** `data/processed/team_venue_form_latest.csv`  
**Shape:** 359 rows × 4 columns

| Column | Description |
|--------|-------------|
| `team` | Team name |
| `venue` | Venue name |
| `team_venue_form` | Team win rate at this venue (last 5) |
| `window` | Rolling window size (5) |

### 6.4 matchup_form_latest.csv

**Location:** `data/processed/matchup_form_latest.csv`  
**Shape:** 166 rows × 4 columns  
**Coverage:** Every team-vs-team pair in IPL history

| Column | Description |
|--------|-------------|
| `team` | Team name |
| `opponent` | Opponent team name |
| `matchup_form` | Win rate vs this opponent (last 5 meetings) |
| `window` | Rolling window size (5) |

---

## 7. Model Artifacts

| File | Type | Purpose | Size |
|------|------|---------|------|
| `score_model.pkl` | Torch/ensemble | Predict final innings total (live match) | 617 KB |
| `win_model.pkl` | CatBoost + calibration | Predict win probability (live match) | 26.3 MB |
| `pre_match_score_model.pkl` | MLP sklearn | Predict 1st innings score (before match) | 433 KB |
| `pre_match_win_model.pkl` | MLP sklearn | Predict win probability (before match) | 433 KB |
| `score_uncertainty.json` | JSON | Residual quantiles for score interval | 1 KB |

**Production model performance (2026 test holdout):**

| Model | Metric | Value |
|-------|--------|-------|
| Score (live) | MAE | 15.36 runs |
| Score (live) | RMSE | 19.81 runs |
| Win (live) | Accuracy | 67.1% |
| Win (live) | Log Loss | 0.4922 |
| Win (live) | Brier Score | 0.1681 |

**Score uncertainty profile:**
- 10th percentile residual: −12.24 runs  
- 90th percentile residual: +28.61 runs  
- Standard deviation: 18.06 runs

---

## 8. Data Pipeline Overview

```
Cricsheet IPL CSV2
data/ipl_csv2/*.csv          (1,172 match ball-by-ball files)
data/ipl_csv2/*_info.csv     (1,172 match metadata files)
          │
          ▼
scripts/preprocess_ipl.py
          │
          ├── Normalize team/venue names (TEAM_ALIASES, VENUE_ALIASES)
          ├── Extract match metadata (winner, toss, date, teams)
          ├── Compute per-ball features (state, phase, momentum, rates)
          ├── Compute rolling team form (5-match window)
          ├── Compute head-to-head matchup form
          ├── Compute venue statistics (avg scores, bat-first win rate)
          ├── Compute player form (batter SR/avg, bowler econ/strike)
          ├── Compute batter-vs-bowler matchup stats
          └── Extract 2026 active squad pools
          │
          ▼
data/processed/
  ipl_features.csv              (278,705 rows × 60 cols — main training data)
  team_form_latest.csv          (team recent form)
  team_venue_form_latest.csv    (team form at each venue)
  matchup_form_latest.csv       (head-to-head records)
  venue_stats.csv               (venue score/win-rate stats)
  batter_form_latest.csv        (batter career stats)
  bowler_form_latest.csv        (bowler career stats)
  batter_bowler_form_latest.csv (matchup head-to-head stats)
  team_player_pool_2026.csv     (2026 squad pools)
  active_teams_2026.csv         (current active teams)
          │
          ▼
scripts/train_models.py          (CPU baseline — HistGradientBoosting)
scripts/train_gpu_best.py        (GPU search — XGBoost, CatBoost, PyTorch)
scripts/train_pre_match.py       (pre-match MLP — 3 features only)
          │
          ▼
models/
  score_model.pkl
  win_model.pkl
  pre_match_score_model.pkl
  pre_match_win_model.pkl
  score_uncertainty.json
```

---

## 9. Feature Definitions

### Phase Boundaries

| Phase | Overs | Description |
|-------|-------|-------------|
| powerplay | 1–6 | Fielding restrictions apply |
| middle | 7–15 | Build-up phase |
| death | 16–20 | Slog/finishing phase |

### Form Metric Calculation

All form metrics use a **rolling 5-match window** (last 5 encounters):
- **Team form:** wins / matches in last 5
- **Team-venue form:** wins at this venue / last 5 at this venue
- **H2H form:** wins vs this opponent / last 5 meetings

Player stats are **career cumulative** (not windowed):
- **Strike rate:** (runs / balls) × 100
- **Batting average:** runs / dismissals
- **Economy:** (runs / balls) × 6
- **Bowling strike rate:** balls / wickets

### Dew Risk Score

Computed at runtime from live weather:
```
dew_risk = 0.5 × (temp_factor) + 0.5 × (humidity_factor)
where:
  temp_factor     = 1 if temp < 20 else (0.7 if temp < 28 else 0.3)
  humidity_factor = 1 if humidity > 80 else (0.7 if humidity > 65 else 0.3)
```
Range: 0 (low dew risk) to 1 (high dew risk)

---

## 10. Teams & Venues Reference

### Active IPL Teams 2026

| Short Name | Full Name | Home Venue |
|------------|-----------|------------|
| CSK | Chennai Super Kings | MA Chidambaram Stadium |
| DC | Delhi Capitals | Arun Jaitley Stadium |
| GT | Gujarat Titans | Narendra Modi Stadium |
| KKR | Kolkata Knight Riders | Eden Gardens |
| LSG | Lucknow Super Giants | Ekana Cricket Stadium |
| MI | Mumbai Indians | Wankhede Stadium |
| PBKS | Punjab Kings | Punjab Cricket Association Stadium |
| RR | Rajasthan Royals | Sawai Mansingh Stadium |
| RCB | Royal Challengers Bengaluru | M. Chinnaswamy Stadium |
| SRH | Sunrisers Hyderabad | Rajiv Gandhi International Stadium |

### Key Venue Aliases

| Raw Name in Data | Normalized Name |
|-----------------|-----------------|
| Feroz Shah Kotla | Arun Jaitley Stadium |
| M. Chidambaram Stadium | MA Chidambaram Stadium |
| Motera Stadium | Narendra Modi Stadium |
| DY Patil Sports Academy | DY Patil Stadium |
| M Chinnaswamy Stadium, Bengaluru | M. Chinnaswamy Stadium |
| Ekana International Cricket Stadium, Lucknow | Ekana Cricket Stadium |

### Historical Team Aliases

| Old Name | Current Name |
|----------|-------------|
| Delhi Daredevils | Delhi Capitals |
| Kings XI Punjab | Punjab Kings |
| Royal Challengers Bangalore | Royal Challengers Bengaluru |
| Rising Pune Supergiants | Rising Pune Supergiant |
| Pune Warriors | Pune Warriors India |
