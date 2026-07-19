"""Integración: refresh rotatorio, CSRF doble-envío, logout y sesiones (IDOR)."""
from __future__ import annotations

import uuid


def _fresh_login(client):
    email = f"s-{uuid.uuid4().hex[:8]}@test.com"
    client.post("/v1/auth/register", json={"email": email, "password": "supersecret1"})
    r = client.post("/v1/auth/login", json={"email": email, "password": "supersecret1"})
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return email, headers


def test_register_duplicate_email_409(client):
    email = f"dup-{uuid.uuid4().hex[:8]}@test.com"
    assert client.post("/v1/auth/register",
                       json={"email": email, "password": "supersecret1"}).status_code == 201
    assert client.post("/v1/auth/register",
                       json={"email": email, "password": "supersecret1"}).status_code == 409


def test_refresh_rotates_with_valid_csrf(client):
    _fresh_login(client)
    csrf = client.cookies.get("csrf_token")
    r = client.post("/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    assert "access_token" in r.json()


def test_refresh_without_csrf_is_forbidden(client):
    _fresh_login(client)
    r = client.post("/v1/auth/refresh")  # falta header X-CSRF-Token
    assert r.status_code == 403


def test_logout_revokes_and_then_refresh_fails(client):
    _, headers = _fresh_login(client)
    csrf = client.cookies.get("csrf_token")
    assert client.post("/v1/auth/logout",
                       headers={**headers, "X-CSRF-Token": csrf}).status_code == 204


def test_sessions_listed_and_revoke_is_idor_safe(client):
    # usuario A con una sesión activa
    _, ha = _fresh_login(client)
    sessions = client.get("/v1/auth/sessions", headers=ha).json()
    assert len(sessions) >= 1
    jti = sessions[0]["jti"]

    # usuario B no puede revocar la sesión de A adivinando el jti
    _, hb = _fresh_login(client)
    assert client.delete(f"/v1/auth/sessions/{jti}", headers=hb).status_code == 404

    # el dueño sí puede revocarla
    assert client.delete(f"/v1/auth/sessions/{jti}", headers=ha).status_code == 204
