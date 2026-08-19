import os
import random

from mcp_can.dbc import load_dbc
from mcp_can.simulator.state import (
    CORRELATED_SIGNALS,
    ENGINE_TEMP_MAX_C,
    IDLE_RPM,
    DrivingState,
    tick,
)


def _db():
    db_path = os.path.join(os.path.dirname(__file__), "..", "vehicle.dbc")
    return load_dbc(os.path.abspath(db_path))


def test_fuel_never_increases():
    random.seed(0)
    state = DrivingState(fuel_pct=50.0)
    for _ in range(200):
        next_state = tick(state, dt_s=0.2)
        assert next_state.fuel_pct <= state.fuel_pct
        state = next_state


def test_values_stay_within_valid_ranges():
    random.seed(1)
    state = DrivingState()
    for _ in range(500):
        state = tick(state, dt_s=0.2)
        assert 0.0 <= state.throttle_pct <= 100.0
        assert 0.0 <= state.rpm <= 16383.0
        assert 0.0 <= state.speed_kph <= 300.0
        assert -40.0 <= state.engine_temp_c <= ENGINE_TEMP_MAX_C
        assert 0.0 <= state.fuel_pct <= 100.0


def test_rpm_and_speed_rise_toward_target_under_sustained_throttle():
    random.seed(2)
    state = DrivingState(throttle_pct=100.0, rpm=IDLE_RPM, speed_kph=0.0)
    # Hold throttle steady (bypass tick()'s own throttle wander) and let
    # rpm/speed chase their targets for a few seconds of simulated time.
    for _ in range(100):
        state = tick(state, dt_s=0.1)
        state.throttle_pct = 100.0
    assert state.rpm > IDLE_RPM + 1000
    assert state.speed_kph > 20.0


def test_engine_warms_up_toward_operating_temperature():
    random.seed(3)
    state = DrivingState(engine_temp_c=20.0)
    for _ in range(500):
        state = tick(state, dt_s=0.2)
    assert state.engine_temp_c > 70.0


def test_correlated_signals_produce_dbc_valid_values():
    # Ranges per vehicle.dbc, capped to what's actually bit-encodable (not
    # just the declared min/max -- see ENGINE_TEMP_MAX_C):
    # ENGINE_SPEED [0,16383], ENGINE_TEMP [-40,87.5],
    # THROTTLE_POSITION/ENGINE_LOAD/FUEL_LEVEL [0,100], WHEEL_SPEED_* [0,300].
    random.seed(4)
    ranges = {
        "ENGINE_SPEED": (0, 16383),
        "ENGINE_TEMP": (-40, ENGINE_TEMP_MAX_C),
        "THROTTLE_POSITION": (0, 100),
        "ENGINE_LOAD": (0, 100),
        "FUEL_LEVEL": (0, 100),
        "WHEEL_SPEED_FL": (0, 300),
        "WHEEL_SPEED_FR": (0, 300),
        "WHEEL_SPEED_RL": (0, 300),
        "WHEEL_SPEED_RR": (0, 300),
    }
    assert set(CORRELATED_SIGNALS) == set(ranges)
    state = DrivingState(throttle_pct=100.0, rpm=16000.0, speed_kph=295.0, fuel_pct=1.0)
    for name, fn in CORRELATED_SIGNALS.items():
        lo, hi = ranges[name]
        for _ in range(50):
            value = fn(state)
            assert lo <= value <= hi, f"{name}={value} outside [{lo},{hi}]"


def test_correlated_signals_are_actually_encodable():
    # Regression test: CORRELATED_SIGNALS values previously passed the
    # DBC-declared min/max check above while still exceeding what the
    # signal's bit width can encode (ENGINE_TEMP's 8 bits cap out at 87.5,
    # below the declared 127.5 max), which made cantools' Message.encode
    # raise. Drive the underlying signals to their extremes and confirm
    # encoding every ENGINE_STATUS/ABS_STATUS message actually succeeds.
    db = _db()
    engine_msg = db.get_message_by_name("ENGINE_STATUS")
    abs_msg = db.get_message_by_name("ABS_STATUS")
    random.seed(5)
    extreme_states = [
        DrivingState(throttle_pct=100.0, rpm=16000.0, speed_kph=295.0, engine_temp_c=87.5),
        DrivingState(throttle_pct=0.0, rpm=0.0, speed_kph=0.0, engine_temp_c=-40.0),
    ]
    for state in extreme_states:
        for _ in range(50):
            engine_msg.encode(
                {
                    "ENGINE_SPEED": CORRELATED_SIGNALS["ENGINE_SPEED"](state),
                    "ENGINE_TEMP": CORRELATED_SIGNALS["ENGINE_TEMP"](state),
                    "THROTTLE_POSITION": CORRELATED_SIGNALS["THROTTLE_POSITION"](state),
                    "ENGINE_LOAD": CORRELATED_SIGNALS["ENGINE_LOAD"](state),
                    "FUEL_LEVEL": CORRELATED_SIGNALS["FUEL_LEVEL"](state),
                }
            )
            abs_msg.encode(
                {
                    "WHEEL_SPEED_FL": CORRELATED_SIGNALS["WHEEL_SPEED_FL"](state),
                    "WHEEL_SPEED_FR": CORRELATED_SIGNALS["WHEEL_SPEED_FR"](state),
                    "WHEEL_SPEED_RL": CORRELATED_SIGNALS["WHEEL_SPEED_RL"](state),
                    "WHEEL_SPEED_RR": CORRELATED_SIGNALS["WHEEL_SPEED_RR"](state),
                }
            )
