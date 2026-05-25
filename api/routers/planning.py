import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, case, delete, func, select
from sqlalchemy.orm import Session, joinedload

from api.deps import get_current_user, require_roles, sbc_scope
from database import get_db
from models import (
    Alert, CategorieEnum, Execution, NiveauAlerteEnum,
    Passage, RoleEnum, SBCEnum, Site,
    StatutAlerteEnum, StatutImportEnum, StatutPassageEnum, User,
)
from planning_engine import (
    detect_missed_passages, generate_planning, replan_missed_passages,
)
from schemas.common import PaginatedResponse
from schemas.passage import (
    PassageResponse, PassageStatusUpdate,
    PlanningGenerateRequest, PlanningReplanRequest, PlanningStats,
)

router = APIRouter()

MOIS_NOMS = [
    'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
    'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre',
]


# ---------------------------------------------------------------------------
# Helpers de conversion ORM ↔ dict moteur
# ---------------------------------------------------------------------------

def _site_to_dict(s: Site) -> dict:
    return {
        "code_site": s.code_site, "nom": s.nom,
        "categorie": s.categorie.value, "sbc": s.sbc.value,
        "sto": s.sto, "region": s.region, "cycle": s.cycle,
    }


def _passage_to_engine_dict(p: Passage) -> dict:
    return {
        "_db_id": p.id,
        "code_site": p.site.code_site,
        "categorie": p.site.categorie.value,
        "sbc": p.site.sbc.value,
        "sto": p.site.sto,
        "passage_num": p.passage_num,
        "total_passages": p.total_passages,
        "mois_num": p.mois_num,
        "mois_nom": p.mois_nom,
        "date_planifiee": p.date_planifiee,
        "statut": "impossible_a_rattraper" if p.impossible_a_rattraper else p.statut.value,
        "date_execution": p.execution.date_execution if p.execution else None,
        "wo_ticket": p.execution.wo_ticket if p.execution else None,
    }


def _row_to_stats(row) -> dict:
    t = row.total or 0
    f = row.faits or 0
    return {
        "total": t, "faits": f,
        "non_effectues": row.non_effectues or 0,
        "en_retard": row.en_retard or 0,
        "a_venir": row.a_venir or 0,
        "taux_realisation": round(f / t, 4) if t > 0 else 0.0,
    }


def _compute_stats(db: Session, annee: int, sbc_filter: Optional[str] = None) -> dict:
    today = date.today()
    d7  = today - timedelta(days=7)
    d30 = today - timedelta(days=30)
    mois_courant_num = today.month

    conditions = [Passage.annee == annee]
    if sbc_filter:
        conditions.append(Site.sbc == SBCEnum(sbc_filter))

    fait_c    = case((Passage.statut == StatutPassageEnum.Fait, 1))
    non_eff_c = case((Passage.statut == StatutPassageEnum.Non_effectue, 1))
    retard_c  = case((and_(Passage.statut == StatutPassageEnum.Prevu, Passage.date_planifiee < today), 1))
    avenir_c  = case((and_(Passage.statut == StatutPassageEnum.Prevu, Passage.date_planifiee >= today), 1))

    # ── Agrégat global ────────────────────────────────────────────────────
    agg = (
        select(
            func.count().label("total"),
            func.count(fait_c).label("faits"),
            func.count(non_eff_c).label("non_effectues"),
            func.count(retard_c).label("en_retard"),
            func.count(avenir_c).label("a_venir"),
        )
        .select_from(Passage).join(Site)
        .where(*conditions)
    )
    row = db.execute(agg).first()

    def by_group(group_col):
        return db.execute(
            select(group_col,
                   func.count().label("total"),
                   func.count(fait_c).label("faits"),
                   func.count(non_eff_c).label("non_effectues"),
                   func.count(retard_c).label("en_retard"),
                   func.count(avenir_c).label("a_venir"))
            .select_from(Passage).join(Site)
            .where(*conditions)
            .group_by(group_col)
        ).all()

    par_sbc  = {r[0].value: _row_to_stats(r) for r in by_group(Site.sbc)}
    par_sto  = {r[0]: _row_to_stats(r)        for r in by_group(Site.sto)}
    par_cat  = {r[0].value: _row_to_stats(r)  for r in by_group(Site.categorie)}
    par_mois = {r[0]: _row_to_stats(r)        for r in db.execute(
        select(Passage.mois_num,
               func.count().label("total"),
               func.count(fait_c).label("faits"),
               func.count(non_eff_c).label("non_effectues"),
               func.count(retard_c).label("en_retard"),
               func.count(avenir_c).label("a_venir"))
        .select_from(Passage).join(Site)
        .where(*conditions)
        .group_by(Passage.mois_num).order_by(Passage.mois_num)
    ).all()}

    total = row.total or 0
    faits = row.faits or 0

    # ── Retards par ancienneté ─────────────────────────────────────────────
    anc_moins_7j = case((and_(
        Passage.statut == StatutPassageEnum.Prevu,
        Passage.date_planifiee >= d7,
        Passage.date_planifiee < today,
    ), 1))
    anc_j7_30 = case((and_(
        Passage.statut == StatutPassageEnum.Prevu,
        Passage.date_planifiee >= d30,
        Passage.date_planifiee < d7,
    ), 1))
    anc_plus_30 = case((and_(
        Passage.statut == StatutPassageEnum.Prevu,
        Passage.date_planifiee < d30,
    ), 1))

    anc_row = db.execute(
        select(
            func.count(anc_moins_7j).label("moins_7j"),
            func.count(anc_j7_30).label("j7_a_30j"),
            func.count(anc_plus_30).label("plus_30j"),
        ).select_from(Passage).join(Site).where(*conditions)
    ).first()

    retards_par_anciennete = {
        "moins_7j": anc_row.moins_7j or 0,
        "j7_a_30j": anc_row.j7_a_30j or 0,
        "plus_30j":  anc_row.plus_30j or 0,
    }

    # ── Projection annuelle ────────────────────────────────────────────────
    mois_ecoules = mois_courant_num
    cadence = round(faits / mois_ecoules, 1) if mois_ecoules > 0 else 0.0
    projection_fin_annee = round(cadence * 12)
    ecart_projection = projection_fin_annee - total
    taux_projection = round(projection_fin_annee / total, 4) if total > 0 else 0.0

    projection = {
        "mois_ecoules": mois_ecoules,
        "cadence_actuelle": cadence,
        "projection_fin_annee": projection_fin_annee,
        "objectif_annuel": total,
        "ecart_projection": ecart_projection,
        "taux_projection": taux_projection,
    }

    # ── Mois courant ───────────────────────────────────────────────────────
    mc_stats = par_mois.get(mois_courant_num, {"total": 0, "faits": 0})
    planifie_ce_mois  = mc_stats["total"]
    faits_ce_mois_all = mc_stats["faits"]
    taux_mois = round(faits_ce_mois_all / planifie_ce_mois, 4) if planifie_ce_mois > 0 else 0.0

    if mois_courant_num > 1:
        faits_prec = sum(
            par_mois.get(m, {"faits": 0})["faits"] for m in range(1, mois_courant_num)
        )
        moyenne_mois_precedents = round(faits_prec / (mois_courant_num - 1))
    else:
        moyenne_mois_precedents = 0

    mois_courant = {
        "nom": MOIS_NOMS[mois_courant_num - 1],
        "planifie_ce_mois": planifie_ce_mois,
        "faits_ce_mois": faits_ce_mois_all,
        "taux_mois": taux_mois,
        "moyenne_mois_precedents": moyenne_mois_precedents,
    }

    # ── Performance SBC enrichie ───────────────────────────────────────────
    sbc_mois_cond = [Passage.annee == annee, Passage.mois_num == mois_courant_num]
    if sbc_filter:
        sbc_mois_cond.append(Site.sbc == SBCEnum(sbc_filter))

    sbc_mois_rows = db.execute(
        select(Site.sbc, func.count(fait_c).label("faits_ce_mois"))
        .select_from(Passage).join(Site)
        .where(*sbc_mois_cond)
        .group_by(Site.sbc)
    ).all()
    faits_mois_par_sbc = {r[0].value: (r.faits_ce_mois or 0) for r in sbc_mois_rows}

    sbc_perf_list = [
        {
            "sbc": sbc_name,
            "total_planifie": stats["total"],
            "faits": stats["faits"],
            "en_retard": stats["en_retard"],
            "taux": stats["taux_realisation"],
            "cible_mensuelle": round(stats["total"] / 12) if stats["total"] > 0 else 0,
            "faits_ce_mois": faits_mois_par_sbc.get(sbc_name, 0),
            "rang": 0,
        }
        for sbc_name, stats in par_sbc.items()
    ]
    sbc_perf_list.sort(key=lambda x: x["taux"], reverse=True)
    for i, item in enumerate(sbc_perf_list):
        item["rang"] = i + 1

    # ── Bottom performers ──────────────────────────────────────────────────
    sites_crit_cond = [
        Passage.annee == annee,
        Passage.statut == StatutPassageEnum.Prevu,
        Passage.date_planifiee < d30,
    ]
    if sbc_filter:
        sites_crit_cond.append(Site.sbc == SBCEnum(sbc_filter))

    sites_crit_rows = db.execute(
        select(Site.sbc, func.count(Site.id.distinct()).label("cnt"))
        .select_from(Passage).join(Site)
        .where(*sites_crit_cond)
        .group_by(Site.sbc)
    ).all()
    sites_critiques_par_sbc = {r[0].value: (r.cnt or 0) for r in sites_crit_rows}

    bottom_performers = sorted(
        [
            {
                "sbc": sbc_name,
                "retards": stats["en_retard"],
                "taux": stats["taux_realisation"],
                "sites_critiques": sites_critiques_par_sbc.get(sbc_name, 0),
            }
            for sbc_name, stats in par_sbc.items()
        ],
        key=lambda x: x["retards"], reverse=True,
    )

    # ── Retards par STO ────────────────────────────────────────────────────
    retards_par_sto = sorted(
        [
            {"sto": sto_name, "retards": stats["en_retard"], "taux": stats["taux_realisation"]}
            for sto_name, stats in par_sto.items()
        ],
        key=lambda x: x["retards"], reverse=True,
    )

    # ── Tendance retards — 7 derniers jours ───────────────────────────────
    tendance_retards = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        cnt = db.execute(
            select(func.count()).select_from(Passage).join(Site)
            .where(
                *conditions,
                Passage.date_planifiee < d,
                Passage.statut != StatutPassageEnum.Fait,
            )
        ).scalar() or 0
        tendance_retards.append({"date": d, "retards": cnt})

    return {
        "total": total, "faits": faits,
        "non_effectues": row.non_effectues or 0,
        "en_retard": row.en_retard or 0,
        "a_venir": row.a_venir or 0,
        "taux_realisation": round(faits / total, 4) if total > 0 else 0.0,
        "par_sbc": par_sbc, "par_sto": par_sto,
        "par_categorie": par_cat, "par_mois": par_mois,
        # Nouveau
        "retards_par_anciennete": retards_par_anciennete,
        "projection": projection,
        "mois_courant": mois_courant,
        "par_sbc_perf": sbc_perf_list,
        "bottom_performers": bottom_performers,
        "retards_par_sto": retards_par_sto,
        "tendance_retards": tendance_retards,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/stats", response_model=PlanningStats, summary="KPIs globaux dashboard")
def get_stats(
    annee: int = Query(2026),
    sbc: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sbc = sbc_scope(sbc, current_user)
    return _compute_stats(db, annee, sbc)


@router.get("", response_model=PaginatedResponse[PassageResponse], summary="Planning complet")
def list_planning(
    annee: int = Query(2026),
    sbc: Optional[str] = Query(None),
    sto: Optional[str] = Query(None),
    mois_num: Optional[int] = Query(None, ge=1, le=12),
    statut: Optional[StatutPassageEnum] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sbc = sbc_scope(sbc, current_user)
    stmt = (
        select(Passage)
        .join(Site)
        .options(joinedload(Passage.site), joinedload(Passage.execution))
        .where(Passage.annee == annee)
    )
    if sbc:
        try:
            stmt = stmt.where(Site.sbc == SBCEnum(sbc))
        except ValueError:
            raise HTTPException(400, f"SBC invalide : {sbc}")
    if sto:
        stmt = stmt.where(Site.sto == sto)
    if mois_num:
        stmt = stmt.where(Passage.mois_num == mois_num)
    if statut:
        stmt = stmt.where(Passage.statut == statut)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    items = db.execute(stmt.order_by(Passage.date_planifiee).offset(skip).limit(limit)).scalars().all()
    return PaginatedResponse(total=total, skip=skip, limit=limit, items=items)


@router.get("/{passage_id}", response_model=PassageResponse, summary="Détail d'un passage")
def get_passage(
    passage_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    p = db.execute(
        select(Passage)
        .options(joinedload(Passage.site), joinedload(Passage.execution))
        .where(Passage.id == passage_id)
    ).scalar_one_or_none()
    if not p:
        raise HTTPException(404, f"Passage {passage_id} introuvable")
    return p


@router.patch("/{passage_id}/statut", response_model=PassageResponse, summary="Mettre à jour le statut")
def update_passage_statut(
    passage_id: int,
    data: PassageStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    p = db.execute(
        select(Passage)
        .options(joinedload(Passage.site), joinedload(Passage.execution))
        .where(Passage.id == passage_id)
    ).scalar_one_or_none()
    if not p:
        raise HTTPException(404, f"Passage {passage_id} introuvable")

    p.statut = data.statut

    if data.statut == StatutPassageEnum.Fait:
        if not data.date_execution or not data.wo_ticket:
            raise HTTPException(400, "date_execution et wo_ticket sont requis pour marquer Fait")

        if p.execution:
            p.execution.date_execution = data.date_execution
            p.execution.wo_ticket = data.wo_ticket
        else:
            exec_obj = Execution(
                passage_id=p.id,
                site_id=p.site_id,
                date_execution=data.date_execution,
                wo_ticket=data.wo_ticket,
            )
            db.add(exec_obj)

    db.commit()
    db.refresh(p)
    return p


@router.post("/generer", status_code=201, summary="Générer le planning annuel")
def generer_planning(
    data: PlanningGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(RoleEnum.admin, RoleEnum.manager)),
):
    """
    Génère (ou régénère si force=True) le planning annuel complet
    en appelant generate_planning() du moteur.
    """
    existing = db.execute(
        select(func.count(Passage.id)).where(Passage.annee == data.annee)
    ).scalar()

    if existing > 0 and not data.force:
        raise HTTPException(
            400,
            f"Un planning de {existing} passages existe déjà pour {data.annee}. "
            "Utilisez force=true pour écraser.",
        )

    # Charger les sites actifs
    sites_orm = db.execute(select(Site).where(Site.actif == True)).scalars().all()
    if not sites_orm:
        raise HTTPException(400, "Aucun site actif trouvé en base")
    sites_dicts = [_site_to_dict(s) for s in sites_orm]
    site_id_map = {s.code_site: s.id for s in sites_orm}

    # Historique d'exécution existant
    exec_rows = db.execute(
        select(Execution, Passage, Site)
        .join(Passage, Execution.passage_id == Passage.id)
        .join(Site, Passage.site_id == Site.id)
    ).all()
    exec_history = [
        {
            "code_site": site.code_site,
            "mois_num": passage.mois_num,
            "date_exec": exec_.date_execution,
            "wo_ticket": exec_.wo_ticket,
        }
        for exec_, passage, site in exec_rows
    ]

    # Génération moteur
    planning_dicts = generate_planning(sites_dicts, year=data.annee, exec_history=exec_history)

    # Supprimer l'existant si force
    if data.force and existing > 0:
        db.execute(delete(Passage).where(Passage.annee == data.annee))
        db.flush()

    # Insérer les nouveaux passages
    for p_dict in planning_dicts:
        statut_str = p_dict.get("statut", "Prevu")
        if statut_str == "impossible_a_rattraper":
            statut = StatutPassageEnum.Non_effectue
            impossible = True
        else:
            statut = StatutPassageEnum[statut_str]
            impossible = False

        db.add(Passage(
            site_id=site_id_map[p_dict["code_site"]],
            passage_num=p_dict["passage_num"],
            total_passages=p_dict["total_passages"],
            mois_num=p_dict["mois_num"],
            mois_nom=p_dict["mois_nom"],
            annee=data.annee,
            date_planifiee=p_dict["date_planifiee"],
            statut=statut,
            impossible_a_rattraper=impossible,
        ))

    db.commit()
    return {"annee": data.annee, "passages_crees": len(planning_dicts), "force": data.force}


@router.post("/replanifier", summary="Re-planifier les passages en retard")
def replanifier(
    data: PlanningReplanRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(RoleEnum.admin, RoleEnum.manager)),
):
    """
    Détecte les passages manqués et les re-planifie via replan_missed_passages().
    Génère des alertes pour les passages impossibles à rattraper.
    """
    ref = data.reference_date or date.today()

    # Charger le planning complet avec relations
    passages_orm = db.execute(
        select(Passage)
        .join(Site)
        .options(joinedload(Passage.site), joinedload(Passage.execution))
        .where(Passage.annee == data.annee)
    ).scalars().all()

    if not passages_orm:
        raise HTTPException(404, f"Aucun passage trouvé pour l'année {data.annee}")

    # Convertir en dicts moteur (avec _db_id pour rétro-référence)
    planning_dicts = [_passage_to_engine_dict(p) for p in passages_orm]
    db_id_map = {(d["code_site"], d["passage_num"]): d["_db_id"] for d in planning_dicts}

    sites_orm = db.execute(select(Site).where(Site.actif == True)).scalars().all()
    sites_dicts = [_site_to_dict(s) for s in sites_orm]

    updated, alertes = replan_missed_passages(
        planning_dicts, sites_dicts, year=data.annee, reference_date=ref
    )

    # Appliquer les modifications en DB
    replanifies, impossibles = 0, 0
    orig_map = {(d["code_site"], d["passage_num"]): d for d in planning_dicts}

    for upd in updated:
        key = (upd["code_site"], upd["passage_num"])
        orig = orig_map.get(key)
        if not orig:
            continue

        db_id = db_id_map.get(key)
        if not db_id:
            continue

        passage_db = db.get(Passage, db_id)
        if not passage_db:
            continue

        if upd["statut"] == "impossible_a_rattraper":
            passage_db.impossible_a_rattraper = True
            passage_db.statut = StatutPassageEnum.Non_effectue
            impossibles += 1
        elif orig["date_planifiee"] != upd["date_planifiee"]:
            if not passage_db.date_planifiee_initiale:
                passage_db.date_planifiee_initiale = orig["date_planifiee"]
            passage_db.date_planifiee = upd["date_planifiee"]
            passage_db.mois_num = upd["mois_num"]
            passage_db.mois_nom = upd["mois_nom"]
            passage_db.is_replanifie = True
            replanifies += 1

    # Créer les alertes DB
    for alerte in alertes:
        site_id = None
        site_obj = db.execute(
            select(Site).where(Site.code_site == alerte["code_site"])
        ).scalar_one_or_none()
        if site_obj:
            site_id = site_obj.id
        db.add(Alert(
            niveau=NiveauAlerteEnum.critique,
            type_alerte="replanification",
            site_id=site_id,
            message=alerte["message"],
            statut=StatutAlerteEnum.nouvelle,
        ))

    db.commit()
    return {
        "reference_date": ref,
        "replanifies": replanifies,
        "impossibles": impossibles,
        "alertes_creees": len(alertes),
    }
