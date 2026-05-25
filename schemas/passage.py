import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict
from models import StatutPassageEnum
from schemas.site import SiteMinimal
from schemas.execution import ExecutionMinimal


class PassageResponse(BaseModel):
    id: int
    site_id: int
    site: SiteMinimal
    execution: Optional[ExecutionMinimal]
    passage_num: int
    total_passages: int
    mois_num: int
    mois_nom: str
    annee: int
    date_planifiee: date
    date_planifiee_initiale: Optional[date]
    statut: StatutPassageEnum
    is_replanifie: bool
    impossible_a_rattraper: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PassageStatusUpdate(BaseModel):
    statut: StatutPassageEnum
    date_execution: Optional[date] = None
    wo_ticket: Optional[str] = None


class PlanningGenerateRequest(BaseModel):
    annee: int = 2026
    force: bool = False


class PlanningReplanRequest(BaseModel):
    annee: int = 2026
    reference_date: Optional[date] = None


class StatsByGroup(BaseModel):
    total: int
    faits: int
    non_effectues: int
    en_retard: int
    a_venir: int
    taux_realisation: float


class RetardsAnciennete(BaseModel):
    moins_7j: int
    j7_a_30j: int
    plus_30j: int


class Projection(BaseModel):
    mois_ecoules: int
    cadence_actuelle: float
    projection_fin_annee: int
    objectif_annuel: int
    ecart_projection: int
    taux_projection: float


class MoisCourant(BaseModel):
    nom: str
    planifie_ce_mois: int
    faits_ce_mois: int
    taux_mois: float
    moyenne_mois_precedents: int


class SBCPerf(BaseModel):
    sbc: str
    total_planifie: int
    faits: int
    en_retard: int
    taux: float
    cible_mensuelle: int
    faits_ce_mois: int
    rang: int


class BottomPerformer(BaseModel):
    sbc: str
    retards: int
    taux: float
    sites_critiques: int


class STORetards(BaseModel):
    sto: str
    retards: int
    taux: float


class TendanceJour(BaseModel):
    date: date
    retards: int


class PlanningStats(BaseModel):
    # Existant
    total: int
    faits: int
    non_effectues: int
    en_retard: int
    a_venir: int
    taux_realisation: float
    par_sbc: dict[str, StatsByGroup]
    par_sto: dict[str, StatsByGroup]
    par_categorie: dict[str, StatsByGroup]
    par_mois: dict[int, StatsByGroup]
    # Nouveau
    retards_par_anciennete: RetardsAnciennete
    projection: Projection
    mois_courant: MoisCourant
    par_sbc_perf: list[SBCPerf]
    bottom_performers: list[BottomPerformer]
    retards_par_sto: list[STORetards]
    tendance_retards: list[TendanceJour]
