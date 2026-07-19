"""
Rutas de autenticación: registro, login, refresh rotatorio, logout, sesiones.

Defensas:
  - Argon2id para passwords.
  - Rate limit por IP en login/registro (anti fuerza bruta / creación masiva).
  - Mensaje de error genérico en login (no revela si el email existe).
  - Refresh rotatorio con detección de reuso -> revoca toda la cadena.
  - Refresh token en cookie HttpOnly (nunca en el body ni en localStorage) +
    CSRF por doble-envío (cookie legible por JS + header) para las dos únicas
    rutas que dependen de esa cookie (refresh, logout) -- el resto de la API
    usa el access token vía header Authorization, que no viaja cross-site
    solo, así que no necesita CSRF.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.security import (
    hash_password, verify_password, needs_rehash,
    create_access_token, create_refresh_token, decode_token,
)
from ..core.config import settings
from ..core.ratelimit import allow, rate_limit_dep
from ..db.session import get_db
from ..db.models import User, RefreshToken, Role, AuditLog
from ..schemas.schemas import RegisterIn, LoginIn, TokenOut, UserOut, SessionOut
from .deps import get_current_user

router = APIRouter(prefix="/v1/auth", tags=["auth"])

_REFRESH_COOKIE_PATH = "/v1/auth"  # el navegador solo la adjunta en requests a /v1/auth/*
_CSRF_COOKIE_PATH = "/"            # el frontend corre en otras rutas (/fixtures, /bets...)
                                    # y necesita leerla vía document.cookie desde ahí -- si
                                    # quedara en /v1/auth (una ruta de API, no de frontend),
                                    # el navegador jamás la expondría a ese JS.


def _cookie_flags() -> dict:
    # SameSite=None + Secure en no-dev: frontend y backend viven en dominios
    # distintos en Railway (servicios separados), así que "Lax" bastaría solo
    # si algún día comparten dominio raíz. Secure=True es obligatorio junto
    # con SameSite=None (el navegador rechaza la cookie si no).
    if settings.environment == "dev":
        return {"secure": False, "samesite": "lax"}
    return {"secure": True, "samesite": "none"}


def _set_session_cookies(response: Response, refresh_token: str) -> None:
    flags = _cookie_flags()
    max_age = settings.refresh_token_ttl_days * 86400
    response.set_cookie(
        "refresh_token", refresh_token, httponly=True, path=_REFRESH_COOKIE_PATH,
        max_age=max_age, **flags,
    )
    # csrf_token: NO httponly -- el frontend lo lee de document.cookie y lo
    # reenvía como header en refresh/logout (doble-envío: si un sitio ajeno
    # dispara el POST, no puede leer la cookie de otro origen para copiar el
    # header, así que el envío cruzado no matchea).
    response.set_cookie(
        "csrf_token", secrets.token_urlsafe(32), httponly=False, path=_CSRF_COOKIE_PATH,
        max_age=max_age, **flags,
    )


def _clear_session_cookies(response: Response) -> None:
    # El borrado debe repetir secure/samesite EXACTOS de cuando se creó: los
    # navegadores ignoran un Set-Cookie de borrado que no incluya Secure si la
    # cookie original lo tenía ("Leave Secure Cookies Alone") -- sin esto, el
    # navegador se queda con el csrf_token viejo después de logout/reuso.
    flags = _cookie_flags()
    response.delete_cookie("refresh_token", path=_REFRESH_COOKIE_PATH, **flags)
    response.delete_cookie("csrf_token", path=_CSRF_COOKIE_PATH, **flags)


def _verify_csrf(request: Request) -> None:
    cookie_val = request.cookies.get("csrf_token")
    header_val = request.headers.get("x-csrf-token")
    if not cookie_val or not header_val or not secrets.compare_digest(cookie_val, header_val):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "csrf inválido")


def _issue_tokens(db: Session, user: User, response: Response) -> TokenOut:
    access = create_access_token(str(user.id), user.role.value)
    refresh, jti = create_refresh_token(str(user.id))
    db.add(RefreshToken(
        jti=jti,
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_ttl_days),
    ))
    db.commit()
    _set_session_cookies(response, refresh)
    return TokenOut(access_token=access)


@router.post(
    "/register", response_model=UserOut, status_code=201,
    dependencies=[Depends(rate_limit_dep("register", settings.register_rate_limit_per_min))],
)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "email ya registrado")
    if db.query(User).filter(func.lower(User.nickname) == body.nickname.lower()).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "nickname ya está en uso")
    user = User(
        email=body.email, nickname=body.nickname,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Carrera: otro registro tomó el mismo email/nickname entre el chequeo y
        # el commit -> el unique de la BD es la última línea de defensa.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "email o nickname ya en uso")
    db.refresh(user)
    db.add(AuditLog(
        actor_id=user.id, action="register", resource=f"user:{user.id}",
        detail={"request_id": request.state.request_id},
    ))
    db.commit()
    return user


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    if not allow(f"login:{ip}", settings.login_rate_limit_per_min,
                 window_sec=settings.login_lockout_seconds):
        # Retry-After = ventana de bloqueo (30 min) -> el frontend lo usa para la
        # cuenta regresiva del botón "Entrar".
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "demasiados intentos",
            headers={"Retry-After": str(settings.login_lockout_seconds)},
        )

    user = db.query(User).filter(User.email == body.email).first()
    # verificación constante: siempre comparamos para no filtrar existencia por timing
    valid = user is not None and verify_password(body.password, user.password_hash)
    if not valid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "credenciales inválidas")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cuenta inactiva")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
        db.commit()

    db.add(AuditLog(
        actor_id=user.id, action="login", resource=f"user:{user.id}",
        detail={"request_id": request.state.request_id},
    ))
    db.commit()
    return _issue_tokens(db, user, response)


@router.post("/refresh", response_model=TokenOut)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    _verify_csrf(request)
    raw = request.cookies.get("refresh_token")
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sin sesión")

    payload = decode_token(raw)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh inválido")

    jti = payload["jti"]
    stored = db.query(RefreshToken).filter(RefreshToken.jti == jti).first()
    if not stored:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh desconocido")
    if stored.revoked:
        # reuso de token revocado => posible robo. Revoca toda la cadena del usuario.
        db.query(RefreshToken).filter(RefreshToken.user_id == stored.user_id).update(
            {RefreshToken.revoked: True}
        )
        db.commit()
        _clear_session_cookies(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh revocado")

    # rotación: invalida el actual, emite nuevo par
    stored.revoked = True
    db.commit()
    user = db.get(User, stored.user_id)
    if not user or not user.is_active:
        _clear_session_cookies(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "usuario inválido")
    return _issue_tokens(db, user, response)


@router.post("/logout", status_code=204)
def logout(
    request: Request, response: Response,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    _verify_csrf(request)
    raw = request.cookies.get("refresh_token")
    if raw:
        payload = decode_token(raw)
        if payload and payload.get("type") == "refresh":
            db.query(RefreshToken).filter(
                RefreshToken.jti == payload["jti"], RefreshToken.user_id == user.id
            ).update({RefreshToken.revoked: True})
            db.commit()
    _clear_session_cookies(response)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Sesiones (refresh tokens) activas del usuario autenticado."""
    now = datetime.now(timezone.utc)
    rows = db.query(RefreshToken).filter(
        RefreshToken.user_id == user.id,
        RefreshToken.revoked.is_(False),
        RefreshToken.expires_at > now,
    ).order_by(RefreshToken.created_at.desc()).all()
    return rows


@router.delete("/sessions/{jti}", status_code=204)
def revoke_session(jti: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Revoca una sesión propia por jti. Filtra por user_id -- anti-IDOR,
    no se puede revocar la sesión de otro usuario adivinando el jti."""
    updated = db.query(RefreshToken).filter(
        RefreshToken.jti == jti, RefreshToken.user_id == user.id,
    ).update({RefreshToken.revoked: True})
    db.commit()
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sesión no encontrada")
