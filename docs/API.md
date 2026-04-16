# API

## Python Entry Points

### Live prediction

Functions:

- ipl_predictor.load_models()
- ipl_predictor.load_support_tables()
- ipl_predictor.predict_match_state(payload, support_tables, score_model, win_model)

Required payload fields:

- season
- venue
- batting_team
- bowling_team
- innings
- runs
- wickets
- overs

Conditionally required:

- first_innings_total when innings is 2

Useful optional fields:

- striker
- bowler
- runs_last_5
- wickets_last_5
- toss_winner
- toss_decision
- use_live_weather
- batting_team_form
- bowling_team_form

Returns:

- Tuple of (prediction, errors)
- prediction is None when validation fails

Prediction dictionary includes keys such as:

- predicted_total
- win_prob
- win_prob_raw
- win_prob_pct
- win_prob_band
- win_stability_flags
- phase
- venue_par_score
- runs_vs_par
- projected_range
- simulated_median
- collapse_risk_pct
- big_finish_chance_pct
- temperature_c
- dew_risk

### Pre-match prediction

Functions:

- ipl_predictor.load_pre_match_models()
- ipl_predictor.predict_pre_match(team1, team2, venue, score_model, win_model)

Return keys:

- predicted_score
- exact_predicted_score
- team1
- team2
- team1_win_prob
- team2_win_prob
- likely_winner

## Flask HTTP API

### POST /api/predict

Purpose:

- Run a live prediction from JSON or form payload

Success response example:

```json
{
  "ok": true,
  "prediction": {
    "predicted_total": "171.2",
    "win_prob": "0.738",
    "win_prob_pct": "73.8%"
  }
}
```

Validation failure example:

```json
{
  "ok": false,
  "errors": [
    "Venue is required."
  ]
}
```

### GET /api/monitoring

Purpose:

- Return latest production drift-check report generated from logged prediction events.

Optional query:

- `refresh=true` to recompute drift report immediately.

Example success response (truncated):

```json
{
  "ok": true,
  "monitoring": {
    "status": "stable",
    "events_used": 500,
    "feature_drift": {
      "runs": {
        "z_score": 0.84,
        "warning": false
      }
    }
  }
}
```

## Model Artifacts

Live deployment artifacts:

- models/score_model.pkl
- models/win_model.pkl
- models/score_uncertainty.json
- models/win_stability_profile.json

Optional pre-match artifacts:

- models/pre_match_score_model.pkl
- models/pre_match_win_model.pkl
- models/pre_match_model_report.json

Promotion reports:

- models/deployment_report.json
- models/best_model_search_report.json
- models/production_drift_report.json
- models/model_registry.json
