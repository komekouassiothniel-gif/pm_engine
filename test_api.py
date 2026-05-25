"""
test_api.py — Tests d'intégration de l'API REST PM MTN CI
Prérequis : PostgreSQL actif + schéma créé (python seed.py OU alembic upgrade head)

Lancer : pytest test_api.py -v
"""

import io
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import openpyxl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from api.main import app
from api.deps import hash_password
from database import SessionLocal, get_db, init_db
from models import (
    Alert, Execution, Import, NiveauAlerteEnum, Passage,
    RoleEnum, Site, StatutAlerteEnum, StatutPassageEnum,
    CategorieEnum, SBCEnum, User,
)
from planning_engine import generate_planning

# ---------------------------------------------------------------------------
# Setup / fixtures
# ---------------------------------------------------------------------------

init_db()  # crée les tables si inexistantes


@pytest.fixture(autouse=True)
def clean_tables():
    """Vide les tables de test avant chaque test."""
    db = SessionLocal()
    try:
        db.execute(delete(Alert))
        db.execute(delete(Import))
        db.execute(delete(Execution))
        db.execute(delete(Passage))
        db.execute(delete(Site))
        db.execute(delete(User))
        db.commit()
    finally:
        db.close()


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def admin(db):
    user = User(
        nom="Admin Test",
        email="admin@test.com",
        password_hash=hash_password("Admin2026!"),
        role=RoleEnum.admin,
        actif=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def sbc_user(db):
    user = User(
        nom="SBC Afro",
        email="afro@test.com",
        password_hash=hash_password("Admin2026!"),
        role=RoleEnum.sbc,
        sbc_associe="Afro",
        actif=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def token(admin):
    with TestClient(app) as c:
        r = c.post("/api/v1/auth/login", json={"email": "admin@test.com", "password": "Admin2026!"})
        assert r.status_code == 200, r.text
        return r.json()["access_token"]


@pytest.fixture
def sbc_token(sbc_user):
    with TestClient(app) as c:
        r = c.post("/api/v1/auth/login", json={"email": "afro@test.com", "password": "Admin2026!"})
        assert r.status_code == 200, r.text
        return r.json()["access_token"]


@pytest.fixture
def test_sites(db):
    sites_data = [
        {"code_site": "CI00001", "nom": "GridGen Test",  "categorie": CategorieEnum.GRID_GEN,
         "sbc": SBCEnum.Afro,   "sto": "STO ABIDJAN NORD", "region": "LAGUNES"},
        {"code_site": "CI00002", "nom": "GridOnly Test", "categorie": CategorieEnum.GRID_ONLY,
         "sbc": SBCEnum.CCS,    "sto": "STO DALOA",        "region": "HAUT-SASSANDRA"},
        {"code_site": "CI00003", "nom": "GenOnly Test",  "categorie": CategorieEnum.GEN_ONLY,
         "sbc": SBCEnum.Hammer, "sto": "STO KORHOGO",      "region": "HAMBOL"},
        {"code_site": "CI00004", "nom": "Solar Test",    "categorie": CategorieEnum.SOLAR_ONLY,
         "sbc": SBCEnum.Afro,   "sto": "STO YAMOUSSOUKRO", "region": "BELIER"},
    ]
    sites = [Site(**d, actif=True) for d in sites_data]
    for s in sites:
        db.add(s)
    db.commit()
    return sites


@pytest.fixture
def test_passages(db, test_sites):
    sites_dicts = [
        {"code_site": "CI00001", "nom": "GridGen Test",  "categorie": "GRID_GEN",
         "sbc": "Afro",   "sto": "STO ABIDJAN NORD", "region": "LAGUNES"},
        {"code_site": "CI00002", "nom": "GridOnly Test", "categorie": "GRID_ONLY",
         "sbc": "CCS",    "sto": "STO DALOA",        "region": "HAUT-SASSANDRA"},
        {"code_site": "CI00003", "nom": "GenOnly Test",  "categorie": "GEN_ONLY",
         "sbc": "Hammer", "sto": "STO KORHOGO",      "region": "HAMBOL"},
        {"code_site": "CI00004", "nom": "Solar Test",    "categorie": "SOLAR_ONLY",
         "sbc": "Afro",   "sto": "STO YAMOUSSOUKRO", "region": "BELIER"},
    ]
    site_id_map = {s.code_site: s.id for s in test_sites}
    planning = generate_planning(sites_dicts, year=2026)
    passages = []
    for p in planning:
        obj = Passage(
            site_id=site_id_map[p["code_site"]],
            passage_num=p["passage_num"],
            total_passages=p["total_passages"],
            mois_num=p["mois_num"],
            mois_nom=p["mois_nom"],
            annee=2026,
            date_planifiee=p["date_planifiee"],
            statut=StatutPassageEnum.Prevu,
        )
        db.add(obj)
        passages.append(obj)
    db.commit()
    return passages


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def make_excel(rows: list[dict]) -> bytes:
    """Crée un fichier Excel en mémoire à partir d'une liste de dicts."""
    wb = openpyxl.Workbook()
    ws = wb.active
    if rows:
        ws.append(list(rows[0].keys()))
        for row in rows:
            ws.append(list(row.values()))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Tests authentification
# ---------------------------------------------------------------------------

class TestAuth:
    def test_login_success(self, admin):
        with TestClient(app) as c:
            r = c.post("/api/v1/auth/login", json={"email": "admin@test.com", "password": "Admin2026!"})
        assert r.status_code == 200
        body = r.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["user"]["email"] == "admin@test.com"
        assert "password_hash" not in str(body)

    def test_login_wrong_password(self, admin):
        with TestClient(app) as c:
            r = c.post("/api/v1/auth/login", json={"email": "admin@test.com", "password": "wrong"})
        assert r.status_code == 401

    def test_login_unknown_user(self):
        with TestClient(app) as c:
            r = c.post("/api/v1/auth/login", json={"email": "nobody@test.com", "password": "x"})
        assert r.status_code == 401

    def test_protected_endpoint_without_token(self):
        with TestClient(app) as c:
            r = c.get("/api/v1/sites")
        assert r.status_code == 401

    def test_token_works_on_protected_endpoint(self, token, test_sites):
        with TestClient(app) as c:
            r = c.get("/api/v1/sites", headers=auth_header(token))
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Tests sites
# ---------------------------------------------------------------------------

class TestSites:
    def test_list_sites(self, token, test_sites):
        with TestClient(app) as c:
            r = c.get("/api/v1/sites", headers=auth_header(token))
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == len(test_sites)
        assert len(body["items"]) == len(test_sites)

    def test_list_sites_filter_sbc(self, token, test_sites):
        with TestClient(app) as c:
            r = c.get("/api/v1/sites?sbc=Afro", headers=auth_header(token))
        assert r.status_code == 200
        items = r.json()["items"]
        assert all(s["sbc"] == "Afro" for s in items)

    def test_get_site_detail(self, token, test_sites):
        with TestClient(app) as c:
            r = c.get("/api/v1/sites/CI00001", headers=auth_header(token))
        assert r.status_code == 200
        assert r.json()["code_site"] == "CI00001"

    def test_get_site_not_found(self, token):
        with TestClient(app) as c:
            r = c.get("/api/v1/sites/CI99999", headers=auth_header(token))
        assert r.status_code == 404

    def test_create_site(self, token):
        payload = {
            "code_site": "CI09001", "nom": "Nouveau Site",
            "categorie": "GRID_GEN", "sbc": "Afro",
            "sto": "STO TEST", "region": "TEST",
        }
        with TestClient(app) as c:
            r = c.post("/api/v1/sites", json=payload, headers=auth_header(token))
        assert r.status_code == 201
        assert r.json()["code_site"] == "CI09001"

    def test_create_site_invalid_code(self, token):
        payload = {
            "code_site": "XX123", "nom": "Bad",
            "categorie": "GRID_GEN", "sbc": "Afro",
            "sto": "STO TEST", "region": "TEST",
        }
        with TestClient(app) as c:
            r = c.post("/api/v1/sites", json=payload, headers=auth_header(token))
        assert r.status_code == 422

    def test_sbc_user_sees_only_own_sites(self, sbc_token, test_sites):
        with TestClient(app) as c:
            r = c.get("/api/v1/sites", headers=auth_header(sbc_token))
        assert r.status_code == 200
        items = r.json()["items"]
        # L'utilisateur SBC Afro ne doit voir que ses sites
        assert all(s["sbc"] == "Afro" for s in items)


# ---------------------------------------------------------------------------
# Tests planning
# ---------------------------------------------------------------------------

class TestPlanning:
    def test_list_planning_returns_all(self, token, test_passages):
        with TestClient(app) as c:
            r = c.get("/api/v1/planning?limit=200", headers=auth_header(token))
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == len(test_passages)

    def test_filter_by_sbc(self, token, test_passages):
        with TestClient(app) as c:
            r = c.get("/api/v1/planning?sbc=Afro&limit=200", headers=auth_header(token))
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) > 0
        assert all(p["site"]["sbc"] == "Afro" for p in items)

    def test_filter_by_mois(self, token, test_passages):
        with TestClient(app) as c:
            r = c.get("/api/v1/planning?mois_num=1&limit=200", headers=auth_header(token))
        assert r.status_code == 200
        items = r.json()["items"]
        assert all(p["mois_num"] == 1 for p in items)

    def test_update_statut_to_fait(self, token, test_passages, db):
        passage = db.execute(
            select(Passage).where(Passage.site_id != None)
        ).scalar()
        with TestClient(app) as c:
            r = c.patch(
                f"/api/v1/planning/{passage.id}/statut",
                json={"statut": "Fait", "date_execution": "2026-01-15", "wo_ticket": "WO-TEST-999"},
                headers=auth_header(token),
            )
        assert r.status_code == 200
        body = r.json()
        assert body["statut"] == "Fait"
        assert body["execution"]["wo_ticket"] == "WO-TEST-999"

    def test_update_statut_fait_missing_wo(self, token, test_passages, db):
        passage = db.execute(select(Passage)).scalar()
        with TestClient(app) as c:
            r = c.patch(
                f"/api/v1/planning/{passage.id}/statut",
                json={"statut": "Fait"},
                headers=auth_header(token),
            )
        assert r.status_code == 400

    def test_stats_structure(self, token, test_passages):
        with TestClient(app) as c:
            r = c.get("/api/v1/planning/stats", headers=auth_header(token))
        assert r.status_code == 200
        body = r.json()
        # Vérifier les clés attendues
        for key in ("total", "faits", "non_effectues", "en_retard", "a_venir",
                    "taux_realisation", "par_sbc", "par_sto", "par_categorie", "par_mois"):
            assert key in body, f"Clé manquante : {key}"
        assert body["total"] == len(test_passages)
        assert body["taux_realisation"] == 0.0  # aucun fait initialement
        # par_sbc doit avoir les 3 SBCs connus
        for sbc in ("Afro", "CCS", "Hammer"):
            assert sbc in body["par_sbc"], f"SBC manquant dans les stats : {sbc}"
        # par_mois : au moins quelques mois couverts
        assert len(body["par_mois"]) > 0


# ---------------------------------------------------------------------------
# Tests import SBC
# ---------------------------------------------------------------------------

class TestImports:
    def test_upload_valid_excel(self, token, test_passages, db):
        # Trouver un passage existant pour CI00001 mois 1
        passage = db.execute(
            select(Passage).join(Site).where(
                Site.code_site == "CI00001",
                Passage.mois_num == 1
            )
        ).scalar()
        assert passage is not None, "Passage CI00001/mois 1 introuvable"

        excel_data = make_excel([
            {"code_site": "CI00001", "mois_num": 1,
             "date_exec": "2026-01-15", "wo_ticket": "WO-UPLOAD-001"},
        ])
        with TestClient(app) as c:
            r = c.post(
                "/api/v1/imports/upload",
                files={"file": ("rapport.xlsx", excel_data,
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                headers=auth_header(token),
            )
        assert r.status_code == 201
        body = r.json()
        assert body["integres"] == 1
        assert body["doublons"] == 0
        assert body["non_trouves"] == 0

    def test_upload_deduplicate_wo(self, token, test_passages, db):
        excel_data = make_excel([
            {"code_site": "CI00001", "mois_num": 1, "date_exec": "2026-01-10", "wo_ticket": "WO-DUP"},
            {"code_site": "CI00001", "mois_num": 2, "date_exec": "2026-02-10", "wo_ticket": "WO-DUP"},
        ])
        with TestClient(app) as c:
            r = c.post(
                "/api/v1/imports/upload",
                files={"file": ("rapport.xlsx", excel_data,
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                headers=auth_header(token),
            )
        assert r.status_code == 201
        body = r.json()
        assert body["integres"] == 1
        assert body["doublons"] == 1

    def test_upload_unknown_site(self, token, test_passages):
        excel_data = make_excel([
            {"code_site": "CI99999", "mois_num": 1, "date_exec": "2026-01-10", "wo_ticket": "WO-UNK"},
        ])
        with TestClient(app) as c:
            r = c.post(
                "/api/v1/imports/upload",
                files={"file": ("rapport.xlsx", excel_data,
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                headers=auth_header(token),
            )
        assert r.status_code == 201
        assert r.json()["non_trouves"] == 1

    def test_upload_wrong_format(self, token):
        with TestClient(app) as c:
            r = c.post(
                "/api/v1/imports/upload",
                files={"file": ("rapport.csv", b"code_site,mois_num\n", "text/csv")},
                headers=auth_header(token),
            )
        assert r.status_code == 400
