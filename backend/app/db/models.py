"""
Modelo de datos. Sin dinero real: las predicciones usan PUNTOS VIRTUALES.
Trazabilidad vía AuditLog y stake/payout en puntos sobre UserPrediction.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    String, Integer, Float, Boolean, DateTime, ForeignKey, Enum, JSON,
    UniqueConstraint, Index, CheckConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, enum.Enum):
    user = "user"
    admin = "admin"


class FixtureStatus(str, enum.Enum):
    scheduled = "scheduled"
    live = "live"
    finished = "finished"


class PredictionStatus(str, enum.Enum):
    pending = "pending"
    won = "won"
    lost = "lost"
    void = "void"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # Red de seguridad a nivel DB contra saldos negativos por bugs de liquidación.
        CheckConstraint("points_balance >= 0", name="ck_users_balance_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.user)
    points_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)  # bankroll virtual inicial
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    predictions: Mapped[list["UserPrediction"]] = relationship(back_populates="user")


class RefreshToken(Base):
    """Permite revocación/rotación de refresh tokens (defensa robo de sesión)."""
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    fifa_code: Mapped[str | None] = mapped_column(String(3))
    elo: Mapped[float | None] = mapped_column(Float)


class Fixture(Base):
    __tablename__ = "fixtures"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String(40), unique=True)  # id proveedor externo
    stage: Mapped[str] = mapped_column(String(40))  # group_a, round_16, ...
    home_team: Mapped[str] = mapped_column(String(100))
    away_team: Mapped[str] = mapped_column(String(100))
    kickoff_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    neutral: Mapped[bool] = mapped_column(Boolean, default=True)  # Mundial = sede neutral
    status: Mapped[FixtureStatus] = mapped_column(Enum(FixtureStatus), default=FixtureStatus.scheduled)
    home_score: Mapped[int | None] = mapped_column(Integer)
    away_score: Mapped[int | None] = mapped_column(Integer)
    # Orden global de ronda para el DESBLOQUEO PROGRESIVO (realismo): 1-3 jornadas
    # de grupos, 4=dieciseisavos, 5=octavos, 6=cuartos, 7=semis, 8=3er puesto,
    # 9=final. Solo se muestran/apuestan las rondas hasta la activa (la menor con
    # partidos 'scheduled'); las siguientes se revelan al simular la anterior.
    round_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    # Resultado REAL del Mundial 2026, oculto mientras el partido está 'scheduled'
    # (no se expone en FixtureOut). Al "jugar"/simular la jornada desde el panel
    # admin, se usa este marcador verídico en vez de uno aleatorio: la demo
    # arranca al inicio del torneo y va revelando los resultados reales.
    result_home_score: Mapped[int | None] = mapped_column(Integer)
    result_away_score: Mapped[int | None] = mapped_column(Integer)


class UserPrediction(Base):
    """
    Predicción del usuario con puntos virtuales.
    idempotency_key evita doble-submit (replay). Único por usuario.
    """
    __tablename__ = "user_predictions"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_user_idem"),
        Index("ix_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), index=True)
    market: Mapped[str] = mapped_column(String(40))   # "1x2", "ou_2.5", ...
    selection: Mapped[str] = mapped_column(String(40))  # "home", "over", ...
    stake_points: Mapped[int] = mapped_column(Integer)
    odds_taken: Mapped[float] = mapped_column(Float)    # cuota justa al momento (server-side)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    status: Mapped[PredictionStatus] = mapped_column(Enum(PredictionStatus), default=PredictionStatus.pending)
    payout_points: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="predictions")


class AuditLog(Base):
    """Bitácora inmutable (append-only) sin secretos/PII sensible."""
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(60))
    resource: Mapped[str] = mapped_column(String(120))
    detail: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
