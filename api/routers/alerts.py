import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import get_current_user, sbc_scope
from database import get_db
from models import Alert, NiveauAlerteEnum, StatutAlerteEnum, User
from schemas.alert import AlertResponse, AlertUpdate
from schemas.common import PaginatedResponse

router = APIRouter()


@router.get("", response_model=PaginatedResponse[AlertResponse], summary="Liste des alertes")
def list_alerts(
    niveau: Optional[NiveauAlerteEnum] = Query(None),
    statut: Optional[StatutAlerteEnum] = Query(None, description="Défaut : toutes sauf fermée"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Alert)
    if niveau:
        stmt = stmt.where(Alert.niveau == niveau)
    if statut:
        stmt = stmt.where(Alert.statut == statut)
    else:
        stmt = stmt.where(Alert.statut != StatutAlerteEnum.fermee)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    items = db.execute(
        stmt.order_by(Alert.created_at.desc()).offset(skip).limit(limit)
    ).scalars().all()
    return PaginatedResponse(total=total, skip=skip, limit=limit, items=items)


@router.get("/count", summary="Nombre d'alertes nouvelles (badge)")
def count_new_alerts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    n = db.execute(
        select(func.count(Alert.id)).where(Alert.statut == StatutAlerteEnum.nouvelle)
    ).scalar()
    return {"count": n}


@router.get("/{alert_id}", response_model=AlertResponse, summary="Détail d'une alerte")
def get_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(404, f"Alerte {alert_id} introuvable")
    return a


@router.patch("/{alert_id}", response_model=AlertResponse, summary="Mettre à jour une alerte")
def update_alert(
    alert_id: int,
    data: AlertUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(404, f"Alerte {alert_id} introuvable")
    a.statut = data.statut
    if data.commentaire is not None:
        a.commentaire = data.commentaire
    if data.statut == StatutAlerteEnum.prise_en_charge:
        a.prise_en_charge_par = current_user.id
    db.commit()
    db.refresh(a)
    return a


@router.delete("/{alert_id}", status_code=204, summary="Fermer une alerte")
def close_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(404, f"Alerte {alert_id} introuvable")
    a.statut = StatutAlerteEnum.fermee
    db.commit()
