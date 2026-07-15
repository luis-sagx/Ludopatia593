"""
App FastAPI. Monolito modular: API + servicio de inferencia en proceso.
Seguridad: headers endurecidos, CORS restringido, rate limit global, modelo
cargado al arranque.
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .core.config import settings
from .core.logging import configure_logging
from .core.ratelimit import allow
from .ml.inference import inference
from .api import auth, predictions, bets, admin, leaderboard

configure_logging()
logger = logging.getLogger(__name__)
access_logger = logging.getLogger("access")
_is_dev = settings.environment == "dev"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not inference.load():  # carga model.json si existe (no falla si no está)
        logger.warning(
            "model.json no encontrado: endpoints de predicción devolverán 503 "
            "hasta que se cargue un modelo."
        )
    yield


# Fuera de 'dev' se ocultan /docs, /redoc y /openapi.json (menos superficie/recon).
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _is_dev else None,
    redoc_url="/redoc" if _is_dev else None,
    openapi_url="/openapi.json" if _is_dev else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,   # restringido, no "*"
    allow_credentials=True,
    allow_methods=["GET", "POST"],         # la API solo expone GET/POST
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # request_id: reusa el del proxy si viene (X-Request-Id), si no genera uno.
    # Se guarda en request.state para poder cruzarlo con AuditLog en los routers.
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    start = time.perf_counter()
    ip = request.client.host if request.client else "unknown"

    # rate limit global por IP (defensa abuso)
    if not allow(f"global:{ip}", settings.rate_limit_per_min):
        resp = JSONResponse(
            {"detail": "rate limit excedido"},
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )
    else:
        resp = await call_next(request)

    # Traza estructurada de cada request. Solo metadata -- nunca headers ni
    # body -- así Authorization/credenciales quedan fuera por construcción.
    access_logger.info(
        "http_request",
        extra={"http": {
            "request_id": request_id,
            "ip": ip,
            "method": request.method,
            "path": request.url.path,
            "status": resp.status_code,
            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
        }},
    )

    # headers de seguridad
    resp.headers["X-Request-Id"] = request_id
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = "default-src 'self'"
    if settings.environment != "dev":
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp


app.include_router(auth.router)
app.include_router(predictions.router)
app.include_router(bets.router)
app.include_router(leaderboard.router)
app.include_router(admin.router)


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": inference.ready, "model_version": inference.version}
