"""
Fixtures compartidas para la suite pytest.

Arranca la app contra SQLite (sin Docker/Postgres/Redis): entrena el modelo,
crea el esquema y siembra admin + fixtures una sola vez por sesión. Redis no
está disponible en CI -> el rate limiter degrada a memoria local (probado en
test_ratelimit.py), lo cual es suficiente para ejercitar la lógica.
"""
from __future__ import annotations

import os
import pathlib
import uuid

# El entorno DEBE fijarse antes de importar cualquier módulo de la app: el
# singleton `settings` lee las variables al importarse.
_DB = pathlib.Path(__file__).parent / "_pytest.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_DB}")
os.environ.setdefault("JWT_SECRET", "test-secret-not-used-in-prod")
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "admin-pass-123")

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def _bootstrap():
    """Entrena el modelo, crea el esquema y siembra la BD una vez."""
    from app.db.session import Base, engine
    from app.db import models  # noqa: F401  (registra las tablas)
    from app.ml.train import main as train_main
    from app.seed import main as seed_main

    train_main()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    seed_main()
    yield
    if _DB.exists():
        _DB.unlink()


@pytest.fixture()
def client(_bootstrap):
    """TestClient con lifespan activo (carga el modelo en memoria)."""
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_ratelimit():
    """Limpia el estado en memoria del rate limiter entre tests para que el
    límite global (120/min) no arrastre conteos de un test a otro."""
    from app.core import ratelimit
    ratelimit._mem.clear()
    yield
    ratelimit._mem.clear()


# ---- helpers de autenticación reutilizables ----

def _register_and_login(client, email: str, password: str) -> dict:
    client.post("/v1/auth/register", json={"email": email, "password": password})
    r = client.post("/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def user_headers(client):
    # Email único por test: la BD se siembra una vez por sesión, así que un
    # email fijo se compartiría entre tests y arrastraría saldo/apuestas.
    return _register_and_login(client, f"u-{uuid.uuid4().hex[:8]}@test.com", "supersecret1")


@pytest.fixture()
def admin_headers(client):
    r = client.post(
        "/v1/auth/login",
        json={"email": "admin@example.com", "password": "admin-pass-123"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def scheduled_fixture_id(client):
    """Id de un fixture apostable (status scheduled)."""
    fixtures = client.get("/v1/fixtures").json()
    scheduled = [f for f in fixtures if f["status"] == "scheduled"]
    assert scheduled, "el seed no dejó fixtures 'scheduled'"
    return scheduled[0]["id"]
