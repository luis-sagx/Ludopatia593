"""Esquemas Pydantic: validación fuerte de entrada/salida (defensa inyección)."""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, ConfigDict


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    # El refresh token ya no viaja en el body -- va en cookie HttpOnly
    # (ver api/auth.py). Solo el access token, que el frontend guarda en
    # memoria (nunca localStorage).
    access_token: str
    token_type: str = "bearer"


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    jti: str
    created_at: datetime
    expires_at: datetime


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    role: str
    points_balance: int


class FixtureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    stage: str
    home_team: str
    away_team: str
    kickoff_utc: datetime
    status: str
    home_score: int | None = None
    away_score: int | None = None


class PredictionIn(BaseModel):
    fixture_id: int
    market: str = Field(max_length=40)
    selection: str = Field(max_length=40)
    stake_points: int = Field(gt=0, le=100000)
    idempotency_key: str = Field(min_length=8, max_length=64)


class PredictionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    fixture_id: int
    market: str
    selection: str
    stake_points: int
    odds_taken: float
    status: str
    payout_points: int | None = None
    created_at: datetime
