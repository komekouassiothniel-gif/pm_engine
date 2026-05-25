"""
alembic/env.py
Configuration de l'environnement Alembic pour le projet PM MTN CI.

Commandes à exécuter pour la première migration :
    alembic revision --autogenerate -m "init"
    alembic upgrade head

Pour les migrations suivantes :
    alembic revision --autogenerate -m "description_du_changement"
    alembic upgrade head

Rollback :
    alembic downgrade -1        # recule d'une version
    alembic downgrade base      # revient à zéro
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

# --- Résolution du chemin parent pour importer models.py ---
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

load_dotenv(ROOT_DIR / ".env")

# Import des métadonnées — déclenche la découverte de tous les modèles
from models import Base  # noqa: E402

# --- Config Alembic ---
config = context.config

# Surcharger l'URL depuis la variable d'environnement
_db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/pm_mtn_db")
config.set_main_option("sqlalchemy.url", _db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Cible pour l'autogenerate : tous les modèles déclarés dans Base
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Mode offline (génère le SQL sans se connecter à la DB)
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Mode online (connexion réelle à la DB)
# ---------------------------------------------------------------------------

def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
