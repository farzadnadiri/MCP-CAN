"""Shared UDS-style diagnostic service/response-code constants and logic.

Matches the SERVICE_ID / RESPONSE_CODE VAL_ tables defined in ``vehicle.dbc``
for the DIAGNOSTIC_REQUEST (1047) / DIAGNOSTIC_RESPONSE_* (1048-1051)
messages. Used by both the simulator (to answer requests) and the MCP server
(to build requests and present response codes as names).

DIAGNOSTIC_REQUEST has no per-ECU target field, so a request is treated as
functionally addressed to every ECU: each one answers on its own
DIAGNOSTIC_RESPONSE_<ECU> frame id.
"""
from typing import Dict, Tuple

REQUEST_MESSAGE = "DIAGNOSTIC_REQUEST"
RESPONSE_MESSAGES = [
    "DIAGNOSTIC_RESPONSE_ENGINE",
    "DIAGNOSTIC_RESPONSE_ABS",
    "DIAGNOSTIC_RESPONSE_AIRBAG",
    "DIAGNOSTIC_RESPONSE_BODY",
]

SERVICE_IDS: Dict[str, int] = {
    "START_DIAGNOSTIC_SESSION": 0x10,
    "RESET_ECU": 0x11,
    "READ_DATA_BY_ID": 0x22,
    "WRITE_MEMORY": 0x30,
    "ROUTINE_CONTROL": 0x2F,
    "READ_MEMORY": 0x31,
}

RESPONSE_CODES: Dict[int, str] = {
    0: "OK",
    1: "GENERAL_REJECT",
    17: "SERVICE_NOT_SUPPORTED",
    33: "INVALID_FORMAT",
    34: "CONDITION_NOT_CORRECT",
}
_OK = 0
_SERVICE_NOT_SUPPORTED = 17


def response_code_name(code: int) -> str:
    return RESPONSE_CODES.get(code, f"UNKNOWN(0x{code:02x})")


def ecu_name_from_response_message(message_name: str) -> str:
    return message_name.replace("DIAGNOSTIC_RESPONSE_", "")


def handle_service(service_id: int, parameter_id: int, data_field: int) -> Tuple[int, int]:
    """Decide (response_code, data_field) for a diagnostic request.

    Pure logic, no I/O, so it's cheap to unit test independent of the bus.
    """
    if service_id in (SERVICE_IDS["START_DIAGNOSTIC_SESSION"], SERVICE_IDS["RESET_ECU"]):
        return _OK, 0
    if service_id == SERVICE_IDS["READ_DATA_BY_ID"]:
        # Deterministic-but-varying canned value so different parameter ids
        # read back different data, without needing real per-parameter state.
        return _OK, (parameter_id * 37) % 0xFFFFFFFFFF
    # ROUTINE_CONTROL / READ_MEMORY / WRITE_MEMORY and anything unknown.
    return _SERVICE_NOT_SUPPORTED, 0
