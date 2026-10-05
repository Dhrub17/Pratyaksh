"""Request schemas (pydantic v2). The ingest schema is intentionally permissive about extra
fields so newer edge versions can add data without breaking older backends."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class Window(BaseModel):
    start: str
    end: str
    duration_s: Optional[float] = None


class Attendance(BaseModel):
    model_config = ConfigDict(extra="allow")
    observed_count: int = Field(ge=0)
    peak_count: int = Field(ge=0)
    median_count: Optional[float] = None
    sustained_tracks: Optional[int] = None
    confidence: float = Field(ge=0, le=1)
    samples: Optional[int] = None
    coverage_pct: Optional[float] = None
    timeline: list[int] = []


class InfraItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    item: str
    sanctioned: int
    detected: int
    operational: Optional[int] = None
    utilization_pct: Optional[float] = None
    status: Literal["ok", "missing", "partial", "idle"]
    source: Optional[str] = None


class SessionEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_: str = Field(alias="schema")
    centre_id: str
    camera_id: Optional[str] = None
    session_id: str
    batch_id: Optional[str] = None
    window: Window
    attendance: Attendance
    infrastructure: list[InfraItem] = []
    tamper: list[dict[str, Any]] = []
    camera_health: dict[str, Any] = {}
    flags: list[str] = []
    evidence: list[dict[str, Any]] = []
    mode: Optional[str] = "lite"
    prev_hash: str
    hash: str


class RegisterIn(BaseModel):
    session_id: str
    batch_id: Optional[str] = None
    date: Optional[str] = None
    reported_count: int = Field(ge=0, le=500)


class AlertUpdate(BaseModel):
    status: Literal["open", "acknowledged", "resolved", "escalated", "dismissed"]
    note: str = ""


class CentreIn(BaseModel):
    id: str
    name: str
    state: str
    district: str = ""
    lat: float
    lng: float
    scheme: str = "PMKVY 4.0"
    trades: list[str] = []
    capacity: int = 30
    sanctioned_inventory: dict[str, int] = {}
    device_key: str
    bandwidth_mode: Literal["full", "lite", "ultra", "offline"] = "lite"
