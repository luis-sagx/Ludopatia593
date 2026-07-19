"""Integración: registro, login, /me y ofuscación de docs."""
from __future__ import annotations


def test_health_reports_model_loaded(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["model_loaded"] is True


def test_register_then_login_ok(client):
    r = client.post("/v1/auth/register",
                    json={"email": "new@test.com", "password": "supersecret1"})
    assert r.status_code == 201, r.text
    r = client.post("/v1/auth/login",
                    json={"email": "new@test.com", "password": "supersecret1"})
    assert r.status_code == 200, r.text
    assert "access_token" in r.json()


def test_login_wrong_password_401(client):
    client.post("/v1/auth/register",
                json={"email": "wp@test.com", "password": "supersecret1"})
    r = client.post("/v1/auth/login",
                    json={"email": "wp@test.com", "password": "wrong-one"})
    assert r.status_code == 401


def test_me_requires_auth(client):
    assert client.get("/v1/auth/me").status_code in (401, 403)


def test_me_returns_starting_balance(client, user_headers):
    me = client.get("/v1/auth/me", headers=user_headers).json()
    assert me["points_balance"] == 1000


def test_docs_hidden_outside_dev_is_config_driven(client):
    # En 'dev' (entorno de test) /docs está expuesto; el runbook verifica que
    # en production devuelve 404. Aquí solo fijamos el contrato: la ruta existe
    # sólo cuando environment == dev.
    from app.core.config import settings
    r = client.get("/openapi.json")
    if settings.environment == "dev":
        assert r.status_code == 200
    else:
        assert r.status_code == 404
