"""Unidad: primitiva allow() del rate limiter (fallback en memoria)."""
from __future__ import annotations

import pytest

from app.core import ratelimit
from app.core.ratelimit import allow


@pytest.fixture(autouse=True)
def _force_memory_backend(monkeypatch):
    # Sin Redis en CI: fuerza el camino de memoria de forma determinista.
    monkeypatch.setattr(ratelimit, "_r", None)
    monkeypatch.setattr(ratelimit, "_last_reconnect", ratelimit.time.time())
    ratelimit._mem.clear()
    yield
    ratelimit._mem.clear()


def test_allows_up_to_limit_then_blocks():
    key = "test:ip-a"
    assert all(allow(key, limit=3) for _ in range(3))  # 3 permitidas
    assert allow(key, limit=3) is False                # 4.ª bloqueada


def test_separate_keys_have_independent_counters():
    assert allow("test:ip-b", limit=1) is True
    assert allow("test:ip-b", limit=1) is False
    # otra key no se ve afectada
    assert allow("test:ip-c", limit=1) is True


def test_old_hits_expire_out_of_window():
    key = "test:ip-d"
    # Inserta un hit "viejo" (fuera de la ventana de 60s) manualmente.
    ratelimit._mem[key] = [ratelimit.time.time() - 120]
    # Ese hit viejo no cuenta -> con limit=1 la nueva petición pasa.
    assert allow(key, limit=1) is True
