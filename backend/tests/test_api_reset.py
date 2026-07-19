"""Integración: reinicio del torneo desde cero (endpoint admin reset-tournament)."""
from __future__ import annotations

import uuid


def _bet(client, headers, fid, key):
    return client.post("/v1/bets", headers=headers, json={
        "fixture_id": fid, "market": "1x2", "selection": "home",
        "stake_points": 100, "idempotency_key": key,
    })


def test_tournament_starts_from_first_round_all_scheduled(client, admin_headers):
    # Tras reiniciar, TODOS los fixtures visibles son apostables (scheduled): el
    # torneo arranca en el primer partido, sin jornada pre-jugada. (Se resetea
    # primero porque la BD de la sesión es compartida entre tests.)
    client.post("/v1/admin/reset-tournament", headers=admin_headers)
    fixtures = client.get("/v1/fixtures").json()
    assert fixtures, "no hay fixtures tras el reset"
    assert all(f["status"] == "scheduled" for f in fixtures)


def test_reset_requires_admin(client, user_headers):
    assert client.post("/v1/admin/reset-tournament", headers=user_headers).status_code == 403


def test_reset_needs_auth(client):
    assert client.post("/v1/admin/reset-tournament").status_code in (401, 403)


def test_reset_clears_bets_and_restores_balance(client, admin_headers):
    # usuario apuesta y gasta puntos
    email = f"r-{uuid.uuid4().hex[:8]}@test.com"
    client.post("/v1/auth/register", json={"email": email, "password": "supersecret1"})
    tok = client.post("/v1/auth/login",
                      json={"email": email, "password": "supersecret1"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}

    fid = client.get("/v1/fixtures").json()[0]["id"]
    assert _bet(client, h, fid, "reset-bet-1").status_code == 201
    assert client.get("/v1/auth/me", headers=h).json()["points_balance"] == 900

    # admin reinicia el torneo
    r = client.post("/v1/admin/reset-tournament", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["predictions_deleted"] >= 1
    assert body["fixtures_reset"] >= 1

    # saldo restaurado y sin apuestas
    assert client.get("/v1/auth/me", headers=h).json()["points_balance"] == 1000
    assert client.get("/v1/bets", headers=h).json() == []


def test_reset_reopens_fixtures_for_betting(client, admin_headers):
    # finaliza una ronda, luego resetea y comprueba que se puede volver a apostar
    client.post("/v1/admin/simulate", json={"count": 1}, headers=admin_headers)
    r = client.post("/v1/admin/reset-tournament", headers=admin_headers)
    assert r.status_code == 200

    fixtures = client.get("/v1/fixtures").json()
    assert all(f["status"] == "scheduled" for f in fixtures)

    # un usuario nuevo puede apostar tras el reset
    email = f"r2-{uuid.uuid4().hex[:8]}@test.com"
    client.post("/v1/auth/register", json={"email": email, "password": "supersecret1"})
    tok = client.post("/v1/auth/login",
                      json={"email": email, "password": "supersecret1"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert _bet(client, h, fixtures[0]["id"], "post-reset-bet").status_code == 201
