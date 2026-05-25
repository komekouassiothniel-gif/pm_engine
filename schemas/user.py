import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr
from models import RoleEnum


class UserCreate(BaseModel):
    nom: str
    email: EmailStr
    password: str
    role: RoleEnum = RoleEnum.sbc
    sbc_associe: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    nom: str
    email: str
    role: RoleEnum
    sbc_associe: Optional[str]
    actif: bool
    derniere_connexion: Optional[datetime]
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
