"""
Dependencias de autenticación y autorización (RBAC, mínimo privilegio).
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from ..core.security import decode_token
from ..db.session import get_db
from ..db.models import User, Role

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "falta token")
    payload = decode_token(creds.credentials)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token inválido")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "usuario inválido")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Segregación admin/usuario: solo rol admin pasa."""
    if user.role != Role.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "requiere admin")
    return user
