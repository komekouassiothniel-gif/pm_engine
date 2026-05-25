"""
api/main.py — Application FastAPI principale PM MTN CI (MS-Huawei)
Lancement : uvicorn api.main:app --reload --port 8000
Docs      : http://localhost:8000/docs
"""

import sys
import os
# Assure que pm_engine/ est dans le path quel que soit le CWD
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routers import admin, alerts, assistant, auth, imports, planning, rapports, sites
from database import SessionLocal
from scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler(SessionLocal)
    yield
    stop_scheduler()


app = FastAPI(
    title="PM Planning API — MS-Huawei / MTN CI",
    description=(
        "API de gestion du planning de maintenance préventive (PM) "
        "pour le réseau télécom MTN Côte d'Ivoire."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware CORS (frontend React en développement)
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",  # Vite
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Gestionnaire d'erreurs global
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": f"Erreur interne du serveur : {type(exc).__name__}: {exc}"},
    )

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

PREFIX = "/api/v1"

app.include_router(admin.router,    prefix=f"{PREFIX}/admin",    tags=["Administration"])
app.include_router(auth.router,     prefix=f"{PREFIX}/auth",     tags=["Authentification"])
app.include_router(sites.router,    prefix=f"{PREFIX}/sites",    tags=["Sites"])
app.include_router(planning.router, prefix=f"{PREFIX}/planning", tags=["Planning"])
app.include_router(imports.router,  prefix=f"{PREFIX}/imports",  tags=["Imports SBC"])
app.include_router(alerts.router,   prefix=f"{PREFIX}/alerts",   tags=["Alertes"])
app.include_router(rapports.router,   prefix=f"{PREFIX}/rapports",   tags=["Rapports"])
app.include_router(assistant.router, prefix=f"{PREFIX}/assistant", tags=["Assistant IA"])

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get(f"{PREFIX}/health", tags=["Système"], summary="État du service")
def health():
    return {"status": "ok", "version": "1.0.0", "service": "PM Planning API"}
