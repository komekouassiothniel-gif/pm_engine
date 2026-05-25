"""
config.py
Constantes métier centralisées pour le moteur de planification PM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class PlanningConfig:
    # Capacité terrain
    MAX_PASSAGES_PAR_JOUR_PAR_SBC: int = 15

    # Fréquences contractuelles (passages/an sauf GEN_ONLY qui est par mois)
    FREQ_GRID_ONLY: int = 4
    FREQ_GRID_GEN: int = 12
    FREQ_SOLAR_ONLY: int = 6
    FREQ_GEN_ONLY_PAR_MOIS: int = 3  # × 12 mois = 36/an

    # Cycles GRID_ONLY : initialisés dans __post_init__ pour éviter les mutables par défaut
    CYCLES: Optional[dict] = None

    # Déduplication import SBC : max passages acceptés par mois et par catégorie
    MAX_PASSAGES_MOIS_GRID_ONLY: int = 1
    MAX_PASSAGES_MOIS_GRID_GEN: int = 1
    MAX_PASSAGES_MOIS_SOLAR_ONLY: int = 1
    MAX_PASSAGES_MOIS_GEN_ONLY: int = 3

    # Paramètres de planification
    ANNEE: int = 2026
    RANDOM_SEED: int = 42

    def __post_init__(self) -> None:
        if self.CYCLES is None:
            self.CYCLES = {
                "A": [1, 4, 7, 10],
                "B": [2, 5, 8, 11],
                "C": [3, 6, 9, 12],
            }


CONFIG = PlanningConfig()
