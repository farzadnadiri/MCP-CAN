import logging
import random
import threading
import time
from typing import List, Tuple

import can
import cantools

from ..bus import make_bus
from ..config import configure_logging, get_settings
from ..dbc import decode_frame, load_dbc, signal_int
from ..diagnostics import REQUEST_MESSAGE, RESPONSE_MESSAGES, handle_service
from ..obd import OBD_BROADCAST_ID, build_response_frame, parse_request, simulate_response
from .profiles import DEFAULT_PROFILE

logger = logging.getLogger(__name__)


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
            except Exception:
                logger.exception("Error sending %s", self.msg.name)
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
                    except Exception:
                        logger.exception("OBD responder error")


class DiagnosticResponderThread(threading.Thread):
    """Simulates every ECU answering broadcast UDS-style diagnostic requests.

    See `diagnostics.py` for why this responds from all 4 ECUs rather than
    a single addressed one.
    """

    def __init__(self, db: cantools.database.Database, bus: can.BusABC):
        super().__init__(daemon=True)
        self.db = db
        self.bus = bus
        self.request_msg = db.get_message_by_name(REQUEST_MESSAGE)
        self.response_msgs = [db.get_message_by_name(name) for name in RESPONSE_MESSAGES]

    def run(self) -> None:
        while True:
            msg = self.bus.recv(timeout=0.1)
            if msg and msg.arbitration_id == self.request_msg.frame_id:
                try:
                    decoded = decode_frame(self.db, self.request_msg.frame_id, msg.data)
                    service_id = signal_int(decoded.get("SERVICE_ID", 0))
                    parameter_id = signal_int(decoded.get("PARAMETER_ID", 0))
                    data_field = signal_int(decoded.get("DATA_FIELD", 0))
                    response_code, response_data = handle_service(
                        service_id, parameter_id, data_field
                    )
                    for response_msg in self.response_msgs:
                        payload = response_msg.encode(
                            {
                                "SERVICE_ID": service_id,
                                "PARAMETER_ID": parameter_id,
                                "RESPONSE_CODE": response_code,
                                "DATA_FIELD": response_data,
                            }
                        )
                        self.bus.send(
                            can.Message(
                                arbitration_id=response_msg.frame_id,
                                data=payload,
                                is_extended_id=False,
                            )
                        )
                except Exception:
                    logger.exception("Diagnostic responder error")


def run_simulator(profile: List[Tuple[str, float]] = DEFAULT_PROFILE) -> None:
    configure_logging()
    settings = get_settings()
    db = load_dbc(settings.dbc_path)
    bus = make_bus(settings.can_interface, settings.can_channel)
    threads: List[SimThread] = []
    for msg_name, period in profile:
        t = SimThread(db, msg_name, period, bus)
        threads.append(t)
        t.start()
    # Each listener gets its own bus instance: a single python-can Bus's
    # recv() queue is consumed once per message, so threads sharing one
    # instance would silently steal frames from each other rather than each
    # seeing every frame.
    obd_t = OBDResponderThread(make_bus(settings.can_interface, settings.can_channel))
    obd_t.start()
    diag_t = DiagnosticResponderThread(
        db, make_bus(settings.can_interface, settings.can_channel)
    )
    diag_t.start()
    logger.info(
        "ECU simulation running (%d profile threads + OBD + diagnostics). Press Ctrl-C to exit.",
        len(threads),
    )
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down simulation...")
        try:
            bus.shutdown()
        except Exception:
            pass


def main() -> None:
    run_simulator()
