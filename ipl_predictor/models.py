from __future__ import annotations

from datetime import datetime, timezone
import secrets

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    predictions: Mapped[list[Prediction]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True, default=lambda: secrets.token_urlsafe(24))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    used_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_match_id: Mapped[str | None] = mapped_column(String(128), index=True)
    season: Mapped[str | None] = mapped_column(String(32))
    venue: Mapped[str | None] = mapped_column(String(255))
    batting_team: Mapped[str | None] = mapped_column(String(255))
    bowling_team: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    predictions: Mapped[list[Prediction]] = relationship(back_populates="match", cascade="all, delete-orphan")


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_name: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(128), index=True)
    artifact_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("model_name", "version", name="uq_model_name_version"),)


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id"), nullable=True)
    score_model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"), nullable=True)
    win_model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"), nullable=True)
    input_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    output_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    monitoring_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="predictions")
    match: Mapped[Match | None] = relationship(back_populates="predictions")
    outcome: Mapped[PredictionOutcome | None] = relationship(back_populates="prediction", uselist=False, cascade="all, delete-orphan")


class PredictionOutcome(Base):
    __tablename__ = "prediction_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"), unique=True, nullable=False)
    actual_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_win: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_abs_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    win_brier_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    prediction: Mapped[Prediction] = relationship(back_populates="outcome")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MonitoringEvent(Base):
    __tablename__ = "monitoring_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    event_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MonitoringOutcome(Base):
    __tablename__ = "monitoring_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    payload_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    outcome_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


Index("idx_predictions_user_created", Prediction.user_id, Prediction.created_at)
Index("idx_predictions_match", Prediction.match_id)
Index("idx_outcomes_prediction_resolved", PredictionOutcome.prediction_id, PredictionOutcome.resolved_at)
Index("idx_audit_user_created_action", AuditLog.user_id, AuditLog.created_at, AuditLog.action)
