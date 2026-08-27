from mcp_can import j1939
from mcp_can.simulator.faults import PRESETS, FaultState
from mcp_can.simulator.j1939_runner import (
    BROADCAST_SCHEDULE,
    J1939_FAULT_DTCS,
    _encode_frame,
    active_dm1_dtcs,
    signals_for_pgn,
)
from mcp_can.simulator.state import DrivingState


def test_signals_for_pgn_map_driving_state_onto_every_broadcast_pgn():
    state = DrivingState(throttle_pct=40.0, rpm=1800.0, speed_kph=60.0, engine_temp_c=88.0)
    for pgn, *_ in BROADCAST_SCHEDULE:
        signals = signals_for_pgn(pgn, state)
        assert signals, f"no signal mapping for PGN 0x{pgn:04X}"
        # Whatever we map must round-trip through the encoder cleanly.
        j1939.encode_pgn(pgn, signals)


def test_engine_speed_broadcast_reflects_rpm():
    state = DrivingState(rpm=2000.0)
    msg = _encode_frame(j1939.PGN_EEC1, j1939.SA_ENGINE, 3, state)
    assert msg.is_extended_id
    decoded = j1939.decode_pgn(j1939.PGN_EEC1, bytes(msg.data))
    assert decoded["ENGINE_SPEED"] == 2000.0


def test_active_dm1_dtcs_follow_fault_state():
    fault_state = FaultState()
    assert active_dm1_dtcs(fault_state) == []
    assert active_dm1_dtcs(None) == []

    fault_state.activate("overheat")
    assert active_dm1_dtcs(fault_state) == J1939_FAULT_DTCS["overheat"]


def test_every_fault_preset_has_a_j1939_dtc_mapping():
    # Keeps J1939_FAULT_DTCS in sync with faults.PRESETS.
    assert set(J1939_FAULT_DTCS) == set(PRESETS)
    for dtcs in J1939_FAULT_DTCS.values():
        for dtc in dtcs:
            assert j1939.decode_dtc(j1939.encode_dtc(dtc)) == dtc
