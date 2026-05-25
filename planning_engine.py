"""
planning_engine.py
Moteur de planification et re-planification des maintenances préventives passives (PM)
Réseau télécom MTN Côte d'Ivoire — Projet MS-Huawei
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil
from typing import Any, Optional

from config import CONFIG

# ---------------------------------------------------------------------------
# Constantes métier
# ---------------------------------------------------------------------------

CATEGORIES = {"GRID_ONLY", "GRID_GEN", "SOLAR_ONLY", "GEN_ONLY"}
SBCS = {"Afro", "CCS", "Hammer"}
CYCLES = {"A", "B", "C"}

PASSAGES_PAR_CATEGORIE: dict[str, int] = {
    "GRID_ONLY": CONFIG.FREQ_GRID_ONLY,
    "GRID_GEN": CONFIG.FREQ_GRID_GEN,
    "SOLAR_ONLY": CONFIG.FREQ_SOLAR_ONLY,
    "GEN_ONLY": CONFIG.FREQ_GEN_ONLY_PAR_MOIS * 12,
}

# Mois actifs par cycle GRID_ONLY
CYCLE_MOIS: dict[str, list[int]] = CONFIG.CYCLES

# Mois → cycle (inverse de CYCLE_MOIS)
MOIS_VERS_CYCLE: dict[int, str] = {m: c for c, mois in CYCLE_MOIS.items() for m in mois}

# Capacité terrain : passages max par SBC par jour ouvrable
CAPACITE_MAX_PAR_SBC_PAR_JOUR: int = CONFIG.MAX_PASSAGES_PAR_JOUR_PAR_SBC

# Max passages intégrables par mois par catégorie (pour import_executions)
MAX_PASSAGES_PAR_MOIS: dict[str, int] = {
    "GRID_ONLY": CONFIG.MAX_PASSAGES_MOIS_GRID_ONLY,
    "GRID_GEN": CONFIG.MAX_PASSAGES_MOIS_GRID_GEN,
    "SOLAR_ONLY": CONFIG.MAX_PASSAGES_MOIS_SOLAR_ONLY,
    "GEN_ONLY": CONFIG.MAX_PASSAGES_MOIS_GEN_ONLY,
}

NOMS_MOIS = [
    "", "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]


# ---------------------------------------------------------------------------
# Structures de données
# ---------------------------------------------------------------------------

@dataclass
class Site:
    code_site: str
    nom: str
    categorie: str
    sbc: str
    sto: str
    region: str
    cycle: Optional[str] = None  # GRID_ONLY uniquement

    def __post_init__(self) -> None:
        if self.categorie not in CATEGORIES:
            raise ValueError(f"Catégorie inconnue : {self.categorie}")
        if self.sbc not in SBCS:
            raise ValueError(f"SBC inconnu : {self.sbc}")


@dataclass
class Passage:
    code_site: str
    categorie: str
    sbc: str
    sto: str
    passage_num: int
    total_passages: int
    mois_num: int
    mois_nom: str
    date_planifiee: date
    statut: str = "Prevu"          # Prevu | Fait | Non_effectue | impossible_a_rattraper
    date_execution: Optional[date] = None
    wo_ticket: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code_site": self.code_site,
            "categorie": self.categorie,
            "sbc": self.sbc,
            "sto": self.sto,
            "passage_num": self.passage_num,
            "total_passages": self.total_passages,
            "mois_num": self.mois_num,
            "mois_nom": self.mois_nom,
            "date_planifiee": self.date_planifiee,
            "statut": self.statut,
            "date_execution": self.date_execution,
            "wo_ticket": self.wo_ticket,
        }


# ---------------------------------------------------------------------------
# 1. get_working_days
# ---------------------------------------------------------------------------

def get_working_days(year: int, month: int) -> list[date]:
    """Retourne la liste des jours ouvrables (lundi–vendredi) d'un mois donné."""
    result: list[date] = []
    d = date(year, month, 1)
    while d.month == month:
        if d.weekday() < 5:  # 0=lun … 4=ven
            result.append(d)
        d += timedelta(days=1)
    return result


# ---------------------------------------------------------------------------
# 2. assign_balanced_dates
# ---------------------------------------------------------------------------

def assign_balanced_dates(
    n_sites: int,
    working_days: list[date],
    seed: int = 42,
) -> list[date]:
    """
    Distribue n_sites dates de façon équilibrée sur working_days.

    Garantit que chaque jour reçoit au plus ceil(n_sites / len(working_days))
    passages. Résultat trié, reproductible via seed.
    """
    if not working_days:
        raise ValueError("Aucun jour ouvrable disponible.")
    if n_sites == 0:
        return []

    max_par_jour = ceil(n_sites / len(working_days))
    slots: list[date] = []
    for d in working_days:
        slots.extend([d] * max_par_jour)

    rng = random.Random(seed)
    rng.shuffle(slots)
    return sorted(slots[:n_sites])


# ---------------------------------------------------------------------------
# 3. assign_grid_only_cycles
# ---------------------------------------------------------------------------

def assign_grid_only_cycles(
    sites_grid_only: list[dict[str, Any]],
    exec_history: Optional[list[dict[str, Any]]] = None,
) -> dict[str, str]:
    """
    Assigne le cycle A/B/C à chaque site GRID_ONLY.

    Priorité :
    1. Cycle explicitement présent dans les données du site.
    2. Déduction depuis exec_history (mois → cycle via MOIS_VERS_CYCLE).
    3. Distribution équilibrée des sites restants (groupe le moins peuplé).

    Retourne : {code_site: "A"|"B"|"C"}
    """
    assignments: dict[str, str] = {}

    # Cycle explicite dans les données
    for s in sites_grid_only:
        if s.get("cycle") in CYCLES:
            assignments[s["code_site"]] = s["cycle"]

    # Déduction depuis l'historique
    if exec_history:
        for entry in exec_history:
            code = entry.get("code_site")
            mois = entry.get("mois_num")
            if code and mois and code not in assignments:
                cycle = MOIS_VERS_CYCLE.get(mois)
                if cycle:
                    assignments[code] = cycle

    # Distribution équilibrée des sites restants
    sans_cycle = sorted(s["code_site"] for s in sites_grid_only if s["code_site"] not in assignments)
    if sans_cycle:
        compteurs: dict[str, int] = {"A": 0, "B": 0, "C": 0}
        for c in assignments.values():
            if c in compteurs:
                compteurs[c] += 1
        for code in sans_cycle:
            cycle_min = min(compteurs, key=lambda c: compteurs[c])
            assignments[code] = cycle_min
            compteurs[cycle_min] += 1

    return assignments


# ---------------------------------------------------------------------------
# 4. generate_planning
# ---------------------------------------------------------------------------

def generate_planning(
    sites: list[dict[str, Any]],
    year: int = 2026,
    exec_history: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """
    Génère le planning annuel complet pour tous les sites.

    exec_history : passages déjà exécutés — marqués Fait et utilisés pour
    déduire les cycles GRID_ONLY.

    Retourne une liste de dicts (un dict par passage planifié).
    """
    exec_history = exec_history or []

    # Index exec : (code_site, mois_num, rang_dans_mois) → entry
    exec_by_site_mois: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for entry in exec_history:
        exec_by_site_mois[(entry["code_site"], entry["mois_num"])].append(entry)
    for entries in exec_by_site_mois.values():
        entries.sort(key=lambda e: e.get("date_exec") or date.min)

    exec_index: dict[tuple[str, int, int], dict[str, Any]] = {
        (sm[0], sm[1], idx): entry
        for sm, entries in exec_by_site_mois.items()
        for idx, entry in enumerate(entries, start=1)
    }

    # Cycles GRID_ONLY
    sites_go = [s for s in sites if s["categorie"] == "GRID_ONLY"]
    cycle_map = assign_grid_only_cycles(sites_go, exec_history)

    # Jours ouvrables par mois
    wd_cache: dict[int, list[date]] = {m: get_working_days(year, m) for m in range(1, 13)}

    # Regrouper les sites par (mois, sbc, catégorie) pour distribution équilibrée
    # GEN_ONLY : 3 sous-groupes par mois (un par décade)
    groups: dict[tuple[int, str, str, int], list[str]] = defaultdict(list)
    # clé : (mois, sbc, catégorie, décade)  — décade = 0 pour non-GEN_ONLY

    solar_sites_ordered: list[dict[str, Any]] = [s for s in sites if s["categorie"] == "SOLAR_ONLY"]

    for s in sites:
        cat = s["categorie"]
        sbc = s["sbc"]
        code = s["code_site"]

        if cat == "GRID_ONLY":
            cycle = cycle_map.get(code, "A")
            for m in CYCLE_MOIS[cycle]:
                groups[(m, sbc, cat, 0)].append(code)

        elif cat == "GRID_GEN":
            for m in range(1, 13):
                groups[(m, sbc, cat, 0)].append(code)

        elif cat == "SOLAR_ONLY":
            idx_site = next(
                (i for i, s2 in enumerate(solar_sites_ordered) if s2["code_site"] == code),
                None,
            )
            if idx_site is None:
                continue
            start = 2 if idx_site % 2 == 0 else 1
            for m in range(start, 13, 2):
                groups[(m, sbc, cat, 0)].append(code)

        elif cat == "GEN_ONLY":
            for m in range(1, 13):
                for decade in range(3):
                    groups[(m, sbc, cat, decade)].append(code)

    # Pré-calculer les dates assignées par groupe
    decade_day_ranges = [(1, 10), (11, 20), (21, 31)]

    date_assignments: dict[tuple[int, str, str, int], list[date]] = {}
    for (mois, sbc, cat, decade), codes in groups.items():
        if cat == "GEN_ONLY":
            d_start, d_end = decade_day_ranges[decade]
            wd = [d for d in wd_cache[mois] if d_start <= d.day <= d_end]
            if not wd:
                wd = wd_cache[mois]
        else:
            wd = wd_cache[mois]

        seed = hash((year, mois, sbc, cat, decade)) & 0xFFFFFFFF
        try:
            dates = assign_balanced_dates(len(codes), wd, seed=seed)
        except ValueError:
            fallback = wd[0] if wd else date(year, mois, 1)
            dates = [fallback] * len(codes)
        date_assignments[(mois, sbc, cat, decade)] = dates

    # Compteur de position par groupe
    group_pos: dict[tuple[int, str, str, int], int] = defaultdict(int)

    def next_date(mois: int, sbc: str, cat: str, decade: int = 0) -> date:
        key = (mois, sbc, cat, decade)
        pos = group_pos[key]
        group_pos[key] += 1
        dates = date_assignments.get(key, [])
        if pos < len(dates):
            return dates[pos]
        # Fallback si le groupe est vide (ne devrait pas arriver)
        wd = wd_cache[mois]
        return wd[pos % len(wd)] if wd else date(year, mois, 1)

    def exec_info(code: str, mois: int, rang: int = 1) -> tuple[str, Optional[date], Optional[str]]:
        entry = exec_index.get((code, mois, rang))
        if entry is None:
            return "Prevu", None, None
        return "Fait", entry.get("date_exec"), entry.get("wo_ticket")

    planning: list[dict[str, Any]] = []

    for s in sites:
        cat = s["categorie"]
        sbc = s["sbc"]
        code = s["code_site"]
        sto = s["sto"]
        total = PASSAGES_PAR_CATEGORIE[cat]

        if cat == "GRID_ONLY":
            cycle = cycle_map.get(code, "A")
            for p_num, mois in enumerate(CYCLE_MOIS[cycle], start=1):
                d = next_date(mois, sbc, cat)
                statut, date_exec, wo = exec_info(code, mois)
                planning.append(Passage(
                    code_site=code, categorie=cat, sbc=sbc, sto=sto,
                    passage_num=p_num, total_passages=total,
                    mois_num=mois, mois_nom=NOMS_MOIS[mois],
                    date_planifiee=d, statut=statut,
                    date_execution=date_exec, wo_ticket=wo,
                ).to_dict())

        elif cat == "GRID_GEN":
            for p_num, mois in enumerate(range(1, 13), start=1):
                d = next_date(mois, sbc, cat)
                statut, date_exec, wo = exec_info(code, mois)
                planning.append(Passage(
                    code_site=code, categorie=cat, sbc=sbc, sto=sto,
                    passage_num=p_num, total_passages=total,
                    mois_num=mois, mois_nom=NOMS_MOIS[mois],
                    date_planifiee=d, statut=statut,
                    date_execution=date_exec, wo_ticket=wo,
                ).to_dict())

        elif cat == "SOLAR_ONLY":
            idx_site = next(
                (i for i, s2 in enumerate(solar_sites_ordered) if s2["code_site"] == code),
                None,
            )
            if idx_site is None:
                continue
            start = 2 if idx_site % 2 == 0 else 1
            mois_list = list(range(start, 13, 2))
            for p_num, mois in enumerate(mois_list, start=1):
                d = next_date(mois, sbc, cat)
                statut, date_exec, wo = exec_info(code, mois)
                planning.append(Passage(
                    code_site=code, categorie=cat, sbc=sbc, sto=sto,
                    passage_num=p_num, total_passages=total,
                    mois_num=mois, mois_nom=NOMS_MOIS[mois],
                    date_planifiee=d, statut=statut,
                    date_execution=date_exec, wo_ticket=wo,
                ).to_dict())

        elif cat == "GEN_ONLY":
            p_num = 0
            for mois in range(1, 13):
                for decade in range(3):
                    p_num += 1
                    d = next_date(mois, sbc, cat, decade)
                    rang_mois = decade + 1  # 1, 2 ou 3
                    statut, date_exec, wo = exec_info(code, mois, rang_mois)
                    planning.append(Passage(
                        code_site=code, categorie=cat, sbc=sbc, sto=sto,
                        passage_num=p_num, total_passages=total,
                        mois_num=mois, mois_nom=NOMS_MOIS[mois],
                        date_planifiee=d, statut=statut,
                        date_execution=date_exec, wo_ticket=wo,
                    ).to_dict())

    return planning


# ---------------------------------------------------------------------------
# 5. detect_missed_passages
# ---------------------------------------------------------------------------

def detect_missed_passages(
    planning: list[dict[str, Any]],
    reference_date: Optional[date] = None,
) -> list[dict[str, Any]]:
    """
    Identifie les passages en retard : statut='Prevu' ET date_planifiee < reference_date.
    Retourne la liste triée du plus ancien au plus récent.
    """
    if reference_date is None:
        reference_date = date.today()
    missed = [
        p for p in planning
        if p["statut"] == "Prevu" and p["date_planifiee"] < reference_date
    ]
    return sorted(missed, key=lambda p: p["date_planifiee"])


# ---------------------------------------------------------------------------
# 6. replan_missed_passages
# ---------------------------------------------------------------------------

def replan_missed_passages(
    planning: list[dict[str, Any]],
    sites: list[dict[str, Any]],
    year: int = 2026,
    reference_date: Optional[date] = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Re-planifie les passages manqués sur des slots futurs disponibles.

    Contrainte : max CAPACITE_MAX_PAR_SBC_PAR_JOUR passages par SBC par jour.
    Les passages impossibles à caser avant fin décembre sont marqués
    'impossible_a_rattraper' et génèrent une alerte.

    Retourne : (planning_mis_a_jour, alertes)
    alertes : liste de dicts {code_site, passage_num, message}
    """
    if reference_date is None:
        reference_date = date.today()

    end_of_year = date(year, 12, 31)

    # Occupation actuelle des slots futurs : {(date, sbc): count}
    occupation: dict[tuple[date, str], int] = defaultdict(int)
    for p in planning:
        if p["statut"] == "Prevu" and p["date_planifiee"] >= reference_date:
            occupation[(p["date_planifiee"], p["sbc"])] += 1

    # Pré-calculer les jours ouvrables futurs par SBC (partagés entre sites)
    def future_working_days_gen(from_date: date, end_date: date):
        d = from_date
        while d <= end_date:
            if d.weekday() < 5:
                yield d
            d += timedelta(days=1)

    missed = detect_missed_passages(planning, reference_date)

    # Index : (code_site, passage_num) → index dans planning
    planning_index: dict[tuple[str, int], int] = {
        (p["code_site"], p["passage_num"]): i
        for i, p in enumerate(planning)
    }

    alertes: list[dict[str, Any]] = []
    updated = [p.copy() for p in planning]

    for passage in missed:
        code = passage["code_site"]
        sbc = passage["sbc"]
        p_num = passage["passage_num"]

        # Chercher le prochain slot disponible
        slot_trouve: Optional[date] = None
        for d in future_working_days_gen(reference_date, end_of_year):
            if occupation[(d, sbc)] < CAPACITE_MAX_PAR_SBC_PAR_JOUR:
                slot_trouve = d
                break

        idx = planning_index.get((code, p_num))
        if idx is None:
            continue

        if slot_trouve is None:
            updated[idx]["statut"] = "impossible_a_rattraper"
            alertes.append({
                "code_site": code,
                "passage_num": p_num,
                "sbc": sbc,
                "message": (
                    f"Impossible de re-planifier le passage {p_num} du site {code} "
                    f"(SBC {sbc}) : capacité épuisée avant le {end_of_year}."
                ),
            })
        else:
            occupation[(slot_trouve, sbc)] += 1
            updated[idx]["date_planifiee"] = slot_trouve
            updated[idx]["statut"] = "Prevu"
            updated[idx]["mois_num"] = slot_trouve.month
            updated[idx]["mois_nom"] = NOMS_MOIS[slot_trouve.month]

    return updated, alertes


# ---------------------------------------------------------------------------
# 7. import_executions
# ---------------------------------------------------------------------------

def import_executions(
    planning: list[dict[str, Any]],
    rapport_sbc: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Intègre un rapport SBC dans le planning avec nettoyage automatique.

    rapport_sbc : liste de dicts {code_site, mois_num, date_exec, wo_ticket}

    Nettoyage :
    - Doublons de WO (garder le premier)
    - Dépassement du max passages/mois par catégorie

    Retourne : {"updated": planning_mis_a_jour, "stats": {integres, doublons, non_trouves}}
    """
    # Index planning : (code_site, mois_num) → [indices]
    plan_index: dict[tuple[str, int], list[int]] = defaultdict(list)
    for i, p in enumerate(planning):
        plan_index[(p["code_site"], p["mois_num"])].append(i)

    cat_index: dict[str, str] = {p["code_site"]: p["categorie"] for p in planning}

    updated = [p.copy() for p in planning]
    stats = {"integres": 0, "doublons": 0, "non_trouves": 0}

    seen_wo: set[str] = set()
    integrated_count: dict[tuple[str, int], int] = defaultdict(int)

    # Initialiser depuis les exécutions déjà présentes dans le planning
    for p in updated:
        if p["statut"] == "Fait":
            integrated_count[(p["code_site"], p["mois_num"])] += 1
            if p.get("wo_ticket"):
                seen_wo.add(p["wo_ticket"])

    for entry in rapport_sbc:
        code = entry.get("code_site")
        mois = entry.get("mois_num")
        date_exec = entry.get("date_exec")
        wo = entry.get("wo_ticket")

        # WO doublon
        if wo and wo in seen_wo:
            stats["doublons"] += 1
            continue

        cat = cat_index.get(code)
        if cat is None:
            stats["non_trouves"] += 1
            continue

        # Dépassement du max mensuel
        if integrated_count[(code, mois)] >= MAX_PASSAGES_PAR_MOIS[cat]:
            stats["doublons"] += 1
            continue

        # Premier passage Prevu disponible pour ce site/mois
        candidates = [
            i for i in plan_index.get((code, mois), [])
            if updated[i]["statut"] == "Prevu"
        ]
        if not candidates:
            stats["non_trouves"] += 1
            continue

        idx = candidates[0]
        updated[idx]["statut"] = "Fait"
        updated[idx]["date_execution"] = date_exec
        updated[idx]["wo_ticket"] = wo

        if wo:
            seen_wo.add(wo)
        integrated_count[(code, mois)] += 1
        stats["integres"] += 1

    return {"updated": updated, "stats": stats}


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

def print_planning_stats(planning: list[dict[str, Any]]) -> None:
    """Affiche un résumé statistique du planning."""
    total = len(planning)
    by_statut: dict[str, int] = defaultdict(int)
    by_cat: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for p in planning:
        by_statut[p["statut"]] += 1
        by_cat[p["categorie"]][p["statut"]] += 1

    print(f"\n{'='*55}")
    print(f"  PLANNING STATS  ({total} passages total)")
    print(f"{'='*55}")
    for statut, cnt in sorted(by_statut.items()):
        print(f"  {statut:<30}: {cnt:>5}")
    print(f"\n  Par catégorie :")
    for cat in sorted(by_cat):
        counts = by_cat[cat]
        total_cat = sum(counts.values())
        print(f"    {cat:<12}: {total_cat:>4} "
              f"(Fait={counts.get('Fait', 0)}, Prevu={counts.get('Prevu', 0)}, "
              f"impossible={counts.get('impossible_a_rattraper', 0)})")
    print(f"{'='*55}\n")


# ---------------------------------------------------------------------------
# Démonstration
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sites_demo = [
        {"code_site": "CI00001", "nom": "TestGridGen", "categorie": "GRID_GEN",
         "sbc": "Afro", "sto": "STO ABIDJAN NORD", "region": "LAGUNES"},
        {"code_site": "CI00002", "nom": "TestGridOnly", "categorie": "GRID_ONLY",
         "sbc": "CCS", "sto": "STO DALOA", "region": "HAUT-SASSANDRA"},
        {"code_site": "CI00003", "nom": "TestGenOnly", "categorie": "GEN_ONLY",
         "sbc": "Hammer", "sto": "STO KORHOGO", "region": "HAMBOL"},
        {"code_site": "CI00004", "nom": "TestSolar", "categorie": "SOLAR_ONLY",
         "sbc": "Afro", "sto": "STO YAMOUSSOUKRO", "region": "BELIER"},
        {"code_site": "CI00005", "nom": "GridOnly2", "categorie": "GRID_ONLY",
         "sbc": "Afro", "sto": "STO ABIDJAN SUD", "region": "LAGUNES"},
        {"code_site": "CI00006", "nom": "GridOnly3", "categorie": "GRID_ONLY",
         "sbc": "Hammer", "sto": "STO BOUAKE", "region": "GBEKE"},
    ]

    print("=" * 55)
    print("  DÉMONSTRATION DU MOTEUR DE PLANIFICATION PM")
    print("=" * 55)

    # ── 1. Génération du planning annuel ─────────────────────────
    print("\n[1] Génération du planning annuel 2026...")
    planning = generate_planning(sites_demo, year=2026)
    print(f"    -> {len(planning)} passages generes.")
    print_planning_stats(planning)

    # -- 2. Import d'executions --
    print("[2] Import d'un rapport SBC (avec doublons)...")
    rapport = [
        {"code_site": "CI00001", "mois_num": 1,
         "date_exec": date(2026, 1, 8),  "wo_ticket": "WO-2026-001"},
        {"code_site": "CI00001", "mois_num": 2,
         "date_exec": date(2026, 2, 5),  "wo_ticket": "WO-2026-002"},
        {"code_site": "CI00003", "mois_num": 1,
         "date_exec": date(2026, 1, 5),  "wo_ticket": "WO-2026-003"},
        # WO doublon
        {"code_site": "CI00001", "mois_num": 1,
         "date_exec": date(2026, 1, 9),  "wo_ticket": "WO-2026-001"},
        # Site inconnu
        {"code_site": "CI99999", "mois_num": 1,
         "date_exec": date(2026, 1, 10), "wo_ticket": "WO-2026-999"},
    ]
    result = import_executions(planning, rapport)
    planning = result["updated"]
    print(f"    -> Stats import : {result['stats']}")

    # -- 3. Detection des retards --
    ref = date(2026, 4, 1)
    print(f"\n[3] Detection des passages en retard (ref: {ref})...")
    missed = detect_missed_passages(planning, reference_date=ref)
    print(f"    -> {len(missed)} passages en retard.")
    for m in missed[:5]:
        print(f"       {m['code_site']} | passage {m['passage_num']:>2} | "
              f"prevu {m['date_planifiee']} | {m['sbc']}")
    if len(missed) > 5:
        print(f"       ... et {len(missed) - 5} autres.")

    # -- 4. Re-planification --
    print(f"\n[4] Re-planification des passages manques...")
    planning, alertes = replan_missed_passages(
        planning, sites_demo, year=2026, reference_date=ref
    )
    print(f"    -> {len(alertes)} alerte(s).")
    for a in alertes:
        print(f"       ALERTE : {a['message']}")

    # -- 5. Stats finales --
    print("\n[5] Stats finales :")
    print_planning_stats(planning)

    futurs = [p for p in planning if p["statut"] == "Prevu" and p["date_planifiee"] >= ref]
    print(f"    5 prochains passages planifies :")
    for p in sorted(futurs, key=lambda x: x["date_planifiee"])[:5]:
        print(f"       {p['code_site']} | passage {p['passage_num']:>2} | "
              f"{p['date_planifiee']} | {p['sbc']}")
