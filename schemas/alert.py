import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict
from models import NiveauAlerteEnum, StatutAlerteEnum


class AlertResponse(BaseModel):
    id: int
    niveau: NiveauAlerteEnum
    type_alerte: str
    site_id: Optional[int]
    message: str
    detail: Optional[str]
    statut: StatutAlerteEnum
    prise_en_charge_par: Optional[int]
    commentaire: Optional[str]
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AlertUpdate(BaseModel):
    statut: StatutAlerteEnum
    commentaire: Optional[str] = None
