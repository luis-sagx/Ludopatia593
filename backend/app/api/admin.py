"""
Panel administrativo (RBAC admin). Liquidación de fixtures, recarga de modelo,
auditoría. Segregado de las rutas de usuario.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db.session import get_db
from ..db.models import User, Fixture, FixtureStatus, UserPrediction, PredictionStatus, AuditLog
from ..ml.inference import inference
from ..ml.markets import market_1x2, market_over_under, market_btts
from .deps import require_admin
from ..services.api_football import sync_world_cup_fixtures

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin", tags=["admin"])


class ResultIn(BaseModel):
    home_score: int = Field(ge=0, le=30)
    away_score: int = Field(ge=0, le=30)


class SimulateIn(BaseModel):
    """Parámetros para simular el cierre de una tanda de partidos por jugar."""
    count: int | None = Field(default=None, ge=1, le=200, description="cuántos fixtures cerrar (los más próximos)")
    stage: str | None = Field(default=None, max_length=40, description="limitar a una fase, p.ej. group_a")


def _won(market: str, selection: str, hg: int, ag: int) -> bool:
    if market == "1x2":
        res = "home" if hg > ag else "draw" if hg == ag else "away"
        return selection == res
    if market.startswith("ou_"):
        line = float(market.split("_")[1])
        total = hg + ag
        return (selection == "over" and total > line) or (selection == "under" and total < line)
    if market == "btts":
        both = hg > 0 and ag > 0
        return (selection == "yes" and both) or (selection == "no" and not both)
    return False


def _sample_scoreline(fx: Fixture) -> tuple[int, int]:
    """Marcador REALISTA muestreado de la distribución Dixon-Coles del partido.

    La matriz P[i,j] ya incluye la corrección tau y refleja fuerzas de ataque/
    defensa de cada selección, así que los marcadores dominantes son los típicos
    de un Mundial (1-0, 2-1, 1-1, 2-0...). No es aleatorio uniforme: los favoritos
    ganan con más frecuencia, tal como ocurre en la realidad.
    """
    mat = np.asarray(inference.model.score_matrix(fx.home_team, fx.away_team, neutral=fx.neutral), dtype=float)
    flat = mat.ravel()
    total = flat.sum()
    if total <= 0:
        return 0, 0
    idx = int(np.random.choice(flat.size, p=flat / total))
    cols = mat.shape[1]
    return idx // cols, idx % cols


def _apply_result(db: Session, fx: Fixture, hg: int, ag: int, actor_id: int, request_id: str | None = None) -> int:
    """Cierra un fixture con el marcador dado y liquida sus predicciones pendientes.

    Acredita pagos al ganador bajo bloqueo de fila (anti race). Devuelve cuántas
    predicciones se liquidaron. NO hace commit (lo hace el endpoint que llama).
    """
    fx.home_score = hg
    fx.away_score = ag
    fx.status = FixtureStatus.finished

    preds = db.query(UserPrediction).filter(
        UserPrediction.fixture_id == fx.id,
        UserPrediction.status == PredictionStatus.pending,
    ).with_for_update().all()

    settled = 0
    for p in preds:
        if _won(p.market, p.selection, hg, ag):
            payout = int(round(p.stake_points * p.odds_taken))
            p.payout_points = payout
            p.status = PredictionStatus.won
            u = db.query(User).filter(User.id == p.user_id).with_for_update().one()
            u.points_balance += payout
        else:
            p.payout_points = 0
            p.status = PredictionStatus.lost
        p.settled_at = datetime.now(timezone.utc)
        settled += 1

    db.add(AuditLog(
        actor_id=actor_id, action="settle_fixture", resource=f"fixture:{fx.id}",
        detail={"score": f"{hg}-{ag}", "settled": settled, "request_id": request_id},
    ))
    return settled


@router.post("/fixtures/{fixture_id}/result")
def settle_fixture(
    fixture_id: int,
    body: ResultIn,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Registra resultado y liquida todas las predicciones pendientes. Idempotente."""
    fx = db.get(Fixture, fixture_id)
    if not fx:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "fixture no existe")
    # Anti doble-liquidación / manipulación de resultado ya registrado.
    if fx.status == FixtureStatus.finished:
        raise HTTPException(status.HTTP_409_CONFLICT, "fixture ya liquidado")

    settled = _apply_result(db, fx, body.home_score, body.away_score, admin.id, request.state.request_id)
    db.commit()
    return {"fixture_id": fixture_id, "settled": settled}


@router.post("/simulate")
def simulate_results(
    body: SimulateIn,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Simula el CIERRE de los partidos por jugar: genera un marcador realista con
    el modelo, marca los fixtures como finalizados y liquida (gana/pierde) todas
    las apuestas pendientes acreditando los pagos. Pensado para la demo académica.
    """
    if not inference.ready:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "modelo no cargado")

    q = db.query(Fixture).filter(Fixture.status == FixtureStatus.scheduled)
    if body.stage:
        q = q.filter(Fixture.stage == body.stage)
    fixtures = q.order_by(Fixture.kickoff_utc.asc()).all()
    if body.count:
        fixtures = fixtures[: body.count]

    results = []
    total_settled = 0
    for fx in fixtures:
        hg, ag = _sample_scoreline(fx)
        settled = _apply_result(db, fx, hg, ag, admin.id, request.state.request_id)
        total_settled += settled
        results.append({
            "fixture_id": fx.id, "home_team": fx.home_team, "away_team": fx.away_team,
            "score": f"{hg}-{ag}", "settled": settled,
        })
    db.commit()
    return {"simulated": len(results), "settled": total_settled, "results": results}


@router.post("/model/reload")
def reload_model(admin: User = Depends(require_admin)):
    """Recarga atómica del modelo serializado (promoción de versión)."""
    ok = inference.load()
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "model.json no encontrado")
    return {"reloaded": True, "version": inference.version, "teams": len(inference.teams)}


@router.get("/audit")
def audit_tail(
    limit: int = 100,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500)).all()
    return [
        {"id": r.id, "actor_id": r.actor_id, "action": r.action,
         "resource": r.resource, "detail": r.detail, "at": r.created_at}
        for r in rows
    ]


@router.post("/fixtures/sync")
def sync_fixtures(
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        result = sync_world_cup_fixtures(db)
    except Exception:
        # No filtrar detalles internos al cliente; el error queda en el log server-side.
        logger.exception("sync football-data.org falló")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "no se pudo sincronizar fixtures")

    db.add(AuditLog(
        actor_id=admin.id,
        action="sync_fixtures",
        resource="world_cup_2026",
        detail={
            "imported": result.imported,
            "inserted": result.inserted,
            "updated": result.updated,
            "competition_code": result.competition_code,
            "season": result.season,
            "request_id": request.state.request_id,
        },
    ))
    db.commit()
    return {
        "ok": True,
        "imported": result.imported,
        "inserted": result.inserted,
        "updated": result.updated,
        "competition_code": result.competition_code,
        "season": result.season,
    }
