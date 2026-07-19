"""
Catálogo de fixtures + predicciones del modelo + simulación de torneo.
Lecturas intensivas -> cacheadas en Redis con TTL.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, or_, func
from sqlalchemy.orm import Session

from ..db.session import get_db
from ..db.models import Fixture
from ..schemas.schemas import FixtureOut
from ..ml.inference import inference
from ..ml.montecarlo import simulate_tournament
from ..core.ratelimit import get_redis
from ..services.api_football import is_real_fixture, normalize_team_name

router = APIRouter(prefix="/v1", tags=["predictions"])

_TOURNEY_CACHE_KEY = "tourney:champion"
_TOURNEY_TTL = 21600  # 6 h: los grupos no cambian, así que se puede cachear largo

# Predicciones batch de partidos por jugar. TTL corto: las cuotas del modelo son
# estables, pero un partido puede pasar a 'finished' (simular/liquidar) y debe
# salir del lote. Se invalida explícitamente al liquidar (ver api/admin.py).
_PRED_CACHE_KEY = "fixtures:predictions"
_PRED_TTL = 300


def _compute_champion(db: Session) -> dict:
    """Simula el torneo (Monte Carlo) a partir de los grupos oficiales cargados.

    Devuelve probabilidades de campeón/finalista/avance. No usa caché: es la
    parte cara; los llamadores deciden cachearla.
    """
    groups: dict[str, list[str]] = {}
    fixtures = db.query(Fixture).order_by(Fixture.kickoff_utc).all()
    real_fixtures = [fx for fx in fixtures if is_real_fixture(fx)]
    selected = real_fixtures or fixtures
    for fx in selected:
        if not fx.stage.startswith("group_"):
            continue
        group_name = fx.stage.split("_", 1)[1].upper()
        bucket = groups.setdefault(group_name, [])
        for team in (fx.home_team, fx.away_team):
            if team in inference.teams and team not in bucket:
                bucket.append(team)

    groups = {k: v for k, v in groups.items() if len(v) == 4}
    if not groups:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "no hay grupos oficiales cargados; sincroniza fixtures del Mundial 2026",
        )

    result = simulate_tournament(inference.model, groups, n_sims=2000)
    result["source"] = "football-data.org" if real_fixtures else "demo"
    result["group_count"] = len(groups)
    return result


def warm_champion_cache(db: Session) -> bool:
    """Precalcula y cachea el ranking de campeón (se llama al sembrar la DB).

    Así la primera visita a la vista "Ganador del Mundial" es instantánea en vez
    de esperar la simulación Monte Carlo. Silencioso si no hay Redis o grupos.
    """
    _r = get_redis()
    if _r is None or not inference.ready:
        return False
    try:
        result = _compute_champion(db)
    except HTTPException:
        return False
    _r.setex(_TOURNEY_CACHE_KEY, _TOURNEY_TTL, json.dumps(result))
    return True


def invalidate_prediction_cache() -> None:
    """Invalida el caché batch de predicciones. Se llama tras liquidar/simular
    para que un fixture recién finalizado deje de exponer cuotas al frontend."""
    _r = get_redis()
    if _r is None:
        return
    try:
        _r.delete(_PRED_CACHE_KEY)
    except Exception:
        pass


def _active_round(db: Session) -> int:
    """Ronda activa: la menor con partidos 'scheduled'. Todo lo <= a ella es
    visible/apostable (jornadas ya jugadas + la actual); las siguientes quedan
    ocultas hasta simular la actual. Si no queda nada por jugar, devuelve un
    valor alto (torneo terminado -> se ve todo)."""
    val = (
        db.query(func.min(Fixture.round_order))
        .filter(Fixture.status == "scheduled")
        .scalar()
    )
    return int(val) if val is not None else 10**9


@router.get("/fixtures", response_model=list[FixtureOut])
def list_fixtures(
    stage: str | None = Query(None, max_length=40),
    db: Session = Depends(get_db),
):
    q = db.query(Fixture)
    real_exists = db.query(Fixture.id).filter(or_(
        Fixture.external_id.like("football-data:%"),
        Fixture.external_id.like("api-football:%"),
    )).first() is not None
    if real_exists:
        q = q.filter(or_(
            Fixture.external_id.like("football-data:%"),
            Fixture.external_id.like("api-football:%"),
        ))
    if stage:
        q = q.filter(Fixture.stage == stage)
    # Desbloqueo progresivo: solo rondas hasta la activa (oculta la eliminatoria
    # futura para no revelar el cuadro completo antes de tiempo).
    q = q.filter(Fixture.round_order <= _active_round(db))
    status_order = case(
        (Fixture.status == "live", 0),
        (Fixture.status == "scheduled", 1),
        else_=2,
    )
    return q.order_by(status_order, Fixture.kickoff_utc).limit(200).all()


@router.get("/fixtures/predictions")
def fixtures_predictions(db: Session = Depends(get_db)):
    """Predicciones (cuotas) de TODOS los partidos no finalizados en UNA sola
    respuesta. Evita el patrón N+1 desde el frontend (una petición por partido
    saturaba el rate limit). Cacheada en Redis con TTL corto.

    Devuelve un mapa { "<fixture_id>": prediccion }.
    """
    if not inference.ready:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "modelo no cargado")

    _r = get_redis()
    if _r is not None:
        cached = _r.get(_PRED_CACHE_KEY)
        if cached:
            return json.loads(cached)

    fixtures = (
        db.query(Fixture)
        .filter(Fixture.status != "finished")
        .filter(Fixture.round_order <= _active_round(db))
        .order_by(Fixture.kickoff_utc)
        .limit(200)
        .all()
    )
    out: dict[str, dict] = {}
    for fx in fixtures:
        try:
            out[str(fx.id)] = inference.predict_match(
                fx.home_team, fx.away_team, neutral=fx.neutral
            )
        except KeyError:
            # Equipo sin datos en el modelo: se omite en vez de fallar todo.
            continue

    if _r is not None:
        _r.setex(_PRED_CACHE_KEY, _PRED_TTL, json.dumps(out))
    return out


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
        return inference.predict_match(
            normalize_team_name(home),
            normalize_team_name(away),
            neutral=neutral,
        )
    except KeyError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"equipo sin datos: {e}")


@router.get("/tournament/champion")
def tournament_champion(db: Session = Depends(get_db)):
    """Probabilidades de campeón/finalista/avance vía Monte Carlo. Cacheado."""
    if not inference.ready:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "modelo no cargado")

    _r = get_redis()
    if _r is not None:
        cached = _r.get(_TOURNEY_CACHE_KEY)
        if cached:
            return json.loads(cached)

    result = _compute_champion(db)

    if _r is not None:
        _r.setex(_TOURNEY_CACHE_KEY, _TOURNEY_TTL, json.dumps(result))
    return result
