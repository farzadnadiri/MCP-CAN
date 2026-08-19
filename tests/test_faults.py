import os

from mcp_can.dbc import load_dbc
from mcp_can.simulator.faults import (
    PRESETS,
    FaultState,
    build_control_frame,
    preset_from_code,
)


def _db():
    db_path = os.path.join(os.path.dirname(__file__), "..", "vehicle.dbc")
    return load_dbc(os.path.abspath(db_path))


def test_build_control_frame_and_preset_from_code_roundtrip():
    for name in PRESETS:
        arb_id, data = build_control_frame(name)
        assert preset_from_code(data[0]) == name

    # Clearing (None) and an unrecognized name both encode as 0 / decode to None.
    _, cleared_data = build_control_frame(None)
    assert cleared_data[0] == 0
    assert preset_from_code(0) is None
    _, unknown_data = build_control_frame("not_a_real_preset")
    assert unknown_data[0] == 0


def test_fault_state_activate_and_clear():
    state = FaultState()
    assert state.active_preset_name() is None
    assert not state.has_override("ENGINE_TEMP")

    state.activate("overheat")
    assert state.active_preset_name() == "overheat"
    assert state.has_override("ENGINE_TEMP")
    assert state.get_override("ENGINE_TEMP") == PRESETS["overheat"].overrides["ENGINE_TEMP"]
    assert state.dtcs() == ["P0217"]

    state.activate(None)
    assert state.active_preset_name() is None
    assert not state.has_override("ENGINE_TEMP")
    assert state.dtcs() == []


def test_fault_state_activate_ignores_unknown_preset():
    state = FaultState()
    state.activate("not_a_real_preset")
    assert state.active_preset_name() is None


def test_fault_state_get_override_for_unaffected_signal_is_none():
    state = FaultState()
    state.activate("low_fuel")
    assert not state.has_override("ENGINE_TEMP")
    assert state.get_override("ENGINE_TEMP") is None


def test_every_preset_override_targets_a_real_dbc_signal():
    # Catches typos in faults.py's override tables that would otherwise only
    # surface as a silently-ignored override at simulator runtime.
    db = _db()
    all_signal_names = {sig.name for msg in db.messages for sig in msg.signals}
    for preset in PRESETS.values():
        for signal_name in preset.overrides:
            assert signal_name in all_signal_names, (
                f"{preset.name}: {signal_name!r} is not a signal in vehicle.dbc"
            )


def test_every_preset_override_encodes_without_error():
    # Regression guard for the same class of bug as
    # test_state.py::test_correlated_signals_are_actually_encodable --
    # a preset value outside its signal's bit-encodable range would raise
    # in Message.encode if SimThread's clamp step were ever removed.
    db = _db()
    for preset in PRESETS.values():
        by_message = {}
        for signal_name, value in preset.overrides.items():
            for msg in db.messages:
                if any(sig.name == signal_name for sig in msg.signals):
                    by_message.setdefault(msg, {})[signal_name] = value
                    break
        for msg, partial_signals in by_message.items():
            signals = {
                sig.name: partial_signals.get(sig.name, sig.minimum or 0) for sig in msg.signals
            }
            msg.encode(signals)
