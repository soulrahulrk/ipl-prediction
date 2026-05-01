"""add monitoring outcomes table

Revision ID: 20260425_0002
Revises: 20260425_0001
Create Date: 2026-04-25 00:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260425_0002"
down_revision = "20260425_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monitoring_outcomes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("outcome_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_monitoring_outcomes_event_id", "monitoring_outcomes", ["event_id"], unique=False)
    op.create_index("ix_monitoring_outcomes_payload_hash", "monitoring_outcomes", ["payload_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_monitoring_outcomes_payload_hash", table_name="monitoring_outcomes")
    op.drop_index("ix_monitoring_outcomes_event_id", table_name="monitoring_outcomes")
    op.drop_table("monitoring_outcomes")
