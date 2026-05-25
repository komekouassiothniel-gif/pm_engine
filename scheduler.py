"""
scheduler.py — Tâches planifiées pour PM MTN CI (MS-Huawei).
Démarré au lancement de l'API via api/main.py (lifespan).

Job actif :
  - Le 20 de chaque mois à 08h00 : alerte de rappel "mise_a_jour_sites"
    (évite les doublons si une alerte ouverte existe déjà)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

_scheduler = BackgroundScheduler(timezone="UTC")


def _monthly_site_update_reminder(db_factory) -> None:
    db = db_factory()
    try:
        from sqlalchemy import select
        from models import Alert, NiveauAlerteEnum, StatutAlerteEnum

        # Ne crée pas de doublon si une alerte ouverte existe déjà
        existing = db.execute(
            select(Alert).where(
                Alert.type_alerte == "mise_a_jour_sites",
                Alert.statut.in_([
                    StatutAlerteEnum.nouvelle,
                    StatutAlerteEnum.prise_en_charge,
                ]),
            )
        ).scalar_one_or_none()

        if existing:
            return

        db.add(Alert(
            niveau=NiveauAlerteEnum.avertissement,
            type_alerte="mise_a_jour_sites",
            message=(
                "Rappel : mise à jour mensuelle des sites à effectuer (20 du mois). "
                "Uploadez la liste mise à jour via Sites > Mise à jour mensuelle."
            ),
            statut=StatutAlerteEnum.nouvelle,
        ))
        db.commit()
        print("[Scheduler] Alerte 'mise_a_jour_sites' créée.")

    except Exception as exc:
        db.rollback()
        print(f"[Scheduler] Erreur job mise_a_jour_sites : {exc}")
    finally:
        db.close()


def start_scheduler(db_factory) -> None:
    _scheduler.add_job(
        _monthly_site_update_reminder,
        trigger=CronTrigger(day=20, hour=8, minute=0),
        args=[db_factory],
        id="monthly_site_update_reminder",
        replace_existing=True,
    )
    _scheduler.start()
    print("[Scheduler] Démarré — job 'mise_a_jour_sites' le 20 de chaque mois à 08h00 UTC.")


def stop_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        print("[Scheduler] Arrêté.")
