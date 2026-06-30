"""
Modelo Dixon-Coles para predicción de marcadores de fútbol.

Extiende el modelo Poisson bivariante con:
  - Fuerzas de ataque/defensa por equipo.
  - Ventaja de localía.
  - Corrección tau de Dixon-Coles para la dependencia en marcadores bajos
    (0-0, 1-0, 0-1, 1-1), donde el Poisson independiente subestima/sobreestima.
  - Decaimiento temporal exponencial: los partidos recientes pesan más.

Referencia: Dixon & Coles (1997), "Modelling Association Football Scores
and Inefficiencies in the Football Betting Market".
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from scipy.optimize import minimize
from scipy.stats import poisson


def _tau(home_goals: int, away_goals: int, lambda_h: float, lambda_a: float, rho: float) -> float:
    """Factor de corrección Dixon-Coles para marcadores bajos."""
    if home_goals == 0 and away_goals == 0:
        return 1.0 - lambda_h * lambda_a * rho
    if home_goals == 0 and away_goals == 1:
        return 1.0 + lambda_h * rho
    if home_goals == 1 and away_goals == 0:
        return 1.0 + lambda_a * rho
    if home_goals == 1 and away_goals == 1:
        return 1.0 - rho
    return 1.0


@dataclass
class DixonColesModel:
    """Modelo entrenable. Guarda parámetros por equipo + globales."""

    max_goals: int = 10
    xi: float = 0.0018  # tasa de decaimiento temporal (por día). 0 = sin decaimiento.
    teams: list[str] = field(default_factory=list)
    attack: dict[str, float] = field(default_factory=dict)
    defence: dict[str, float] = field(default_factory=dict)
    home_adv: float = 0.0
    rho: float = 0.0
    fitted: bool = False

    # ----- entrenamiento -----
    def fit(
        self,
        home_teams: np.ndarray,
        away_teams: np.ndarray,
        home_goals: np.ndarray,
        away_goals: np.ndarray,
        days_ago: np.ndarray | None = None,
    ) -> "DixonColesModel":
        """
        Ajusta por máxima verosimilitud.

        days_ago: antigüedad de cada partido en días (para decaimiento temporal).
                  Si None, todos los partidos pesan igual.
        """
        self.teams = sorted(set(home_teams) | set(away_teams))
        n = len(self.teams)
        idx = {t: i for i, t in enumerate(self.teams)}

        h_idx = np.array([idx[t] for t in home_teams])
        a_idx = np.array([idx[t] for t in away_teams])
        hg = np.asarray(home_goals, dtype=int)
        ag = np.asarray(away_goals, dtype=int)

        if days_ago is None:
            weights = np.ones(len(hg))
        else:
            weights = np.exp(-self.xi * np.asarray(days_ago, dtype=float))

        # Vector de parámetros: [attack(n), defence(n), home_adv, rho]
        # Restricción de identificabilidad: media de ataques = 0 (se aplica al leer).
        def unpack(params):
            atk = params[:n]
            dfc = params[n : 2 * n]
            home = params[2 * n]
            rho = params[2 * n + 1]
            return atk, dfc, home, rho

        def neg_log_likelihood(params):
            atk, dfc, home, rho = unpack(params)
            # centrar ataque para identificabilidad
            atk = atk - atk.mean()
            lam_h = np.exp(atk[h_idx] - dfc[a_idx] + home)
            lam_a = np.exp(atk[a_idx] - dfc[h_idx])

            ll = (
                poisson.logpmf(hg, lam_h)
                + poisson.logpmf(ag, lam_a)
            )
            # término tau (puede ser <=0 para rho extremo -> clip)
            tau = np.array(
                [_tau(h, a, lh, la, rho) for h, a, lh, la in zip(hg, ag, lam_h, lam_a)]
            )
            tau = np.clip(tau, 1e-10, None)
            ll = ll + np.log(tau)
            return -np.sum(weights * ll)

        x0 = np.concatenate([
            np.zeros(n),          # attack
            np.zeros(n),          # defence
            [0.25],               # home_adv inicial
            [-0.05],              # rho inicial
        ])

        res = minimize(
            neg_log_likelihood,
            x0,
            method="L-BFGS-B",
            bounds=[(-3, 3)] * (2 * n) + [(-1, 1), (-0.2, 0.2)],
            options={"maxiter": 500},
        )

        atk, dfc, home, rho = unpack(res.x)
        atk = atk - atk.mean()
        self.attack = {t: float(atk[i]) for t, i in idx.items()}
        self.defence = {t: float(dfc[i]) for t, i in idx.items()}
        self.home_adv = float(home)
        self.rho = float(rho)
        self.fitted = True
        return self

    # ----- predicción -----
    def _lambdas(self, home: str, away: str, neutral: bool = False) -> tuple[float, float]:
        """Tasas esperadas de gol para local y visitante."""
        if not self.fitted:
            raise RuntimeError("modelo no entrenado")
        for t in (home, away):
            if t not in self.attack:
                raise KeyError(f"equipo desconocido: {t}")
        home_term = 0.0 if neutral else self.home_adv
        lam_h = np.exp(self.attack[home] - self.defence[away] + home_term)
        lam_a = np.exp(self.attack[away] - self.defence[home])
        return float(lam_h), float(lam_a)

    def score_matrix(self, home: str, away: str, neutral: bool = False) -> np.ndarray:
        """
        Matriz P[i,j] = prob de marcador (i goles local, j goles visitante).
        Incluye corrección tau de Dixon-Coles. Normalizada.
        """
        lam_h, lam_a = self._lambdas(home, away, neutral)
        m = self.max_goals + 1
        ph = poisson.pmf(np.arange(m), lam_h)
        pa = poisson.pmf(np.arange(m), lam_a)
        mat = np.outer(ph, pa)

        # corrección tau solo afecta esquina baja
        for i in (0, 1):
            for j in (0, 1):
                mat[i, j] *= _tau(i, j, lam_h, lam_a, self.rho)

        mat = mat / mat.sum()
        return mat

    # ----- serialización -----
    def to_dict(self) -> dict:
        return {
            "max_goals": self.max_goals,
            "xi": self.xi,
            "teams": self.teams,
            "attack": self.attack,
            "defence": self.defence,
            "home_adv": self.home_adv,
            "rho": self.rho,
            "fitted": self.fitted,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DixonColesModel":
        m = cls(max_goals=d["max_goals"], xi=d["xi"])
        m.teams = d["teams"]
        m.attack = d["attack"]
        m.defence = d["defence"]
        m.home_adv = d["home_adv"]
        m.rho = d["rho"]
        m.fitted = d["fitted"]
        return m
