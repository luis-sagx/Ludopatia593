"""
Panel administrativo (RBAC admin). Liquidación de fixtures, recarga de modelo,
auditoría. Segregado de las rutas de usuario.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db.session import get_db
from ..db.models import User, Fixture, FixtureStatus, UserPrediction, PredictionStatus, AuditLog
from ..ml.inference import inference
from ..ml.markets import market_1x2, market_over_under, market_btts
from .deps import require_admin

router = APIRouter(prefix="/v1/admin", tags=["admin"])


class ResultIn(BaseModel):
    home_score: int = Field(ge=0, le=30)
    away_score: int = Field(ge=0, le=30)


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


@router.post("/fixtures/{fixture_id}/result")
def settle_fixture(
    fixture_id: int,
    body: ResultIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Registra resultado y liquida todas las predicciones pendientes. Idempotente."""
    fx = db.get(Fixture, fixture_id)
    if not fx:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "fixture no existe")

    fx.home_score = body.home_score
    fx.away_score = body.away_score
    fx.status = FixtureStatus.finished

    preds = db.query(UserPrediction).filter(
        UserPrediction.fixture_id == fixture_id,
        UserPrediction.status == PredictionStatus.pending,
    ).with_for_update().all()

    settled = 0
    for p in preds:
        win = _won(p.market, p.selection, body.home_score, body.away_score)
        if win:
            payout = int(round(p.stake_points * p.odds_taken))
            p.payout_points = payout
            p.status = PredictionStatus.won
            # acredita al usuario bajo bloqueo de fila
            u = db.query(User).filter(User.id == p.user_id).with_for_update().one()
            u.points_balance += payout
        else:
            p.payout_points = 0
            p.status = PredictionStatus.lost
        p.settled_at = datetime.now(timezone.utc)
        settled += 1

    db.add(AuditLog(
        actor_id=admin.id, action="settle_fixture", resource=f"fixture:{fixture_id}",
        detail={"score": f"{body.home_score}-{body.away_score}", "settled": settled},
    ))
    db.commit()
    return {"fixture_id": fixture_id, "settled": settled}


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
