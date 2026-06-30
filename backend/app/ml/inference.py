"""
Servicio de inferencia: carga el modelo serializado y sirve predicciones.
Stateless salvo el modelo en memoria. Recarga atómica al promover versión nueva.
"""
from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

from .dixon_coles import DixonColesModel
from .markets import build_match_markets
from .data import DATA_DIR

MODEL_PATH = DATA_DIR / "model.json"


class InferenceService:
    def __init__(self):
        self._lock = RLock()
        self._model: DixonColesModel | None = None
        self.version: str | None = None

    def load(self, path: Path = MODEL_PATH) -> bool:
        if not path.exists():
            return False
        with self._lock:
            self._model = DixonColesModel.from_dict(json.loads(path.read_text()))
            self.version = str(int(path.stat().st_mtime))  # mtime como id de versión simple
        return True

    @property
    def ready(self) -> bool:
        return self._model is not None

    @property
    def teams(self) -> list[str]:
        return self._model.teams if self._model else []

    def predict_match(self, home: str, away: str, neutral: bool = True,
                      market_odds: dict | None = None) -> dict:
        if not self._model:
            raise RuntimeError("modelo no cargado")
        mat = self._model.score_matrix(home, away, neutral=neutral)
        return {
            "model_version": self.version,
            "home_team": home,
            "away_team": away,
            "neutral": neutral,
            "markets": build_match_markets(mat, market_odds=market_odds),
        }

    @property
    def model(self) -> DixonColesModel:
        if not self._model:
            raise RuntimeError("modelo no cargado")
        return self._model


inference = InferenceService()
