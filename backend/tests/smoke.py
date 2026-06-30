"""
Smoke test end-to-end con SQLite en memoria (sin Docker/Postgres).
Verifica: registro, login, predicción del modelo, apuesta con puntos,
idempotencia, IDOR, liquidación admin y leaderboard.

Uso: DATABASE_URL=sqlite:///./smoke.db python -m tests.smoke
"""
from __future__ import annotations

import os
os.environ.setdefault("DATABASE_URL", "sqlite:///./smoke.db")
os.environ.setdefault("JWT_SECRET", "test-secret")

from fastapi.testclient import TestClient

from app.db.session import Base, engine
from app.db import models  # noqa: F401  (registra tablas)
from app.main import app
from app.ml.train import main as train_main


def run():
    # entrena modelo (genera data/model.json)
    train_main()

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    # crea admin + fixtures vía seed
    os.environ["ADMIN_PASSWORD"] = "admin-pass-123"
    from app.seed import main as seed_main
    seed_main()

    c = TestClient(app)

    assert c.get("/health").json()["model_loaded"] is True

    # registro + login
    r = c.post("/v1/auth/register", json={"email": "u1@test.com", "password": "supersecret1"})
    assert r.status_code == 201, r.text
    r = c.post("/v1/auth/login", json={"email": "u1@test.com", "password": "supersecret1"})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}

    # login mal -> 401
    assert c.post("/v1/auth/login", json={"email": "u1@test.com", "password": "wrong"}).status_code == 401

    # predicción del modelo sobre fixture 1
    r = c.get("/v1/fixtures/1/prediction")
    assert r.status_code == 200, r.text
    p = r.json()["markets"]["1x2"]
    assert abs(p["home"]["prob"] + p["draw"]["prob"] + p["away"]["prob"] - 1.0) < 1e-3
    print("1x2 fixture1:", {k: p[k]["prob"] for k in ("home", "draw", "away")})

    # apuesta con puntos
    bet = {"fixture_id": 1, "market": "1x2", "selection": "home",
           "stake_points": 100, "idempotency_key": "idem-key-0001"}
    r = c.post("/v1/bets", json=bet, headers=h)
    assert r.status_code == 201, r.text
    bet_id = r.json()["id"]
    odds = r.json()["odds_taken"]
    print("apuesta creada id", bet_id, "odds servidor", odds)

    # idempotencia: mismo key -> misma apuesta, no duplica
    r2 = c.post("/v1/bets", json=bet, headers=h)
    assert r2.json()["id"] == bet_id, "idempotencia falló"

    # saldo descontó 100 una sola vez
    bal = c.get("/v1/auth/me", headers=h).json()["points_balance"]
    assert bal == 900, f"saldo esperado 900, got {bal}"
    print("saldo tras 1 apuesta idempotente:", bal)

    # IDOR: otro usuario no ve la apuesta ajena
    c.post("/v1/auth/register", json={"email": "u2@test.com", "password": "supersecret2"})
    tok2 = c.post("/v1/auth/login", json={"email": "u2@test.com", "password": "supersecret2"}).json()["access_token"]
    h2 = {"Authorization": f"Bearer {tok2}"}
    assert c.get(f"/v1/bets/{bet_id}", headers=h2).status_code == 404, "IDOR no bloqueado!"
    print("IDOR bloqueado OK")

    # admin liquida fixture 1 con victoria local -> gana
    atok = c.post("/v1/auth/login", json={"email": "admin@example.com", "password": "admin-pass-123"}).json()["access_token"]
    ah = {"Authorization": f"Bearer {atok}"}
    r = c.post("/v1/admin/fixtures/1/result", json={"home_score": 2, "away_score": 0}, headers=ah)
    assert r.status_code == 200, r.text
    print("liquidación:", r.json())

    perf = c.get("/v1/me/performance", headers=h).json()
    print("performance u1:", {k: perf[k] for k in ("won", "hit_rate", "roi", "points_balance")})
    assert perf["won"] == 1

    # usuario normal NO puede liquidar (RBAC)
    assert c.post("/v1/admin/fixtures/1/result", json={"home_score": 1, "away_score": 1}, headers=h).status_code == 403
    print("RBAC admin OK")

    lb = c.get("/v1/leaderboard").json()
    print("leaderboard top:", lb[:2])

    print("\nSMOKE TEST OK ✅")


if __name__ == "__main__":
    run()
