"""Leaderboard y rendimiento del usuario (ROI, hit-rate en puntos virtuales)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from ..db.session import get_db
from ..db.models import User, UserPrediction, PredictionStatus
from .deps import get_current_user

router = APIRouter(prefix="/v1", tags=["leaderboard"])


@router.get("/leaderboard")
def leaderboard(db: Session = Depends(get_db)):
    """Top 50 por saldo de puntos."""
    rows = db.query(User.id, User.email, User.points_balance).order_by(
        User.points_balance.desc()
    ).limit(50).all()
    return [
        {"rank": i + 1, "user_id": r.id,
         "email": r.email.split("@")[0] + "@…",  # ofusca PII en tablero público
         "points": r.points_balance}
        for i, r in enumerate(rows)
    ]


@router.get("/me/performance")
def my_performance(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(
        func.count(UserPrediction.id),
        func.coalesce(func.sum(UserPrediction.stake_points), 0),
        func.coalesce(func.sum(UserPrediction.payout_points), 0),
        func.coalesce(func.sum(case((UserPrediction.status == PredictionStatus.won, 1), else_=0)), 0),
        func.coalesce(func.sum(case((UserPrediction.status != PredictionStatus.pending, 1), else_=0)), 0),
    ).filter(UserPrediction.user_id == user.id).one()

    total, staked, returned, won, settled = q
    roi = round((returned - staked) / staked, 4) if staked else 0.0
    hit_rate = round(won / settled, 4) if settled else 0.0
    return {
        "total_predictions": total,
        "settled": settled,
        "won": won,
        "hit_rate": hit_rate,
        "points_staked": int(staked),
        "points_returned": int(returned),
        "roi": roi,
        "points_balance": user.points_balance,
    }
