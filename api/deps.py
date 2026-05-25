"""
api/deps.py — Dépendances partagées : JWT, authentification, contrôle des rôles.
"""
import hashlib
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models import RoleEnum, User

# ---------------------------------------------------------------------------
# Constantes JWT
# ---------------------------------------------------------------------------

SECRET_KEY: str = os.getenv("SECRET_KEY", "changeme-dev-key")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 8

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


# ---------------------------------------------------------------------------
# Helpers mot de passe
# ---------------------------------------------------------------------------

def verify_password(plain: str, hashed: str) -> bool:
    """Vérifie bcrypt. Fallback SHA-256 pour compatibilité avec seed.py initial."""
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
        return hashlib.sha256(plain.encode()).hexdigest() == hashed


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def create_access_token(user_id: int, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {"sub": str(user_id), "role": role, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


# ---------------------------------------------------------------------------
# Dépendances FastAPI
# ---------------------------------------------------------------------------

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalide ou expiré",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise exc
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: Optional[str] = payload.get("sub")
        if not user_id:
            raise exc
    except JWTError:
        raise exc

    user = db.execute(select(User).where(User.id == int(user_id))).scalar_one_or_none()
    if not user or not user.actif:
        raise HTTPException(status_code=401, detail="Utilisateur inactif ou introuvable")
    return user


def require_roles(*allowed: RoleEnum):
    """
    Fabrique de dépendance.
    Usage : user: User = Depends(require_roles(RoleEnum.admin, RoleEnum.manager))
    """
    def check(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed:
            roles_str = ", ".join(r.value for r in allowed)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Rôle requis : {roles_str}",
            )
        return current_user
    return check


def sbc_scope(sbc: Optional[str], current_user: User) -> Optional[str]:
    """
    Pour un utilisateur SBC, force le filtre sur son périmètre.
    Les autres rôles peuvent filtrer librement.
    """
    if current_user.role == RoleEnum.sbc:
        return current_user.sbc_associe
    return sbc
