"""
Primitivas de seguridad: hashing Argon2id + JWT (acceso corto + refresh rotatorio).

- Contraseñas: Argon2id (memory-hard, resistente a GPU/ASIC). Nunca texto plano,
  nunca MD5/SHA simple.
- Tokens: access corto (15 min) firmado; refresh con jti para revocación/rotación.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from jose import jwt, JWTError

from .config import settings

# Parámetros Argon2id explícitos (defensa en profundidad, no defaults implícitos).
_ph = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,  # 64 MiB
    parallelism=2,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True si los parámetros cambiaron y conviene re-hashear al próximo login."""
    try:
        return _ph.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(sub: str, role: str) -> str:
    now = _now()
    payload = {
        "sub": sub,
        "role": role,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_min)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(sub: str) -> tuple[str, str]:
    """Devuelve (token, jti). El jti se persiste para permitir revocación/rotación."""
    now = _now()
    jti = str(uuid.uuid4())
    payload = {
        "sub": sub,
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.refresh_token_ttl_days)).timestamp()),
        "jti": jti,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, jti


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
