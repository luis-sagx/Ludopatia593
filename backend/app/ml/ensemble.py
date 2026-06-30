"""
Ensamble: blend Dixon-Coles (estructura de marcador) + GBM (señal de features).

GBM = HistGradientBoostingClassifier (sklearn) sobre ELO/forma/descanso.
Predicción final 1X2 = w * dixon_coles + (1-w) * gbm, luego renormaliza.
El blend mejora calibración y reduce varianza frente a cualquiera solo.

Regularización anti-overfitting: profundidad/hojas limitadas + early stopping
con validación temporal interna.
"""
from __future__ import annotations

import json
import numpy as np
from pathlib import Path
from sklearn.ensemble import HistGradientBoostingClassifier

from .features import FEATURE_COLS, build_features, ELO_BASE, ELO_HOME_ADV
from .data import DATA_DIR

GBM_PATH = DATA_DIR / "gbm.json"  # guardamos metadata + ELO; el modelo se reentrena rápido


class EnsembleGBM:
    def __init__(self, weight_dc: float = 0.6):
        self.weight_dc = weight_dc
        self.clf: HistGradientBoostingClassifier | None = None
        self.final_elo: dict[str, float] = {}

    def fit(self, df) -> dict:
        feats = build_features(df)
        self.final_elo = feats.attrs["final_elo"]
        X = feats[FEATURE_COLS].values
        y = feats["outcome"].values

        self.clf = HistGradientBoostingClassifier(
            max_depth=3,              # poco profundo -> regulariza
            max_leaf_nodes=15,
            learning_rate=0.05,
            l2_regularization=1.0,
            max_iter=300,
            early_stopping=True,      # corta cuando deja de mejorar
            validation_fraction=0.15,
            random_state=42,
        )
        self.clf.fit(X, y)
        return {"n": len(y), "classes": list(self.clf.classes_)}

    def _gbm_probs(self, elo_h, elo_a, form_h, form_a, rest_h, rest_a, neutral) -> np.ndarray:
        home_field = 0.0 if neutral else ELO_HOME_ADV
        x = np.array([[
            (elo_h + home_field) - elo_a, elo_h, elo_a,
            form_h, form_a, rest_h, rest_a, int(neutral),
        ]])
        p = self.clf.predict_proba(x)[0]
        # alinea a [home, draw, away] según clases del modelo
        out = np.zeros(3)
        for cls, prob in zip(self.clf.classes_, p):
            out[int(cls)] = prob
        return out

    def blend_1x2(self, dc_probs: dict, home: str, away: str, neutral: bool = True) -> dict:
        """Combina probabilidades 1X2 de Dixon-Coles con las del GBM."""
        if self.clf is None:
            return dc_probs
        eh = self.final_elo.get(home, ELO_BASE)
        ea = self.final_elo.get(away, ELO_BASE)
        gbm = self._gbm_probs(eh, ea, 0.5, 0.5, 7, 7, neutral)  # forma neutra sin histórico vivo
        dc = np.array([dc_probs["home"], dc_probs["draw"], dc_probs["away"]])
        blend = self.weight_dc * dc + (1 - self.weight_dc) * gbm
        blend = blend / blend.sum()
        return {"home": float(blend[0]), "draw": float(blend[1]), "away": float(blend[2])}

    def save_meta(self):
        GBM_PATH.write_text(json.dumps({"weight_dc": self.weight_dc, "final_elo": self.final_elo}))
