"""
database.py
Connexion PostgreSQL, session SQLAlchemy 2.x et helpers pour FastAPI.
"""

import os
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()

# ---------------------------------------------------------------------------
# Engine & SessionFactory
# ---------------------------------------------------------------------------

DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/pm_mtn_db",
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,   # vérifie la connexion avant chaque usage
    pool_size=5,
    max_overflow=10,
    echo=os.getenv("DEBUG", "False").lower() == "true",
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    class_=Session,
)


# ---------------------------------------------------------------------------
# Dépendance FastAPI
# ---------------------------------------------------------------------------

def get_db() -> Generator[Session, None, None]:
    """
    Injecteur de dépendance FastAPI.

    Usage dans un router :
        @router.get("/")
        def endpoint(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def init_db() -> None:
    """
    Crée toutes les tables déclarées dans models.py si elles n'existent pas.
    À utiliser en développement ou au premier démarrage.
    En production, préférer les migrations Alembic.
    """
    from models import Base  # import local pour éviter les imports circulaires
    Base.metadata.create_all(bind=engine)


def check_db_connection() -> bool:
    """Vérifie que la base de données est accessible. Retourne True si OK."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        print(f"[DB] Connexion impossible : {exc}")
        return False
