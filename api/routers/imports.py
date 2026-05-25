import io
from datetime import datetime, timezone

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from api.deps import get_current_user
from database import get_db
from models import Execution, Import, Passage, Site, StatutImportEnum, StatutPassageEnum, User
from planning_engine import import_executions

router = APIRouter()


def _first_matching_column(columns, candidates: tuple[str, ...]) -> str | None:
    normalized = {str(c).strip().lower(): c for c in columns}
    for candidate in candidates:
        found = normalized.get(candidate.lower())
        if found is not None:
            return found
    for c in columns:
        c_norm = str(c).strip().lower()
        if any(candidate.lower() in c_norm for candidate in candidates):
            return c
    return None


def _read_excel_with_detected_header(contents: bytes) -> pd.DataFrame:
    raw = pd.read_excel(io.BytesIO(contents), header=None, dtype=str, nrows=15)
    header_row = 0
    markers = ("site id", "code site", "code_site", "executed", "date_exec", "work order", "wo_ticket")
    for i in range(len(raw)):
        row_text = " ".join(str(v).strip().lower() for v in raw.iloc[i].values if pd.notna(v))
        if sum(marker in row_text for marker in markers) >= 2:
            header_row = i
            break
    df = pd.read_excel(io.BytesIO(contents), header=header_row)
    df.columns = [str(c).replace("\n", " ").strip() for c in df.columns]
    return df


def _normalize_sbc_report(df: pd.DataFrame) -> list[dict]:
    code_col = _first_matching_column(df.columns, ("code_site", "Site ID", "CODE SITE"))
    month_col = _first_matching_column(df.columns, ("mois_num", "month", "mois"))
    date_col = _first_matching_column(df.columns, ("date_exec", "Executed date", "date execution"))
    wo_col = _first_matching_column(df.columns, ("wo_ticket", "Work Order Number", "WO"))

    if not code_col or not date_col or not wo_col:
        missing = []
        if not code_col:
            missing.append("code_site / Site ID / CODE SITE")
        if not date_col:
            missing.append("date_exec / Executed date")
        if not wo_col:
            missing.append("wo_ticket / Work Order Number")
        raise HTTPException(400, f"Colonnes manquantes : {', '.join(missing)}")

    rows: list[dict] = []
    for _, row in df.iterrows():
        code_raw = row.get(code_col)
        date_raw = row.get(date_col)
        wo_raw = row.get(wo_col)

        code = str(code_raw or "").strip().upper()
        wo = str(wo_raw or "").strip()
        if not code.startswith("CI") or code.lower() == "nan":
            continue
        if not wo or wo.lower() in {"nan", "none"}:
            continue

        parsed_date = pd.to_datetime(date_raw, dayfirst=True, errors="coerce")
        if pd.isna(parsed_date):
            continue
        date_exec = parsed_date.date()

        mois_num = None
        if month_col:
            try:
                mois_num = int(row.get(month_col))
            except (TypeError, ValueError):
                mois_num = None
        if mois_num is None:
            mois_num = date_exec.month

        rows.append({
            "code_site": code,
            "mois_num": mois_num,
            "date_exec": date_exec,
            "wo_ticket": wo,
        })
    return rows


@router.post("/upload", status_code=201, summary="Importer un rapport SBC (Excel)")
async def upload_rapport_sbc(
    file: UploadFile = File(...),
    annee: int = Query(2026),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filename = file.filename or ""
    if not filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Seuls les fichiers Excel (.xlsx / .xls) sont acceptes")

    contents = await file.read()
    try:
        df = _read_excel_with_detected_header(contents)
    except Exception as exc:
        raise HTTPException(400, f"Impossible de lire le fichier Excel : {exc}")

    rapport_sbc = _normalize_sbc_report(df)
    nb_lignes_brut = len(rapport_sbc)
    if not rapport_sbc:
        raise HTTPException(400, "Aucune ligne valide trouvee dans le fichier")

    passages_orm = db.execute(
        select(Passage)
        .join(Site)
        .options(joinedload(Passage.site), joinedload(Passage.execution))
        .where(Passage.annee == annee)
    ).scalars().all()

    if not passages_orm:
        raise HTTPException(404, f"Aucun passage en base pour l'annee {annee}")

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

    result = import_executions(planning_dicts, rapport_sbc)
    updated = result["updated"]
    stats = result["stats"]

    import_log = Import(
        nom_fichier=filename,
        date_import=datetime.now(timezone.utc),
        importe_par=current_user.id,
        nb_lignes_brut=nb_lignes_brut,
        nb_integres=stats["integres"],
        nb_doublons=stats["doublons"],
        nb_max_depasse=0,
        nb_non_trouves=stats["non_trouves"],
        statut=(
            StatutImportEnum.succes if stats["non_trouves"] == 0 and stats["doublons"] == 0
            else StatutImportEnum.partiel if stats["integres"] > 0
            else StatutImportEnum.echec
        ),
        detail_erreurs=None,
    )
    db.add(import_log)
    db.flush()

    orig_statut = {d["_db_id"]: d["statut"] for d in planning_dicts}

    for upd in updated:
        db_id = upd.get("_db_id")
        if not db_id:
            continue
        if upd["statut"] == "Fait" and orig_statut.get(db_id) != "Fait":
            passage_db = db.get(Passage, db_id)
            if not passage_db:
                continue
            passage_db.statut = StatutPassageEnum.Fait

            if not passage_db.execution:
                db.add(Execution(
                    passage_id=db_id,
                    site_id=passage_db.site_id,
                    date_execution=upd["date_execution"],
                    wo_ticket=upd["wo_ticket"],
                    import_id=import_log.id,
                ))
            else:
                passage_db.execution.date_execution = upd["date_execution"]
                passage_db.execution.wo_ticket = upd["wo_ticket"]
                passage_db.execution.import_id = import_log.id

    db.commit()
    db.refresh(import_log)

    return {
        "import_id": import_log.id,
        "id": import_log.id,
        "fichier": filename,
        "nom_fichier": filename,
        "nb_lignes_brut": nb_lignes_brut,
        "integres": stats["integres"],
        "doublons": stats["doublons"],
        "non_trouves": stats["non_trouves"],
        "nb_integres": stats["integres"],
        "nb_doublons": stats["doublons"],
        "nb_non_trouves": stats["non_trouves"],
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
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": [
            {
                "id": i.id,
                "nom_fichier": i.nom_fichier,
                "date_import": i.date_import,
                "statut": i.statut.value,
                "nb_lignes_brut": i.nb_lignes_brut,
                "nb_integres": i.nb_integres,
                "nb_doublons": i.nb_doublons,
                "nb_non_trouves": i.nb_non_trouves,
                "nb_max_depasse": i.nb_max_depasse,
            }
            for i in items
        ],
    }


@router.get("/{import_id}", summary="Detail d'un import")
def get_import(
    import_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    imp = db.get(Import, import_id)
    if not imp:
        raise HTTPException(404, f"Import {import_id} introuvable")
    return {
        "id": imp.id,
        "nom_fichier": imp.nom_fichier,
        "date_import": imp.date_import,
        "statut": imp.statut.value,
        "nb_lignes_brut": imp.nb_lignes_brut,
        "nb_integres": imp.nb_integres,
        "nb_doublons": imp.nb_doublons,
        "nb_max_depasse": imp.nb_max_depasse,
        "nb_non_trouves": imp.nb_non_trouves,
        "detail_erreurs": imp.detail_erreurs,
    }


@router.delete("/{import_id}", status_code=204, summary="Annuler un import et reinitialiser les passages associes")
def cancel_import(
    import_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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
