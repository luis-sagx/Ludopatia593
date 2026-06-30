"""
Configuración central. Secretos SOLO desde entorno (nunca hardcodeados).
Pydantic valida tipos al arranque -> falla rápido si falta config crítica.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "ludopatia593-predictor"
    environment: str = "dev"

    # Seguridad: en prod, JWT_SECRET DEBE venir del entorno/vault, no del default.
    jwt_secret: str = "dev-only-insecure-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_min: int = 15      # token de acceso corto
    refresh_token_ttl_days: int = 7     # refresh rotatorio

    database_url: str = "postgresql+psycopg2://app:app@localhost:5432/predictor"
    redis_url: str = "redis://localhost:6379/0"

    # Rate limiting (defensa fuerza bruta / abuso API)
    rate_limit_per_min: int = 60
    login_rate_limit_per_min: int = 5

    # API-Football (plan free). Vacío => ETL usa dataset local.
    api_football_key: str = ""
    api_football_base: str = "https://v3.football.api-sports.io"

    cors_origins: list[str] = ["http://localhost:3000"]


settings = Settings()
