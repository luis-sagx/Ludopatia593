"""
Entrena Dixon-Coles y evalúa con validación temporal (walk-forward).

Validación temporal estricta: entrena hasta una fecha de corte, predice los
partidos posteriores. NUNCA k-fold aleatorio -> evita fuga de datos del futuro.

Uso:
    python -m app.ml.train
Genera: data/model.json  (modelo serializado para el servicio de inferencia)
"""
from __future__ import annotations

import json
import numpy as np
from pathlib import Path

from .dixon_coles import DixonColesModel
from .markets import market_1x2
from .calibration import brier_score, log_loss, ranked_probability_score
from .data import load_results, DATA_DIR

MODEL_PATH = DATA_DIR / "model.json"


def _outcome_index(hg: int, ag: int) -> int:
    """0=home win, 1=draw, 2=away win."""
    if hg > ag:
        return 0
    if hg == ag:
        return 1
    return 2


def evaluate_walk_forward(df, n_test: int = 400) -> dict:
    """Entrena con todo menos los últimos n_test partidos; evalúa en esos."""
    df = df.sort_values("date").reset_index(drop=True)
    split = len(df) - n_test
    train_df, test_df = df.iloc[:split], df.iloc[split:]

    model = DixonColesModel()
    model.fit(
        train_df["home_team"].values,
        train_df["away_team"].values,
        train_df["home_score"].values,
        train_df["away_score"].values,
        days_ago=train_df["days_ago"].values,
    )

    probs, outcomes = [], []
    skipped = 0
    for _, row in test_df.iterrows():
        try:
            mat = model.score_matrix(row["home_team"], row["away_team"])
        except KeyError:
            skipped += 1  # equipo no visto en train -> no se puede predecir
            continue
        p = market_1x2(mat)
        probs.append([p["home"], p["draw"], p["away"]])
        outcomes.append(_outcome_index(row["home_score"], row["away_score"]))

    probs = np.array(probs)
    outcomes = np.array(outcomes)

    return {
        "n_train": int(split),
        "n_test_used": int(len(outcomes)),
        "n_skipped_unknown_team": skipped,
        "brier": round(brier_score(probs, outcomes), 4),
        "log_loss": round(log_loss(probs, outcomes), 4),
        "rps": round(ranked_probability_score(probs, outcomes), 4),
        # baseline ingenuo: siempre prob base de clases en train para comparar
    }


def main():
    df = load_results()
    print(f"datos: {len(df)} partidos (fuente: {df.attrs.get('source')})")

    metrics = evaluate_walk_forward(df)
    print("evaluación walk-forward:")
    for k, v in metrics.items():
        print(f"  {k}: {v}")

    # entrena modelo final con TODOS los datos para producción
    model = DixonColesModel()
    model.fit(
        df["home_team"].values,
        df["away_team"].values,
        df["home_score"].values,
        df["away_score"].values,
        days_ago=df["days_ago"].values,
    )
    Path(MODEL_PATH).write_text(json.dumps(model.to_dict()))
    print(f"modelo guardado -> {MODEL_PATH}")
    print(f"home_adv={model.home_adv:.3f}  rho={model.rho:.3f}  equipos={len(model.teams)}")


if __name__ == "__main__":
    main()
