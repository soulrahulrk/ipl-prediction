from __future__ import annotations

from marshmallow import EXCLUDE, Schema, ValidationError, fields, validates_schema

from .common import ACTIVE_IPL_TEAMS_2026, normalize_venue


class PredictRequestSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    season = fields.String(required=True)
    venue = fields.String(required=True)
    batting_team = fields.String(required=True)
    bowling_team = fields.String(required=True)
    innings = fields.Integer(required=True)
    runs = fields.Float(required=True)
    wickets = fields.Integer(required=True)
    overs = fields.String(required=True)
    first_innings_total = fields.Float(load_default=None)

    @validates_schema
    def validate_logic(self, data, **kwargs):
        errors = {}

        if data.get("batting_team") == data.get("bowling_team"):
            errors["bowling_team"] = ["Batting and bowling team must be different."]

        if data.get("batting_team") not in ACTIVE_IPL_TEAMS_2026:
            errors["batting_team"] = ["Unknown batting_team. Use active IPL team name."]

        if data.get("bowling_team") not in ACTIVE_IPL_TEAMS_2026:
            errors["bowling_team"] = ["Unknown bowling_team. Use active IPL team name."]

        if not normalize_venue(data.get("venue")):
            errors["venue"] = ["Venue is required and must be recognized."]

        runs = data.get("runs", 0.0)
        wickets = data.get("wickets", 0)
        innings = data.get("innings")

        if runs < 0:
            errors["runs"] = ["runs cannot be negative."]

        if wickets < 0 or wickets > 10:
            errors["wickets"] = ["wickets must be between 0 and 10."]

        overs_text = str(data.get("overs", "")).strip()
        try:
            parts = overs_text.split(".")
            overs = int(parts[0]) if parts[0] else 0
            balls = int(parts[1]) if len(parts) > 1 else 0
            if overs < 0 or overs > 20:
                errors["overs"] = ["overs must be between 0 and 20."]
            if balls < 0 or balls > 5:
                errors["overs"] = ["ball segment in overs must be 0-5."]
            if overs == 20 and balls > 0:
                errors["overs"] = ["overs cannot exceed 20.0 in T20."]
        except Exception:
            errors["overs"] = ["overs must be in format O.B (for example 12.3)."]

        if innings not in (1, 2):
            errors["innings"] = ["innings must be 1 or 2."]

        if innings == 2:
            first_innings_total = data.get("first_innings_total")
            if first_innings_total is None:
                errors["first_innings_total"] = ["first_innings_total is required for innings 2."]
            elif first_innings_total < 0:
                errors["first_innings_total"] = ["first_innings_total cannot be negative."]
            elif first_innings_total < runs:
                errors["first_innings_total"] = ["first_innings_total cannot be less than current runs in chase."]

        if errors:
            raise ValidationError(errors)


class OutcomeRequestSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    prediction_id = fields.Integer(load_default=None)
    event_id = fields.String(load_default=None)
    match_id = fields.String(load_default=None)
    actual_total = fields.Float(load_default=None)
    actual_win = fields.Integer(load_default=None)

    @validates_schema
    def validate_logic(self, data, **kwargs):
        errors = {}

        if data.get("actual_total") is None and data.get("actual_win") is None:
            errors["actual_total"] = ["Provide at least one of actual_total or actual_win."]

        if data.get("actual_total") is not None and data["actual_total"] < 0:
            errors["actual_total"] = ["actual_total cannot be negative."]

        if data.get("actual_win") is not None and data["actual_win"] not in (0, 1):
            errors["actual_win"] = ["actual_win must be 0 or 1."]

        if errors:
            raise ValidationError(errors)
