import re, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator
from models import CategorieEnum, SBCEnum, StatutPassageEnum


class SiteCreate(BaseModel):
    code_site: str
    nom: str
    categorie: CategorieEnum
    sbc: SBCEnum
    sto: str
    region: str
    type_alimentation: Optional[str] = None
    cycle: Optional[str] = None
    date_acceptance: Optional[date] = None
    date_handover: Optional[date] = None
    techno: Optional[str] = None
    passive_handler: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    priorite: Optional[str] = None
    typologie: Optional[str] = None

    @field_validator("code_site")
    @classmethod
    def validate_code_site(cls, v: str) -> str:
        if not re.match(r"^CI\d{5}$", v.upper()):
            raise ValueError('Format invalide : attendu "CI" + 5 chiffres (ex: CI01234)')
        return v.upper()

    @field_validator("cycle")
    @classmethod
    def validate_cycle(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("A", "B", "C"):
            raise ValueError("Le cycle doit être A, B ou C")
        return v


class SiteUpdate(BaseModel):
    nom: Optional[str] = None
    categorie: Optional[CategorieEnum] = None
    sbc: Optional[SBCEnum] = None
    sto: Optional[str] = None
    region: Optional[str] = None
    type_alimentation: Optional[str] = None
    cycle: Optional[str] = None
    date_acceptance: Optional[date] = None
    date_handover: Optional[date] = None
    techno: Optional[str] = None
    passive_handler: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    priorite: Optional[str] = None
    typologie: Optional[str] = None
    actif: Optional[bool] = None


class SiteResponse(BaseModel):
    id: int
    code_site: str
    nom: str
    categorie: CategorieEnum
    sbc: SBCEnum
    sto: str
    region: str
    type_alimentation: Optional[str]
    cycle: Optional[str]
    actif: bool
    date_acceptance: Optional[date]
    date_handover: Optional[date]
    techno: Optional[str]
    passive_handler: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    priorite: Optional[str]
    typologie: Optional[str]
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class SiteMinimal(BaseModel):
    id: int
    code_site: str
    nom: str
    categorie: CategorieEnum
    sbc: SBCEnum
    sto: str
    model_config = ConfigDict(from_attributes=True)


class SiteStats(BaseModel):
    total_passages_annee: int
    passages_faits: int
    passages_en_retard: int
    passages_a_venir: int
    taux_realisation: float
    dernier_passage: Optional[date] = None
    prochain_passage: Optional[date] = None


class PassageHistorique(BaseModel):
    id: int
    mois: str
    passage_num: str
    date_planifiee: date
    statut: str
    date_execution: Optional[date] = None
    wo_ticket: Optional[str] = None
    niveau_carburant: Optional[int] = None
    ch_ge: Optional[int] = None
    tension_batterie: Optional[float] = None
    snags: Optional[str] = None
    observations: Optional[str] = None


class SnagRecurrent(BaseModel):
    description: str
    count: int
    derniere_date: Optional[date] = None


class SiteDetailResponse(SiteResponse):
    marque_ge: Optional[str] = None
    puissance_ge: Optional[int] = None
    stats: SiteStats
    historique: list[PassageHistorique]
    snags_recurrents: list[SnagRecurrent]
    model_config = ConfigDict(from_attributes=False)
