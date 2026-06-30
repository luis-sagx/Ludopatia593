"""
Compara Dixon-Coles solo vs ensamble (DC + GBM) con validación temporal.
Justifica (o no) el blend con métricas honestas. Uso: python -m app.ml.eval_ensemble
"""
from __future__ import annotations

import numpy as np

from .data import load_results
from .dixon_coles import DixonColesModel
from .markets import market_1x2
from .ensemble import EnsembleGBM
from .features import build_features, FEATURE_COLS, ELO_HOME_ADV, ELO_BASE
from .calibration import brier_score, log_loss, ranked_probability_score


def _outcome(hg, ag):
    return 0 if hg > ag else (1 if hg == ag else 2)


def main():
    df = load_results().sort_values("date").reset_index(drop=True)
    n_test = 400
    split = len(df) - n_test
    train_df, test_df = df.iloc[:split], df.iloc[split:]

    # Dixon-Coles
    dc = DixonColesModel().fit(
        train_df["home_team"].values, train_df["away_team"].values,
        train_df["home_score"].values, train_df["away_score"].values,
        days_ago=train_df["days_ago"].values,
    )
    # Ensamble (GBM entrenado sobre features del train)
    ens = EnsembleGBM(weight_dc=0.6)
    ens.fit(train_df)

    dc_probs, ens_probs, outcomes = [], [], []
    for _, r in test_df.iterrows():
        try:
            mat = dc.score_matrix(r["home_team"], r["away_team"])
        except KeyError:
            continue
        p = market_1x2(mat)
        dc_p = [p["home"], p["draw"], p["away"]]
        bl = ens.blend_1x2(p, r["home_team"], r["away_team"], neutral=bool(r.get("neutral", False)))
        dc_probs.append(dc_p)
        ens_probs.append([bl["home"], bl["draw"], bl["away"]])
        outcomes.append(_outcome(r["home_score"], r["away_score"]))

    dc_probs = np.array(dc_probs); ens_probs = np.array(ens_probs); outcomes = np.array(outcomes)

    def report(name, P):
        print(f"{name:18s} brier={brier_score(P, outcomes):.4f}  "
              f"logloss={log_loss(P, outcomes):.4f}  rps={ranked_probability_score(P, outcomes):.4f}")

    print(f"n_test={len(outcomes)}")
    report("Dixon-Coles", dc_probs)
    report("Ensamble DC+GBM", ens_probs)


if __name__ == "__main__":
    main()
