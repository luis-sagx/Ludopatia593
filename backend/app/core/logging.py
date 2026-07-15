"""
Logging estructurado JSON para la traza de requests HTTP (sección 03 del
hardening plan). Nunca recibe headers ni bodies -- solo metadata de la
petición -- así que Authorization/credenciales no pueden filtrarse por
construcción, no por criterio manual caso a caso.
"""
from __future__ import annotations

import json
import logging
import sys

from .config import settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        http = getattr(record, "http", None)
        if http:
            payload.update(http)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """DEBUG solo en 'dev' -- fuera de dev, INFO (no filtrar detalle interno)."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.DEBUG if settings.environment == "dev" else logging.INFO)
