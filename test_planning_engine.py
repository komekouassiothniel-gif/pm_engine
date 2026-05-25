"""
test_planning_engine.py
Tests unitaires du moteur de planification PM — pytest
"""

import pytest
from datetime import date
from collections import Counter

from config import CONFIG
from planning_engine import (
    PASSAGES_PAR_CATEGORIE,
    CYCLE_MOIS,
    assign_balanced_dates,
    assign_grid_only_cycles,
    detect_missed_passages,
    generate_planning,
    get_working_days,
    import_executions,
    replan_missed_passages,
)

# ---------------------------------------------------------------------------
# Sites de test
# ---------------------------------------------------------------------------

SITES_TEST = [
    {"code_site": "CI00001", "nom": "TestGridGen", "categorie": "GRID_GEN",
     "sbc": "Afro", "sto": "STO ABIDJAN NORD", "region": "LAGUNES"},
    {"code_site": "CI00002", "nom": "TestGridOnly", "categorie": "GRID_ONLY",
     "sbc": "CCS", "sto": "STO DALOA", "region": "HAUT-SASSANDRA"},
    {"code_site": "CI00003", "nom": "TestGenOnly", "categorie": "GEN_ONLY",
     "sbc": "Hammer", "sto": "STO KORHOGO", "region": "HAMBOL"},
    {"code_site": "CI00004", "nom": "TestSolar", "categorie": "SOLAR_ONLY",
     "sbc": "Afro", "sto": "STO YAMOUSSOUKRO", "region": "BELIER"},
]


# ---------------------------------------------------------------------------
# Fixtures (scope=module : generate_planning calculé une seule fois par suite)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def planning_grid_gen():
    return generate_planning([SITES_TEST[0]], year=2026)


@pytest.fixture(scope="module")
def planning_grid_only():
    return generate_planning([SITES_TEST[1]], year=2026)


@pytest.fixture(scope="module")
def planning_gen_only():
    return generate_planning([SITES_TEST[2]], year=2026)


@pytest.fixture(scope="module")
def planning_solar_only():
    return generate_planning([SITES_TEST[3]], year=2026)


@pytest.fixture(scope="module")
def planning_all():
    return generate_planning(SITES_TEST, year=2026)


# ---------------------------------------------------------------------------
# get_working_days
# ---------------------------------------------------------------------------

class TestGetWorkingDays:
    def test_january_2026_count(self):
        wd = get_working_days(2026, 1)
        # Janvier 2026 : 31 jours, pas de jours fériés spéciaux
        assert len(wd) == 22

    def test_all_weekdays(self):
        wd = get_working_days(2026, 3)
        for d in wd:
            assert d.weekday() < 5, f"{d} est un week-end"

    def test_all_in_correct_month(self):
        wd = get_working_days(2026, 6)
        for d in wd:
            assert d.month == 6

    def test_february_2026(self):
        wd = get_working_days(2026, 2)
        assert len(wd) == 20  # Fév 2026 : 28 jours, 20 ouvrables


# ---------------------------------------------------------------------------
# assign_balanced_dates
# ---------------------------------------------------------------------------

class TestAssignBalancedDates:
    def test_count_matches_n_sites(self):
        wd = get_working_days(2026, 1)
        dates = assign_balanced_dates(50, wd, seed=42)
        assert len(dates) == 50

    def test_no_date_outside_working_days(self):
        wd = get_working_days(2026, 3)
        wd_set = set(wd)
        dates = assign_balanced_dates(30, wd, seed=0)
        for d in dates:
            assert d in wd_set

    def test_balanced_distribution(self):
        wd = get_working_days(2026, 1)
        n = 100
        dates = assign_balanced_dates(n, wd, seed=7)
        from math import ceil
        max_per_day = ceil(n / len(wd))
        counter = Counter(dates)
        for d, cnt in counter.items():
            assert cnt <= max_per_day, f"{d} a {cnt} passages (max {max_per_day})"

    def test_reproducible_with_seed(self):
        wd = get_working_days(2026, 5)
        d1 = assign_balanced_dates(20, wd, seed=99)
        d2 = assign_balanced_dates(20, wd, seed=99)
        assert d1 == d2

    def test_different_seeds_differ(self):
        wd = get_working_days(2026, 5)
        d1 = assign_balanced_dates(20, wd, seed=1)
        d2 = assign_balanced_dates(20, wd, seed=2)
        assert d1 != d2

    def test_zero_sites(self):
        wd = get_working_days(2026, 1)
        assert assign_balanced_dates(0, wd) == []

    def test_empty_working_days_raises(self):
        with pytest.raises(ValueError):
            assign_balanced_dates(5, [])


# ---------------------------------------------------------------------------
# assign_grid_only_cycles
# ---------------------------------------------------------------------------

class TestAssignGridOnlyCycles:
    def _make_sites(self, n: int) -> list[dict]:
        return [
            {"code_site": f"CI{i:05d}", "categorie": "GRID_ONLY",
             "sbc": "Afro", "sto": "X", "region": "Y"}
            for i in range(n)
        ]

    def test_groups_are_balanced_312_sites(self):
        sites = self._make_sites(312)
        assignments = assign_grid_only_cycles(sites)
        counts = Counter(assignments.values())
        # 312 / 3 = 104 — chaque groupe doit être exactement 104
        assert counts["A"] == 104
        assert counts["B"] == 104
        assert counts["C"] == 104

    def test_groups_balanced_non_divisible(self):
        sites = self._make_sites(100)
        assignments = assign_grid_only_cycles(sites)
        counts = Counter(assignments.values())
        # Différence max entre groupes = 1
        assert max(counts.values()) - min(counts.values()) <= 1

    def test_deduces_cycle_from_history(self):
        sites = [{"code_site": "CI00001", "categorie": "GRID_ONLY",
                  "sbc": "Afro", "sto": "X", "region": "Y"}]
        history = [{"code_site": "CI00001", "mois_num": 4}]  # Avril → cycle A
        assignments = assign_grid_only_cycles(sites, exec_history=history)
        assert assignments["CI00001"] == "A"

    def test_explicit_cycle_takes_priority(self):
        sites = [{"code_site": "CI00001", "categorie": "GRID_ONLY",
                  "sbc": "Afro", "sto": "X", "region": "Y", "cycle": "C"}]
        history = [{"code_site": "CI00001", "mois_num": 1}]  # Janv → A, mais C explicite
        assignments = assign_grid_only_cycles(sites, exec_history=history)
        assert assignments["CI00001"] == "C"

    def test_all_sites_assigned(self):
        sites = self._make_sites(50)
        assignments = assign_grid_only_cycles(sites)
        assert len(assignments) == 50
        for v in assignments.values():
            assert v in {"A", "B", "C"}


# ---------------------------------------------------------------------------
# generate_planning
# ---------------------------------------------------------------------------

class TestGeneratePlanning:
    def test_grid_gen_12_passages(self, planning_grid_gen):
        assert len(planning_grid_gen) == 12

    def test_grid_only_4_passages(self, planning_grid_only):
        assert len(planning_grid_only) == 4

    def test_gen_only_36_passages(self, planning_gen_only):
        assert len(planning_gen_only) == 36

    def test_solar_only_6_passages(self, planning_solar_only):
        assert len(planning_solar_only) == 6

    def test_passage_nums_sequential(self, planning_grid_gen):
        nums = [p["passage_num"] for p in planning_grid_gen]
        assert nums == list(range(1, 13))

    def test_total_passages_correct(self, planning_grid_gen):
        for p in planning_grid_gen:
            assert p["total_passages"] == 12

    def test_all_dates_are_working_days(self, planning_all):
        for p in planning_all:
            assert p["date_planifiee"].weekday() < 5, (
                f"{p['code_site']} passage {p['passage_num']} planifié un week-end : "
                f"{p['date_planifiee']}"
            )

    def test_grid_only_mois_coherent_with_cycle(self, planning_grid_only):
        assignments = assign_grid_only_cycles([SITES_TEST[1]])
        cycle = assignments["CI00002"]
        expected_months = set(CYCLE_MOIS[cycle])
        actual_months = {p["mois_num"] for p in planning_grid_only}
        assert actual_months == expected_months

    def test_exec_history_marks_fait(self):
        sites = [SITES_TEST[0]]
        history = [{"code_site": "CI00001", "mois_num": 1,
                    "date_exec": date(2026, 1, 8), "wo_ticket": "WO-001"}]
        planning = generate_planning(sites, year=2026, exec_history=history)
        jan_passage = next((p for p in planning if p["mois_num"] == 1), None)
        assert jan_passage is not None, "Aucun passage trouvé pour le mois 1"
        assert jan_passage["statut"] == "Fait"
        assert jan_passage["wo_ticket"] == "WO-001"

    def test_full_count_all_sites(self, planning_all):
        expected = sum(PASSAGES_PAR_CATEGORIE[s["categorie"]] for s in SITES_TEST)
        assert len(planning_all) == expected

    def test_gen_only_3_passages_per_month(self, planning_gen_only):
        by_month = Counter(p["mois_num"] for p in planning_gen_only)
        for m in range(1, 13):
            assert by_month[m] == 3, f"Mois {m} : {by_month[m]} passages (attendu 3)"


# ---------------------------------------------------------------------------
# detect_missed_passages
# ---------------------------------------------------------------------------

class TestDetectMissedPassages:
    def test_detects_past_prevu(self):
        planning = [
            {"code_site": "CI00001", "passage_num": 1, "statut": "Prevu",
             "date_planifiee": date(2026, 1, 15)},
            {"code_site": "CI00001", "passage_num": 2, "statut": "Prevu",
             "date_planifiee": date(2026, 5, 10)},
        ]
        missed = detect_missed_passages(planning, reference_date=date(2026, 4, 1))
        assert len(missed) == 1
        assert missed[0]["passage_num"] == 1

    def test_fait_not_detected(self):
        planning = [
            {"code_site": "CI00001", "passage_num": 1, "statut": "Fait",
             "date_planifiee": date(2026, 1, 15)},
        ]
        assert detect_missed_passages(planning, date(2026, 4, 1)) == []

    def test_sorted_oldest_first(self):
        planning = [
            {"code_site": "CI00001", "passage_num": 3, "statut": "Prevu",
             "date_planifiee": date(2026, 3, 10)},
            {"code_site": "CI00001", "passage_num": 1, "statut": "Prevu",
             "date_planifiee": date(2026, 1, 8)},
            {"code_site": "CI00001", "passage_num": 2, "statut": "Prevu",
             "date_planifiee": date(2026, 2, 5)},
        ]
        missed = detect_missed_passages(planning, date(2026, 4, 1))
        dates = [m["date_planifiee"] for m in missed]
        assert dates == sorted(dates)


# ---------------------------------------------------------------------------
# replan_missed_passages
# ---------------------------------------------------------------------------

class TestReplanMissedPassages:
    def test_missed_march_replanned_on_future_slot(self):
        """Un passage manqué en mars doit être re-planifié sur un slot futur."""
        sites = [SITES_TEST[0]]  # GRID_GEN, Afro
        planning = generate_planning(sites, year=2026)
        ref = date(2026, 4, 1)

        # Vérifier qu'il y a bien des passages manqués avant de re-planifier
        missed_before = detect_missed_passages(planning, ref)
        assert len(missed_before) > 0

        updated, alertes = replan_missed_passages(planning, sites, year=2026, reference_date=ref)

        # Après re-planification, les passages re-planifiés doivent être ≥ ref
        still_missed = detect_missed_passages(updated, ref)
        assert len(still_missed) == 0, (
            f"Des passages sont encore en retard : {still_missed}"
        )

    def test_replanned_dates_are_working_days(self):
        sites = [SITES_TEST[0]]
        planning = generate_planning(sites, year=2026)
        ref = date(2026, 6, 1)
        updated, _ = replan_missed_passages(planning, sites, year=2026, reference_date=ref)
        for p in updated:
            if p["statut"] == "Prevu":
                assert p["date_planifiee"].weekday() < 5

    def test_capacity_respected(self):
        """Aucun jour ne doit dépasser CAPACITE_MAX_PAR_SBC_PAR_JOUR."""
        from planning_engine import CAPACITE_MAX_PAR_SBC_PAR_JOUR
        sites = [SITES_TEST[0]]
        planning = generate_planning(sites, year=2026)
        ref = date(2026, 6, 1)
        updated, _ = replan_missed_passages(planning, sites, year=2026, reference_date=ref)

        from collections import defaultdict
        occ: dict[tuple, int] = defaultdict(int)
        for p in updated:
            if p["statut"] == "Prevu":
                occ[(p["date_planifiee"], p["sbc"])] += 1
        for (d, sbc), cnt in occ.items():
            assert cnt <= CAPACITE_MAX_PAR_SBC_PAR_JOUR

    def test_impossible_generates_alert(self):
        """Si fin d'année trop proche, générer une alerte impossible_a_rattraper."""
        sites = [SITES_TEST[2]]  # GEN_ONLY : 36 passages — facile à saturer
        planning = generate_planning(sites, year=2026)
        # Référence au 31 déc → tout est en retard, et il n'y a plus de slots
        ref = date(2026, 12, 31)
        updated, alertes = replan_missed_passages(planning, sites, year=2026, reference_date=ref)
        impossible = [p for p in updated if p["statut"] == "impossible_a_rattraper"]
        assert len(impossible) > 0
        assert len(alertes) > 0


# ---------------------------------------------------------------------------
# import_executions
# ---------------------------------------------------------------------------

class TestImportExecutions:
    def test_basic_integration(self):
        sites = [SITES_TEST[0]]
        planning = generate_planning(sites, year=2026)
        rapport = [{"code_site": "CI00001", "mois_num": 1,
                    "date_exec": date(2026, 1, 8), "wo_ticket": "WO-001"}]
        result = import_executions(planning, rapport)
        assert result["stats"]["integres"] == 1
        jan = next(
            (p for p in result["updated"]
             if p["code_site"] == "CI00001" and p["mois_num"] == 1 and p["statut"] == "Fait"),
            None,
        )
        assert jan is not None, "Passage janvier CI00001 non trouvé ou non marqué Fait"
        assert jan["wo_ticket"] == "WO-001"

    def test_wo_deduplication(self):
        sites = [SITES_TEST[0]]
        planning = generate_planning(sites, year=2026)
        rapport = [
            {"code_site": "CI00001", "mois_num": 1,
             "date_exec": date(2026, 1, 8),  "wo_ticket": "WO-DUP"},
            {"code_site": "CI00001", "mois_num": 2,
             "date_exec": date(2026, 2, 10), "wo_ticket": "WO-DUP"},  # même WO
        ]
        result = import_executions(planning, rapport)
        assert result["stats"]["integres"] == 1
        assert result["stats"]["doublons"] == 1

    def test_unknown_site_counted_as_not_found(self):
        sites = [SITES_TEST[0]]
        planning = generate_planning(sites, year=2026)
        rapport = [{"code_site": "CI99999", "mois_num": 1,
                    "date_exec": date(2026, 1, 8), "wo_ticket": "WO-XXX"}]
        result = import_executions(planning, rapport)
        assert result["stats"]["non_trouves"] == 1
        assert result["stats"]["integres"] == 0

    def test_max_per_month_grid_gen(self):
        """GRID_GEN : max 1 passage/mois — le 2e est compté comme doublon."""
        sites = [SITES_TEST[0]]
        planning = generate_planning(sites, year=2026)
        rapport = [
            {"code_site": "CI00001", "mois_num": 3,
             "date_exec": date(2026, 3, 5),  "wo_ticket": "WO-A"},
            {"code_site": "CI00001", "mois_num": 3,
             "date_exec": date(2026, 3, 12), "wo_ticket": "WO-B"},
        ]
        result = import_executions(planning, rapport)
        assert result["stats"]["integres"] == 1
        assert result["stats"]["doublons"] == 1

    def test_max_per_month_gen_only(self):
        """GEN_ONLY : max 3 passages/mois — le 4e est compté comme doublon."""
        sites = [SITES_TEST[2]]
        planning = generate_planning(sites, year=2026)
        rapport = [
            {"code_site": "CI00003", "mois_num": 1,
             "date_exec": date(2026, 1, 3),  "wo_ticket": "WO-G1"},
            {"code_site": "CI00003", "mois_num": 1,
             "date_exec": date(2026, 1, 12), "wo_ticket": "WO-G2"},
            {"code_site": "CI00003", "mois_num": 1,
             "date_exec": date(2026, 1, 22), "wo_ticket": "WO-G3"},
            {"code_site": "CI00003", "mois_num": 1,
             "date_exec": date(2026, 1, 25), "wo_ticket": "WO-G4"},  # 4e → doublon
        ]
        result = import_executions(planning, rapport)
        assert result["stats"]["integres"] == 3
        assert result["stats"]["doublons"] == 1

    def test_stats_keys_present(self):
        sites = [SITES_TEST[0]]
        planning = generate_planning(sites, year=2026)
        result = import_executions(planning, [])
        assert set(result["stats"].keys()) == {"integres", "doublons", "non_trouves"}

    def test_planning_length_unchanged(self):
        sites = [SITES_TEST[0]]
        planning = generate_planning(sites, year=2026)
        rapport = [{"code_site": "CI00001", "mois_num": 1,
                    "date_exec": date(2026, 1, 8), "wo_ticket": "WO-001"}]
        result = import_executions(planning, rapport)
        assert len(result["updated"]) == len(planning)


# ---------------------------------------------------------------------------
# TestConfig
# ---------------------------------------------------------------------------

class TestConfig:
    def test_config_values_coherent(self):
        """FREQ_GEN_ONLY_PAR_MOIS * 12 doit correspondre à PASSAGES_PAR_CATEGORIE."""
        assert CONFIG.FREQ_GEN_ONLY_PAR_MOIS * 12 == PASSAGES_PAR_CATEGORIE["GEN_ONLY"]


# ---------------------------------------------------------------------------
# TestAdditionalCoverage
# ---------------------------------------------------------------------------

class TestAdditionalCoverage:
    def test_replan_respects_capacity(self):
        """Aucun SBC ne dépasse MAX_PASSAGES_PAR_JOUR_PAR_SBC après re-planification."""
        from collections import defaultdict
        sites = [
            {"code_site": f"CI{i:05d}", "nom": f"Site{i}", "categorie": "GRID_GEN",
             "sbc": "Afro", "sto": "X", "region": "Y"}
            for i in range(1, 20)
        ]
        planning = generate_planning(sites, year=2026)
        ref = date(2026, 6, 1)
        updated, _ = replan_missed_passages(planning, sites, year=2026, reference_date=ref)
        occ: dict = defaultdict(int)
        for p in updated:
            if p["statut"] == "Prevu":
                occ[(p["date_planifiee"], p["sbc"])] += 1
        for (d, sbc), cnt in occ.items():
            assert cnt <= CONFIG.MAX_PASSAGES_PAR_JOUR_PAR_SBC, (
                f"{sbc} a {cnt} passages le {d} (max {CONFIG.MAX_PASSAGES_PAR_JOUR_PAR_SBC})"
            )

    def test_grid_only_cycle_deterministic(self):
        """assign_grid_only_cycles retourne le même résultat sur 3 appels successifs."""
        sites = [
            {"code_site": f"CI{i:05d}", "categorie": "GRID_ONLY",
             "sbc": "Afro", "sto": "X", "region": "Y"}
            for i in range(30)
        ]
        results = [assign_grid_only_cycles(sites) for _ in range(3)]
        assert results[0] == results[1] == results[2]

    def test_import_max_gen_only_3_per_month(self):
        """5 entrées Gen Only même mois → max 3 intégrées, 2 comptées comme doublons."""
        planning = generate_planning([SITES_TEST[2]], year=2026)
        rapport = [
            {"code_site": "CI00003", "mois_num": 1,
             "date_exec": date(2026, 1, d), "wo_ticket": f"WO-G{d}"}
            for d in [5, 12, 22, 26, 28]
        ]
        result = import_executions(planning, rapport)
        assert result["stats"]["integres"] == 3
        assert result["stats"]["doublons"] == 2

    def test_end_of_year_alert_generated(self):
        """Passage impossible à rattraper → statut correct et structure d'alerte valide."""
        sites = [SITES_TEST[2]]
        planning = generate_planning(sites, year=2026)
        ref = date(2026, 12, 31)
        updated, alertes = replan_missed_passages(planning, sites, year=2026, reference_date=ref)
        impossible = [p for p in updated if p["statut"] == "impossible_a_rattraper"]
        assert len(impossible) > 0
        assert len(alertes) > 0
        for alerte in alertes:
            assert "impossible" in alerte["message"].lower()
            assert {"code_site", "passage_num", "sbc", "message"}.issubset(alerte.keys())
