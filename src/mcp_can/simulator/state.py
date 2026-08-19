"""Correlated vehicle driving state.

Without this, `SimThread`'s per-signal independent random draws mean e.g.
ENGINE_SPEED and THROTTLE_POSITION have zero relationship tick to tick --
not much like a moving vehicle. This module holds a few "driver input"-like
base variables that evolve smoothly over time, plus a table mapping DBC
signal names to values derived from them. Signals not in that table (doors,
seatbelts, crash/fault flags, etc.) keep using `SimThread`'s independent
random draws -- they're discrete/situational, not driving-dynamics signals
with an obvious relationship to throttle/speed/rpm.

`tick()` is a pure function (state in, state out) so it's testable without
any threading or timing; `VehicleState` just calls it from a background
loop and exposes a thread-safe snapshot.
"""
import math
import random
import threading
import time
from dataclasses import dataclass, replace
from typing import Callable, Dict, Optional

IDLE_RPM = 800.0
AMBIENT_TEMP_C = 20.0
OPERATING_TEMP_C = 90.0


@dataclass
class DrivingState:
    throttle_pct: float = 0.0
    rpm: float = IDLE_RPM
    speed_kph: float = 0.0
    engine_temp_c: float = AMBIENT_TEMP_C
    fuel_pct: float = 80.0


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _approach(current: float, target: float, time_constant_s: float, dt_s: float) -> float:
    """Move `current` toward `target` with exponential-decay lag.

    Standard first-order-lag smoothing: `time_constant_s` is roughly how
    long it takes to close ~63% of the gap, independent of how often
    `tick()` is actually called.
    """
    alpha = 1 - math.exp(-dt_s / time_constant_s)
    return current + (target - current) * alpha


def tick(state: DrivingState, dt_s: float) -> DrivingState:
    """Advance driving state by `dt_s` seconds. Not real vehicle physics --
    just enough correlation that related signals move together."""
    throttle = state.throttle_pct + random.uniform(-8, 8) * dt_s
    if random.random() < 0.3 * dt_s:  # an occasional bigger press/lift
        throttle += random.uniform(-30, 30)
    throttle = _clamp(throttle, 0.0, 100.0)

    rpm = _approach(state.rpm, IDLE_RPM + throttle * 45, time_constant_s=2.0, dt_s=dt_s)
    target_speed = max(0.0, (rpm - IDLE_RPM) * 0.045)
    speed = _approach(state.speed_kph, target_speed, time_constant_s=3.0, dt_s=dt_s)
    engine_temp = _approach(
        state.engine_temp_c, OPERATING_TEMP_C, time_constant_s=60.0, dt_s=dt_s
    ) + random.uniform(-0.3, 0.3)
    fuel = state.fuel_pct - (0.002 + throttle * 0.0002) * dt_s

    return DrivingState(
        throttle_pct=throttle,
        rpm=_clamp(rpm, 0.0, 16383.0),
        speed_kph=_clamp(speed, 0.0, 300.0),
        engine_temp_c=_clamp(engine_temp, -40.0, 127.5),
        fuel_pct=_clamp(fuel, 0.0, 100.0),
    )


CorrelatedFn = Callable[[DrivingState], float]

CORRELATED_SIGNALS: Dict[str, CorrelatedFn] = {
    "ENGINE_SPEED": lambda s: round(s.rpm),
    "ENGINE_TEMP": lambda s: round(s.engine_temp_c, 1),
    "THROTTLE_POSITION": lambda s: round(s.throttle_pct, 1),
    "ENGINE_LOAD": lambda s: round(
        _clamp(s.throttle_pct * 0.9 + random.uniform(-3, 3), 0.0, 100.0), 1
    ),
    "FUEL_LEVEL": lambda s: round(s.fuel_pct, 1),
    "WHEEL_SPEED_FL": lambda s: round(
        _clamp(s.speed_kph + random.uniform(-1.0, 1.0), 0.0, 300.0), 2
    ),
    "WHEEL_SPEED_FR": lambda s: round(
        _clamp(s.speed_kph + random.uniform(-1.2, 1.2), 0.0, 300.0), 2
    ),
    "WHEEL_SPEED_RL": lambda s: round(
        _clamp(s.speed_kph + random.uniform(-1.0, 1.0), 0.0, 300.0), 2
    ),
    "WHEEL_SPEED_RR": lambda s: round(
        _clamp(s.speed_kph + random.uniform(-1.2, 1.2), 0.0, 300.0), 2
    ),
}


class VehicleState:
    """Thread-safe, continuously-ticking driving state.

    A single background loop advances the state; readers only ever call
    `snapshot()`, never mutate it directly.
    """

    def __init__(self, tick_s: float = 0.2):
        self._tick_s = tick_s
        self._lock = threading.Lock()
        self._state = DrivingState()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="VehicleStateTicker")
        self._thread.start()

    def _run(self) -> None:
        while True:
            time.sleep(self._tick_s)
            with self._lock:
                self._state = tick(self._state, self._tick_s)

    def snapshot(self) -> DrivingState:
        with self._lock:
            return replace(self._state)
