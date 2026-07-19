"""Integración: apuestas — creación, idempotencia, descuento de saldo, IDOR."""
from __future__ import annotations


def _place_bet(client, headers, fid, key="idem-key-aaa"):
    return client.post("/v1/bets", headers=headers, json={
        "fixture_id": fid, "market": "1x2", "selection": "home",
        "stake_points": 100, "idempotency_key": key,
    })


def test_create_bet_deducts_balance_once(client, user_headers, scheduled_fixture_id):
    r = _place_bet(client, user_headers, scheduled_fixture_id)
    assert r.status_code == 201, r.text
    bal = client.get("/v1/auth/me", headers=user_headers).json()["points_balance"]
    assert bal == 900


def test_idempotency_key_does_not_duplicate(client, user_headers, scheduled_fixture_id):
    r1 = _place_bet(client, user_headers, scheduled_fixture_id, key="idem-dup")
    r2 = _place_bet(client, user_headers, scheduled_fixture_id, key="idem-dup")
    assert r1.json()["id"] == r2.json()["id"]
    # el saldo se descontó una sola vez
    bal = client.get("/v1/auth/me", headers=user_headers).json()["points_balance"]
    assert bal == 900


def test_bet_requires_auth(client, scheduled_fixture_id):
    r = _place_bet(client, {}, scheduled_fixture_id)
    assert r.status_code in (401, 403)


def test_idor_other_user_cannot_read_bet(client, user_headers, scheduled_fixture_id):
    bet_id = _place_bet(client, user_headers, scheduled_fixture_id, key="idem-idor").json()["id"]
    # segundo usuario
    client.post("/v1/auth/register",
                json={"email": "intruder@test.com", "password": "supersecret2"})
    tok = client.post("/v1/auth/login",
                      json={"email": "intruder@test.com", "password": "supersecret2"}
                      ).json()["access_token"]
    h2 = {"Authorization": f"Bearer {tok}"}
    assert client.get(f"/v1/bets/{bet_id}", headers=h2).status_code == 404
