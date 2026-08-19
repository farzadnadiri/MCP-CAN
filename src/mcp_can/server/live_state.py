"""Background bus listener maintaining live state for the web dashboard.

Runs once per server process, independent of the per-call MCP tool
listeners. Needs its own dedicated bus instance for the same reason
`simulator/runner.py`'s responder threads do: a single `python-can` Bus
instance's `recv()` queue is consumed once per message, so sharing one
with another listener would silently steal frames from it.

Read-only: this only *observes* traffic, it never sends.
"""
import logging
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, Optional

import cantools

from ..bus import make_bus, shutdown_bus
from ..dbc import decode_frame

logger = logging.getLogger(__name__)

ACTIVITY_LOG_SIZE = 50


def _display_value(value: Any) -> Any:
    # NamedSignalValue (choice-decoded signals) isn't JSON-serializable;
    # its str() is the human-readable choice name, which is what a
    # dashboard viewer wants to see anyway (e.g. "FAULT_PRESENT", not "1").
    if hasattr(value, "name") and hasattr(value, "value"):
        return str(value)
    return value


class LiveState:
    """Thread-safe snapshot of the most recently seen value for every signal."""

    def __init__(self, db: cantools.database.Database, can_interface: str, can_channel: str):
        self.db = db
        self._can_interface = can_interface
        self._can_channel = can_channel
        self._lock = threading.Lock()
        self._signals: Dict[str, Dict[str, Any]] = {}
        self._activity: Deque[Dict[str, Any]] = deque(maxlen=ACTIVITY_LOG_SIZE)
        self._frame_count = 0
        self._started_at = time.time()
        self._thread: Optional[threading.Thread] = None
        self._unit_by_signal: Dict[str, str] = {
            sig.name: (sig.unit or "") for msg in db.messages for sig in msg.signals
        }

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="LiveStateListener")
        self._thread.start()

    def _run(self) -> None:
        bus = make_bus(self._can_interface, self._can_channel)
        try:
            while True:
                msg = bus.recv(timeout=0.5)
                if msg is None:
                    continue
                try:
                    message = self.db.get_message_by_frame_id(msg.arbitration_id)
                    decoded = decode_frame(self.db, msg.arbitration_id, msg.data)
                except Exception:
                    continue
                with self._lock:
                    self._frame_count += 1
                    for name, value in decoded.items():
                        self._signals[name] = {
                            "value": _display_value(value),
                            "unit": self._unit_by_signal.get(name, ""),
                            "message": message.name,
                            "timestamp": msg.timestamp,
                        }
                    self._activity.append(
                        {
                            "timestamp": msg.timestamp,
                            "arbitration_id": hex(msg.arbitration_id),
                            "message": message.name,
                        }
                    )
        except Exception:
            logger.exception("Live-state listener stopped unexpectedly")
        finally:
            shutdown_bus(bus)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "signals": dict(self._signals),
                "activity": list(self._activity),
                "frame_count": self._frame_count,
                "uptime_s": round(time.time() - self._started_at, 1),
            }
