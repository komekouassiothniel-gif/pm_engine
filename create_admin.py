"""
create_admin.py
Crée l'utilisateur admin dans la base de données si il n'existe pas encore.
Usage : python create_admin.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import select

from api.deps import hash_password
from database import SessionLocal, init_db
from models import RoleEnum, User


def create_admin() -> None:
    init_db()
    db = SessionLocal()
    try:
        existing = db.execute(
            select(User).where(User.email == "admin@mtn-ci.com")
        ).scalar_one_or_none()

        if existing:
            print("Admin déjà existant")
            return

        admin = User(
            nom="Administrateur",
            email="admin@mtn-ci.com",
            password_hash=hash_password("Admin2026!"),
            role=RoleEnum.admin,
            actif=True,
        )
        db.add(admin)
        db.commit()
        print("Admin créé")
    finally:
        db.close()


if __name__ == "__main__":
    create_admin()
