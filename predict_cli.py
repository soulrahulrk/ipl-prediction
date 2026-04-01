from ipl_predictor import load_models, load_support_tables, normalize_team, normalize_venue, predict_match_state


def get_input(prompt: str, default: str | None = None) -> str:
    raw = input(prompt).strip()
    if not raw and default is not None:
        return default
    return raw


def parse_int_input(prompt: str, default: int | None = None) -> int:
    raw = get_input(prompt, default=str(default) if default is not None else None)
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"Invalid integer for: {prompt}")


def parse_float_input(prompt: str, default: float | None = None) -> float:
    raw = get_input(prompt, default=str(default) if default is not None else None)
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"Invalid number for: {prompt}")


def main() -> None:
    print("IPL Prediction CLI")
    print("Leave last-5 values blank to use 0.")

    try:
        payload = {
            "season": get_input("Season (e.g., 2025 or 2020/21): "),
            "venue": get_input("Venue: "),
            "batting_team": get_input("Batting team: "),
            "bowling_team": get_input("Bowling team: "),
            "striker": get_input("Current striker (optional): ", default="Unknown"),
            "bowler": get_input("Current bowler (optional): ", default="Unknown"),
            "toss_winner": get_input("Toss winner (optional): ", default=""),
            "toss_decision": get_input("Toss decision (bat/field, optional): ", default="").strip().lower(),
            "innings": parse_int_input("Innings (1 or 2): "),
            "runs": parse_float_input("Current runs: "),
            "wickets": parse_int_input("Wickets fallen: "),
            "overs": get_input("Overs bowled (format 12.3): "),
            "runs_last_5": parse_float_input("Runs in last 5 overs: ", default=0.0),
            "wickets_last_5": parse_float_input("Wickets in last 5 overs: ", default=0.0),
            "use_live_weather": get_input("Use live weather from internet? (yes/no): ", default="yes").lower()
            in {"yes", "y", "true", "1"},
        }
    except ValueError as exc:
        print(f"Error: {exc}")
        return

    if payload["innings"] == 2:
        try:
            payload["first_innings_total"] = parse_float_input("First innings total: ")
        except ValueError as exc:
            print(f"Error: {exc}")
            return

    support_tables = load_support_tables()
    normalized_venue = normalize_venue(payload["venue"])
    normalized_batting_team = normalize_team(payload["batting_team"])
    normalized_bowling_team = normalize_team(payload["bowling_team"])

    batting_team_default = support_tables.team_form_map.get(normalized_batting_team, 0.5)
    bowling_team_default = support_tables.team_form_map.get(normalized_bowling_team, 0.5)
    batting_venue_default = support_tables.team_venue_form_map.get(
        (normalized_batting_team, normalized_venue),
        0.5,
    )
    bowling_venue_default = support_tables.team_venue_form_map.get(
        (normalized_bowling_team, normalized_venue),
        0.5,
    )

    payload["batting_team_form"] = float(
        get_input("Batting team form (0-1, optional): ", default=f"{batting_team_default:.3f}")
    )
    payload["bowling_team_form"] = float(
        get_input("Bowling team form (0-1, optional): ", default=f"{bowling_team_default:.3f}")
    )
    payload["batting_team_venue_form"] = float(
        get_input("Batting team venue form (0-1, optional): ", default=f"{batting_venue_default:.3f}")
    )
    payload["bowling_team_venue_form"] = float(
        get_input("Bowling team venue form (0-1, optional): ", default=f"{bowling_venue_default:.3f}")
    )

    score_model, win_model = load_models()
    prediction, errors = predict_match_state(
        payload,
        support_tables=support_tables,
        score_model=score_model,
        win_model=win_model,
    )
    if errors:
        for error in errors:
            print(f"Error: {error}")
        return

    assert prediction is not None
    print("\nPrediction")
    print(f"Predicted final innings total: {prediction['predicted_total']}")
    print(f"Win probability for {prediction['batting_team']}: {prediction['win_prob']}")
    print(f"Win probability %: {prediction['win_prob_pct']}")
    print(f"Win probability band: {prediction['win_prob_band']}")
    print(f"Current phase: {prediction['phase']}")
    print(f"Venue par score: {prediction['venue_par_score']}")
    print(f"Runs vs par: {prediction['runs_vs_par']}")
    print(f"Projected range: {prediction['projected_range']}")
    print(f"Simulated median score: {prediction['simulated_median']}")
    print(f"Collapse risk: {prediction['collapse_risk_pct']}")
    print(f"Big finish chance: {prediction['big_finish_chance_pct']}")
    print(f"Temperature (C): {prediction['temperature_c']}")
    print(f"Dew risk: {prediction['dew_risk']}")
    if prediction["target_remaining"]:
        print(f"Target remaining: {prediction['target_remaining']}")
    if prediction["current_minus_required_rr"]:
        print(f"Current RR minus Req RR: {prediction['current_minus_required_rr']}")
    if prediction["required_minus_current_rr"]:
        print(f"Req RR minus current RR: {prediction['required_minus_current_rr']}")


if __name__ == "__main__":
    main()
