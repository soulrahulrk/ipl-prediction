"""initial saas schema

Revision ID: 20260425_0001
Revises:
Create Date: 2026-04-25 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260425_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "invites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("used_by_user_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["used_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invites_token", "invites", ["token"], unique=True)
    op.create_index("ix_invites_email", "invites", ["email"], unique=False)

    op.create_table(
        "matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_match_id", sa.String(length=128), nullable=True),
        sa.Column("season", sa.String(length=32), nullable=True),
        sa.Column("venue", sa.String(length=255), nullable=True),
        sa.Column("batting_team", sa.String(length=255), nullable=True),
        sa.Column("bowling_team", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_matches_external_match_id", "matches", ["external_match_id"], unique=False)

    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=128), nullable=False),
        sa.Column("artifact_uri", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_name", "version", name="uq_model_name_version"),
    )
    op.create_index("ix_model_versions_model_name", "model_versions", ["model_name"], unique=False)
    op.create_index("ix_model_versions_version", "model_versions", ["version"], unique=False)

    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=True),
        sa.Column("score_model_version_id", sa.Integer(), nullable=True),
        sa.Column("win_model_version_id", sa.Integer(), nullable=True),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("output_payload", sa.JSON(), nullable=False),
        sa.Column("monitoring_event_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"]),
        sa.ForeignKeyConstraint(["score_model_version_id"], ["model_versions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["win_model_version_id"], ["model_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_predictions_monitoring_event_id", "predictions", ["monitoring_event_id"], unique=False)
    op.create_index("idx_predictions_user_created", "predictions", ["user_id", "created_at"], unique=False)
    op.create_index("idx_predictions_match", "predictions", ["match_id"], unique=False)

    op.create_table(
        "prediction_outcomes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("prediction_id", sa.Integer(), nullable=False),
        sa.Column("actual_total", sa.Float(), nullable=True),
        sa.Column("actual_win", sa.Integer(), nullable=True),
        sa.Column("score_abs_error", sa.Float(), nullable=True),
        sa.Column("win_brier_error", sa.Float(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["prediction_id"], ["predictions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prediction_id"),
    )
    op.create_index("idx_outcomes_prediction_resolved", "prediction_outcomes", ["prediction_id", "resolved_at"], unique=False)

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_audit_user_created_action", "audit_logs", ["user_id", "created_at", "action"], unique=False)

    op.create_table(
        "monitoring_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_monitoring_events_event_id", "monitoring_events", ["event_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_monitoring_events_event_id", table_name="monitoring_events")
    op.drop_table("monitoring_events")

    op.drop_index("idx_audit_user_created_action", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("idx_outcomes_prediction_resolved", table_name="prediction_outcomes")
    op.drop_table("prediction_outcomes")

    op.drop_index("idx_predictions_match", table_name="predictions")
    op.drop_index("idx_predictions_user_created", table_name="predictions")
    op.drop_index("ix_predictions_monitoring_event_id", table_name="predictions")
    op.drop_table("predictions")

    op.drop_index("ix_model_versions_version", table_name="model_versions")
    op.drop_index("ix_model_versions_model_name", table_name="model_versions")
    op.drop_table("model_versions")

    op.drop_index("ix_matches_external_match_id", table_name="matches")
    op.drop_table("matches")

    op.drop_index("ix_invites_email", table_name="invites")
    op.drop_index("ix_invites_token", table_name="invites")
    op.drop_table("invites")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
