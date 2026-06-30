"""
Catálogo de fixtures + predicciones del modelo + simulación de torneo.
Lecturas intensivas -> cacheadas en Redis con TTL.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..db.session import get_db
from ..db.models import Fixture
from ..schemas.schemas import FixtureOut
from ..ml.inference import inference
from ..ml.montecarlo import simulate_tournament
from ..core.ratelimit import _r, _redis_ok

router = APIRouter(prefix="/v1", tags=["predictions"])

_TOURNEY_CACHE_KEY = "tourney:champion"
_TOURNEY_TTL = 3600


@router.get("/fixtures", response_model=list[FixtureOut])
def list_fixtures(
    stage: str | None = Query(None, max_length=40),
    db: Session = Depends(get_db),
):
    q = db.query(Fixture)
    if stage:
        q = q.filter(Fixture.stage == stage)
    return q.order_by(Fixture.kickoff_utc).limit(200).all()


@router.get("/fixtures/{fixture_id}/prediction")
def fixture_prediction(fixture_id: int, db: Session = Depends(get_db)):
    if not inference.ready:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "modelo no cargado")
    fx = db.get(Fixture, fixture_id)
    if not fx:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "fixture no existe")
    try:
        return inference.predict_match(fx.home_team, fx.away_team, neutral=fx.neutral)
    except KeyError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"equipo sin datos: {e}")


@router.get("/predict")
def predict_adhoc(
    home: str = Query(max_length=100),
    away: str = Query(max_length=100),
    neutral: bool = True,
):
    """Predicción ad-hoc entre dos selecciones conocidas por el modelo."""
    if not inference.ready:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "modelo no cargado")
    try:
        return inference.predict_match(home, away, neutral=neutral)
    except KeyError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"equipo sin datos: {e}")


@router.get("/tournament/champion")
def tournament_champion():
    """Probabilidades de campeón/finalista/avance vía Monte Carlo. Cacheado."""
    if not inference.ready:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "modelo no cargado")

    if _redis_ok and _r is not None:
        cached = _r.get(_TOURNEY_CACHE_KEY)
        if cached:
            return json.loads(cached)

    teams = inference.teams
    if len(teams) < 8:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "insuficientes equipos")
    # demo: arma grupos de 4 con los equipos disponibles
    groups = {}
    for i in range(0, len(teams) - len(teams) % 4, 4):
        groups[chr(ord("A") + i // 4)] = teams[i : i + 4]
    result = simulate_tournament(inference.model, groups, n_sims=5000)

    if _redis_ok and _r is not None:
        _r.setex(_TOURNEY_CACHE_KEY, _TOURNEY_TTL, json.dumps(result))
    return result
