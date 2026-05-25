from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class ExecutionCreate(BaseModel):
    passage_id: int
    site_id: int
    date_execution: date
    wo_ticket: str
    operateur: Optional[str] = None
    niveau_carburant: Optional[int] = None
    ch_ge: Optional[int] = None
    tension_batterie: Optional[float] = None
    snags: Optional[str] = None
    checklist_ok: Optional[bool] = None
    observations: Optional[str] = None


class ExecutionMinimal(BaseModel):
    id: int
    date_execution: date
    wo_ticket: str
    operateur: Optional[str]
    model_config = ConfigDict(from_attributes=True)


class ExecutionResponse(ExecutionCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
