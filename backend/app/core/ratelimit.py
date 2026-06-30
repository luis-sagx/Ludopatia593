"""
Rate limiting por ventana fija sobre Redis (defensa fuerza bruta / abuso).
Si Redis no está disponible, degrada a memoria local (best-effort).
"""
from __future__ import annotations

import time
from collections import defaultdict

import redis

from .config import settings

try:
    _r = redis.from_url(settings.redis_url, socket_connect_timeout=1)
    _r.ping()
    _redis_ok = True
except Exception:
    _r = None
    _redis_ok = False

_mem: dict[str, list[float]] = defaultdict(list)


def allow(key: str, limit: int, window_sec: int = 60) -> bool:
    """True si la acción está permitida; False si excede el límite."""
    now = time.time()
    if _redis_ok and _r is not None:
        try:
            pipe = _r.pipeline()
            bucket = f"rl:{key}:{int(now // window_sec)}"
            pipe.incr(bucket)
            pipe.expire(bucket, window_sec)
            count, _ = pipe.execute()
            return int(count) <= limit
        except Exception:
            pass  # cae a memoria
    # fallback memoria
    hits = [t for t in _mem[key] if now - t < window_sec]
    hits.append(now)
    _mem[key] = hits
    return len(hits) <= limit
