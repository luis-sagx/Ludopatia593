"""Unidad: hashing Argon2id y JWT (acceso/refresh, firma, expiración)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.core import security
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)


def test_hash_is_argon2id_and_not_plaintext():
    h = hash_password("supersecret1")
    assert h != "supersecret1"
    assert h.startswith("$argon2id$")


def test_verify_password_correct_and_wrong():
    h = hash_password("supersecret1")
    assert verify_password("supersecret1", h) is True
    assert verify_password("wrong-password", h) is False


def test_verify_password_rejects_garbage_hash():
    # Un hash inválido no debe reventar, debe devolver False.
    assert verify_password("x", "not-a-valid-hash") is False


def test_needs_rehash_false_for_current_params():
    assert needs_rehash(hash_password("supersecret1")) is False


def test_needs_rehash_true_for_invalid_hash():
    assert needs_rehash("garbage") is True


def test_access_token_roundtrip_carries_role():
    tok = create_access_token(sub="42", role="admin")
    payload = decode_token(tok)
    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["role"] == "admin"
    assert payload["type"] == "access"
    assert "jti" in payload


def test_refresh_token_returns_persistable_jti():
    tok, jti = create_refresh_token(sub="42")
    payload = decode_token(tok)
    assert payload["type"] == "refresh"
    assert payload["jti"] == jti


def test_decode_rejects_tampered_signature():
    tok = create_access_token(sub="42", role="user")
    header, payload, sig = tok.split(".")
    # Muta el primer caracter del payload: cambia el contenido firmado, así que
    # la firma deja de validar (robusto, no depende de base64 no-canónico).
    mutated_payload = ("A" if payload[0] != "A" else "B") + payload[1:]
    tampered = ".".join([header, mutated_payload, sig])
    assert decode_token(tampered) is None


def test_decode_rejects_expired_token(monkeypatch):
    # Fuerza un exp en el pasado moviendo _now() hacia atrás al firmar.
    from app.core import security as sec

    real_now = sec._now()
    monkeypatch.setattr(sec, "_now", lambda: real_now - timedelta(hours=1))
    tok = create_access_token(sub="42", role="user")
    monkeypatch.undo()
    assert decode_token(tok) is None


def test_decode_rejects_wrong_secret(monkeypatch):
    tok = create_access_token(sub="42", role="user")
    monkeypatch.setattr(security.settings, "jwt_secret", "otro-secreto-distinto")
    assert decode_token(tok) is None
