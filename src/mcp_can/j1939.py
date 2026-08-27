"""SAE J1939 protocol logic: 29-bit ID decomposition, a small PGN/SPN
catalog, PGN encode/decode, J1939-73 diagnostic (DM1) trouble codes, and the
Request PGN (0xEA00) helper.

Deliberately self-contained rather than DBC-driven: `vehicle.dbc` models a
light-vehicle 11-bit-ID bus, whereas J1939 (trucks/buses) rides 29-bit
extended IDs whose arbitration field *is* structured data (priority / PGN /
source address). Keeping it here — pure functions, no bus or MCP awareness —
mirrors how `obd.py`/`diagnostics.py` are organised.

Wire details follow SAE J1939-21 (transport/PGN) and J1939-73 (diagnostics).
Only a curated handful of the ~thousands of standardised PGNs/SPNs are
implemented; see `PGN_CATALOG`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from cantools import j1939 as _ct_j1939

# --- Well-known PGNs (SAE J1939-71 / -73) -----------------------------------
PGN_EEC1 = 0xF004  # 61444 Electronic Engine Controller 1
PGN_EEC2 = 0xF003  # 61443 Electronic Engine Controller 2
PGN_ET1 = 0xFEEE  # 65262 Engine Temperature 1
PGN_CCVS1 = 0xFEF1  # 65265 Cruise Control / Vehicle Speed 1
PGN_LFE1 = 0xFEF2  # 65266 Fuel Economy (Liquid)
PGN_DD1 = 0xFEFC  # 65276 Dash Display 1
PGN_DM1 = 0xFECA  # 65226 Active Diagnostic Trouble Codes
PGN_REQUEST = 0xEA00  # 59904 Request PGN

# --- Standard-ish source addresses (SAE J1939-71 Appendix B) ---------------
SA_ENGINE = 0x00
SA_BRAKES = 0x0B
SA_INSTRUMENT_CLUSTER = 0x17
SA_OFF_BOARD_DIAGNOSTIC_TOOL = 0xF9
ADDRESS_GLOBAL = 0xFF


@dataclass(frozen=True)
class SpnDef:
    """One Suspect Parameter Number within a PGN's 8-byte payload.

    `start_bit` is counted from the LSB of byte 0, little-endian (Intel)
    ordering — the convention J1939 uses for essentially every parameter.
    """

    spn: int
    name: str
    start_bit: int
    length_bits: int
    scale: float = 1.0
    offset: float = 0.0
    unit: str = ""


@dataclass(frozen=True)
class PgnDef:
    pgn: int
    acronym: str
    name: str
    length: int
    spns: List[SpnDef] = field(default_factory=list)


PGN_CATALOG: Dict[int, PgnDef] = {
    PGN_EEC1: PgnDef(
        PGN_EEC1,
        "EEC1",
        "Electronic Engine Controller 1",
        8,
        [
            SpnDef(513, "ACTUAL_ENGINE_PERCENT_TORQUE", 16, 8, 1.0, -125.0, "%"),
            SpnDef(190, "ENGINE_SPEED", 24, 16, 0.125, 0.0, "rpm"),
        ],
    ),
    PGN_EEC2: PgnDef(
        PGN_EEC2,
        "EEC2",
        "Electronic Engine Controller 2",
        8,
        [
            SpnDef(91, "ACCELERATOR_PEDAL_POSITION_1", 8, 8, 0.4, 0.0, "%"),
            SpnDef(92, "ENGINE_PERCENT_LOAD_AT_CURRENT_SPEED", 16, 8, 1.0, 0.0, "%"),
        ],
    ),
    PGN_ET1: PgnDef(
        PGN_ET1,
        "ET1",
        "Engine Temperature 1",
        8,
        [
            SpnDef(110, "ENGINE_COOLANT_TEMPERATURE", 0, 8, 1.0, -40.0, "degC"),
            SpnDef(174, "ENGINE_FUEL_TEMPERATURE_1", 8, 8, 1.0, -40.0, "degC"),
        ],
    ),
    PGN_CCVS1: PgnDef(
        PGN_CCVS1,
        "CCVS1",
        "Cruise Control / Vehicle Speed 1",
        8,
        [
            SpnDef(84, "WHEEL_BASED_VEHICLE_SPEED", 8, 16, 1.0 / 256.0, 0.0, "km/h"),
        ],
    ),
    PGN_LFE1: PgnDef(
        PGN_LFE1,
        "LFE1",
        "Fuel Economy (Liquid)",
        8,
        [
            SpnDef(183, "ENGINE_FUEL_RATE", 0, 16, 0.05, 0.0, "L/h"),
            SpnDef(51, "ENGINE_THROTTLE_VALVE_1_POSITION", 16, 8, 0.4, 0.0, "%"),
        ],
    ),
    PGN_DD1: PgnDef(
        PGN_DD1,
        "DD1",
        "Dash Display 1",
        8,
        [
            SpnDef(96, "FUEL_LEVEL_1", 8, 8, 0.4, 0.0, "%"),
        ],
    ),
    PGN_DM1: PgnDef(PGN_DM1, "DM1", "Active Diagnostic Trouble Codes", 8, []),
    PGN_REQUEST: PgnDef(PGN_REQUEST, "REQUEST", "Request PGN", 3, []),
}


# --- 29-bit ID decomposition ---------------------------------------------------
@dataclass(frozen=True)
class J1939Id:
    priority: int
    reserved: int
    data_page: int
    pdu_format: int
    pdu_specific: int
    source_address: int

    @property
    def pgn(self) -> int:
        return int(_ct_j1939.pgn_from_frame_id(self.to_int()))

    @property
    def is_pdu1(self) -> bool:
        """PDU1 (peer-to-peer): PF < 240, so PS is a destination address."""
        return bool(_ct_j1939.is_pdu_format_1(self.pdu_format))

    @property
    def destination_address(self) -> Optional[int]:
        return self.pdu_specific if self.is_pdu1 else None

    @property
    def is_broadcast(self) -> bool:
        da = self.destination_address
        return da is None or da == ADDRESS_GLOBAL

    def to_int(self) -> int:
        return int(
            _ct_j1939.frame_id_pack(
                priority=self.priority,
                reserved=self.reserved,
                data_page=self.data_page,
                pdu_format=self.pdu_format,
                pdu_specific=self.pdu_specific,
                source_address=self.source_address,
            )
        )


def parse_can_id(can_id: int) -> J1939Id:
    """Decompose a 29-bit extended CAN ID into its J1939 fields."""
    fid = _ct_j1939.frame_id_unpack(can_id)
    return J1939Id(
        priority=fid.priority,
        reserved=fid.reserved,
        data_page=fid.data_page,
        pdu_format=fid.pdu_format,
        pdu_specific=fid.pdu_specific,
        source_address=fid.source_address,
    )


def build_can_id(
    pgn: int,
    source_address: int,
    priority: int = 6,
    destination_address: Optional[int] = None,
) -> int:
    """Compose a 29-bit extended CAN ID for a PGN.

    For a PDU1 (peer-to-peer) PGN the low byte of the PGN carries no meaning
    and `destination_address` (default global 0xFF) fills the PS field; for a
    PDU2 (broadcast) PGN the group-extension byte comes from the PGN itself
    and `destination_address` is ignored.
    """
    parts = _ct_j1939.pgn_unpack(pgn)
    if _ct_j1939.is_pdu_format_1(parts.pdu_format):
        pdu_specific = ADDRESS_GLOBAL if destination_address is None else destination_address
    else:
        pdu_specific = parts.pdu_specific
    return int(
        _ct_j1939.frame_id_pack(
            priority=priority,
            reserved=parts.reserved,
            data_page=parts.data_page,
            pdu_format=parts.pdu_format,
            pdu_specific=pdu_specific,
            source_address=source_address,
        )
    )


# --- PGN payload encode/decode ----------------------------------------------
def _extract(data: bytes, start_bit: int, length_bits: int) -> int:
    raw = int.from_bytes(data, "little")
    return (raw >> start_bit) & ((1 << length_bits) - 1)


def _place(acc: int, value: int, start_bit: int, length_bits: int) -> int:
    mask = (1 << length_bits) - 1
    return (acc & ~(mask << start_bit)) | ((value & mask) << start_bit)


def decode_pgn(pgn: int, data: bytes) -> Dict[str, Any]:
    """Decode a PGN payload into named SPN values.

    DM1 (active DTCs) is dispatched to `parse_dm1`; unknown PGNs return an
    empty dict rather than guessing.
    """
    if pgn == PGN_DM1:
        lamps, dtcs = parse_dm1(data)
        return {"lamps": lamps, "dtcs": [d.as_dict() for d in dtcs]}
    definition = PGN_CATALOG.get(pgn)
    if definition is None:
        return {}
    out: Dict[str, Any] = {}
    for spn in definition.spns:
        raw = _extract(data, spn.start_bit, spn.length_bits)
        value = raw * spn.scale + spn.offset
        out[spn.name] = round(value, 3) if isinstance(value, float) else value
    return out


def encode_pgn(pgn: int, signals: Dict[str, float], length: Optional[int] = None) -> bytes:
    """Encode named SPN values into a PGN payload.

    Bits not covered by a supplied signal are left at 1 (0xFF fill), the
    J1939 "not available" pattern.
    """
    definition = PGN_CATALOG.get(pgn)
    if definition is None:
        raise KeyError(f"PGN 0x{pgn:04X} is not in the catalog")
    size = length or definition.length
    acc = int.from_bytes(b"\xff" * size, "little")
    by_name = {spn.name: spn for spn in definition.spns}
    for name, value in signals.items():
        spn = by_name.get(name)
        if spn is None:
            raise KeyError(f"{name!r} is not an SPN of {definition.acronym}")
        raw = round((value - spn.offset) / spn.scale)
        raw = max(0, min(raw, (1 << spn.length_bits) - 1))
        acc = _place(acc, raw, spn.start_bit, spn.length_bits)
    return acc.to_bytes(size, "little")


# --- J1939-73 diagnostic trouble codes (DM1) --------------------------------
@dataclass(frozen=True)
class J1939Dtc:
    """A single diagnostic trouble code as carried in DM1/DM2.

    `spn` Suspect Parameter Number, `fmi` Failure Mode Identifier
    (0-31, see `FMI_DESCRIPTIONS`), `oc` Occurrence Count, `cm` SPN
    Conversion Method.
    """

    spn: int
    fmi: int
    oc: int = 1
    cm: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "spn": self.spn,
            "fmi": self.fmi,
            "fmi_name": FMI_DESCRIPTIONS.get(self.fmi, "unknown"),
            "occurrence_count": self.oc,
            "conversion_method": self.cm,
        }


FMI_DESCRIPTIONS: Dict[int, str] = {
    0: "data valid but above normal operating range (most severe)",
    1: "data valid but below normal operating range (most severe)",
    2: "data erratic, intermittent or incorrect",
    3: "voltage above normal or shorted high",
    4: "voltage below normal or shorted low",
    5: "current below normal or open circuit",
    6: "current above normal or grounded circuit",
    7: "mechanical system not responding properly",
    8: "abnormal frequency, pulse width or period",
    9: "abnormal update rate",
    10: "abnormal rate of change",
    11: "root cause not known",
    12: "bad intelligent device or component",
    13: "out of calibration",
    14: "special instructions",
    15: "data valid but above normal operating range (least severe)",
    16: "data valid but above normal operating range (moderately severe)",
    17: "data valid but below normal operating range (least severe)",
    18: "data valid but below normal operating range (moderately severe)",
    19: "received network data in error",
    31: "condition exists",
}

# DM1/DM2 lamp status: byte 1 holds two bits each for these four lamps.
_LAMP_NAMES = ["malfunction_indicator", "red_stop", "amber_warning", "protect"]
_LAMP_STATES = {0: "off", 1: "on", 3: "not_available"}


def encode_dtc(dtc: J1939Dtc) -> bytes:
    """Pack one DTC into its 4-byte DM1 wire form (SAE J1939-73 5.7.1)."""
    b0 = dtc.spn & 0xFF
    b1 = (dtc.spn >> 8) & 0xFF
    b2 = ((dtc.spn >> 16) & 0x07) << 5 | (dtc.fmi & 0x1F)
    b3 = ((dtc.cm & 0x01) << 7) | (dtc.oc & 0x7F)
    return bytes([b0, b1, b2, b3])


def decode_dtc(data: bytes) -> J1939Dtc:
    """Inverse of `encode_dtc`."""
    b0, b1, b2, b3 = data[0], data[1], data[2], data[3]
    spn = b0 | (b1 << 8) | ((b2 >> 5) & 0x07) << 16
    fmi = b2 & 0x1F
    cm = (b3 >> 7) & 0x01
    oc = b3 & 0x7F
    return J1939Dtc(spn=spn, fmi=fmi, oc=oc, cm=cm)


def build_dm1(dtcs: List[J1939Dtc], mil_on: bool = False) -> bytes:
    """Build a DM1 payload: 2 lamp-status bytes then 4 bytes per DTC.

    A DM1 with no active faults still carries one all-zero "no fault" DTC
    slot, per the standard.
    """
    mil = 1 if mil_on else 0
    lamp_byte = mil & 0x03
    payload = bytes([lamp_byte, 0xFF])
    if not dtcs:
        return payload + bytes([0, 0, 0, 0])
    for dtc in dtcs:
        payload += encode_dtc(dtc)
    return payload


def parse_dm1(data: bytes) -> Tuple[Dict[str, str], List[J1939Dtc]]:
    """Parse a DM1 payload into (lamp status, list of active DTCs).

    The all-zero "no active faults" placeholder decodes to an empty list.
    """
    if len(data) < 2:
        return ({}, [])
    lamp_byte = data[0]
    lamps = {
        name: _LAMP_STATES.get((lamp_byte >> (2 * i)) & 0x03, "unknown")
        for i, name in enumerate(_LAMP_NAMES)
    }
    dtcs: List[J1939Dtc] = []
    for i in range(2, len(data) - 3, 4):
        chunk = data[i : i + 4]
        if chunk == b"\x00\x00\x00\x00" or chunk == b"\xff\xff\xff\xff":
            continue
        dtcs.append(decode_dtc(chunk))
    return (lamps, dtcs)


# --- Request PGN (0xEA00) ---------------------------------------------------
def build_request_pgn(
    requested_pgn: int,
    source_address: int = SA_OFF_BOARD_DIAGNOSTIC_TOOL,
    destination_address: int = ADDRESS_GLOBAL,
    priority: int = 6,
) -> Tuple[int, bytes]:
    """Build a Request PGN frame asking every (or one) ECU to send `requested_pgn`."""
    can_id = build_can_id(
        PGN_REQUEST,
        source_address=source_address,
        priority=priority,
        destination_address=destination_address,
    )
    data = bytes(
        [
            requested_pgn & 0xFF,
            (requested_pgn >> 8) & 0xFF,
            (requested_pgn >> 16) & 0xFF,
        ]
    )
    return (can_id, data)


def parse_request_pgn(data: bytes) -> Optional[int]:
    """Return the PGN a Request PGN frame is asking for, or None if malformed."""
    if len(data) < 3:
        return None
    return data[0] | (data[1] << 8) | (data[2] << 16)


def describe_pgn(pgn: int) -> Dict[str, Any]:
    """Catalog metadata for one PGN (for `list_j1939_pgns` / `j1939-pgns`)."""
    definition = PGN_CATALOG.get(pgn)
    if definition is None:
        return {"pgn": pgn, "pgn_hex": f"0x{pgn:04X}", "known": False}
    return {
        "pgn": definition.pgn,
        "pgn_hex": f"0x{definition.pgn:04X}",
        "acronym": definition.acronym,
        "name": definition.name,
        "length": definition.length,
        "known": True,
        "spns": [
            {
                "spn": s.spn,
                "name": s.name,
                "start_bit": s.start_bit,
                "length_bits": s.length_bits,
                "scale": s.scale,
                "offset": s.offset,
                "unit": s.unit,
            }
            for s in definition.spns
        ],
    }
