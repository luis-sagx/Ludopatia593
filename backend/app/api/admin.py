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
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.ratelimit import rate_limit_dep
from ..db.session import get_db
from ..db.models import User, Role, Fixture, FixtureStatus, UserPrediction, PredictionStatus, AuditLog
from ..ml.inference import inference
from ..ml.markets import market_1x2, market_over_under, market_btts
from .predictions import invalidate_prediction_cache
from .deps import require_admin
from ..services.api_football import sync_world_cup_fixtures
from ..seed import future_kickoff

logger = logging.getLogger(__name__)

# Bankroll virtual inicial (coincide con el default de User.points_balance). Al
# reiniciar el torneo cada usuario vuelve a este saldo.
STARTING_BALANCE = 1000

# Límite a nivel de router: cubre TODAS las rutas admin (actuales y futuras)
# con una sola línea -- defensa en profundidad, RBAC ya es el control primario.
router = APIRouter(
    prefix="/v1/admin", tags=["admin"],
    dependencies=[Depends(rate_limit_dep("admin", settings.admin_rate_limit_per_min))],
)


class ResultIn(BaseModel):
    home_score: int = Field(ge=0, le=30)
    away_score: int = Field(ge=0, le=30)


class SimulateIn(BaseModel):
    """Parámetros para simular el cierre de una tanda de partidos por jugar.

    Por defecto (sin parámetros) juega la SIGUIENTE JORNADA/RONDA completa: los
    partidos de la ronda activa más temprana. Al terminarla, la siguiente ronda
    se desbloquea (desbloqueo progresivo, como un mundial real). Los parámetros
    count/stage permiten un cierre manual más granular desde el panel.
    """
    count: int | None = Field(default=None, ge=1, le=200, description="cuántos fixtures cerrar (los más próximos)")
    stage: str | None = Field(default=None, max_length=40, description="limitar a una fase, p.ej. group_a")


ROUND_LABELS = {
    1: "Jornada 1 (grupos)", 2: "Jornada 2 (grupos)", 3: "Jornada 3 (grupos)",
    4: "Dieciseisavos de final", 5: "Octavos de final", 6: "Cuartos de final",
    7: "Semifinales", 8: "Partido por el 3.º puesto", 9: "Final",
}


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


def _resolve_scoreline(fx: Fixture) -> tuple[int, int]:
    """Marcador con el que se cierra un fixture al simular la jornada.

    Si el fixture tiene guardado su resultado REAL del Mundial 2026
    (result_home/away_score), se usa ese marcador verídico para que la demo
    revele los resultados reales al avanzar el torneo. Solo cuando no se conoce
    (p.ej. final y tercer puesto, aún por disputarse) se muestrea del modelo.
    """
    if fx.result_home_score is not None and fx.result_away_score is not None:
        return fx.result_home_score, fx.result_away_score
    return _sample_scoreline(fx)


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
    invalidate_prediction_cache()
    return {"fixture_id": fixture_id, "settled": settled}


@router.post("/reset-tournament")
def reset_tournament(
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Reinicia el torneo DESDE CERO (primer partido).

    - Borra todas las apuestas/predicciones de todos los usuarios.
    - Devuelve a cada usuario NO admin el bankroll inicial.
    - Vuelve todos los fixtures a 'scheduled', limpia el marcador en vivo y
      reprograma sus kickoffs a futuro (conservando el resultado real oculto en
      result_home/away_score para revelarlo al simular). Así los usuarios apuestan
      desde la jornada 1 y el admin va avanzando ronda a ronda.

    Operación destructiva pero acotada al estado del juego: NO borra cuentas ni
    la bitácora de auditoría. Protegida por RBAC admin + rate limit del router.
    """
    now = datetime.now(timezone.utc)

    deleted_preds = db.query(UserPrediction).delete(synchronize_session=False)
    users_reset = (
        db.query(User)
        .filter(User.role == Role.user)
        .update({User.points_balance: STARTING_BALANCE}, synchronize_session=False)
    )

    fixtures = db.query(Fixture).order_by(Fixture.round_order, Fixture.id).all()
    for seq, fx in enumerate(fixtures):
        fx.status = FixtureStatus.scheduled
        fx.home_score = None
        fx.away_score = None
        fx.kickoff_utc = future_kickoff(now, fx.round_order, seq)

    db.add(AuditLog(
        actor_id=admin.id, action="reset_tournament", resource="tournament",
        detail={
            "predictions_deleted": deleted_preds,
            "users_reset": users_reset,
            "fixtures_reset": len(fixtures),
            "request_id": request.state.request_id,
        },
    ))
    db.commit()
    invalidate_prediction_cache()
    return {
        "ok": True,
        "predictions_deleted": deleted_preds,
        "users_reset": users_reset,
        "fixtures_reset": len(fixtures),
    }


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
    played_round = None
    if body.stage:
        q = q.filter(Fixture.stage == body.stage)
        fixtures = q.order_by(Fixture.kickoff_utc.asc()).all()
        if body.count:
            fixtures = fixtures[: body.count]
    elif body.count:
        fixtures = q.order_by(Fixture.kickoff_utc.asc()).all()[: body.count]
    else:
        # Por defecto: juega la SIGUIENTE JORNADA/RONDA completa (desbloqueo
        # progresivo). La ronda activa = la menor round_order aún 'scheduled'.
        played_round = (
            db.query(func.min(Fixture.round_order))
            .filter(Fixture.status == FixtureStatus.scheduled)
            .scalar()
        )
        if played_round is None:
            return {"simulated": 0, "settled": 0, "round": None, "round_label": None,
                    "tournament_over": True, "results": []}
        played_round = int(played_round)
        fixtures = (
            q.filter(Fixture.round_order == played_round)
            .order_by(Fixture.kickoff_utc.asc())
            .all()
        )

    results = []
    total_settled = 0
    for fx in fixtures:
        hg, ag = _resolve_scoreline(fx)
        settled = _apply_result(db, fx, hg, ag, admin.id, request.state.request_id)
        total_settled += settled
        results.append({
            "fixture_id": fx.id, "home_team": fx.home_team, "away_team": fx.away_team,
            "score": f"{hg}-{ag}", "settled": settled,
        })
    db.commit()
    invalidate_prediction_cache()
    # ¿queda algo por jugar tras esta ronda?
    remaining = (
        db.query(func.min(Fixture.round_order))
        .filter(Fixture.status == FixtureStatus.scheduled)
        .scalar()
    )
    return {
        "simulated": len(results), "settled": total_settled,
        "round": played_round,
        "round_label": ROUND_LABELS.get(played_round) if played_round else None,
        "tournament_over": remaining is None,
        "results": results,
    }


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
