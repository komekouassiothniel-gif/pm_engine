"""
seed.py
Peuplement initial de la base de données pour le projet PM MTN CI.

Usage :
    python seed.py

Ce script :
  1. Initialise le schéma (create_all)
  2. Insère 1 utilisateur admin de test
  3. Insère les 4 sites de test du moteur de planification
  4. Génère et insère le planning annuel 2026 complet
  5. Affiche un résumé
"""

import sys
import os

# Assure que le dossier courant est dans le path (pour imports relatifs)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import select

from api.deps import hash_password
from database import SessionLocal, init_db
from models import (
    Alert,
    CategorieEnum,
    Import,
    NiveauAlerteEnum,
    Passage,
    RoleEnum,
    SBCEnum,
    Site,
    StatutAlerteEnum,
    StatutImportEnum,
    StatutPassageEnum,
    User,
)
from planning_engine import generate_planning

# ---------------------------------------------------------------------------
# Données de test
# ---------------------------------------------------------------------------

SITES_TEST = [
    {
        "code_site": "CI00001",
        "nom": "TestGridGen",
        "categorie": "GRID_GEN",
        "sbc": "Afro",
        "sto": "STO ABIDJAN NORD",
        "region": "LAGUNES",
    },
    {
        "code_site": "CI00002",
        "nom": "TestGridOnly",
        "categorie": "GRID_ONLY",
        "sbc": "CCS",
        "sto": "STO DALOA",
        "region": "HAUT-SASSANDRA",
    },
    {
        "code_site": "CI00003",
        "nom": "TestGenOnly",
        "categorie": "GEN_ONLY",
        "sbc": "Hammer",
        "sto": "STO KORHOGO",
        "region": "HAMBOL",
    },
    {
        "code_site": "CI00004",
        "nom": "TestSolar",
        "categorie": "SOLAR_ONLY",
        "sbc": "Afro",
        "sto": "STO YAMOUSSOUKRO",
        "region": "BELIER",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_password(password: str) -> str:
    """Hash bcrypt via passlib — compatible avec l'authentification JWT."""
    return hash_password(password)


def _statut_passage(statut_str: str) -> tuple[StatutPassageEnum, bool]:
    """
    Convertit le statut string du moteur de planification en
    (StatutPassageEnum, impossible_a_rattraper).
    """
    if statut_str == "impossible_a_rattraper":
        return StatutPassageEnum.Non_effectue, True
    mapping = {
        "Prevu":        StatutPassageEnum.Prevu,
        "Fait":         StatutPassageEnum.Fait,
        "Non_effectue": StatutPassageEnum.Non_effectue,
    }
    return mapping.get(statut_str, StatutPassageEnum.Prevu), False


# ---------------------------------------------------------------------------
# Seed principal
# ---------------------------------------------------------------------------

def seed() -> None:
    print("=" * 55)
    print("  SEED — Base de données PM MTN CI")
    print("=" * 55)

    # 1. Création du schéma
    print("\n[1] Initialisation du schema (create_all)...")
    try:
        init_db()
        print("    OK — Schema pret.")
    except Exception as exc:
        print(f"    ERREUR lors de l'initialisation : {exc}")
        print("    Verifiez que PostgreSQL est demarré et que DATABASE_URL est correcte.")
        sys.exit(1)

    db = SessionLocal()
    try:
        # ── 2. Vérification anti-doublons ────────────────────────
        existing_admin = db.execute(
            select(User).where(User.email == "admin@mtn-ci.com")
        ).scalar_one_or_none()

        if existing_admin is not None:
            print("\n  La base contient déjà des données de seed.")
            print("  Supprimez les tables et relancez si vous voulez re-seeder.")
            return

        # ── 3. Utilisateur admin ──────────────────────────────────
        print("\n[2] Creation de l'utilisateur admin...")
        admin = User(
            nom="Administrateur",
            email="admin@mtn-ci.com",
            password_hash=_hash_password("Admin2026!"),
            role=RoleEnum.admin,
            actif=True,
        )
        db.add(admin)
        db.flush()  # obtenir admin.id sans commit
        print(f"    OK — User id={admin.id} email={admin.email!r}")

        # ── 4. Sites de test ──────────────────────────────────────
        print("\n[3] Insertion des sites de test...")
        site_map: dict[str, Site] = {}
        for s_data in SITES_TEST:
            site = Site(
                code_site=s_data["code_site"],
                nom=s_data["nom"],
                categorie=CategorieEnum[s_data["categorie"]],
                sbc=SBCEnum[s_data["sbc"]],
                sto=s_data["sto"],
                region=s_data["region"],
                actif=True,
            )
            db.add(site)
            db.flush()
            site_map[s_data["code_site"]] = site
            print(f"    + {site.code_site} ({site.categorie.value}, {site.sbc.value})"
                  f"  → id={site.id}")

        # ── 5. Planning complet via le moteur ─────────────────────
        print("\n[4] Generation du planning 2026 via planning_engine...")
        planning_dicts = generate_planning(SITES_TEST, year=2026)
        print(f"    Moteur -> {len(planning_dicts)} passages calcules.")

        # ── 6. Insertion des passages ──────────────────────────────
        print("\n[5] Insertion des passages en base...")
        passage_objects: list[Passage] = []
        for p_dict in planning_dicts:
            code = p_dict["code_site"]
            site = site_map[code]
            statut_enum, impossible = _statut_passage(p_dict["statut"])

            passage = Passage(
                site_id=site.id,
                passage_num=p_dict["passage_num"],
                total_passages=p_dict["total_passages"],
                mois_num=p_dict["mois_num"],
                mois_nom=p_dict["mois_nom"],
                annee=2026,
                date_planifiee=p_dict["date_planifiee"],
                statut=statut_enum,
                impossible_a_rattraper=impossible,
            )
            db.add(passage)
            passage_objects.append(passage)

        # ── 7. Exemple d'alerte de démo ───────────────────────────
        demo_site = site_map.get("CI00003")  # GEN_ONLY — site le plus actif
        if demo_site:
            alerte = Alert(
                niveau=NiveauAlerteEnum.information,
                type_alerte="import",
                site_id=demo_site.id,
                message="Planning initial 2026 genere avec succes.",
                statut=StatutAlerteEnum.nouvelle,
            )
            db.add(alerte)

        # ── 8. Exemple de traçabilité d'import ────────────────────
        import_log = Import(
            nom_fichier="seed_initial_2026.py",
            importe_par=admin.id,
            nb_lignes_brut=len(planning_dicts),
            nb_integres=len(planning_dicts),
            nb_doublons=0,
            nb_max_depasse=0,
            nb_non_trouves=0,
            statut=StatutImportEnum.succes,
        )
        db.add(import_log)

        # ── 9. Commit final ───────────────────────────────────────
        db.commit()

        # ── 10. Résumé ────────────────────────────────────────────
        print("\n" + "=" * 55)
        print("  SEED TERMINE AVEC SUCCES")
        print("=" * 55)
        print(f"  Sites inseres    : {len(site_map)}")
        print(f"  Passages crees   : {len(passage_objects)}")
        print(f"  Repartition      :")

        from collections import Counter
        by_cat = Counter(p["categorie"] for p in planning_dicts)
        for cat, cnt in sorted(by_cat.items()):
            print(f"    {cat:<12} : {cnt} passages")

        print(f"\n  Connexion admin  : admin@mtn-ci.com / Admin2026!")
        print("=" * 55)

    except Exception as exc:
        db.rollback()
        print(f"\nERREUR — rollback effectue : {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
