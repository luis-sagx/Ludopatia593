"""Unidad: validaciones de configuración (fail-fast de secretos, URLs, CORS)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_prod_rejects_default_insecure_secret():
    with pytest.raises(ValidationError):
        Settings(environment="production", jwt_secret="dev-only-insecure-change-me")


def test_prod_rejects_short_secret():
    with pytest.raises(ValidationError):
        Settings(environment="production", jwt_secret="corto")


def test_prod_accepts_strong_secret():
    s = Settings(environment="production", jwt_secret="a" * 32)
    assert s.environment == "production"


def test_dev_allows_default_secret():
    s = Settings(environment="dev", jwt_secret="dev-only-insecure-change-me")
    assert s.jwt_secret == "dev-only-insecure-change-me"


@pytest.mark.parametrize(
    "raw,expected_prefix",
    [
        ("postgres://u:p@h:5432/db", "postgresql+psycopg2://"),
        ("postgresql://u:p@h:5432/db", "postgresql+psycopg2://"),
        ("postgresql+psycopg2://u:p@h:5432/db", "postgresql+psycopg2://"),
    ],
)
def test_database_url_normalized_to_psycopg2(raw, expected_prefix):
    s = Settings(jwt_secret="a" * 32, database_url=raw)
    assert s.database_url.startswith(expected_prefix)
    assert "+psycopg2+psycopg2" not in s.database_url  # no doble sustitución


def test_cors_origins_comma_separated():
    s = Settings(jwt_secret="a" * 32, cors_origins="https://a.com, https://b.com")
    assert s.cors_origins == ["https://a.com", "https://b.com"]


def test_cors_origins_json_list():
    s = Settings(jwt_secret="a" * 32, cors_origins='["https://a.com","https://b.com"]')
    assert s.cors_origins == ["https://a.com", "https://b.com"]
