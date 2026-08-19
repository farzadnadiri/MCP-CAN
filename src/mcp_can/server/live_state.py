"""Background bus listener maintaining live/historical state for the server.

Runs once per server process, independent of any per-call listeners. Backs
both the web dashboard (`snapshot()`) and the frame-history-based MCP tools
(`frames_since()`) — a single continuously-running listener instead of each
tool call racing its own fresh bus connection, so a frame sent between two
tool calls (or "stolen" by a competing listener) is no longer simply lost.

Needs its own dedicated bus instance for the same reason
`simulator/runner.py`'s responder threads do: a single `python-can` Bus
instance's `recv()` queue is consumed once per message, so sharing one with
another listener would silently steal frames from it.

Read-only: this only *observes* traffic, it never sends.
"""
import logging
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

import cantools

from ..bus import make_bus, shutdown_bus
from ..dbc import decode_frame

logger = logging.getLogger(__name__)

ACTIVITY_LOG_SIZE = 50
DEFAULT_HISTORY_WINDOW_S = 60.0


def _display_value(value: Any) -> Any:
    # NamedSignalValue (choice-decoded signals) isn't JSON-serializable;
    # its str() is the human-readable choice name, which is what a
    # dashboard viewer wants to see anyway (e.g. "FAULT_PRESENT", not "1").
    if hasattr(value, "name") and hasattr(value, "value"):
        return str(value)
    return value


class LiveState:
    """Thread-safe live signal snapshot plus a time-windowed raw frame history."""

    def __init__(
        self,
        db: cantools.database.Database,
        can_interface: str,
        can_channel: str,
        history_window_s: float = DEFAULT_HISTORY_WINDOW_S,
    ):
        self.db = db
        self._can_interface = can_interface
        self._can_channel = can_channel
        self._history_window_s = history_window_s
        self._lock = threading.Lock()
        self._signals: Dict[str, Dict[str, Any]] = {}
        self._activity: Deque[Dict[str, Any]] = deque(maxlen=ACTIVITY_LOG_SIZE)
        self._frames: Deque[Dict[str, Any]] = deque()
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
                with self._lock:
                    self._frame_count += 1
                    self._frames.append(
                        {
                            "timestamp": msg.timestamp,
                            "arbitration_id": msg.arbitration_id,
                            "data": list(msg.data),
                        }
                    )
                    self._prune_frames_locked()

                # Signal/activity tracking is best-effort: frames the DBC
                # doesn't define (e.g. raw OBD-II responses) still count
                # toward frame history above, just not toward these.
                try:
                    message = self.db.get_message_by_frame_id(msg.arbitration_id)
                    decoded = decode_frame(self.db, msg.arbitration_id, msg.data)
                except Exception:
                    continue
                with self._lock:
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

    def _prune_frames_locked(self) -> None:
        cutoff = time.time() - self._history_window_s
        while self._frames and self._frames[0]["timestamp"] < cutoff:
            self._frames.popleft()

    def frames_since(self, start_time: float) -> List[Dict[str, Any]]:
        """Raw frames (timestamp, arbitration_id, data) seen at or after `start_time`.

        May return fewer frames than expected if `start_time` predates this
        instance's `history_window_s` retention window.
        """
        with self._lock:
            return [f for f in self._frames if f["timestamp"] >= start_time]

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "signals": dict(self._signals),
                "activity": list(self._activity),
                "frame_count": self._frame_count,
                "uptime_s": round(time.time() - self._started_at, 1),
            }
