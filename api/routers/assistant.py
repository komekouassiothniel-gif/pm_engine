import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from datetime import date
from typing import List

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import google.generativeai as genai
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from api.deps import get_current_user
from database import get_db
from models import Alert, Passage, Site, StatutAlerteEnum, StatutPassageEnum, User

router = APIRouter()

_SYSTEM_PROMPT = (
    "Tu es un assistant IA spécialisé en gestion de maintenance préventive passive "
    "pour le réseau télécom MTN Côte d'Ivoire (projet MS-Huawei). "
    "Tu aides le coordinateur PM à analyser les données de planning, détecter les anomalies, "
    "anticiper les retards et générer des rapports. "
    "Tu réponds toujours en français, de façon concise et professionnelle. "
    "Voici le contexte actuel du planning : {contexte}"
)


class ChatMessage(BaseModel):
    role: str    # "user" | "model"
    content: str


class ChatRequest(BaseModel):
    message: str
    conversation_history: List[ChatMessage] = []


def _build_context(db: Session) -> str:
    today = date.today()
    current_month = today.month
    current_year = today.year

    total_sites = db.execute(
        select(func.count(Site.id)).where(Site.actif == True)
    ).scalar() or 0

    passages = db.execute(
        select(Passage)
        .options(joinedload(Passage.site))
        .where(Passage.annee == current_year)
    ).scalars().all()

    total = len(passages)
    faits = sum(1 for p in passages if p.statut == StatutPassageEnum.Fait)
    en_retard = sum(
        1 for p in passages
        if p.statut != StatutPassageEnum.Fait
        and p.date_planifiee
        and p.date_planifiee < today
        and not p.impossible_a_rattraper
    )
    faits_ce_mois = sum(
        1 for p in passages
        if p.statut == StatutPassageEnum.Fait and p.mois_num == current_month
    )
    taux = round(faits / total * 100, 1) if total else 0

    sbc_stats: dict = {}
    for p in passages:
        sbc = p.site.sbc.value if p.site else "?"
        s = sbc_stats.setdefault(sbc, {"total": 0, "faits": 0})
        s["total"] += 1
        if p.statut == StatutPassageEnum.Fait:
            s["faits"] += 1

    top_sbc = sorted(
        [
            (sbc, round(v["faits"] / v["total"] * 100, 1) if v["total"] else 0)
            for sbc, v in sbc_stats.items()
        ],
        key=lambda x: x[1],
        reverse=True,
    )[:3]

    alertes = db.execute(
        select(Alert.niveau, func.count(Alert.id))
        .where(Alert.statut.in_([
            StatutAlerteEnum.nouvelle,
            StatutAlerteEnum.vue,
            StatutAlerteEnum.prise_en_charge,
        ]))
        .group_by(Alert.niveau)
    ).all()
    alertes_str = ", ".join(f"{n.value}: {c}" for n, c in alertes) or "aucune"

    return (
        f"Date: {today.strftime('%d/%m/%Y')} | "
        f"Sites actifs: {total_sites} | "
        f"Taux réalisation {current_year}: {taux}% ({faits}/{total} passages) | "
        f"Passages en retard: {en_retard} | "
        f"Faits en {today.strftime('%B %Y')}: {faits_ce_mois} | "
        f"Top SBC: {', '.join(f'{s}={t}%' for s, t in top_sbc)} | "
        f"Alertes actives — {alertes_str}"
    )


@router.post("/chat", summary="Chat avec l'assistant IA Gemini")
def chat(
    req: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(500, "GEMINI_API_KEY manquante dans la configuration serveur")

    try:
        contexte = _build_context(db)
        system_prompt = _SYSTEM_PROMPT.format(contexte=contexte)

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=system_prompt,
        )

        history = [
            {"role": msg.role, "parts": [msg.content]}
            for msg in req.conversation_history
        ]
        session = model.start_chat(history=history)
        response = session.send_message(req.message)

        return {"reply": response.text, "contexte_utilise": contexte}

    except Exception as exc:
        raise HTTPException(502, f"Erreur Gemini : {exc}")
