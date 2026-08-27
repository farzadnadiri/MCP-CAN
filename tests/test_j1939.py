import pytest

from mcp_can import j1939


def test_parse_build_can_id_roundtrip_pdu2():
    # EEC1 (0xF004) is a PDU2 / broadcast PGN.
    can_id = j1939.build_can_id(j1939.PGN_EEC1, source_address=0x00, priority=3)
    parsed = j1939.parse_can_id(can_id)
    assert parsed.priority == 3
    assert parsed.pgn == j1939.PGN_EEC1
    assert parsed.source_address == 0x00
    assert parsed.destination_address is None
    assert parsed.is_broadcast is True
    assert parsed.to_int() == can_id


def test_parse_build_can_id_roundtrip_pdu1():
    # Request PGN (0xEA00) is PDU1 / peer-to-peer: PS carries a destination.
    can_id = j1939.build_can_id(
        j1939.PGN_REQUEST, source_address=0xF9, destination_address=0x0B, priority=6
    )
    parsed = j1939.parse_can_id(can_id)
    assert parsed.pgn == j1939.PGN_REQUEST
    assert parsed.is_pdu1 is True
    assert parsed.destination_address == 0x0B
    assert parsed.is_broadcast is False


def test_known_j1939_frame_id_decomposition():
    # 0x0CF00400: priority 3, PGN 0xF004 (EEC1), source address 0x00 -- a
    # value any J1939 reference will decode identically.
    parsed = j1939.parse_can_id(0x0CF00400)
    assert parsed.priority == 3
    assert parsed.pgn == 0xF004
    assert parsed.source_address == 0x00


@pytest.mark.parametrize(
    "pgn,signals",
    [
        (j1939.PGN_EEC1, {"ENGINE_SPEED": 1500.0, "ACTUAL_ENGINE_PERCENT_TORQUE": 40.0}),
        (j1939.PGN_ET1, {"ENGINE_COOLANT_TEMPERATURE": 90.0}),
        (j1939.PGN_CCVS1, {"WHEEL_BASED_VEHICLE_SPEED": 88.5}),
        (j1939.PGN_DD1, {"FUEL_LEVEL_1": 42.0}),
    ],
)
def test_encode_decode_pgn_roundtrip(pgn, signals):
    data = j1939.encode_pgn(pgn, signals)
    assert len(data) == j1939.PGN_CATALOG[pgn].length
    decoded = j1939.decode_pgn(pgn, data)
    for name, value in signals.items():
        assert decoded[name] == pytest.approx(value, abs=1.0)


def test_engine_speed_uses_j1939_quarter_rpm_scaling():
    # SPN 190 is 0.125 rpm/bit; 1500 rpm -> raw 12000 -> bytes 0xE0 0x2E.
    data = j1939.encode_pgn(j1939.PGN_EEC1, {"ENGINE_SPEED": 1500.0})
    assert data[3] == 0xE0 and data[4] == 0x2E
    assert j1939.decode_pgn(j1939.PGN_EEC1, data)["ENGINE_SPEED"] == 1500.0


def test_decode_unknown_pgn_is_empty_not_guessed():
    assert j1939.decode_pgn(0x1234, bytes(8)) == {}


def test_encode_pgn_rejects_unknown_signal():
    with pytest.raises(KeyError):
        j1939.encode_pgn(j1939.PGN_EEC1, {"NOT_A_REAL_SPN": 1})


def test_dtc_pack_unpack_roundtrip():
    for dtc in [
        j1939.J1939Dtc(spn=110, fmi=0, oc=1),
        j1939.J1939Dtc(spn=84, fmi=5, oc=3),
        j1939.J1939Dtc(spn=524287, fmi=31, oc=126, cm=1),  # all fields at max
    ]:
        assert j1939.decode_dtc(j1939.encode_dtc(dtc)) == dtc


def test_dm1_with_faults_sets_lamp_and_carries_dtcs():
    dtcs = [j1939.J1939Dtc(spn=110, fmi=0, oc=2)]
    payload = j1939.build_dm1(dtcs, mil_on=True)
    lamps, parsed = j1939.parse_dm1(payload)
    assert lamps["malfunction_indicator"] == "on"
    assert parsed == dtcs


def test_dm1_no_faults_parses_to_empty_list():
    lamps, parsed = j1939.parse_dm1(j1939.build_dm1([]))
    assert lamps["malfunction_indicator"] == "off"
    assert parsed == []


def test_request_pgn_builds_pdu1_frame_and_roundtrips_payload():
    can_id, data = j1939.build_request_pgn(j1939.PGN_EEC1)
    parsed = j1939.parse_can_id(can_id)
    assert parsed.pgn == j1939.PGN_REQUEST
    assert parsed.source_address == j1939.SA_OFF_BOARD_DIAGNOSTIC_TOOL
    assert list(data) == [0x04, 0xF0, 0x00]  # PGN little-endian, 3 bytes
    assert j1939.parse_request_pgn(data) == j1939.PGN_EEC1


def test_parse_request_pgn_rejects_short_payload():
    assert j1939.parse_request_pgn(b"\x01\x02") is None


def test_describe_pgn_known_and_unknown():
    known = j1939.describe_pgn(j1939.PGN_EEC1)
    assert known["known"] is True
    assert known["acronym"] == "EEC1"
    assert any(s["spn"] == 190 for s in known["spns"])
    assert j1939.describe_pgn(0xABCD)["known"] is False
