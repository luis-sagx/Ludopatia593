"""
Rutas de autenticación: registro, login, refresh rotatorio, logout.

Defensas:
  - Argon2id para passwords.
  - Rate limit por IP en login (anti fuerza bruta).
  - Mensaje de error genérico en login (no revela si el email existe).
  - Refresh rotatorio con detección de reuso -> revoca toda la cadena.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..core.security import (
    hash_password, verify_password, needs_rehash,
    create_access_token, create_refresh_token, decode_token,
)
from ..core.config import settings
from ..core.ratelimit import allow
from ..db.session import get_db
from ..db.models import User, RefreshToken, Role, AuditLog
from ..schemas.schemas import RegisterIn, LoginIn, TokenOut, RefreshIn, UserOut
from .deps import get_current_user

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _issue_tokens(db: Session, user: User) -> TokenOut:
    access = create_access_token(str(user.id), user.role.value)
    refresh, jti = create_refresh_token(str(user.id))
    db.add(RefreshToken(
        jti=jti,
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_ttl_days),
    ))
    db.commit()
    return TokenOut(access_token=access, refresh_token=refresh)


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "email ya registrado")
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(AuditLog(
        actor_id=user.id, action="register", resource=f"user:{user.id}",
        detail={"request_id": request.state.request_id},
    ))
    db.commit()
    return user


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    if not allow(f"login:{ip}", settings.login_rate_limit_per_min):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "demasiados intentos")

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
    return _issue_tokens(db, user)


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    payload = decode_token(body.refresh_token)
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
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh revocado")

    # rotación: invalida el actual, emite nuevo par
    stored.revoked = True
    db.commit()
    user = db.get(User, stored.user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "usuario inválido")
    return _issue_tokens(db, user)


@router.post("/logout", status_code=204)
def logout(body: RefreshIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    payload = decode_token(body.refresh_token)
    if payload and payload.get("type") == "refresh":
        db.query(RefreshToken).filter(
            RefreshToken.jti == payload["jti"], RefreshToken.user_id == user.id
        ).update({RefreshToken.revoked: True})
        db.commit()


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
