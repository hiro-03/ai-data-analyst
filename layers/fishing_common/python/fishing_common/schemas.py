"""
Shared Pydantic v2 schemas.

- FishingRequest  : validated input for POST /fishing
- FishingAdviceResponse : expected shape of inference output
"""
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class FishingRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="Latitude (-90 to 90)")
    lon: float = Field(..., ge=-180, le=180, description="Longitude (-180 to 180)")
    target_species: Optional[str] = None
    spot_type: Optional[str] = None
    start_at: Optional[str] = None

    model_config = {"extra": "ignore"}


class ScoreDetail(BaseModel):
    value: float = Field(..., ge=0, le=100)
    label: str = ""


class SeasonDetail(BaseModel):
    month: int = Field(..., ge=1, le=12)
    label: str = ""


class FishingAdviceResponse(BaseModel):
    summary: str = ""
    score: ScoreDetail
    season: SeasonDetail
    best_windows: List[Any] = []
    recommended_tactics: List[Any] = []
    risk_and_safety: List[Any] = []
    evidence: List[Any] = []

    model_config = {"extra": "ignore"}
