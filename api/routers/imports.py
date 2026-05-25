import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import io
import json
from datetime import datetime, timezone

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from api.deps import get_current_user, require_roles, sbc_scope
from database import get_db
from models import (
    Execution, Import, Passage, RoleEnum, SBCEnum, Site,
    StatutImportEnum, StatutPassageEnum, User,
)
from planning_engine import import_executions
from schemas.common import PaginatedResponse

router = APIRouter()


@router.post("/upload", status_code=201, summary="Importer un rapport SBC (Excel)")
def upload_rapport_sbc(
    file: UploadFile = File(...),
    annee: int = Query(2026),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Colonnes requises dans le fichier Excel :
    code_site | mois_num | date_exec | wo_ticket

    Les doublons WO et les dépassements de quota mensuel sont filtrés automatiquement.
    """
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Seuls les fichiers Excel (.xlsx / .xls) sont acceptés")

    contents = file.file.read()

    # ── Étape 1 : Détecter le format du fichier ──────────────────────────
    try:
        xls = pd.ExcelFile(io.BytesIO(contents))
    except Exception as exc:
        raise HTTPException(400, f"Impossible de lire le fichier : {exc}")

    sheet_names = xls.sheet_names
    ppm_sheet   = next((s for s in sheet_names if "PPM" in s.upper()), None)

    if ppm_sheet:
        # ── Format PPM_PLANNING_FOLLOWING.xlsx — header à l'index 4 ──────
        try:
            df = pd.read_excel(io.BytesIO(contents), sheet_name=ppm_sheet, header=4, dtype=str)
        except Exception as exc:
            raise HTTPException(400, f"Impossible de lire la feuille '{ppm_sheet}' : {exc}")

        df.columns = df.columns.str.strip()

        required_cols = {"Site ID", "ASP", "Executed date", "Work Order Number"}
        missing = required_cols - set(df.columns)
        if missing:
            raise HTTPException(400, (
                f"Colonnes manquantes dans la feuille '{ppm_sheet}' : {', '.join(sorted(missing))}. "
                f"Colonnes présentes : {list(df.columns[:15])}"
            ))

        df = df.rename(columns={
            "Site ID":           "code_site",
            "ASP":               "sbc",
            "Executed date":     "date_exec",
            "Work Order Number": "wo_ticket",
        })

        df["code_site"] = df["code_site"].astype(str).str.strip().str.upper()
        df = df[df["code_site"].str.startswith("CI", na=False)]

        df = df.dropna(subset=["date_exec"])
        df = df[~df["date_exec"].astype(str).str.strip().isin(["", "nan", "NaT", "None"])]

        if df.empty:
            raise HTTPException(400, (
                f"Aucune ligne valide trouvée dans la feuille '{ppm_sheet}'. "
                "Vérifiez que les codes site commencent par 'CI' et que 'Executed date' est renseignée."
            ))

        df["date_exec"] = pd.to_datetime(df["date_exec"], dayfirst=True, errors="coerce").dt.date
        df = df.dropna(subset=["date_exec"])
        df["mois_num"] = df["date_exec"].apply(lambda d: d.month)

        df["wo_ticket"] = df["wo_ticket"].astype(str).str.strip()
        df = df[~df["wo_ticket"].isin(["", "nan", "None"])]

    else:
        # ── Format SBC rapport — auto-détection de la ligne d'en-tête ────
        # Cherche 'Site ID' en priorité, puis 'CODE SITE' en fallback.
        try:
            raw = pd.read_excel(io.BytesIO(contents), header=None, dtype=str, nrows=15)
        except Exception as exc:
            raise HTTPException(400, f"Impossible de lire le fichier : {exc}")

        header_row = None
        site_col   = None

        for marker in ("Site ID", "CODE SITE"):
            for i in range(len(raw)):
                row_vals = [str(v).strip() for v in raw.iloc[i].values if pd.notna(v)]
                if marker in row_vals:
                    header_row = i
                    site_col   = marker
                    break
            if header_row is not None:
                break

        if header_row is None:
            raise HTTPException(400, (
                "En-tête introuvable. La colonne 'Site ID' (ou 'CODE SITE') doit être présente "
                "dans les 15 premières lignes du fichier. "
                f"Colonnes trouvées sur la première ligne : {list(raw.iloc[0].values)[:8]}"
            ))

        try:
            df = pd.read_excel(io.BytesIO(contents), header=header_row)
        except Exception as exc:
            raise HTTPException(400, f"Impossible de relire le fichier (header={header_row}) : {exc}")

        df.columns = df.columns.str.strip()

        required_cols = {site_col, "ASP", "Executed date", "Work Order Number"}
        missing = required_cols - set(df.columns)
        if missing:
            raise HTTPException(400, (
                f"Colonnes manquantes : {', '.join(sorted(missing))}. "
                f"Colonnes présentes : {list(df.columns[:12])}"
            ))

        df = df.rename(columns={
            site_col:            "code_site",
            "ASP":               "sbc",
            "Executed date":     "date_exec",
            "Work Order Number": "wo_ticket",
        })

        df["code_site"] = df["code_site"].astype(str).str.strip().str.upper()
        df = df[df["code_site"].str.startswith("CI", na=False)]

        df = df.dropna(subset=["date_exec"])
        df = df[~df["date_exec"].astype(str).str.strip().isin(["", "nan", "NaT", "None"])]

        if df.empty:
            raise HTTPException(400, (
                "Aucune ligne valide trouvée. Vérifiez que les codes site commencent "
                "par 'CI' et que la colonne 'Executed date' est renseignée."
            ))

        df["date_exec"] = pd.to_datetime(df["date_exec"], dayfirst=True, errors="coerce").dt.date
        df = df.dropna(subset=["date_exec"])
        df["mois_num"] = df["date_exec"].apply(lambda d: d.month)

        df["wo_ticket"] = df["wo_ticket"].astype(str).str.strip()
        df = df[~df["wo_ticket"].isin(["", "nan", "None"])]

    rapport_sbc = df[["code_site", "mois_num", "date_exec", "wo_ticket"]].to_dict("records")
    nb_lignes_brut = len(rapport_sbc)

    # Charger le planning de l'année depuis la DB
    passages_orm = db.execute(
        select(Passage)
        .join(Site)
        .options(joinedload(Passage.site), joinedload(Passage.execution))
        .where(Passage.annee == annee)
    ).scalars().all()

    if not passages_orm:
        raise HTTPException(404, f"Aucun passage en base pour l'année {annee}")

    # Construire la liste de dicts pour le moteur (_db_id pour rétro-référence)
    planning_dicts = []
    for p in passages_orm:
        planning_dicts.append({
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
        })

    # Appel moteur
    result = import_executions(planning_dicts, rapport_sbc)
    updated = result["updated"]
    stats   = result["stats"]

    # Enregistrer la traçabilité import en premier pour obtenir son ID
    import_log = Import(
        nom_fichier=file.filename,
        date_import=datetime.now(timezone.utc),
        importe_par=current_user.id,
        nb_lignes_brut=nb_lignes_brut,
        nb_integres=stats["integres"],
        nb_doublons=stats["doublons"],
        nb_max_depasse=0,
        nb_non_trouves=stats["non_trouves"],
        statut=(
            StatutImportEnum.succes  if stats["non_trouves"] == 0 and stats["doublons"] == 0
            else StatutImportEnum.partiel if stats["integres"] > 0
            else StatutImportEnum.echec
        ),
        detail_erreurs=None,
    )
    db.add(import_log)
    db.flush()  # obtenir import_log.id avant de créer les Executions

    # Mettre à jour la DB en comparant avec l'original
    orig_statut = {d["_db_id"]: d["statut"] for d in planning_dicts}

    for upd in updated:
        db_id = upd.get("_db_id")
        if not db_id:
            continue
        # Passage nouvellement marqué Fait
        if upd["statut"] == "Fait" and orig_statut.get(db_id) != "Fait":
            passage_db = db.get(Passage, db_id)
            if not passage_db:
                continue
            passage_db.statut = StatutPassageEnum.Fait

            if not passage_db.execution:
                exec_obj = Execution(
                    passage_id=db_id,
                    site_id=passage_db.site_id,
                    date_execution=upd["date_execution"],
                    wo_ticket=upd["wo_ticket"],
                    import_id=import_log.id,
                )
                db.add(exec_obj)
            else:
                passage_db.execution.date_execution = upd["date_execution"]
                passage_db.execution.wo_ticket = upd["wo_ticket"]

    db.commit()

    return {
        "import_id": import_log.id,
        "fichier": file.filename,
        "nb_lignes_brut": nb_lignes_brut,
        "integres": stats["integres"],
        "doublons": stats["doublons"],
        "non_trouves": stats["non_trouves"],
        "statut": import_log.statut.value,
    }


@router.get("", summary="Historique des imports")
def list_imports(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    total = db.execute(select(func.count(Import.id))).scalar()
    items = db.execute(
        select(Import).order_by(Import.date_import.desc()).offset(skip).limit(limit)
    ).scalars().all()
    return {
        "total": total, "skip": skip, "limit": limit,
        "items": [
            {
                "id": i.id, "nom_fichier": i.nom_fichier,
                "date_import": i.date_import, "statut": i.statut.value,
                "nb_lignes_brut": i.nb_lignes_brut,
                "nb_integres": i.nb_integres, "nb_doublons": i.nb_doublons,
                "nb_non_trouves": i.nb_non_trouves,
            }
            for i in items
        ],
    }


@router.delete("/{import_id}", status_code=204, summary="Annuler un import et réinitialiser les passages associés")
def cancel_import(
    import_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Supprime l'import et réinitialise à 'Prevu' tous les passages
    qui avaient été marqués 'Fait' lors de cet import.
    """
    imp = db.get(Import, import_id)
    if not imp:
        raise HTTPException(404, f"Import {import_id} introuvable")

    executions = db.execute(
        select(Execution).where(Execution.import_id == import_id)
    ).scalars().all()

    for exec_obj in executions:
        passage = db.get(Passage, exec_obj.passage_id)
        if passage and passage.statut == StatutPassageEnum.Fait:
            passage.statut = StatutPassageEnum.Prevu
        db.delete(exec_obj)

    db.delete(imp)
    db.commit()


@router.get("/{import_id}", summary="Détail d'un import")
def get_import(
    import_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    imp = db.get(Import, import_id)
    if not imp:
        raise HTTPException(404, f"Import {import_id} introuvable")
    return {
        "id": imp.id, "nom_fichier": imp.nom_fichier,
        "date_import": imp.date_import, "statut": imp.statut.value,
        "nb_lignes_brut": imp.nb_lignes_brut,
        "nb_integres": imp.nb_integres, "nb_doublons": imp.nb_doublons,
        "nb_max_depasse": imp.nb_max_depasse, "nb_non_trouves": imp.nb_non_trouves,
        "detail_erreurs": imp.detail_erreurs,
    }
