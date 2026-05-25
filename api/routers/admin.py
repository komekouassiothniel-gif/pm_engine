"""
api/routers/admin.py — Actions d'administration système.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import delete, func, select, text

from api.deps import get_current_user, require_roles
from database import get_db
from models import (
    Alert,
    Execution,
    Import,
    NiveauAlerteEnum,
    Passage,
    RoleEnum,
    Site,
    StatutAlerteEnum,
    User,
)

router = APIRouter()


@router.delete(
    "/reset-system",
    summary="Réinitialiser le système",
    tags=["Administration"],
)
def reset_system(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(RoleEnum.admin)),
):
    """
    Vide les tables opérationnelles via TRUNCATE CASCADE (FK safe).
    Conserve intégralement la table users.
    Crée une alerte de traçabilité après la réinitialisation.
    """
    # ── 1. Compter avant suppression ─────────────────────────────────────────
    nb_exec     = db.execute(select(func.count()).select_from(Execution)).scalar()
    nb_passages = db.execute(select(func.count()).select_from(Passage)).scalar()
    nb_imports  = db.execute(select(func.count()).select_from(Import)).scalar()
    nb_alerts   = db.execute(select(func.count()).select_from(Alert)).scalar()
    nb_sites    = db.execute(select(func.count()).select_from(Site)).scalar()

    # ── 2. TRUNCATE avec CASCADE (respecte les FK automatiquement) ────────────
    db.execute(text(
        "TRUNCATE TABLE executions, passages, imports, alerts, sites "
        "RESTART IDENTITY CASCADE"
    ))
    db.commit()

    # ── 3. Alerte de traçabilité ──────────────────────────────────────────────
    now_str = datetime.now(timezone.utc).strftime("%d/%m/%Y à %H:%M UTC")
    traçabilite = Alert(
        niveau=NiveauAlerteEnum.information,
        type_alerte="reset_systeme",
        site_id=None,
        message=f"Système réinitialisé par {current_user.email} le {now_str}",
        detail=None,
        statut=StatutAlerteEnum.nouvelle,
    )
    db.add(traçabilite)
    db.commit()

    return {
        "message": "Système réinitialisé avec succès",
        "deleted": {
            "executions": nb_exec,
            "passages":   nb_passages,
            "imports":    nb_imports,
            "alertes":    nb_alerts,
            "sites":      nb_sites,
        },
    }
