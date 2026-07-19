"""
Inicializa la base: crea tablas, siembra equipos/fixtures de demo y un admin.
La contraseña admin se toma de ADMIN_PASSWORD (entorno), nunca hardcodeada.

Uso: python -m app.seed
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta

from .db.session import Base, engine, SessionLocal
from .db.models import (
    User, Team, Fixture, FixtureStatus, Role,
    UserPrediction, PredictionStatus,
)
from .core.security import hash_password
from .core.config import settings
from .ml.inference import inference
from .services.api_football import sync_world_cup_fixtures

# ---------------------------------------------------------------------------
# Fase de grupos oficial del Mundial FIFA 2026 (formato 48 equipos, 12 grupos).
# Datos REALES verificados (fuente: Wikipedia, "2026 FIFA World Cup"): las 3
# jornadas de cada grupo con sus marcadores reales (todas 'finished'). Las
# eliminatorias reales se cargan aparte (KNOCKOUT_FIXTURES). Esto mantiene la
# simulación de campeón (Monte Carlo) sobre los grupos ya disputados.
# ---------------------------------------------------------------------------
GROUPS_2026: dict[str, list[str]] = {
    "a": ["Mexico", "South Africa", "South Korea", "Czech Republic"],
    "b": ["Canada", "Switzerland", "Bosnia and Herzegovina", "Qatar"],
    "c": ["Brazil", "Morocco", "Scotland", "Haiti"],
    "d": ["United States", "Australia", "Paraguay", "Turkey"],
    "e": ["Germany", "Ivory Coast", "Ecuador", "Curacao"],
    "f": ["Netherlands", "Japan", "Sweden", "Tunisia"],
    "g": ["Belgium", "Egypt", "Iran", "New Zealand"],
    "h": ["Spain", "Cape Verde", "Uruguay", "Saudi Arabia"],
    "i": ["France", "Norway", "Senegal", "Iraq"],
    "j": ["Argentina", "Austria", "Algeria", "Jordan"],
    "k": ["Portugal", "Colombia", "DR Congo", "Uzbekistan"],
    "l": ["England", "Croatia", "Ghana", "Panama"],
}

# Fixtures REALES de la fase de grupos del Mundial 2026 (fuente: Wikipedia,
# "2026 FIFA World Cup"). Las 3 jornadas con sus marcadores reales verificados;
# todas quedan 'finished'. Cada tupla:
#   (jornada, local, visitante, goles_local, goles_visitante)
REAL_FIXTURES: dict[str, list[tuple]] = {
    "a": [
        (1, "Mexico", "South Africa", 2, 0),
        (1, "South Korea", "Czech Republic", 2, 1),
        (2, "Czech Republic", "South Africa", 1, 1),
        (2, "Mexico", "South Korea", 1, 0),
        (3, "Czech Republic", "Mexico", 0, 3),
        (3, "South Africa", "South Korea", 1, 0),
    ],
    "b": [
        (1, "Canada", "Bosnia and Herzegovina", 1, 1),
        (1, "Qatar", "Switzerland", 1, 1),
        (2, "Switzerland", "Bosnia and Herzegovina", 4, 1),
        (2, "Canada", "Qatar", 6, 0),
        (3, "Switzerland", "Canada", 2, 1),
        (3, "Bosnia and Herzegovina", "Qatar", 3, 1),
    ],
    "c": [
        (1, "Brazil", "Morocco", 1, 1),
        (1, "Haiti", "Scotland", 0, 1),
        (2, "Scotland", "Morocco", 0, 1),
        (2, "Brazil", "Haiti", 3, 0),
        (3, "Scotland", "Brazil", 0, 3),
        (3, "Morocco", "Haiti", 4, 2),
    ],
    "d": [
        (1, "United States", "Paraguay", 4, 1),
        (1, "Australia", "Turkey", 2, 0),
        (2, "United States", "Australia", 2, 0),
        (2, "Turkey", "Paraguay", 0, 1),
        (3, "Turkey", "United States", 3, 2),
        (3, "Paraguay", "Australia", 0, 0),
    ],
    "e": [
        (1, "Germany", "Curacao", 7, 1),
        (1, "Ivory Coast", "Ecuador", 1, 0),
        (2, "Germany", "Ivory Coast", 2, 1),
        (2, "Ecuador", "Curacao", 0, 0),
        (3, "Curacao", "Ivory Coast", 0, 2),
        (3, "Ecuador", "Germany", 2, 1),
    ],
    "f": [
        (1, "Netherlands", "Japan", 2, 2),
        (1, "Sweden", "Tunisia", 5, 1),
        (2, "Netherlands", "Sweden", 5, 1),
        (2, "Tunisia", "Japan", 0, 4),
        (3, "Japan", "Sweden", 1, 1),
        (3, "Tunisia", "Netherlands", 1, 3),
    ],
    "g": [
        (1, "Belgium", "Egypt", 1, 1),
        (1, "Iran", "New Zealand", 2, 2),
        (2, "Belgium", "Iran", 0, 0),
        (2, "New Zealand", "Egypt", 1, 3),
        (3, "Egypt", "Iran", 1, 1),
        (3, "New Zealand", "Belgium", 1, 5),
    ],
    "h": [
        (1, "Spain", "Cape Verde", 0, 0),
        (1, "Saudi Arabia", "Uruguay", 1, 1),
        (2, "Spain", "Saudi Arabia", 4, 0),
        (2, "Uruguay", "Cape Verde", 2, 2),
        (3, "Cape Verde", "Saudi Arabia", 0, 0),
        (3, "Uruguay", "Spain", 0, 1),
    ],
    "i": [
        (1, "France", "Senegal", 3, 1),
        (1, "Iraq", "Norway", 1, 4),
        (2, "France", "Iraq", 3, 0),
        (2, "Norway", "Senegal", 3, 2),
        (3, "Norway", "France", 1, 4),
        (3, "Senegal", "Iraq", 5, 0),
    ],
    "j": [
        (1, "Argentina", "Algeria", 3, 0),
        (1, "Austria", "Jordan", 3, 1),
        (2, "Argentina", "Austria", 2, 0),
        (2, "Jordan", "Algeria", 1, 2),
        (3, "Algeria", "Austria", 3, 3),
        (3, "Jordan", "Argentina", 1, 3),
    ],
    "k": [
        (1, "Portugal", "DR Congo", 1, 1),
        (1, "Uzbekistan", "Colombia", 1, 3),
        (2, "Portugal", "Uzbekistan", 5, 0),
        (2, "Colombia", "DR Congo", 1, 0),
        (3, "Colombia", "Portugal", 0, 0),
        (3, "DR Congo", "Uzbekistan", 3, 1),
    ],
    "l": [
        (1, "England", "Croatia", 4, 2),
        (1, "Ghana", "Panama", 1, 0),
        (2, "England", "Ghana", 0, 0),
        (2, "Panama", "Croatia", 0, 1),
        (3, "Panama", "England", 0, 2),
        (3, "Croatia", "Ghana", 2, 1),
    ],
}

# Fase eliminatoria REAL del Mundial 2026 (fuente: Wikipedia). Cada tupla:
#   (fase, local, visitante, goles_local|None, goles_visitante|None)
# En la demo TODAS empiezan 'scheduled' (apostables); el marcador aquí es el
# resultado REAL que se revela al "jugar"/simular la fase desde el panel admin.
# Los partidos definidos por penales/prórroga guardan el marcador del tiempo
# jugado (el ganador por penales avanza en la realidad). Tercer puesto y final
# aún no se han disputado (None): su resultado se simula con el modelo.
KNOCKOUT_FIXTURES: list[tuple] = [
    # Dieciseisavos de final (round_32)
    ("round_32", "South Africa", "Canada", 0, 1),
    ("round_32", "Brazil", "Japan", 2, 1),
    ("round_32", "Germany", "Paraguay", 1, 1),          # Paraguay 4-3 pen
    ("round_32", "Netherlands", "Morocco", 1, 1),       # Morocco 3-2 pen
    ("round_32", "Ivory Coast", "Norway", 1, 2),
    ("round_32", "France", "Sweden", 3, 0),
    ("round_32", "Mexico", "Ecuador", 2, 0),
    ("round_32", "England", "DR Congo", 2, 1),
    ("round_32", "Belgium", "Senegal", 3, 2),           # a.e.t.
    ("round_32", "United States", "Bosnia and Herzegovina", 2, 0),
    ("round_32", "Spain", "Austria", 3, 0),
    ("round_32", "Portugal", "Croatia", 2, 1),
    ("round_32", "Switzerland", "Algeria", 2, 0),
    ("round_32", "Australia", "Egypt", 1, 1),           # Egypt 4-2 pen
    ("round_32", "Argentina", "Cape Verde", 3, 2),      # a.e.t.
    ("round_32", "Colombia", "Ghana", 1, 0),
    # Octavos de final (round_16)
    ("round_16", "Canada", "Morocco", 0, 3),
    ("round_16", "Paraguay", "France", 0, 1),
    ("round_16", "Brazil", "Norway", 1, 2),
    ("round_16", "Mexico", "England", 2, 3),
    ("round_16", "Portugal", "Spain", 0, 1),
    ("round_16", "United States", "Belgium", 1, 4),
    ("round_16", "Argentina", "Egypt", 3, 2),
    ("round_16", "Switzerland", "Colombia", 0, 0),      # Switzerland 4-3 pen
    # Cuartos de final (quarter_final)
    ("quarter_final", "France", "Morocco", 2, 0),
    ("quarter_final", "Spain", "Belgium", 2, 1),
    ("quarter_final", "Norway", "England", 1, 2),        # a.e.t.
    ("quarter_final", "Argentina", "Switzerland", 3, 1), # a.e.t.
    # Semifinales (semi_final)
    ("semi_final", "France", "Spain", 0, 2),
    ("semi_final", "England", "Argentina", 1, 2),
    # Tercer puesto y final: aún por jugarse (apostables)
    ("third_place", "France", "England", None, None),
    ("final", "Spain", "Argentina", None, None),
]

# Usuarios de demo para que el ranking se vea vivo (contraseña común de demo).
DEMO_USERS = [
    ("lucia@demo.io", 3120),
    ("mateo@demo.io", 2480),
    ("sofia@demo.io", 1975),
    ("diego@demo.io", 1540),
    ("valentina@demo.io", 1230),
    ("nico@demo.io", 860),
    ("camila@demo.io", 640),
]

# Plantillas de apuestas de demo (mercado, selección, stake, cuota). Se aplican
# sobre partidos YA jugados para mostrar un historial realista de gana/pierde.
DEMO_BET_TEMPLATES = [
    ("1x2", "home", 150, 1.85),
    ("ou_2.5", "over", 100, 1.95),
    ("btts", "yes", 120, 2.05),
    ("1x2", "away", 80, 3.40),
    ("ou_2.5", "under", 110, 1.90),
    ("1x2", "draw", 60, 3.10),
]


# Orden global de ronda para el desbloqueo progresivo. Grupos: la ronda = la
# jornada (1,2,3). Eliminatorias en orden real. La final es la última.
KO_ROUND_ORDER: dict[str, int] = {
    "round_32": 4, "round_16": 5, "quarter_final": 6,
    "semi_final": 7, "third_place": 8, "final": 9,
}


def _bet_won(market: str, selection: str, hg: int, ag: int) -> bool:
    """Misma lógica de liquidación que el panel admin (1x2 / over-under / btts)."""
    if market == "1x2":
        res = "home" if hg > ag else "draw" if hg == ag else "away"
        return selection == res
    if market.startswith("ou_"):
        line = float(market.split("_")[1])
        total = hg + ag
        return (selection == "over" and total > line) or (selection == "under" and total < line)
    if market == "btts":
        both = hg > 0 and ag > 0
        return (selection == "yes" and both) or (selection == "no" and not both)
    return False


def _seed_demo_bets(db):
    """Crea historial de apuestas ya liquidadas para los usuarios de demo.

    Cada usuario recibe varias apuestas sobre partidos jugados (jornada 1), con
    su estado ganada/perdida calculado desde el marcador real y el pago aplicado.
    Idempotente: si ya existen (misma idempotency_key) no se duplican.
    """
    finished = (
        db.query(Fixture)
        .filter(Fixture.status == FixtureStatus.finished)
        .order_by(Fixture.id.asc())
        .all()
    )
    if not finished:
        return
    now = datetime.now(timezone.utc)
    for u_idx, (email, _bal) in enumerate(DEMO_USERS):
        user = db.query(User).filter(User.email == email).first()
        if not user:
            continue
        for k in range(5):
            fx = finished[(u_idx + k) % len(finished)]
            market, selection, stake, odds = DEMO_BET_TEMPLATES[(u_idx + k) % len(DEMO_BET_TEMPLATES)]
            key = f"seed-{u_idx}-{k}"
            if db.query(UserPrediction).filter(
                UserPrediction.user_id == user.id,
                UserPrediction.idempotency_key == key,
            ).first():
                continue
            won = _bet_won(market, selection, fx.home_score, fx.away_score)
            db.add(UserPrediction(
                user_id=user.id, fixture_id=fx.id, market=market, selection=selection,
                stake_points=stake, odds_taken=odds, idempotency_key=key,
                status=PredictionStatus.won if won else PredictionStatus.lost,
                payout_points=int(round(stake * odds)) if won else 0,
                created_at=now - timedelta(days=6, hours=k),
                settled_at=now - timedelta(days=5, hours=k),
            ))


def _build_group_stage(db):
    """Crea las fixtures del Mundial 2026 en estado "inicio del torneo".

    La demo arranca justo cuando el Mundial ha empezado: la jornada 1 ya se jugó
    (marcadores reales, 'finished') y TODO lo demás queda 'scheduled' para poder
    apostar (jornadas 2-3 y toda la eliminatoria). Cada partido por jugar guarda
    su resultado REAL en result_home/away_score (oculto): al "jugar"/simular la
    jornada desde el panel admin se revela ese marcador verídico, no uno
    aleatorio. Los kickoffs se reprograman al futuro próximo (el backend rechaza
    apuestas si el kickoff ya pasó) conservando el orden cronológico real.
    """
    now = datetime.now(timezone.utc)
    idx = 0

    # Fase de grupos: jornada 1 jugada (pasado reciente); jornadas 2 y 3 por
    # jugar (futuro próximo, apostables) con su resultado real guardado.
    md_base = {
        1: now - timedelta(days=2),
        2: now + timedelta(days=1),
        3: now + timedelta(days=2),
    }
    for letter, matches in REAL_FIXTURES.items():
        for gi, (md, home, away, hg, ag) in enumerate(matches):
            ext = f"wc2026-g{letter}-{gi}"
            if db.query(Fixture).filter(Fixture.external_id == ext).first():
                continue
            kickoff = md_base[md] + timedelta(hours=idx % 22)
            if md == 1:
                db.add(Fixture(
                    external_id=ext, stage=f"group_{letter}", home_team=home, away_team=away,
                    kickoff_utc=kickoff, neutral=True, round_order=md,
                    status=FixtureStatus.finished, home_score=hg, away_score=ag,
                    result_home_score=hg, result_away_score=ag,
                ))
            else:
                db.add(Fixture(
                    external_id=ext, stage=f"group_{letter}", home_team=home, away_team=away,
                    kickoff_utc=kickoff, neutral=True, status=FixtureStatus.scheduled,
                    round_order=md,
                    result_home_score=hg, result_away_score=ag,
                ))
            idx += 1

    # Eliminatorias: todas por jugar (apostables), con su resultado real guardado
    # cuando ya se conoce. Tercer puesto y final aún no se disputan (result None).
    ko_base = {
        "round_32": now + timedelta(days=3),
        "round_16": now + timedelta(days=4),
        "quarter_final": now + timedelta(days=5),
        "semi_final": now + timedelta(days=6),
        "third_place": now + timedelta(days=7),
        "final": now + timedelta(days=7, hours=6),
    }
    for ki, (stage, home, away, hg, ag) in enumerate(KNOCKOUT_FIXTURES):
        ext = f"wc2026-ko-{ki}"
        if db.query(Fixture).filter(Fixture.external_id == ext).first():
            continue
        kickoff = ko_base[stage] + timedelta(hours=ki % 6)
        db.add(Fixture(
            external_id=ext, stage=stage, home_team=home, away_team=away,
            kickoff_utc=kickoff, neutral=True, status=FixtureStatus.scheduled,
            round_order=KO_ROUND_ORDER[stage],
            result_home_score=hg, result_away_score=ag,
        ))



def main():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        # admin (solo si no existe)
        admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
        if not db.query(User).filter(User.email == admin_email).first():
            pw = os.getenv("ADMIN_PASSWORD")
            if not pw:
                raise SystemExit("define ADMIN_PASSWORD en el entorno para crear el admin")
            db.add(User(email=admin_email, password_hash=hash_password(pw), role=Role.admin))

        # equipos desde el modelo (si está cargado)
        inference.load()
        for name in inference.teams:
            if not db.query(Team).filter(Team.name == name).first():
                db.add(Team(name=name))

        seeded_real = False
        if settings.football_data_api_key:
            try:
                result = sync_world_cup_fixtures(db)
                seeded_real = result.imported > 0
                print(
                    f"sync football-data.org ok: {result.imported} fixtures "
                    f"(competencia {result.competition_code}, temporada {result.season})"
                )
            except Exception as e:
                print(f"sync football-data.org falló, usando demo: {e}")

        if not seeded_real:
            _build_group_stage(db)

        # Usuarios de demo (para poblar el ranking). Contraseña opcional DEMO_PASSWORD.
        demo_pw = os.getenv("DEMO_PASSWORD")
        if demo_pw:
            demo_hash = hash_password(demo_pw)
            for email, balance in DEMO_USERS:
                if not db.query(User).filter(User.email == email).first():
                    db.add(User(
                        email=email, password_hash=demo_hash,
                        role=Role.user, points_balance=balance,
                    ))
            db.flush()  # asegura IDs de usuarios antes de crear su historial
            _seed_demo_bets(db)

        db.commit()
        print(f"seed ok: {db.query(Team).count()} equipos, {db.query(Fixture).count()} fixtures")

    finally:
        db.close()


if __name__ == "__main__":
    main()
