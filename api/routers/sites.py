import sys, os, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import io
from datetime import date
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session

from api.deps import get_current_user, require_roles, sbc_scope
from database import get_db
from models import (
    Alert, CategorieEnum, Execution, NiveauAlerteEnum, Passage,
    RoleEnum, SBCEnum, Site, StatutAlerteEnum, StatutPassageEnum, User,
)
from planning_engine import generate_planning
from schemas.common import PaginatedResponse
from schemas.site import SiteCreate, SiteDetailResponse, SiteResponse, SiteUpdate

router = APIRouter()


# ── Helpers de parsing Excel ────────────────────────────────────────────────────

def _safe_str(val) -> Optional[str]:
    s = str(val or '').strip()
    return None if s in ('', 'nan', 'NaT', 'None', 'NaN') else s

def _safe_float(val) -> Optional[float]:
    try:
        return float(val) if pd.notna(val) else None
    except (TypeError, ValueError):
        return None

def _safe_date_from_excel(val) -> Optional[date]:
    try:
        d = pd.to_datetime(val)
        return None if pd.isna(d) else d.date()
    except Exception:
        return None


def _get_site_or_404(db: Session, code_site: str) -> Site:
    site = db.execute(
        select(Site).where(Site.code_site == code_site)
    ).scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail=f"Site {code_site} introuvable")
    return site


@router.get("", response_model=PaginatedResponse[SiteResponse], summary="Liste des sites")
def list_sites(
    sbc: Optional[str] = Query(None),
    sto: Optional[str] = Query(None),
    categorie: Optional[CategorieEnum] = Query(None),
    actif: Optional[bool] = Query(True),
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sbc = sbc_scope(sbc, current_user)

    stmt = select(Site)
    if sbc:
        try:
            stmt = stmt.where(Site.sbc == SBCEnum(sbc))
        except ValueError:
            raise HTTPException(400, f"SBC invalide : {sbc}")
    if sto:
        stmt = stmt.where(Site.sto == sto)
    if categorie:
        stmt = stmt.where(Site.categorie == categorie)
    if actif is not None:
        stmt = stmt.where(Site.actif == actif)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(Site.code_site.ilike(pattern), Site.nom.ilike(pattern))
        )

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    items = db.execute(stmt.offset(skip).limit(limit)).scalars().all()

    return PaginatedResponse(total=total, skip=skip, limit=limit, items=items)


@router.get("/stats/resume", summary="Résumé des sites")
def site_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = db.execute(
        select(Site.categorie, Site.sbc, func.count().label("n"))
        .where(Site.actif == True)
        .group_by(Site.categorie, Site.sbc)
    ).all()
    return {"par_categorie_sbc": [{"categorie": r.categorie.value, "sbc": r.sbc.value, "total": r.n} for r in rows]}


@router.get("/{code_site}/detail", response_model=SiteDetailResponse, summary="Détail complet d'un site avec stats et historique")
def get_site_detail(
    code_site: str,
    annee: int = Query(2026),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    site = _get_site_or_404(db, code_site)
    today = date.today()

    passages = db.execute(
        select(Passage)
        .where(Passage.site_id == site.id, Passage.annee == annee)
        .order_by(Passage.mois_num, Passage.passage_num)
    ).scalars().all()

    total = len(passages)
    n_faits = sum(1 for p in passages if p.statut == StatutPassageEnum.Fait)
    n_en_retard = sum(
        1 for p in passages
        if p.statut != StatutPassageEnum.Fait and p.date_planifiee < today
    )
    n_a_venir = sum(
        1 for p in passages
        if p.statut == StatutPassageEnum.Prevu and p.date_planifiee >= today
    )

    dernier_exec = db.execute(
        select(Execution.date_execution)
        .where(Execution.site_id == site.id)
        .order_by(Execution.date_execution.desc())
        .limit(1)
    ).scalar_one_or_none()

    prochain = db.execute(
        select(Passage.date_planifiee)
        .where(
            Passage.site_id == site.id,
            Passage.annee == annee,
            Passage.statut == StatutPassageEnum.Prevu,
            Passage.date_planifiee >= today,
        )
        .order_by(Passage.date_planifiee)
        .limit(1)
    ).scalar_one_or_none()

    historique = []
    snag_map: dict[str, dict] = {}
    for p in passages:
        ex = p.execution
        historique.append({
            "id": p.id,
            "mois": p.mois_nom,
            "passage_num": f"{p.passage_num}/{p.total_passages}",
            "date_planifiee": p.date_planifiee,
            "statut": p.statut.value,
            "date_execution": ex.date_execution if ex else None,
            "wo_ticket": ex.wo_ticket if ex else None,
            "niveau_carburant": ex.niveau_carburant if ex else None,
            "ch_ge": ex.ch_ge if ex else None,
            "tension_batterie": ex.tension_batterie if ex else None,
            "snags": ex.snags if ex else None,
            "observations": ex.observations if ex else None,
        })
        if ex and ex.snags:
            for raw in ex.snags.replace("\n", ";").split(";"):
                s = raw.strip()
                if not s:
                    continue
                if s not in snag_map:
                    snag_map[s] = {"count": 0, "derniere_date": None}
                snag_map[s]["count"] += 1
                if snag_map[s]["derniere_date"] is None or ex.date_execution > snag_map[s]["derniere_date"]:
                    snag_map[s]["derniere_date"] = ex.date_execution

    snags_recurrents = sorted(
        [{"description": k, **v} for k, v in snag_map.items()],
        key=lambda x: x["count"],
        reverse=True,
    )

    return {
        "id": site.id,
        "code_site": site.code_site,
        "nom": site.nom,
        "categorie": site.categorie,
        "sbc": site.sbc,
        "sto": site.sto,
        "region": site.region,
        "type_alimentation": site.type_alimentation,
        "cycle": site.cycle,
        "actif": site.actif,
        "date_acceptance": site.date_acceptance,
        "created_at": site.created_at,
        "updated_at": site.updated_at,
        "marque_ge": None,
        "puissance_ge": None,
        "stats": {
            "total_passages_annee": total,
            "passages_faits": n_faits,
            "passages_en_retard": n_en_retard,
            "passages_a_venir": n_a_venir,
            "taux_realisation": n_faits / total if total else 0.0,
            "dernier_passage": dernier_exec,
            "prochain_passage": prochain,
        },
        "historique": historique,
        "snags_recurrents": snags_recurrents,
    }


@router.get("/{code_site}", response_model=SiteResponse, summary="Détail d'un site")
def get_site(
    code_site: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _get_site_or_404(db, code_site)


@router.post("", response_model=SiteResponse, status_code=201, summary="Créer un site")
def create_site(
    data: SiteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(RoleEnum.admin, RoleEnum.manager)),
):
    try:
        if db.execute(select(Site).where(Site.code_site == data.code_site)).scalar_one_or_none():
            raise HTTPException(400, f"Le site {data.code_site} existe déjà")
        site = Site(**data.model_dump())
        db.add(site)
        db.commit()
        db.refresh(site)
        return site
    except HTTPException:
        raise
    except Exception:
        print(f"DETAILED ERROR create_site:\n{traceback.format_exc()}", flush=True)
        raise HTTPException(status_code=500, detail="Erreur interne lors de la création du site")


@router.put("/{code_site}", response_model=SiteResponse, summary="Modifier un site")
def update_site(
    code_site: str,
    data: SiteUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(RoleEnum.admin, RoleEnum.manager)),
):
    site = _get_site_or_404(db, code_site)
    updates = data.model_dump(exclude_unset=True)

    old_cat = site.categorie
    cat_changed = "categorie" in updates and updates["categorie"] != old_cat

    for field, value in updates.items():
        setattr(site, field, value)

    if cat_changed:
        today = date.today()
        current_mois = today.month
        annee = 2026

        future = db.execute(
            select(Passage).where(
                Passage.site_id == site.id,
                Passage.annee == annee,
                Passage.statut == StatutPassageEnum.Prevu,
                Passage.mois_num >= current_mois,
            )
        ).scalars().all()
        for p in future:
            db.delete(p)
        db.flush()

        site_dict = {
            "code_site": site.code_site,
            "nom": site.nom,
            "categorie": site.categorie.value,
            "sbc": site.sbc.value,
            "sto": site.sto,
            "region": site.region,
            "cycle": site.cycle,
        }
        for p_dict in generate_planning([site_dict], year=annee):
            if p_dict["mois_num"] < current_mois:
                continue
            s_str = p_dict.get("statut", "Prevu")
            db.add(Passage(
                site_id=site.id,
                passage_num=p_dict["passage_num"],
                total_passages=p_dict["total_passages"],
                mois_num=p_dict["mois_num"],
                mois_nom=p_dict["mois_nom"],
                annee=annee,
                date_planifiee=p_dict["date_planifiee"],
                statut=(
                    StatutPassageEnum.Non_effectue if s_str == "impossible_a_rattraper"
                    else StatutPassageEnum(s_str)
                ),
                impossible_a_rattraper=(s_str == "impossible_a_rattraper"),
            ))

    db.commit()
    db.refresh(site)
    return site


@router.delete("/{code_site}", status_code=204, summary="Désactiver un site (soft delete)")
def deactivate_site(
    code_site: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(RoleEnum.admin)),
):
    site = _get_site_or_404(db, code_site)
    site.actif = False
    db.commit()


@router.post("/mise-a-jour-mensuelle", summary="Mise à jour mensuelle de la liste des sites")
def mise_a_jour_mensuelle(
    file: UploadFile = File(...),
    annee: int = Query(2026),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(RoleEnum.admin, RoleEnum.manager)),
):
    """
    Upload de la liste Excel des sites acceptés ce mois.
    Détecte automatiquement :
      - Nouveaux sites / sites réactivés → créés + passages pour les mois restants
      - Sites supprimés de la liste → soft-delete + passages futurs annulés
      - Sites dont categorie/sbc/nom a changé → mise à jour + passages ajustés si catégorie changée
    """
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Seuls les fichiers Excel (.xlsx / .xls) sont acceptés")

    contents = file.file.read()
    try:
        df = pd.read_excel(io.BytesIO(contents))
    except Exception as exc:
        raise HTTPException(400, f"Impossible de lire le fichier Excel : {exc}")

    # Normaliser les noms de colonnes (espaces parasites fréquents dans les exports Excel)
    df.columns = df.columns.str.strip()

    # Vérification des colonnes obligatoires du fichier MTN_SITES.xlsx
    required_cols = {"CODE SITE", "Site Name", "STO", "Subcontractor Name", "Region", "Type of power source"}
    missing = required_cols - set(df.columns)
    if missing:
        raise HTTPException(400, (
            f"Colonnes manquantes dans le fichier : {sorted(missing)}. "
            f"Colonnes présentes : {list(df.columns[:15])}"
        ))

    # Catégorisation depuis 'Type of power source'
    _POWER_TO_CAT: dict[str, str] = {
        "grid only":  "GRID_ONLY",
        "grid gen":   "GRID_GEN",
        "solar only": "SOLAR_ONLY",
        "gen only":   "GEN_ONLY",
    }

    # Colonnes GE optionnelles (présentes dans MTN_SITES.xlsx mais sans champ modèle dédié)
    has_ge_brand    = "GE brand"           in df.columns
    has_ge_capacity = "GE capacity (KVA)"  in df.columns

    # Lecture et normalisation des lignes
    excel_sites: dict[str, dict] = {}
    for _, row in df.iterrows():
        try:
            raw_code = row.get("CODE SITE", "")
            if pd.isna(raw_code) or str(raw_code).strip() in ("", "nan"):
                continue
            code = str(raw_code).strip().upper()
            if not code.startswith("CI"):
                continue

            power_raw = str(row.get("Type of power source", "") or "").strip()
            cat_key = power_raw.lower()
            if cat_key not in _POWER_TO_CAT:
                continue  # Source d'alimentation inconnue → ligne ignorée

            # Champs GE lus pour information (non stockés — modèle sans colonne dédiée)
            marque_ge   = str(row["GE brand"]          or "").strip() if has_ge_brand    else None
            puissance_ge = str(row["GE capacity (KVA)"] or "").strip() if has_ge_capacity else None
            if marque_ge   in ("", "nan", "NaT"): marque_ge    = None
            if puissance_ge in ("", "nan", "NaT"): puissance_ge = None

            excel_sites[code] = {
                "code_site": code,
                "nom": str(row.get("Site Name", "") or "").strip(),
                "categorie": _POWER_TO_CAT[cat_key],
                "sbc": str(row.get("Subcontractor Name", "") or "").strip(),
                "sto": str(row.get("STO", "") or "").strip(),
                "region": str(row.get("Region", "") or "").strip(),
                "type_alimentation": power_raw or None,
                "cycle": None,
                # GE — conservés dans le dict pour traçabilité future si le modèle évolue
                "_marque_ge": marque_ge,
                "_puissance_ge": puissance_ge,
                # Colonnes enrichies (optionnelles)
                "date_handover":   _safe_date_from_excel(row.get("Date of Handhover")),
                "techno":          _safe_str(row.get("TECHNO")),
                "passive_handler": _safe_str(row.get("Passive Handler")),
                "latitude":        _safe_float(row.get("Lat")),
                "longitude":       _safe_float(row.get("Long")),
                "priorite":        _safe_str(row.get("Site Priority")),
                "typologie":       _safe_str(row.get("Site type")),
            }
        except Exception:
            continue

    # Chargement de tous les sites existants (actifs et inactifs)
    all_sites_db: dict[str, Site] = {
        s.code_site: s
        for s in db.execute(select(Site)).scalars().all()
    }
    active_codes_db = {code for code, s in all_sites_db.items() if s.actif}
    excel_codes = set(excel_sites.keys())

    today = date.today()
    current_mois = today.month

    ajoutes: list[str] = []
    supprimes: list[str] = []
    modifies: list[str] = []
    passages_generes = 0
    passages_annules = 0

    # ── 1. Nouveaux sites ou réactivations ────────────────────────
    for code in excel_codes - active_codes_db:
        data = excel_sites[code]
        try:
            cat_enum = CategorieEnum(data["categorie"])
            sbc_enum = SBCEnum(data["sbc"])
        except ValueError:
            continue

        site = all_sites_db.get(code)
        if site:
            # Réactivation
            site.actif = True
            site.nom = data["nom"]
            site.categorie = cat_enum
            site.sbc = sbc_enum
            site.sto = data["sto"]
            site.region = data["region"]
            site.date_handover   = data.get("date_handover")
            site.techno          = data.get("techno")
            site.passive_handler = data.get("passive_handler")
            site.latitude        = data.get("latitude")
            site.longitude       = data.get("longitude")
            site.priorite        = data.get("priorite")
            site.typologie       = data.get("typologie")
        else:
            # Création
            site = Site(
                code_site=code,
                nom=data["nom"],
                categorie=cat_enum,
                sbc=sbc_enum,
                sto=data["sto"],
                region=data["region"],
                type_alimentation=data.get("type_alimentation"),
                cycle=data.get("cycle"),
                actif=True,
                date_handover=data.get("date_handover"),
                techno=data.get("techno"),
                passive_handler=data.get("passive_handler"),
                latitude=data.get("latitude"),
                longitude=data.get("longitude"),
                priorite=data.get("priorite"),
                typologie=data.get("typologie"),
            )
            db.add(site)

        db.flush()  # obtenir site.id
        ajoutes.append(code)

        # Générer les passages pour les mois restants
        site_dict = {
            "code_site": code, "nom": data["nom"],
            "categorie": data["categorie"], "sbc": data["sbc"],
            "sto": data["sto"], "region": data["region"],
            "cycle": data.get("cycle"),
        }
        for p_dict in generate_planning([site_dict], year=annee):
            if p_dict["mois_num"] < current_mois:
                continue
            exists = db.execute(
                select(Passage).where(
                    Passage.site_id == site.id,
                    Passage.mois_num == p_dict["mois_num"],
                    Passage.annee == annee,
                    Passage.passage_num == p_dict["passage_num"],
                )
            ).scalar_one_or_none()
            if exists:
                continue
            s_str = p_dict.get("statut", "Prevu")
            db.add(Passage(
                site_id=site.id,
                passage_num=p_dict["passage_num"],
                total_passages=p_dict["total_passages"],
                mois_num=p_dict["mois_num"],
                mois_nom=p_dict["mois_nom"],
                annee=annee,
                date_planifiee=p_dict["date_planifiee"],
                statut=StatutPassageEnum.Non_effectue if s_str == "impossible_a_rattraper"
                       else StatutPassageEnum(s_str),
                impossible_a_rattraper=(s_str == "impossible_a_rattraper"),
            ))
            passages_generes += 1

    # ── 2. Sites retirés de la liste ──────────────────────────────
    for code in active_codes_db - excel_codes:
        site = all_sites_db[code]
        site.actif = False

        future = db.execute(
            select(Passage).where(
                Passage.site_id == site.id,
                Passage.annee == annee,
                Passage.statut == StatutPassageEnum.Prevu,
                Passage.mois_num >= current_mois,
            )
        ).scalars().all()

        for p in future:
            p.statut = StatutPassageEnum.Non_effectue
            p.impossible_a_rattraper = True
            passages_annules += 1

        supprimes.append(code)

    # ── 3. Sites présents dans les deux — détecter les modifications ─
    for code in excel_codes & active_codes_db:
        site = all_sites_db[code]
        data = excel_sites[code]
        try:
            cat_enum = CategorieEnum(data["categorie"])
            sbc_enum = SBCEnum(data["sbc"])
        except ValueError:
            continue

        cat_changed = site.categorie != cat_enum
        changed = (
            cat_changed
            or site.sbc != sbc_enum
            or site.nom != data["nom"]
            or site.sto != data["sto"]
            or site.region != data["region"]
            or site.date_handover   != data.get("date_handover")
            or site.techno          != data.get("techno")
            or site.passive_handler != data.get("passive_handler")
            or site.latitude        != data.get("latitude")
            or site.longitude       != data.get("longitude")
            or site.priorite        != data.get("priorite")
            or site.typologie       != data.get("typologie")
        )
        if not changed:
            continue

        site.nom             = data["nom"]
        site.categorie       = cat_enum
        site.sbc             = sbc_enum
        site.sto             = data["sto"]
        site.region          = data["region"]
        site.date_handover   = data.get("date_handover")
        site.techno          = data.get("techno")
        site.passive_handler = data.get("passive_handler")
        site.latitude        = data.get("latitude")
        site.longitude       = data.get("longitude")
        site.priorite        = data.get("priorite")
        site.typologie       = data.get("typologie")
        modifies.append(code)

        if cat_changed:
            # Supprimer les passages futurs Prévus et régénérer
            future = db.execute(
                select(Passage).where(
                    Passage.site_id == site.id,
                    Passage.annee == annee,
                    Passage.statut == StatutPassageEnum.Prevu,
                    Passage.mois_num >= current_mois,
                )
            ).scalars().all()
            passages_annules += len(future)
            for p in future:
                db.delete(p)
            db.flush()

            site_dict = {
                "code_site": code, "nom": data["nom"],
                "categorie": data["categorie"], "sbc": data["sbc"],
                "sto": data["sto"], "region": data["region"],
                "cycle": site.cycle,
            }
            for p_dict in generate_planning([site_dict], year=annee):
                if p_dict["mois_num"] < current_mois:
                    continue
                s_str = p_dict.get("statut", "Prevu")
                db.add(Passage(
                    site_id=site.id,
                    passage_num=p_dict["passage_num"],
                    total_passages=p_dict["total_passages"],
                    mois_num=p_dict["mois_num"],
                    mois_nom=p_dict["mois_nom"],
                    annee=annee,
                    date_planifiee=p_dict["date_planifiee"],
                    statut=StatutPassageEnum.Non_effectue if s_str == "impossible_a_rattraper"
                           else StatutPassageEnum(s_str),
                    impossible_a_rattraper=(s_str == "impossible_a_rattraper"),
                ))
                passages_generes += 1

    try:
        db.commit()
    except Exception:
        print(f"DETAILED ERROR mise_a_jour_mensuelle commit:\n{traceback.format_exc()}", flush=True)
        db.rollback()
        raise HTTPException(status_code=500, detail="Erreur base de données lors de la mise à jour")

    # Créer une alerte de confirmation
    db.add(Alert(
        niveau=NiveauAlerteEnum.information,
        type_alerte="mise_a_jour_sites",
        message=(
            f"Mise à jour mensuelle du {today.strftime('%d/%m/%Y')} : "
            f"{len(ajoutes)} ajouté(s), {len(supprimes)} désactivé(s), "
            f"{len(modifies)} modifié(s). "
            f"{passages_generes} passages générés, {passages_annules} annulés."
        ),
        statut=StatutAlerteEnum.nouvelle,
    ))
    db.commit()

    return {
        "ajoutes": ajoutes,
        "supprimes": supprimes,
        "modifies": modifies,
        "passages_generes": passages_generes,
        "passages_annules": passages_annules,
        "date_mise_a_jour": today.isoformat(),
    }


@router.post("/import-excel", summary="Importer une liste de sites depuis Excel")
def import_sites_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(RoleEnum.admin, RoleEnum.manager)),
):
    """
    Colonnes attendues dans l'Excel : code_site, nom, categorie, sbc, sto, region
    Colonnes optionnelles : type_alimentation, cycle, date_acceptance
    """
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Seuls les fichiers Excel (.xlsx / .xls) sont acceptés")

    contents = file.file.read()
    try:
        df = pd.read_excel(io.BytesIO(contents))
    except Exception as exc:
        raise HTTPException(400, f"Impossible de lire le fichier Excel : {exc}")

    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    required = {"code_site", "nom", "categorie", "sbc", "sto", "region"}
    missing = required - set(df.columns)
    if missing:
        raise HTTPException(400, f"Colonnes manquantes : {missing}")

    created, skipped, errors = 0, 0, []
    for _, row in df.iterrows():
        try:
            code = str(row["code_site"]).strip().upper()
            if db.execute(select(Site).where(Site.code_site == code)).scalar_one_or_none():
                skipped += 1
                continue
            site = Site(
                code_site=code,
                nom=str(row["nom"]).strip(),
                categorie=CategorieEnum(str(row["categorie"]).strip()),
                sbc=SBCEnum(str(row["sbc"]).strip()),
                sto=str(row["sto"]).strip(),
                region=str(row["region"]).strip(),
                type_alimentation=str(row.get("type_alimentation", "")).strip() or None,
                cycle=str(row.get("cycle", "")).strip() or None,
            )
            db.add(site)
            created += 1
        except Exception as exc:
            errors.append({"ligne": int(_ + 2), "erreur": str(exc)})

    db.commit()
    return {"crees": created, "ignores": skipped, "erreurs": len(errors), "detail": errors[:20]}
