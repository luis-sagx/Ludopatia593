"""
Deriva todos los mercados desde la matriz de marcadores Dixon-Coles.

Una sola matriz P[i,j] alimenta de forma consistente: 1X2, over/under,
ambos marcan (BTTS), marcador exacto y cuotas justas + valor esperado.
"""
from __future__ import annotations

import numpy as np


def market_1x2(score_matrix: np.ndarray) -> dict[str, float]:
    """Prob de victoria local / empate / victoria visitante."""
    home = float(np.tril(score_matrix, -1).sum())  # i > j
    draw = float(np.trace(score_matrix))            # i == j
    away = float(np.triu(score_matrix, 1).sum())    # i < j
    return {"home": home, "draw": draw, "away": away}


def market_over_under(score_matrix: np.ndarray, line: float = 2.5) -> dict[str, float]:
    """Prob de total de goles over/under una línea (típicamente x.5)."""
    m = score_matrix.shape[0]
    totals = np.add.outer(np.arange(m), np.arange(m))
    over = float(score_matrix[totals > line].sum())
    under = float(score_matrix[totals < line].sum())
    return {"over": over, "under": under, "line": line}


def market_btts(score_matrix: np.ndarray) -> dict[str, float]:
    """Ambos equipos marcan (sí/no)."""
    yes = float(score_matrix[1:, 1:].sum())
    return {"yes": yes, "no": 1.0 - yes}


def top_exact_scores(score_matrix: np.ndarray, k: int = 5) -> list[dict]:
    """Los k marcadores exactos más probables."""
    m = score_matrix.shape[0]
    flat = [
        {"home_goals": i, "away_goals": j, "prob": float(score_matrix[i, j])}
        for i in range(m)
        for j in range(m)
    ]
    flat.sort(key=lambda x: x["prob"], reverse=True)
    return flat[:k]


def fair_odds(prob: float) -> float | None:
    """Cuota decimal justa = 1/p. None si prob ~ 0."""
    return round(1.0 / prob, 3) if prob > 1e-9 else None


def expected_value(model_prob: float, market_odds: float) -> float:
    """
    EV por unidad apostada frente a una cuota de mercado.
    EV = p*(cuota-1) - (1-p). EV>0 => el modelo cree que hay valor.
    """
    return round(model_prob * (market_odds - 1.0) - (1.0 - model_prob), 4)


def build_match_markets(
    score_matrix: np.ndarray,
    ou_lines: tuple[float, ...] = (1.5, 2.5, 3.5),
    market_odds: dict | None = None,
) -> dict:
    """
    Paquete completo de mercados de un partido, con cuotas justas y,
    si se pasan cuotas de mercado, el EV correspondiente.

    market_odds esperado (opcional): {"1x2": {"home": 2.1, ...}, ...}
    """
    one_x_two = market_1x2(score_matrix)
    ou = {f"ou_{ln}": market_over_under(score_matrix, ln) for ln in ou_lines}
    btts = market_btts(score_matrix)

    def with_odds(probs: dict, odds_key: str) -> dict:
        out = {}
        for outcome, p in probs.items():
            if outcome == "line":
                out[outcome] = p
                continue
            entry = {"prob": round(p, 4), "fair_odds": fair_odds(p)}
            if market_odds and odds_key in market_odds:
                mo = market_odds[odds_key].get(outcome)
                if mo:
                    entry["market_odds"] = mo
                    entry["ev"] = expected_value(p, mo)
            out[outcome] = entry
        return out

    return {
        "1x2": with_odds(one_x_two, "1x2"),
        "over_under": {k: with_odds(v, k) for k, v in ou.items()},
        "btts": with_odds(btts, "btts"),
        "exact_scores": top_exact_scores(score_matrix, 5),
    }
