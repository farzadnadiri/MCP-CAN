import random
import threading
import time
from typing import List, Tuple

import can
import cantools

from ..bus import make_bus
from ..config import get_settings
from ..dbc import load_dbc
from ..obd import OBD_BROADCAST_ID, build_response_frame, parse_request, simulate_response
from .profiles import DEFAULT_PROFILE


class SimThread(threading.Thread):
    def __init__(
        self,
        db: cantools.database.Database,
        msg_name: str,
        period: float,
        bus: can.BusABC,
    ):
        super().__init__(daemon=True)
        self.db = db
        self.msg = db.get_message_by_name(msg_name)
        self.period = period
        self.bus = bus

    def _random_signal_value(self, sig: cantools.database.can.signal.Signal):
        if sig.choices:
            return random.choice(list(sig.choices.keys()))
        min_val = sig.minimum if sig.minimum is not None else 0
        max_val = sig.maximum if sig.maximum is not None else min_val + 100
        if sig.is_float:
            return round(random.uniform(min_val, max_val), 2)
        value = random.uniform(min_val, max_val)
        raw = (value - sig.offset) / sig.scale if sig.scale else value
        raw = int(round(raw))
        max_raw = 2 ** sig.length - 1
        raw = max(0, min(raw, max_raw))
        return raw * sig.scale + sig.offset if sig.scale else raw

    def run(self):
        while True:
            try:
                signals = {sig.name: self._random_signal_value(sig) for sig in self.msg.signals}
                data = self.msg.encode(signals)
                can_msg = can.Message(
                    arbitration_id=self.msg.frame_id,
                    data=data,
                    is_extended_id=False,
                )
                self.bus.send(can_msg)
                # print(f"Sent {self.msg.name}: {signals}")
            except Exception as e:
                print(f"Error sending {self.msg.name}: {e}")
            time.sleep(self.period)


class OBDResponderThread(threading.Thread):
    def __init__(self, bus: can.BusABC):
        super().__init__(daemon=True)
        self.bus = bus

    def run(self) -> None:
        while True:
            msg = self.bus.recv(timeout=0.1)
            if msg and msg.arbitration_id == OBD_BROADCAST_ID and len(msg.data) > 0:
                service, pid = parse_request(msg.data)
                payload = simulate_response(service, pid)
                if payload is not None:
                    try:
                        arb_id, data = build_response_frame(payload)
                        resp = can.Message(
                            arbitration_id=arb_id,
                            data=data,
                            is_extended_id=False,
                        )
                        self.bus.send(resp)
                    except Exception as e:
                        print(f"OBD responder error: {e}")


def run_simulator(profile: List[Tuple[str, float]] = DEFAULT_PROFILE) -> None:
    settings = get_settings()
    db = load_dbc(settings.dbc_path)
    bus = make_bus(settings.can_interface, settings.can_channel)
    threads: List[SimThread] = []
    for msg_name, period in profile:
        t = SimThread(db, msg_name, period, bus)
        threads.append(t)
        t.start()
    obd_t = OBDResponderThread(bus)
    obd_t.start()
    print("ECU simulation running. Press Ctrl-C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down simulation...")
        try:
            bus.shutdown()
        except Exception:
            pass


def main() -> None:
    run_simulator()

