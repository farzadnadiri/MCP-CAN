"""Fault injection: named scenario presets that override live signal values.

The CLI/MCP tool that activates a scenario runs as a separate process from
the one running `SimThread`/`OBDResponderThread` (same constraint as
OBD-II/diagnostic requests), so activation goes over the bus itself rather
than mutating simulator-process state directly: a small control frame on
`FAULT_CONTROL_ID` selects a preset by index, `FaultListenerThread` (running
in the simulator process) applies it to a shared `FaultState`, and acks on
`FAULT_ACK_ID`. `SimThread` consults `FaultState.get_override` per signal;
`OBDResponderThread` consults `FaultState.dtcs()` for Mode 03 responses.
"""
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import can

logger = logging.getLogger(__name__)

FAULT_CONTROL_ID = 0x7F0
FAULT_ACK_ID = 0x7F1


@dataclass(frozen=True)
class FaultPreset:
    name: str
    description: str
    # Signal name -> forced physical value (or choice int), applied in place
    # of whatever SimThread would otherwise compute for that signal.
    overrides: Dict[str, Any]
    dtcs: List[str] = field(default_factory=list)


PRESETS: Dict[str, FaultPreset] = {
    "overheat": FaultPreset(
        name="overheat",
        description="Engine running at its hottest reportable temperature; "
        "airbag ECU's SYSTEM_STATUS flags a fault.",
        # 87.5 is ENGINE_TEMP's actual encodable ceiling -- see
        # simulator/state.py::ENGINE_TEMP_MAX_C.
        overrides={"ENGINE_TEMP": 87.5, "SYSTEM_STATUS": 1},  # 1 = FAULT_PRESENT
        dtcs=["P0217"],  # Engine Overtemp Condition
    ),
    "abs_fault": FaultPreset(
        name="abs_fault",
        description="ABS wheel speed sensors all reading stuck at zero.",
        overrides={
            "WHEEL_SPEED_FL": 0.0,
            "WHEEL_SPEED_FR": 0.0,
            "WHEEL_SPEED_RL": 0.0,
            "WHEEL_SPEED_RR": 0.0,
            "SYSTEM_STATUS": 1,  # FAULT_PRESENT
        },
        dtcs=["C0035"],  # Left Front Wheel Speed Sensor Circuit
    ),
    "low_fuel": FaultPreset(
        name="low_fuel",
        description="Fuel level critically low.",
        overrides={"FUEL_LEVEL": 2.0},
    ),
}

# Wire format for FAULT_CONTROL_ID: byte 0 = preset index, 0 = clear.
_PRESET_ORDER: List[str] = list(PRESETS)


def build_control_frame(preset: Optional[str]) -> Tuple[int, bytes]:
    """`preset=None` (or unrecognized) clears the active scenario."""
    code = _PRESET_ORDER.index(preset) + 1 if preset in PRESETS else 0
    return FAULT_CONTROL_ID, bytes([code] + [0] * 7)


def preset_from_code(code: int) -> Optional[str]:
    if code <= 0 or code > len(_PRESET_ORDER):
        return None
    return _PRESET_ORDER[code - 1]


class FaultState:
    """Thread-safe holder for the currently active fault scenario."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: Optional[str] = None

    def activate(self, preset: Optional[str]) -> None:
        with self._lock:
            self._active = preset if preset in PRESETS else None

    def active_preset_name(self) -> Optional[str]:
        with self._lock:
            return self._active

    def _active_preset(self) -> Optional[FaultPreset]:
        name = self.active_preset_name()
        return PRESETS.get(name) if name else None

    def has_override(self, signal_name: str) -> bool:
        preset = self._active_preset()
        return preset is not None and signal_name in preset.overrides

    def get_override(self, signal_name: str) -> Any:
        preset = self._active_preset()
        return preset.overrides.get(signal_name) if preset else None

    def dtcs(self) -> List[str]:
        preset = self._active_preset()
        return list(preset.dtcs) if preset else []


class FaultListenerThread(threading.Thread):
    """Listens for scenario-activation control frames and updates `FaultState`."""

    def __init__(self, fault_state: FaultState, bus: can.BusABC):
        super().__init__(daemon=True)
        self.fault_state = fault_state
        self.bus = bus

    def run(self) -> None:
        while True:
            msg = self.bus.recv(timeout=0.1)
            if msg and msg.arbitration_id == FAULT_CONTROL_ID and len(msg.data) > 0:
                preset = preset_from_code(msg.data[0])
                self.fault_state.activate(preset)
                logger.info("Fault scenario set to: %s", preset or "(cleared)")
                try:
                    ack = can.Message(
                        arbitration_id=FAULT_ACK_ID,
                        data=bytes([msg.data[0]] + [0] * 7),
                        is_extended_id=False,
                    )
                    self.bus.send(ack)
                except Exception:
                    logger.exception("Fault ack send error")
