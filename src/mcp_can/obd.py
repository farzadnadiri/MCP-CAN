from __future__ import annotations

from typing import List, Optional, Tuple, Union

OBD_BROADCAST_ID = 0x7DF
OBD_RESPONSE_BASE_ID = 0x7E8  # first ECU response ID


def _single_frame(payload: List[int]) -> List[int]:
    """Build a single-frame ISO-TP message: [len] + payload, padded to 8 bytes."""
    length = len(payload)
    data = [length & 0xFF] + payload
    while len(data) < 8:
        data.append(0x00)
    return data[:8]


def build_request(service: int, pid: Optional[int] = None) -> Tuple[int, bytes]:
    payload: List[int] = [service]
    if pid is not None:
        payload.append(pid)
    data = _single_frame(payload)
    return (OBD_BROADCAST_ID, bytes(data))


def _supported_mask(pids: List[int]) -> Tuple[int, int, int, int]:
    """Return 4 bytes bitmask for PIDs 0x01-0x20."""
    mask = [0, 0, 0, 0]
    for pid in pids:
        if 0x01 <= pid <= 0x20:
            idx = (pid - 1) // 8
            bit = 7 - ((pid - 1) % 8)
            mask[idx] |= (1 << bit)
    return (mask[0], mask[1], mask[2], mask[3])


def simulate_response(service: int, pid: Optional[int]) -> Optional[List[int]]:
    """Return payload bytes (without length) for a given OBD-II request.

    We implement a small subset as single-frame responses.
    """
    if service == 0x01:
        if pid == 0x00:
            a, b, c, d = _supported_mask([0x05, 0x0D, 0x2F, 0x51])
            return [0x41, 0x00, a, b, c, d]
        if pid == 0x05:  # Coolant temp = A-40
            temp_c = 90
            A = temp_c + 40
            return [0x41, 0x05, A]
        if pid == 0x0D:  # Speed km/h
            speed = 50
            return [0x41, 0x0D, speed]
        if pid == 0x2F:  # Fuel tank level input % = 100/255 * A
            level_pct = 50
            A = int(round(level_pct * 255 / 100))
            return [0x41, 0x2F, A]
        if pid == 0x51:  # Fuel type (1 = gasoline)
            return [0x41, 0x51, 0x01]
    if service == 0x03:  # DTCs
        # Return no DTCs
        return [0x43]
    if service == 0x09:
        if pid == 0x00:
            a, b, c, d = _supported_mask([0x02, 0x0A])
            return [0x49, 0x00, a, b, c, d]
        if pid == 0x0A:  # ECU name (ASCII), simple short name in single frame
            name = b"MCP-ECU"
            return [0x49, 0x0A] + list(name[:5])  # truncate to fit single-frame demo
        # VIN (0x02) is multi-frame typically; not supported in this minimal demo
    return None


def parse_request(data: Union[bytes, bytearray]) -> Tuple[int, Optional[int]]:
    """Parse a single-frame request and return (service, pid)."""
    if not data:
        return (0, None)
    length = data[0]
    payload = list(data[1:1 + length])
    if not payload:
        return (0, None)
    service = payload[0]
    pid = payload[1] if len(payload) > 1 else None
    return (service, pid)


def build_response_frame(
    payload: List[int],
    responder_id: int = OBD_RESPONSE_BASE_ID,
) -> Tuple[int, bytes]:
    data = _single_frame(payload)
    return (responder_id, bytes(data))
