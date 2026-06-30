"""
Ingeniería de features para la capa ML (GBM).

Features SIN fuga de datos: cada partido se describe solo con información
disponible ANTES del kickoff (forma previa, ELO previo, descanso). El ELO se
calcula de forma incremental recorriendo el histórico en orden cronológico.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ELO_BASE = 1500.0
ELO_K = 30.0
ELO_HOME_ADV = 65.0  # puntos ELO de ventaja de localía


def _expected(elo_a: float, elo_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Recibe partidos ordenables por fecha con columnas:
      date, home_team, away_team, home_score, away_score, neutral.
    Devuelve un DataFrame con features pre-partido + outcome (0 home,1 draw,2 away).
    """
    df = df.sort_values("date").reset_index(drop=True)

    elo: dict[str, float] = {}
    last5: dict[str, list[int]] = {}      # puntos recientes (3/1/0)
    last_date: dict[str, pd.Timestamp] = {}

    rows = []
    for _, m in df.iterrows():
        h, a = m["home_team"], m["away_team"]
        eh = elo.get(h, ELO_BASE)
        ea = elo.get(a, ELO_BASE)
        neutral = bool(m.get("neutral", False))
        home_field = 0.0 if neutral else ELO_HOME_ADV

        def form(team):
            pts = last5.get(team, [])
            return sum(pts[-5:]) / (3 * max(len(pts[-5:]), 1))

        def rest(team, d):
            ld = last_date.get(team)
            return (d - ld).days if ld is not None else 30

        feat = {
            "elo_diff": (eh + home_field) - ea,
            "elo_home": eh,
            "elo_away": ea,
            "form_home": form(h),
            "form_away": form(a),
            "rest_home": min(rest(h, m["date"]), 60),
            "rest_away": min(rest(a, m["date"]), 60),
            "neutral": int(neutral),
            "outcome": 0 if m["home_score"] > m["away_score"] else (1 if m["home_score"] == m["away_score"] else 2),
        }
        rows.append(feat)

        # actualiza ELO tras el partido (post-hoc, no entra como feature de este)
        exp_h = _expected(eh + home_field, ea)
        if m["home_score"] > m["away_score"]:
            sh, ph, pa = 1.0, 3, 0
        elif m["home_score"] == m["away_score"]:
            sh, ph, pa = 0.5, 1, 1
        else:
            sh, ph, pa = 0.0, 0, 3
        elo[h] = eh + ELO_K * (sh - exp_h)
        elo[a] = ea + ELO_K * ((1 - sh) - (1 - exp_h))
        last5.setdefault(h, []).append(ph)
        last5.setdefault(a, []).append(pa)
        last_date[h] = m["date"]
        last_date[a] = m["date"]

    out = pd.DataFrame(rows)
    out["current_elo_snapshot"] = out.index.map(lambda i: None)  # placeholder
    # guarda el ELO final por equipo como atributo para inferencia futura
    out.attrs["final_elo"] = elo
    return out


FEATURE_COLS = ["elo_diff", "elo_home", "elo_away", "form_home", "form_away",
                "rest_home", "rest_away", "neutral"]
