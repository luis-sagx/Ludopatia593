"""
Configuración central. Secretos SOLO desde entorno (nunca hardcodeados).
Pydantic valida tipos al arranque -> falla rápido si falta config crítica.
"""
from __future__ import annotations

from pydantic import AliasChoices, Field, field_validator
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

    # Rate limiting (defensa fuerza bruta / abuso API). Además del límite
    # global, estos endpoints tienen uno propio más estricto porque su abuso
    # tiene un costo específico (creación masiva de cuentas, farming de
    # puntos, carga sobre operaciones admin) que el límite global no acota.
    rate_limit_per_min: int = 60
    login_rate_limit_per_min: int = 5
    register_rate_limit_per_min: int = 8
    bets_rate_limit_per_min: int = 20
    admin_rate_limit_per_min: int = 30

    # football-data.org. Vacío => ETL usa dataset local.
    football_data_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("FOOTBALL_DATA_API_KEY", "API_FOOTBALL_KEY"),
    )
    football_data_base: str = Field(
        default="https://api.football-data.org/v4",
        validation_alias=AliasChoices("FOOTBALL_DATA_BASE", "API_FOOTBALL_BASE"),
    )
    football_data_competition_code: str = Field(
        default="WC",
        validation_alias=AliasChoices("FOOTBALL_DATA_COMPETITION_CODE"),
    )
    football_data_season: int = Field(
        default=2026,
        validation_alias=AliasChoices("FOOTBALL_DATA_SEASON", "API_FOOTBALL_SEASON"),
    )

    # CORS_ORIGINS puede ser JSON ["url1","url2"] o comma-separated "url1,url2"
    cors_origins: list[str] = ["http://localhost:3000"]

    @field_validator("database_url", mode="before")
    @classmethod
    def fix_postgres_url(cls, v: str) -> str:
        # Railway entrega postgres:// o postgresql:// sin driver spec
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+psycopg2://", 1)
        if v.startswith("postgresql://") and "+psycopg2" not in v:
            return v.replace("postgresql://", "postgresql+psycopg2://", 1)
        return v

    @field_validator("jwt_secret")
    @classmethod
    def reject_weak_secret(cls, v: str, info) -> str:
        # Fail-fast: fuera de 'dev' el default inseguro o un secreto corto son
        # inaceptables (permitirían forjar JWT). En prod DEBE venir del entorno.
        env = info.data.get("environment", "dev")
        if env != "dev" and (v == "dev-only-insecure-change-me" or len(v) < 32):
            raise ValueError(
                "JWT_SECRET inseguro o ausente en entorno no-dev "
                "(usa 'openssl rand -hex 32')"
            )
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> list[str]:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                import json
                return json.loads(v)
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


settings = Settings()
