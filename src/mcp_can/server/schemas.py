"""Pydantic response models for MCP tool structured output.

FastMCP derives each tool's `outputSchema` from its return type annotation,
so these models are what MCP clients see described for each tool — kept
separate from `models.py`'s internal `Frame` dataclass, which is a plain
bus-layer value object, not a wire schema.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class FrameOut(BaseModel):
    timestamp: float
    arbitration_id: str
    data: List[int]
    signal_name: Optional[str] = None
    signal_value: Optional[Any] = None


class SignalSample(BaseModel):
    timestamp: float
    value: Any


class DecodeResult(BaseModel):
    status: str
    signals: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


class ObdResponse(BaseModel):
    status: str
    arbitration_id: Optional[str] = None
    response_service: Optional[int] = None
    pid: Optional[int] = None
    decoded: Optional[Dict[str, Any]] = None
    raw_data: Optional[List[int]] = None
    message: Optional[str] = None


class DiagnosticEcuResponse(BaseModel):
    ecu: str
    service_id: int
    parameter_id: int
    response_code: str
    data_field: int


class DiagnosticResult(BaseModel):
    status: str
    responses: List[DiagnosticEcuResponse] = Field(default_factory=list)
    message: Optional[str] = None


class FaultScenarioResult(BaseModel):
    status: str
    active_preset: Optional[str] = None
    description: Optional[str] = None
    dtcs: List[str] = Field(default_factory=list)
    message: Optional[str] = None


class SignalState(BaseModel):
    value: Any
    unit: str
    message: str
    age_s: float


class VehicleSnapshot(BaseModel):
    signals: Dict[str, SignalState]
    frame_count: int
    uptime_s: float


class J1939DecodeResult(BaseModel):
    status: str
    priority: Optional[int] = None
    pgn: Optional[int] = None
    pgn_hex: Optional[str] = None
    pgn_name: Optional[str] = None
    source_address: Optional[int] = None
    destination_address: Optional[int] = None
    is_broadcast: Optional[bool] = None
    signals: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


class J1939PgnInfo(BaseModel):
    pgn: int
    pgn_hex: str
    acronym: str
    name: str
    length: int
    spns: List[Dict[str, Any]] = Field(default_factory=list)


class J1939PgnCatalog(BaseModel):
    pgns: List[J1939PgnInfo] = Field(default_factory=list)


class J1939RequestResult(BaseModel):
    status: str
    requested_pgn: Optional[int] = None
    requested_pgn_hex: Optional[str] = None
    responses: List[J1939DecodeResult] = Field(default_factory=list)
    message: Optional[str] = None


class J1939Dtc(BaseModel):
    spn: int
    fmi: int
    fmi_name: str
    occurrence_count: int
    conversion_method: int


class J1939DtcResult(BaseModel):
    status: str
    source_address: Optional[int] = None
    lamps: Dict[str, str] = Field(default_factory=dict)
    dtcs: List[J1939Dtc] = Field(default_factory=list)
    message: Optional[str] = None
