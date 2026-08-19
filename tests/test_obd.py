from mcp_can.obd import (
    decode_dtc,
    decode_dtcs,
    decode_pid_value,
    decode_response,
    encode_dtc,
    parse_response,
    simulate_response,
)


def test_parse_response_mode01_speed():
    # 0x41 0x0D <speed> matches simulate_response's Mode 01 PID 0x0D shape
    data = bytes([3, 0x41, 0x0D, 50, 0, 0, 0, 0])
    service, pid, value_bytes = parse_response(data)
    assert service == 0x41
    assert pid == 0x0D
    assert value_bytes == [50]


def test_parse_response_no_pid_mode03():
    # 0x43 (no DTCs) has no PID byte
    data = bytes([1, 0x43, 0, 0, 0, 0, 0, 0])
    service, pid, value_bytes = parse_response(data)
    assert service == 0x43
    assert pid is None
    assert value_bytes == []


def test_decode_pid_value_speed():
    assert decode_pid_value(0x0D, [50]) == {"name": "vehicle_speed", "value": 50, "unit": "km/h"}


def test_decode_pid_value_coolant_temp():
    # A - 40 per simulate_response's own comment
    assert decode_pid_value(0x05, [130]) == {
        "name": "engine_coolant_temp",
        "value": 90,
        "unit": "degC",
    }


def test_decode_pid_value_unknown_pid_returns_none():
    assert decode_pid_value(0x99, [1, 2, 3]) is None


def test_decode_pid_value_no_pid_returns_none():
    assert decode_pid_value(None, [1, 2, 3]) is None


def test_encode_decode_dtc_roundtrip():
    # P0217 (Engine Overtemp Condition) is a well-known code with a
    # published hex encoding (0x02 0x17) -- confirms this matches the real
    # J2012 wire format, not just an internally-consistent roundtrip.
    assert encode_dtc("P0217") == (0x02, 0x17)
    assert decode_dtc(0x02, 0x17) == "P0217"
    for code in ["P0217", "C0035", "B0001", "U0100"]:
        byte_a, byte_b = encode_dtc(code)
        assert decode_dtc(byte_a, byte_b) == code


def test_decode_dtcs_multiple_codes():
    byte_a1, byte_b1 = encode_dtc("P0217")
    byte_a2, byte_b2 = encode_dtc("C0035")
    assert decode_dtcs([byte_a1, byte_b1, byte_a2, byte_b2]) == ["P0217", "C0035"]


def test_decode_dtcs_empty():
    assert decode_dtcs([]) == []


def test_simulate_response_mode03_with_dtcs():
    payload = simulate_response(0x03, None, dtcs=["P0217"])
    assert payload is not None
    assert payload[0] == 0x43
    assert decode_dtcs(payload[1:]) == ["P0217"]


def test_simulate_response_mode03_no_dtcs_matches_previous_behavior():
    assert simulate_response(0x03, None) == [0x43]
    assert simulate_response(0x03, None, dtcs=[]) == [0x43]


def test_decode_response_dispatches_mode03_to_dtcs():
    assert decode_response(0x43, None, [0x02, 0x17]) == {"dtcs": ["P0217"]}


def test_decode_response_dispatches_other_modes_to_decode_pid_value():
    assert decode_response(0x41, 0x0D, [50]) == decode_pid_value(0x0D, [50])
