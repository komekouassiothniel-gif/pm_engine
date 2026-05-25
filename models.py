"""
models.py
Modèles SQLAlchemy 2.x pour l'application PM MTN Côte d'Ivoire (MS-Huawei).
"""

import enum
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums Python
# ---------------------------------------------------------------------------

class CategorieEnum(enum.Enum):
    GRID_ONLY  = "GRID_ONLY"
    GRID_GEN   = "GRID_GEN"
    SOLAR_ONLY = "SOLAR_ONLY"
    GEN_ONLY   = "GEN_ONLY"


class SBCEnum(enum.Enum):
    Afro   = "Afro"
    CCS    = "CCS"
    Hammer = "Hammer"


class StatutPassageEnum(enum.Enum):
    Prevu         = "Prevu"
    Fait          = "Fait"
    Non_effectue  = "Non_effectue"


class NiveauAlerteEnum(enum.Enum):
    critique      = "critique"
    avertissement = "avertissement"
    information   = "information"


class StatutAlerteEnum(enum.Enum):
    nouvelle          = "nouvelle"
    vue               = "vue"
    prise_en_charge   = "prise_en_charge"
    fermee            = "fermee"


class StatutImportEnum(enum.Enum):
    succes  = "succes"
    echec   = "echec"
    partiel = "partiel"


class RoleEnum(enum.Enum):
    admin   = "admin"
    manager = "manager"
    sbc     = "sbc"
    client  = "client"


# ---------------------------------------------------------------------------
# User  (défini en premier — référencé par Import et Alert)
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id                  : Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    nom                 : Mapped[str]            = mapped_column(String(100), nullable=False)
    email               : Mapped[str]            = mapped_column(String(150), unique=True, nullable=False)
    password_hash       : Mapped[str]            = mapped_column(String(255), nullable=False)
    role                : Mapped[RoleEnum]       = mapped_column(SAEnum(RoleEnum), nullable=False)
    sbc_associe         : Mapped[Optional[str]]  = mapped_column(String(20), nullable=True)
    actif               : Mapped[bool]           = mapped_column(Boolean, default=True, nullable=False)
    derniere_connexion  : Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at          : Mapped[datetime]       = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Relations
    imports: Mapped[List["Import"]] = relationship(
        "Import", back_populates="auteur"
    )
    alertes_gerees: Mapped[List["Alert"]] = relationship(
        "Alert",
        back_populates="gestionnaire",
        foreign_keys="[Alert.prise_en_charge_par]",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role.value!r}>"


# ---------------------------------------------------------------------------
# Site
# ---------------------------------------------------------------------------

class Site(Base):
    __tablename__ = "sites"

    id                  : Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    code_site           : Mapped[str]            = mapped_column(String(20), unique=True, nullable=False)
    nom                 : Mapped[str]            = mapped_column(String(100), nullable=False)
    categorie           : Mapped[CategorieEnum]  = mapped_column(SAEnum(CategorieEnum), nullable=False)
    sbc                 : Mapped[SBCEnum]        = mapped_column(SAEnum(SBCEnum), nullable=False)
    sto                 : Mapped[str]            = mapped_column(String(50), nullable=False)
    region              : Mapped[str]            = mapped_column(String(50), nullable=False)
    type_alimentation   : Mapped[Optional[str]]  = mapped_column(String(50), nullable=True)
    cycle               : Mapped[Optional[str]]  = mapped_column(String(1), nullable=True)
    actif               : Mapped[bool]           = mapped_column(Boolean, default=True, nullable=False)
    date_acceptance     : Mapped[Optional[date]]  = mapped_column(Date, nullable=True)
    date_handover       : Mapped[Optional[date]]  = mapped_column(Date, nullable=True)
    techno              : Mapped[Optional[str]]   = mapped_column(String(100), nullable=True)
    passive_handler     : Mapped[Optional[str]]   = mapped_column(String(50), nullable=True)
    latitude            : Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude           : Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    priorite            : Mapped[Optional[str]]   = mapped_column(String(20), nullable=True)
    typologie           : Mapped[Optional[str]]   = mapped_column(String(50), nullable=True)
    created_at          : Mapped[datetime]       = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at          : Mapped[datetime]       = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relations
    passages  : Mapped[List["Passage"]]   = relationship("Passage",   back_populates="site")
    executions: Mapped[List["Execution"]] = relationship("Execution", back_populates="site")
    alertes   : Mapped[List["Alert"]]     = relationship("Alert",     back_populates="site")

    __table_args__ = (
        # Index composite couvrant les filtres les plus fréquents
        Index("ix_sites_sbc_sto_cat_actif", "sbc", "sto", "categorie", "actif"),
    )

    def __repr__(self) -> str:
        return (
            f"<Site id={self.id} code={self.code_site!r} "
            f"cat={self.categorie.value!r} sbc={self.sbc.value!r}>"
        )


# ---------------------------------------------------------------------------
# Passage
# ---------------------------------------------------------------------------

class Passage(Base):
    __tablename__ = "passages"

    id                       : Mapped[int]                 = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id                  : Mapped[int]                 = mapped_column(ForeignKey("sites.id"), nullable=False)
    passage_num              : Mapped[int]                 = mapped_column(Integer, nullable=False)
    total_passages           : Mapped[int]                 = mapped_column(Integer, nullable=False)
    mois_num                 : Mapped[int]                 = mapped_column(Integer, nullable=False)
    mois_nom                 : Mapped[str]                 = mapped_column(String(20), nullable=False)
    annee                    : Mapped[int]                 = mapped_column(Integer, default=2026, nullable=False)
    date_planifiee           : Mapped[date]                = mapped_column(Date, nullable=False)
    date_planifiee_initiale  : Mapped[Optional[date]]      = mapped_column(Date, nullable=True)
    statut                   : Mapped[StatutPassageEnum]   = mapped_column(
        SAEnum(StatutPassageEnum), default=StatutPassageEnum.Prevu, nullable=False
    )
    is_replanifie            : Mapped[bool]                = mapped_column(Boolean, default=False, nullable=False)
    impossible_a_rattraper   : Mapped[bool]                = mapped_column(Boolean, default=False, nullable=False)
    created_at               : Mapped[datetime]            = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at               : Mapped[datetime]            = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relations
    site     : Mapped["Site"]               = relationship("Site",      back_populates="passages")
    execution: Mapped[Optional["Execution"]] = relationship(
        "Execution", back_populates="passage", uselist=False
    )

    __table_args__ = (
        UniqueConstraint("site_id", "mois_num", "annee", "passage_num", name="uq_passage_site_mois"),
        Index("ix_passages_site_mois_annee_statut", "site_id", "mois_num", "annee", "statut"),
        Index("ix_passages_date_planifiee", "date_planifiee"),
        Index("ix_passages_annee_statut", "annee", "statut"),
    )

    def __repr__(self) -> str:
        return (
            f"<Passage id={self.id} site_id={self.site_id} "
            f"num={self.passage_num}/{self.total_passages} "
            f"mois={self.mois_num}/{self.annee} statut={self.statut.value!r}>"
        )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

class Execution(Base):
    __tablename__ = "executions"

    id                : Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    # unique=True → 1 exécution par passage (relation 1-1)
    passage_id        : Mapped[int]            = mapped_column(ForeignKey("passages.id"), unique=True, nullable=False)
    site_id           : Mapped[int]            = mapped_column(ForeignKey("sites.id"), nullable=False)
    date_execution    : Mapped[date]           = mapped_column(Date, nullable=False)
    wo_ticket         : Mapped[str]            = mapped_column(String(50), nullable=False)
    operateur         : Mapped[Optional[str]]  = mapped_column(String(100), nullable=True)
    niveau_carburant  : Mapped[Optional[int]]  = mapped_column(Integer, nullable=True)   # 0-100 %
    ch_ge             : Mapped[Optional[int]]  = mapped_column(Integer, nullable=True)   # heures GE
    tension_batterie  : Mapped[Optional[float]]= mapped_column(Float, nullable=True)     # Volts
    snags             : Mapped[Optional[str]]  = mapped_column(Text, nullable=True)
    checklist_ok      : Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    observations      : Mapped[Optional[str]]  = mapped_column(Text, nullable=True)
    import_id         : Mapped[Optional[int]]  = mapped_column(ForeignKey("imports.id"), nullable=True)
    created_at        : Mapped[datetime]       = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Relations
    passage: Mapped["Passage"] = relationship("Passage", back_populates="execution")
    site   : Mapped["Site"]    = relationship("Site",    back_populates="executions")

    __table_args__ = (
        Index("ix_executions_site_id",        "site_id"),
        Index("ix_executions_date_execution",  "date_execution"),
        Index("ix_executions_wo_ticket",       "wo_ticket"),
    )

    def __repr__(self) -> str:
        return (
            f"<Execution id={self.id} site_id={self.site_id} "
            f"wo={self.wo_ticket!r} date={self.date_execution}>"
        )


# ---------------------------------------------------------------------------
# Import  (traçabilité des fichiers SBC)
# ---------------------------------------------------------------------------

class Import(Base):
    __tablename__ = "imports"

    id             : Mapped[int]               = mapped_column(Integer, primary_key=True, autoincrement=True)
    nom_fichier    : Mapped[str]               = mapped_column(String(200), nullable=False)
    date_import    : Mapped[datetime]          = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    # colonne FK : nom du champ tel que spécifié (entier)
    importe_par    : Mapped[Optional[int]]     = mapped_column(ForeignKey("users.id"), nullable=True)
    nb_lignes_brut : Mapped[Optional[int]]     = mapped_column(Integer, nullable=True)
    nb_integres    : Mapped[Optional[int]]     = mapped_column(Integer, nullable=True)
    nb_doublons    : Mapped[Optional[int]]     = mapped_column(Integer, nullable=True)
    nb_max_depasse : Mapped[Optional[int]]     = mapped_column(Integer, nullable=True)
    nb_non_trouves : Mapped[Optional[int]]     = mapped_column(Integer, nullable=True)
    statut         : Mapped[StatutImportEnum]  = mapped_column(SAEnum(StatutImportEnum), nullable=False)
    detail_erreurs : Mapped[Optional[str]]     = mapped_column(Text, nullable=True)  # JSON

    # Relation (nom distinct de la colonne FK pour éviter le conflit d'attribut)
    auteur: Mapped[Optional["User"]] = relationship("User", back_populates="imports")

    def __repr__(self) -> str:
        return (
            f"<Import id={self.id} fichier={self.nom_fichier!r} "
            f"statut={self.statut.value!r} integres={self.nb_integres}>"
        )


# ---------------------------------------------------------------------------
# Alert
# ---------------------------------------------------------------------------

class Alert(Base):
    __tablename__ = "alerts"

    id                   : Mapped[int]               = mapped_column(Integer, primary_key=True, autoincrement=True)
    niveau               : Mapped[NiveauAlerteEnum]  = mapped_column(SAEnum(NiveauAlerteEnum), nullable=False)
    type_alerte          : Mapped[str]               = mapped_column(String(50), nullable=False)
    site_id              : Mapped[Optional[int]]     = mapped_column(ForeignKey("sites.id"), nullable=True)
    message              : Mapped[str]               = mapped_column(Text, nullable=False)
    detail               : Mapped[Optional[str]]     = mapped_column(Text, nullable=True)  # JSON
    statut               : Mapped[StatutAlerteEnum]  = mapped_column(
        SAEnum(StatutAlerteEnum), default=StatutAlerteEnum.nouvelle, nullable=False
    )
    # colonne FK : nom exact du champ spécifié
    prise_en_charge_par  : Mapped[Optional[int]]     = mapped_column(ForeignKey("users.id"), nullable=True)
    commentaire          : Mapped[Optional[str]]     = mapped_column(Text, nullable=True)
    created_at           : Mapped[datetime]          = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at           : Mapped[datetime]          = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relations
    site       : Mapped[Optional["Site"]] = relationship("Site", back_populates="alertes")
    gestionnaire: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="alertes_gerees",
        foreign_keys="[Alert.prise_en_charge_par]",
    )

    __table_args__ = (
        Index("ix_alerts_statut_niveau",  "statut", "niveau"),
        Index("ix_alerts_site_id",        "site_id"),
        Index("ix_alerts_type_alerte",    "type_alerte"),
    )

    def __repr__(self) -> str:
        return (
            f"<Alert id={self.id} niveau={self.niveau.value!r} "
            f"type={self.type_alerte!r} statut={self.statut.value!r}>"
        )
