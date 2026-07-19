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

# Subconjunto de selecciones con priors plausibles para el fallback sintético.
SYNTH_TEAM_STRENGTHS = {
    "Argentina": (0.75, -0.55),
    "Australia": (0.08, 0.08),
    "Austria": (0.14, 0.04),
    "Belgium": (0.44, -0.22),
    "Brazil": (0.68, -0.48),
    "Cameroon": (0.02, 0.12),
    "Canada": (0.10, 0.10),
    "Chile": (0.05, 0.12),
    "Colombia": (0.26, -0.10),
    "Costa Rica": (-0.02, 0.18),
    "Croatia": (0.38, -0.18),
    "Czech Republic": (0.10, 0.08),
    "Denmark": (0.18, -0.02),
    "Ecuador": (0.12, 0.02),
    "Egypt": (0.02, 0.10),
    "England": (0.62, -0.40),
    "France": (0.72, -0.52),
    "Germany": (0.48, -0.28),
    "Ghana": (0.00, 0.14),
    "Iran": (0.10, 0.06),
    "Italy": (0.40, -0.22),
    "Japan": (0.24, -0.08),
    "Mexico": (0.20, -0.05),
    "Morocco": (0.28, -0.12),
    "Netherlands": (0.50, -0.30),
    "Nigeria": (0.06, 0.12),
    "Norway": (0.10, 0.10),
    "Panama": (-0.05, 0.20),
    "Paraguay": (0.04, 0.12),
    "Peru": (0.06, 0.10),
    "Poland": (0.10, 0.08),
    "Portugal": (0.55, -0.35),
    "Saudi Arabia": (-0.02, 0.18),
    "Scotland": (0.08, 0.12),
    "Senegal": (0.18, -0.03),
    "Serbia": (0.08, 0.10),
    "South Korea": (0.08, 0.10),
    "Spain": (0.60, -0.42),
    "Sweden": (0.08, 0.10),
    "Uruguay": (0.36, -0.16),
    "United States": (0.22, -0.04),
    "Switzerland": (0.16, 0.00),
    "Turkey": (0.14, 0.04),
    "Ukraine": (0.10, 0.08),
    "Wales": (0.06, 0.12),
    "New Zealand": (-0.04, 0.20),
    "Uzbekistan": (0.02, 0.14),
    "Jordan": (-0.02, 0.16),
    # Selecciones del Mundial 2026 que faltaban en el universo del modelo.
    # Priors plausibles según ranking FIFA previo al torneo (nov-2025).
    "Ivory Coast": (0.20, -0.05),
    "Algeria": (0.16, -0.02),
    "Tunisia": (0.06, 0.08),
    "Bosnia and Herzegovina": (0.08, 0.06),
    "Qatar": (0.02, 0.14),
    "Iraq": (0.00, 0.14),
    "DR Congo": (0.08, 0.08),
    "South Africa": (0.02, 0.12),
    "Cape Verde": (-0.02, 0.16),
    "Curacao": (-0.06, 0.20),
    "Haiti": (-0.06, 0.20),
}


def _synthetic(n_matches: int = 4000, seed: int = 42) -> pd.DataFrame:
    """Genera partidos sintéticos con fuerzas latentes -> Poisson realista."""
    rng = np.random.default_rng(seed)
    strength = {
        team: (
            atk + rng.normal(0.0, 0.05),
            # Signo de defensa: el modelo usa lam_visita = exp(atk_a - dfc_local),
            # por lo que defensa ALTA (positiva) => el rival marca MENOS. En los
            # priors, los equipos fuertes traen defensa negativa (buena) por
            # legibilidad, así que la invertimos para que sea consistente.
            -dfc + rng.normal(0.0, 0.05),
        )
        for team, (atk, dfc) in SYNTH_TEAM_STRENGTHS.items()
    }
    home_adv = 0.28

    rows = []
    base = datetime(2018, 1, 1)
    for k in range(n_matches):
        h, a = rng.choice(list(SYNTH_TEAM_STRENGTHS), size=2, replace=False)
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
