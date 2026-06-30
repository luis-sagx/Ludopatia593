"""
Carga de datos de entrenamiento.

Fuente real (gratis): dataset Kaggle "International football results 1872-2024"
  -> CSV con columnas: date, home_team, away_team, home_score, away_score,
     tournament, neutral.
  Descarga: https://www.kaggle.com/datasets/martj42/international-football-results-from-1872-to-2017

Si el CSV no existe, genera un dataset sintético reproducible para que el
pipeline corra de extremo a extremo sin dependencias externas.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
RESULTS_CSV = DATA_DIR / "results.csv"

# Subconjunto de selecciones para el demo sintético (clasificadas/históricas top).
SYNTH_TEAMS = [
    "Argentina", "France", "Brazil", "England", "Spain", "Portugal",
    "Netherlands", "Germany", "Belgium", "Croatia", "Uruguay", "Mexico",
    "USA", "Morocco", "Japan", "Senegal", "Ecuador", "Colombia",
    "Denmark", "Switzerland",
]


def _synthetic(n_matches: int = 4000, seed: int = 42) -> pd.DataFrame:
    """Genera partidos sintéticos con fuerzas latentes -> Poisson realista."""
    rng = np.random.default_rng(seed)
    # fuerza latente por equipo (ataque, defensa)
    strength = {t: (rng.normal(0.2, 0.35), rng.normal(0.2, 0.35)) for t in SYNTH_TEAMS}
    home_adv = 0.28

    rows = []
    base = datetime(2018, 1, 1)
    for k in range(n_matches):
        h, a = rng.choice(SYNTH_TEAMS, size=2, replace=False)
        atk_h, dfc_h = strength[h]
        atk_a, dfc_a = strength[a]
        lam_h = np.exp(atk_h - dfc_a + home_adv)
        lam_a = np.exp(atk_a - dfc_h)
        hg = rng.poisson(lam_h)
        ag = rng.poisson(lam_a)
        date = base + timedelta(days=int(k * 0.6))
        rows.append({
            "date": date.strftime("%Y-%m-%d"),
            "home_team": h,
            "away_team": a,
            "home_score": int(hg),
            "away_score": int(ag),
            "tournament": "Synthetic",
            "neutral": False,
        })
    return pd.DataFrame(rows)


def load_results(path: Path = RESULTS_CSV, min_date: str | None = "2014-01-01") -> pd.DataFrame:
    """
    Carga resultados internacionales. Usa CSV real si existe; si no, sintético.
    Devuelve columnas normalizadas + 'days_ago' para decaimiento temporal.
    """
    if path.exists():
        df = pd.read_csv(path)
        source = "kaggle"
    else:
        df = _synthetic()
        source = "synthetic"

    df["date"] = pd.to_datetime(df["date"])
    if min_date:
        df = df[df["date"] >= pd.Timestamp(min_date)]

    df = df.dropna(subset=["home_score", "away_score"]).copy()
    df["home_score"] = df["home_score"].astype(int)
    df["away_score"] = df["away_score"].astype(int)

    ref = df["date"].max()
    df["days_ago"] = (ref - df["date"]).dt.days
    df.attrs["source"] = source
    return df.reset_index(drop=True)
