"""Integración: cabeceras de seguridad, ofuscación de 'Server' y rate limit."""
from __future__ import annotations


def test_hardened_headers_present(client):
    h = client.get("/health").headers
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["X-Frame-Options"] == "DENY"
    assert h["Referrer-Policy"] == "no-referrer"
    assert h["Content-Security-Policy"] == "default-src 'self'"
    assert "X-Request-Id" in h


def test_server_header_is_obfuscated(client):
    # No debe filtrar uvicorn/versión: ofuscación de versiones.
    assert client.get("/health").headers["Server"] == "ludopatia593"


def test_login_rate_limit_returns_429(client):
    # Límite de login = 5/min. El 6.º intento fallido debe cortar con 429.
    codes = []
    for _ in range(8):
        r = client.post("/v1/auth/login",
                        json={"email": "nobody@test.com", "password": "bad-pass-123"})
        codes.append(r.status_code)
    assert 429 in codes
    # y el 429 llega después de agotar el cupo (no en el primer intento)
    assert codes[0] != 429
