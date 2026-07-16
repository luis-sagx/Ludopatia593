"""
Rate limiting por ventana fija sobre Redis (defensa fuerza bruta / abuso).
Si Redis no está disponible, degrada a memoria local (best-effort).

Deuda técnica conocida: ventana fija, no deslizante -- un cliente puede hacer
hasta ~2x el límite si concentra peticiones justo en el borde entre dos
ventanas (ej. mitad al final del minuto N, mitad al inicio del minuto N+1).
Aceptable para el volumen actual del proyecto; migrar a ventana deslizante
(ej. sorted set con timestamps en Redis) si el tráfico real lo justifica.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Callable

import redis
from fastapi import HTTPException, Request, status

from .config import settings

logger = logging.getLogger(__name__)


def _connect():
    try:
        r = redis.from_url(settings.redis_url, socket_connect_timeout=1)
        r.ping()
        return r
    except Exception:
        return None


_r = _connect()
_mem: dict[str, list[float]] = defaultdict(list)
_last_reconnect = 0.0
_warned_fallback = False


def get_redis():
    """Cliente Redis vivo o None (con reconexión perezosa). Para cache best-effort."""
    global _r, _last_reconnect
    if _r is None and time.time() - _last_reconnect > 5:
        _last_reconnect = time.time()
        _r = _connect()
    return _r


def allow(key: str, limit: int, window_sec: int = 60) -> bool:
    """True si la acción está permitida; False si excede el límite."""
    global _r, _last_reconnect, _warned_fallback
    now = time.time()

    # Reconexión perezosa: si Redis se cayó, reintenta como máximo cada 5s
    # (evita que un fallo transitorio deje el rate limit degradado para siempre).
    if _r is None and now - _last_reconnect > 5:
        _last_reconnect = now
        _r = _connect()

    if _r is not None:
        try:
            pipe = _r.pipeline()
            bucket = f"rl:{key}:{int(now // window_sec)}"
            pipe.incr(bucket)
            pipe.expire(bucket, window_sec)
            count, _ = pipe.execute()
            return int(count) <= limit
        except Exception:
            _r = None  # marca caído -> forzará reconexión perezosa

    # Fallback a memoria (best-effort). En multi-instancia NO es global:
    # avisar una vez fuera de 'dev' para que sea visible en operación.
    if not _warned_fallback and settings.environment != "dev":
        _warned_fallback = True
        logger.warning("rate limit degradado a memoria local: Redis no disponible")
    hits = [t for t in _mem[key] if now - t < window_sec]
    hits.append(now)
    _mem[key] = hits
    return len(hits) <= limit


def rate_limit_dep(key_prefix: str, limit: int) -> Callable[[Request], None]:
    """Dependencia FastAPI reusable: 429 si el IP excede `limit`/min para
    `key_prefix`. Se instancia una vez por ruta/router (`Depends(rate_limit_dep(...))`)
    -- no confundir con `allow()`, que es la primitiva de bajo nivel."""
    def _dep(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        if not allow(f"{key_prefix}:{ip}", limit):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "demasiadas peticiones")
    return _dep
