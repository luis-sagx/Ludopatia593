"""
Simulación Monte Carlo del torneo para mercados de clasificación y campeón.

Propaga las probabilidades partido-a-partido del modelo Dixon-Coles a través
de la estructura del Mundial (grupos + eliminatorias) miles de veces y cuenta
frecuencias. Cómputo puro, sin datos de pago.
"""
from __future__ import annotations

import numpy as np
from collections import defaultdict

from .dixon_coles import DixonColesModel
from .markets import market_1x2


def _sim_group_match(model: DixonColesModel, h: str, a: str, rng) -> tuple[int, int]:
    """Simula un marcador desde la matriz Dixon-Coles (sede neutral en Mundial)."""
    mat = model.score_matrix(h, a, neutral=True)
    flat = mat.flatten()
    k = rng.choice(len(flat), p=flat)
    m = mat.shape[0]
    return divmod(k, m)


def _knockout_winner(model: DixonColesModel, h: str, a: str, rng) -> str:
    """Gana uno: si empate en 90', se decide por prob condicional (penales ~ 50/50)."""
    probs = market_1x2(model.score_matrix(h, a, neutral=True))
    r = rng.random()
    if r < probs["home"]:
        return h
    if r < probs["home"] + probs["away"]:
        return a
    # empate -> penales 50/50
    return h if rng.random() < 0.5 else a


def simulate_tournament(
    model: DixonColesModel,
    groups: dict[str, list[str]],
    n_sims: int = 20000,
    seed: int = 7,
) -> dict:
    """
    groups: {"A": ["Mexico", "Poland", ...], ...} 4 equipos por grupo.
    Avanzan los 2 primeros de cada grupo a un bracket simple.
    Devuelve probabilidades de: avanzar de grupo, llegar a final, ser campeón.

    NOTA: el bracket cruzado real del Mundial 2026 (48 equipos) es más complejo;
    este motor usa un bracket genérico de 16 sembrados por orden de grupo.
    Marca: ESTIMACIÓN estructural, ajustar cruces al fixture oficial.
    """
    rng = np.random.default_rng(seed)
    champion = defaultdict(int)
    finalist = defaultdict(int)
    advanced = defaultdict(int)

    group_names = list(groups.keys())

    for _ in range(n_sims):
        qualifiers = []
        for g, teams in groups.items():
            pts = dict.fromkeys(teams, 0)
            gd = dict.fromkeys(teams, 0)
            # round-robin
            for i in range(len(teams)):
                for j in range(i + 1, len(teams)):
                    hg, ag = _sim_group_match(model, teams[i], teams[j], rng)
                    if hg > ag:
                        pts[teams[i]] += 3
                    elif ag > hg:
                        pts[teams[j]] += 3
                    else:
                        pts[teams[i]] += 1
                        pts[teams[j]] += 1
                    gd[teams[i]] += hg - ag
                    gd[teams[j]] += ag - hg
            ranked = sorted(teams, key=lambda t: (pts[t], gd[t], rng.random()), reverse=True)
            top2 = ranked[:2]
            for t in top2:
                advanced[t] += 1
            qualifiers.extend(top2)

        # bracket simple por eliminación directa
        bracket = qualifiers[:]
        rng.shuffle(bracket)  # siembra aproximada; marca: no es el cruce oficial
        round_teams = bracket
        final_two = None
        while len(round_teams) > 1:
            nxt = []
            for i in range(0, len(round_teams), 2):
                if i + 1 >= len(round_teams):
                    nxt.append(round_teams[i])
                    continue
                w = _knockout_winner(model, round_teams[i], round_teams[i + 1], rng)
                nxt.append(w)
            if len(round_teams) == 2:
                final_two = round_teams
            round_teams = nxt
        if final_two:
            for t in final_two:
                finalist[t] += 1
        champion[round_teams[0]] += 1

    def to_prob(counter):
        return {t: round(c / n_sims, 4) for t, c in sorted(counter.items(), key=lambda x: -x[1])}

    return {
        "n_sims": n_sims,
        "champion": to_prob(champion),
        "finalist": to_prob(finalist),
        "advance_group": to_prob(advanced),
    }
