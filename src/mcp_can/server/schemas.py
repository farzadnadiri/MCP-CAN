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
