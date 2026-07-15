"""
Predicciones del usuario con PUNTOS VIRTUALES (sin dinero real).

Defensas clave (curso software seguro):
  - Cuota tomada del SERVIDOR (re-derivada del modelo), nunca del cliente
    -> imposible manipular odds/payout desde el request.
  - Idempotencia (unique user+key) -> doble-submit/replay no duplica apuesta.
  - Concurrencia: descuento de saldo con bloqueo de fila (SELECT ... FOR UPDATE)
    -> sin race condition / doble gasto de puntos.
  - Solo fixtures 'scheduled' aceptan predicción (no apostar partido en curso/cerrado).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..db.session import get_db
from ..db.models import User, Fixture, FixtureStatus, UserPrediction, AuditLog
from ..schemas.schemas import PredictionIn, PredictionOut
from ..ml.inference import inference
from ..ml.markets import market_1x2, market_over_under, market_btts, fair_odds
from .deps import get_current_user

router = APIRouter(prefix="/v1/bets", tags=["bets"])


def _server_odds(fx: Fixture, market: str, selection: str) -> float:
    """Re-deriva la cuota justa desde el modelo. Fuente única de verdad."""
    mat = inference.model.score_matrix(fx.home_team, fx.away_team, neutral=fx.neutral)
    if market == "1x2":
        probs = market_1x2(mat)
    elif market.startswith("ou_"):
        line = float(market.split("_")[1])
        probs = market_over_under(mat, line)
    elif market == "btts":
        probs = market_btts(mat)
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "mercado no soportado")

    if selection not in probs or selection == "line":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "selección inválida")
    odds = fair_odds(probs[selection])
    if odds is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "outcome sin probabilidad")
    return odds


@router.post("", response_model=PredictionOut, status_code=201)
def place_prediction(
    body: PredictionIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not inference.ready:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "modelo no cargado")

    # idempotencia: si ya existe esa clave para el usuario, devuelve la previa
    existing = db.query(UserPrediction).filter(
        UserPrediction.user_id == user.id,
        UserPrediction.idempotency_key == body.idempotency_key,
    ).first()
    if existing:
        return existing

    fx = db.get(Fixture, body.fixture_id)
    if not fx:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "fixture no existe")
    if fx.status != FixtureStatus.scheduled:
        raise HTTPException(status.HTTP_409_CONFLICT, "fixture no admite predicciones")
    # Defensa en profundidad: aunque el status siga 'scheduled', no aceptar
    # apuestas si el kickoff ya pasó (status desincronizado). Normaliza naive->UTC.
    ko = fx.kickoff_utc
    if ko is not None:
        if ko.tzinfo is None:
            ko = ko.replace(tzinfo=timezone.utc)
        if ko <= datetime.now(timezone.utc):
            raise HTTPException(status.HTTP_409_CONFLICT, "fixture ya inició")

    try:
        odds = _server_odds(fx, body.market, body.selection)
    except KeyError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"equipo sin datos: {e}")

    # bloqueo de fila del usuario para descuento atómico de puntos (anti race)
    locked = db.query(User).filter(User.id == user.id).with_for_update().one()
    if locked.points_balance < body.stake_points:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "puntos insuficientes")
    locked.points_balance -= body.stake_points

    pred = UserPrediction(
        user_id=user.id,
        fixture_id=fx.id,
        market=body.market,
        selection=body.selection,
        stake_points=body.stake_points,
        odds_taken=odds,
        idempotency_key=body.idempotency_key,
    )
    db.add(pred)
    db.add(AuditLog(
        actor_id=user.id, action="place_prediction", resource=f"fixture:{fx.id}",
        detail={
            "market": body.market, "selection": body.selection,
            "stake": body.stake_points, "odds": odds,
            "request_id": request.state.request_id,
        },
    ))
    try:
        db.commit()
    except Exception:
        db.rollback()
        # carrera con idempotency_key duplicada -> devuelve la existente
        existing = db.query(UserPrediction).filter(
            UserPrediction.user_id == user.id,
            UserPrediction.idempotency_key == body.idempotency_key,
        ).first()
        if existing:
            return existing
        raise
    db.refresh(pred)
    return pred


@router.get("", response_model=list[PredictionOut])
def my_predictions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(UserPrediction).filter(
        UserPrediction.user_id == user.id
    ).order_by(UserPrediction.created_at.desc()).limit(200).all()


@router.get("/{pred_id}", response_model=PredictionOut)
def get_prediction(
    pred_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pred = db.get(UserPrediction, pred_id)
    # control IDOR: el recurso debe pertenecer al usuario del token
    if not pred or pred.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no encontrado")
    return pred
