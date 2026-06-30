"""
Calibración de probabilidades y métricas de evaluación honestas.

Sin calibración, las probabilidades del modelo pueden estar sistemáticamente
sobre/sub-confiadas. Platt scaling ajusta una logística sobre las probas crudas.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize


class PlattScaler:
    """Calibración Platt multiclase (one-vs-rest) para 1X2."""

    def __init__(self):
        self.a = 1.0
        self.b = 0.0
        self.fitted = False

    def fit(self, probs: np.ndarray, labels: np.ndarray) -> "PlattScaler":
        """
        probs: prob cruda del outcome observado (vector 1D).
        labels: 1 si el outcome ocurrió, 0 si no.
        Ajusta sigmoid(a*logit(p)+b).
        """
        p = np.clip(probs, 1e-6, 1 - 1e-6)
        logit = np.log(p / (1 - p))

        def nll(params):
            a, b = params
            z = a * logit + b
            q = 1 / (1 + np.exp(-z))
            q = np.clip(q, 1e-9, 1 - 1e-9)
            return -np.sum(labels * np.log(q) + (1 - labels) * np.log(1 - q))

        res = minimize(nll, [1.0, 0.0], method="L-BFGS-B")
        self.a, self.b = float(res.x[0]), float(res.x[1])
        self.fitted = True
        return self

    def transform(self, probs: np.ndarray) -> np.ndarray:
        p = np.clip(probs, 1e-6, 1 - 1e-6)
        logit = np.log(p / (1 - p))
        z = self.a * logit + self.b
        return 1 / (1 + np.exp(-z))


# ----- métricas -----
def brier_score(probs: np.ndarray, outcomes: np.ndarray) -> float:
    """
    Brier multiclase. probs: (n, k), outcomes: (n,) índice de clase real.
    Menor es mejor (0 = perfecto).
    """
    n, k = probs.shape
    onehot = np.zeros((n, k))
    onehot[np.arange(n), outcomes] = 1
    return float(np.mean(np.sum((probs - onehot) ** 2, axis=1)))


def log_loss(probs: np.ndarray, outcomes: np.ndarray) -> float:
    """Log-loss multiclase. Penaliza fuerte la confianza errónea."""
    n = len(outcomes)
    p = np.clip(probs[np.arange(n), outcomes], 1e-12, 1.0)
    return float(-np.mean(np.log(p)))


def ranked_probability_score(probs: np.ndarray, outcomes: np.ndarray) -> float:
    """
    RPS — métrica estándar para 1X2 (resultado ordenado home<draw<away).
    Penaliza menos los errores 'cercanos'. Menor es mejor.
    """
    n, k = probs.shape
    onehot = np.zeros((n, k))
    onehot[np.arange(n), outcomes] = 1
    cum_p = np.cumsum(probs, axis=1)
    cum_o = np.cumsum(onehot, axis=1)
    return float(np.mean(np.sum((cum_p - cum_o) ** 2, axis=1) / (k - 1)))
