"""Integración: RBAC admin y liquidación de resultados."""
from __future__ import annotations


def test_regular_user_cannot_settle_rbac(client, user_headers, scheduled_fixture_id):
    r = client.post(f"/v1/admin/fixtures/{scheduled_fixture_id}/result",
                    json={"home_score": 1, "away_score": 1}, headers=user_headers)
    assert r.status_code == 403


def test_settle_requires_auth(client, scheduled_fixture_id):
    r = client.post(f"/v1/admin/fixtures/{scheduled_fixture_id}/result",
                    json={"home_score": 1, "away_score": 1})
    assert r.status_code in (401, 403)


def test_admin_settles_and_winning_bet_pays(client, admin_headers):
    # usuario aparte que apuesta local
    client.post("/v1/auth/register",
                json={"email": "bettor@test.com", "password": "supersecret1"})
    tok = client.post("/v1/auth/login",
                      json={"email": "bettor@test.com", "password": "supersecret1"}
                      ).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}

    scheduled = [f for f in client.get("/v1/fixtures").json() if f["status"] == "scheduled"]
    fid = scheduled[-1]["id"]  # uno distinto al de otros tests
    client.post("/v1/bets", headers=h, json={
        "fixture_id": fid, "market": "1x2", "selection": "home",
        "stake_points": 100, "idempotency_key": "idem-admin"})

    r = client.post(f"/v1/admin/fixtures/{fid}/result",
                    json={"home_score": 2, "away_score": 0}, headers=admin_headers)
    assert r.status_code == 200, r.text

    perf = client.get("/v1/me/performance", headers=h).json()
    assert perf["won"] == 1


def test_leaderboard_public(client):
    r = client.get("/v1/leaderboard")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_settle_nonexistent_fixture_404(client, admin_headers):
    r = client.post("/v1/admin/fixtures/999999/result",
                    json={"home_score": 1, "away_score": 0}, headers=admin_headers)
    assert r.status_code == 404


def test_settle_twice_conflicts(client, admin_headers):
    scheduled = [f for f in client.get("/v1/fixtures").json() if f["status"] == "scheduled"]
    fid = scheduled[-1]["id"]
    r1 = client.post(f"/v1/admin/fixtures/{fid}/result",
                     json={"home_score": 1, "away_score": 0}, headers=admin_headers)
    assert r1.status_code == 200, r1.text
    # segunda liquidación del mismo fixture -> 409 (anti doble-liquidación)
    r2 = client.post(f"/v1/admin/fixtures/{fid}/result",
                     json={"home_score": 3, "away_score": 3}, headers=admin_headers)
    assert r2.status_code == 409


def test_admin_audit_tail(client, admin_headers):
    r = client.get("/v1/admin/audit?limit=10", headers=admin_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_audit_requires_admin(client, user_headers):
    assert client.get("/v1/admin/audit", headers=user_headers).status_code == 403


def test_admin_model_reload(client, admin_headers):
    r = client.post("/v1/admin/model/reload", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["reloaded"] is True


def test_admin_simulate_one_fixture(client, admin_headers):
    r = client.post("/v1/admin/simulate", json={"count": 1}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["simulated"] <= 1
