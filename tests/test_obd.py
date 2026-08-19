from mcp_can.obd import decode_pid_value, parse_response


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
