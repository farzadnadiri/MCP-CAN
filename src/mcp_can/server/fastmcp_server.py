import asyncio
import json
import logging
import time
import types
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import can
from mcp.server.fastmcp import FastMCP
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse

from .. import j1939
from ..bus import make_bus, shutdown_bus
from ..config import configure_logging, get_settings
from ..dbc import decode_frame, load_dbc, signal_int
from ..diagnostics import (
    REQUEST_MESSAGE,
    RESPONSE_MESSAGES,
    ecu_name_from_response_message,
    response_code_name,
)
from ..obd import build_request, decode_response, parse_response
from ..simulator.faults import FAULT_ACK_ID, PRESETS, build_control_frame
from .live_state import DEFAULT_HISTORY_WINDOW_S, LiveState
from .schemas import (
    DecodeResult,
    DiagnosticEcuResponse,
    DiagnosticResult,
    FaultScenarioResult,
    FrameOut,
    J1939DecodeResult,
    J1939Dtc,
    J1939DtcResult,
    J1939PgnCatalog,
    J1939PgnInfo,
    J1939RequestResult,
    ObdResponse,
    SignalSample,
    SignalState,
    VehicleSnapshot,
)

logger = logging.getLogger(__name__)

_DASHBOARD_HTML = (Path(__file__).parent / "templates" / "dashboard.html").read_text(
    encoding="utf-8"
)


def create_app() -> FastMCP:
    """Create a FastMCP server exposing CAN tools and DBC metadata."""
    settings = get_settings()
    mcp = FastMCP("Vehicle CAN MCP")
    db = load_dbc(settings.dbc_path)
    live_state = LiveState(
        db,
        settings.can_interface,
        settings.can_channel,
        history_window_s=max(settings.max_duration_s, DEFAULT_HISTORY_WINDOW_S),
    )
    live_state.start()

    def _capped_duration(duration_s: float) -> float:
        if duration_s > settings.max_duration_s:
            logger.warning(
                "duration_s=%.1f exceeds max_duration_s=%.1f; capping.",
                duration_s,
                settings.max_duration_s,
            )
            return settings.max_duration_s
        return duration_s

    @mcp.tool()
    def read_can_frames(duration_s: float = 1.0) -> List[FrameOut]:
        """Return every raw frame seen in the last `duration_s` seconds.

        Served from the server's continuously-running frame history buffer,
        so it returns immediately (no waiting) and won't miss frames sent
        between calls -- unlike opening a fresh bus listener per call."""
        duration_s = _capped_duration(duration_s)
        since = time.time() - duration_s
        return [
            FrameOut(
                timestamp=f["timestamp"],
                arbitration_id=hex(f["arbitration_id"]),
                data=f["data"],
            )
            for f in live_state.frames_since(since)
        ]

    @mcp.tool()
    def decode_can_frame(arbitration_id: int, data: List[int]) -> DecodeResult:
        """Decode a single CAN frame's bytes into named signals using the loaded DBC."""
        try:
            decoded = decode_frame(db, arbitration_id, bytes(data))
            return DecodeResult(status="success", signals=decoded)
        except Exception as e:
            return DecodeResult(status="error", message=str(e))

    @mcp.tool()
    def filter_frames(
        arbitration_id: Optional[int] = None,
        signal_name: Optional[str] = None,
        duration_s: float = 1.0,
    ) -> List[FrameOut]:
        """Frames from the last `duration_s` seconds matching the given
        arbitration_id and/or containing signal_name once decoded. Served
        from the frame history buffer -- see `read_can_frames`."""
        duration_s = _capped_duration(duration_s)
        since = time.time() - duration_s
        results: List[FrameOut] = []
        for f in live_state.frames_since(since):
            if arbitration_id is not None and f["arbitration_id"] != arbitration_id:
                continue
            if signal_name:
                try:
                    decoded = decode_frame(db, f["arbitration_id"], bytes(f["data"]))
                except Exception:
                    continue
                if signal_name not in decoded:
                    continue
                results.append(
                    FrameOut(
                        timestamp=f["timestamp"],
                        arbitration_id=hex(f["arbitration_id"]),
                        data=f["data"],
                        signal_name=signal_name,
                        signal_value=decoded[signal_name],
                    )
                )
            else:
                results.append(
                    FrameOut(
                        timestamp=f["timestamp"],
                        arbitration_id=hex(f["arbitration_id"]),
                        data=f["data"],
                    )
                )
        return results

    @mcp.tool()
    def monitor_signal(signal_name: str, duration_s: float = 2.0) -> List[SignalSample]:
        """Timestamped samples of one decoded signal over the last `duration_s`
        seconds. Served from the frame history buffer -- see `read_can_frames`."""
        duration_s = _capped_duration(duration_s)
        since = time.time() - duration_s
        results: List[SignalSample] = []
        for f in live_state.frames_since(since):
            try:
                decoded = decode_frame(db, f["arbitration_id"], bytes(f["data"]))
            except Exception:
                continue
            if signal_name in decoded:
                results.append(SignalSample(timestamp=f["timestamp"], value=decoded[signal_name]))
        return results

    @mcp.tool()
    def get_vehicle_snapshot() -> VehicleSnapshot:
        """The last known value of every signal seen so far (one entry per
        signal, not per frame) -- a single-call overview of current vehicle
        state instead of decoding a stream of raw frames yourself. `age_s`
        is how long ago that value was last updated; a large `age_s` means
        that ECU/message hasn't been seen recently."""
        raw = live_state.snapshot()
        now = time.time()
        signals = {
            name: SignalState(
                value=info["value"],
                unit=info["unit"],
                message=info["message"],
                age_s=round(now - info["timestamp"], 2),
            )
            for name, info in raw["signals"].items()
        }
        return VehicleSnapshot(
            signals=signals, frame_count=raw["frame_count"], uptime_s=raw["uptime_s"]
        )

    @mcp.tool()
    def send_obd_request(
        service: int,
        pid: Optional[int] = None,
        timeout_s: float = 2.0,
    ) -> ObdResponse:
        """Send a standard OBD-II (SAE J1979) request (e.g. service=1, pid=0x0D for
        vehicle speed) and return the first ECU response, decoded where the PID is
        one the simulator implements."""
        timeout_s = _capped_duration(timeout_s)
        bus = make_bus(settings.can_interface, settings.can_channel)
        try:
            arb_id, data = build_request(service, pid)
            bus.send(can.Message(arbitration_id=arb_id, data=data, is_extended_id=False))
            msg = bus.recv(timeout=timeout_s)
            if not msg:
                return ObdResponse(status="timeout", message="No OBD-II response within timeout_s")
            response_service, resp_pid, value_bytes = parse_response(msg.data)
            return ObdResponse(
                status="success",
                arbitration_id=hex(msg.arbitration_id),
                response_service=response_service,
                pid=resp_pid,
                decoded=decode_response(response_service, resp_pid, value_bytes),
                raw_data=list(msg.data),
            )
        except Exception as e:
            return ObdResponse(status="error", message=str(e))
        finally:
            shutdown_bus(bus)

    @mcp.tool()
    def send_diagnostic_request(
        service_id: int,
        parameter_id: int = 0,
        data_field: int = 0,
        timeout_s: float = 2.0,
    ) -> DiagnosticResult:
        """Send a UDS-style diagnostic request (see vehicle.dbc's DIAGNOSTIC_REQUEST
        SERVICE_ID choices, e.g. 0x22=READ_DATA_BY_ID, 0x11=RESET_ECU) and collect
        responses from every ECU that answers within timeout_s."""
        timeout_s = _capped_duration(timeout_s)
        request_msg = db.get_message_by_name(REQUEST_MESSAGE)
        response_frame_ids = {
            db.get_message_by_name(name).frame_id: name for name in RESPONSE_MESSAGES
        }
        bus = make_bus(settings.can_interface, settings.can_channel)
        try:
            payload = request_msg.encode(
                {
                    "SERVICE_ID": service_id,
                    "PARAMETER_ID": parameter_id,
                    "DATA_FIELD": data_field,
                }
            )
            bus.send(
                can.Message(
                    arbitration_id=request_msg.frame_id, data=payload, is_extended_id=False
                )
            )
            responses: List[DiagnosticEcuResponse] = []
            end = time.time() + timeout_s
            while time.time() < end:
                msg = bus.recv(timeout=0.1)
                if msg and msg.arbitration_id in response_frame_ids:
                    decoded = decode_frame(db, msg.arbitration_id, msg.data)
                    responses.append(
                        DiagnosticEcuResponse(
                            ecu=ecu_name_from_response_message(
                                response_frame_ids[msg.arbitration_id]
                            ),
                            service_id=signal_int(decoded.get("SERVICE_ID", 0)),
                            parameter_id=signal_int(decoded.get("PARAMETER_ID", 0)),
                            response_code=response_code_name(
                                signal_int(decoded.get("RESPONSE_CODE", 0))
                            ),
                            data_field=signal_int(decoded.get("DATA_FIELD", 0)),
                        )
                    )
            if not responses:
                return DiagnosticResult(
                    status="timeout", message="No ECU responded within timeout_s"
                )
            return DiagnosticResult(status="success", responses=responses)
        except Exception as e:
            return DiagnosticResult(status="error", message=str(e))
        finally:
            shutdown_bus(bus)

    @mcp.tool()
    def activate_fault_scenario(
        preset: Optional[str] = None,
        timeout_s: float = 2.0,
    ) -> FaultScenarioResult:
        """Activate a fault-injection scenario in the simulator, or clear the
        active one by passing preset=None. Available presets: "overheat"
        (engine at its hottest reportable temperature, SYSTEM_STATUS faults),
        "abs_fault" (all wheel speed sensors stuck at zero, SYSTEM_STATUS
        faults), "low_fuel" (fuel level pinned critically low). Where a
        preset sets DTCs, they then show up in `send_obd_request`'s Mode 03
        (service=3) response. Only affects a simulator sharing this
        process's virtual bus (`mcp-can demo`)."""
        timeout_s = _capped_duration(timeout_s)
        if preset is not None and preset not in PRESETS:
            return FaultScenarioResult(
                status="error",
                message=f"Unknown preset {preset!r}. Choices: {', '.join(PRESETS)}",
            )
        bus = make_bus(settings.can_interface, settings.can_channel)
        try:
            arb_id, data = build_control_frame(preset)
            bus.send(can.Message(arbitration_id=arb_id, data=data, is_extended_id=False))
            end = time.time() + timeout_s
            while time.time() < end:
                msg = bus.recv(timeout=0.1)
                if msg and msg.arbitration_id == FAULT_ACK_ID:
                    active = PRESETS.get(preset) if preset else None
                    return FaultScenarioResult(
                        status="success",
                        active_preset=preset,
                        description=active.description if active else None,
                        dtcs=list(active.dtcs) if active else [],
                    )
            return FaultScenarioResult(
                status="timeout", message="No ack from simulator within timeout_s"
            )
        except Exception as e:
            return FaultScenarioResult(status="error", message=str(e))
        finally:
            shutdown_bus(bus)

    def _decode_j1939(arbitration_id: int, data: bytes) -> J1939DecodeResult:
        parsed = j1939.parse_can_id(arbitration_id)
        definition = j1939.PGN_CATALOG.get(parsed.pgn)
        return J1939DecodeResult(
            status="success",
            priority=parsed.priority,
            pgn=parsed.pgn,
            pgn_hex=f"0x{parsed.pgn:04X}",
            pgn_name=definition.name if definition else None,
            source_address=parsed.source_address,
            destination_address=parsed.destination_address,
            is_broadcast=parsed.is_broadcast,
            signals=j1939.decode_pgn(parsed.pgn, data) or None,
        )

    @mcp.tool()
    def decode_j1939_frame(arbitration_id: int, data: List[int]) -> J1939DecodeResult:
        """Decode a 29-bit J1939 frame: split the extended ID into priority /
        PGN / source + destination address, then decode known SPNs from the
        payload (see `list_j1939_pgns` for the supported catalog). DM1 frames
        return their active DTC list."""
        try:
            return _decode_j1939(arbitration_id, bytes(data))
        except Exception as e:
            return J1939DecodeResult(status="error", message=str(e))

    @mcp.tool()
    def list_j1939_pgns() -> J1939PgnCatalog:
        """The catalog of J1939 Parameter Group Numbers this server can decode
        and (for `request_j1939_pgn`) request from the simulator, each with
        its Suspect Parameter Numbers, bit layout, scaling and units."""
        pgns = [
            J1939PgnInfo(**j1939.describe_pgn(pgn))
            for pgn, definition in j1939.PGN_CATALOG.items()
            if definition.spns
        ]
        return J1939PgnCatalog(pgns=pgns)

    @mcp.tool()
    def request_j1939_pgn(pgn: int, timeout_s: float = 2.0) -> J1939RequestResult:
        """Send a J1939 Request PGN (0xEA00) asking every ECU to transmit
        `pgn` (e.g. 0xF004 EEC1 for engine speed, 0xFEEE ET1 for coolant
        temperature) and return the decoded responses seen within timeout_s.
        Needs a simulator on this process's bus (`mcp-can demo`)."""
        timeout_s = _capped_duration(timeout_s)
        bus = make_bus(settings.can_interface, settings.can_channel)
        try:
            can_id, data = j1939.build_request_pgn(pgn)
            bus.send(can.Message(arbitration_id=can_id, data=data, is_extended_id=True))
            responses: List[J1939DecodeResult] = []
            end = time.time() + timeout_s
            while time.time() < end:
                msg = bus.recv(timeout=0.1)
                if not msg or not msg.is_extended_id:
                    continue
                if j1939.parse_can_id(msg.arbitration_id).pgn == pgn:
                    responses.append(_decode_j1939(msg.arbitration_id, bytes(msg.data)))
            if not responses:
                return J1939RequestResult(
                    status="timeout",
                    requested_pgn=pgn,
                    requested_pgn_hex=f"0x{pgn:04X}",
                    message="No ECU transmitted the requested PGN within timeout_s",
                )
            return J1939RequestResult(
                status="success",
                requested_pgn=pgn,
                requested_pgn_hex=f"0x{pgn:04X}",
                responses=responses,
            )
        except Exception as e:
            return J1939RequestResult(status="error", message=str(e))
        finally:
            shutdown_bus(bus)

    @mcp.tool()
    def read_j1939_dtcs(duration_s: float = 3.0) -> J1939DtcResult:
        """Read the most recent J1939 DM1 (active diagnostic trouble codes)
        broadcast from the last `duration_s` seconds: lamp status plus every
        active SPN/FMI. Served from the frame history buffer -- see
        `read_can_frames`. An empty `dtcs` list means no active faults."""
        duration_s = _capped_duration(duration_s)
        since = time.time() - duration_s
        latest: Optional[Dict[str, Any]] = None
        for f in live_state.frames_since(since):
            try:
                parsed = j1939.parse_can_id(f["arbitration_id"])
            except Exception:
                continue
            if parsed.pgn == j1939.PGN_DM1:
                latest = f
        if latest is None:
            return J1939DtcResult(
                status="timeout", message="No DM1 broadcast seen within duration_s"
            )
        parsed = j1939.parse_can_id(latest["arbitration_id"])
        lamps, dtcs = j1939.parse_dm1(bytes(latest["data"]))
        return J1939DtcResult(
            status="success",
            source_address=parsed.source_address,
            lamps=lamps,
            dtcs=[J1939Dtc(**d.as_dict()) for d in dtcs],
        )

    @mcp.resource("file://vehicle.dbc")
    def dbc_info() -> Dict[str, Any]:
        info: Dict[str, Any] = {}
        try:
            info['status'] = 'success'
            info['version'] = db.version if db.version else 'N/A'
            info['nodes'] = [node.name for node in db.nodes]
            messages_info = []
            for msg in db.messages:
                message_details: Dict[str, Any] = {
                    'name': msg.name,
                    'id': msg.frame_id,
                    'id_hex': hex(msg.frame_id),
                    'length': msg.length,
                    'cycle_time_ms': msg.cycle_time,
                    'senders': msg.senders,
                    'signals': []
                }
                for sig in msg.signals:
                    signal_details = {
                        'name': sig.name,
                        'start_bit': sig.start,
                        'length_bits': sig.length,
                        'scale': sig.scale,
                        'offset': sig.offset,
                        'minimum': sig.minimum,
                        'maximum': sig.maximum,
                        'unit': sig.unit,
                        'choices': sig.choices,
                        'is_signed': sig.is_signed,
                        'is_float': sig.is_float,
                        'byte_order': sig.byte_order,
                        'receivers': sig.receivers,
                    }
                    message_details['signals'].append(signal_details)
                messages_info.append(message_details)
            info['messages'] = messages_info
        except FileNotFoundError:
            info['status'] = 'error'
            info['message'] = "DBC file not found"
        except Exception as e:
            info['status'] = 'error'
            info['message'] = f"An unexpected error occurred: {e}"
        return info

    # Health/compat endpoints for clients that probe OAuth discovery.
    @mcp.custom_route("/.well-known/oauth-authorization-server/sse", methods=["GET", "OPTIONS"])
    async def _auth_discovery(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "auth": False})

    @mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET", "OPTIONS"])
    async def _protected_discovery(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "auth": False})

    @mcp.custom_route("/healthz", methods=["GET"])
    async def _healthz(_: Request) -> JSONResponse:
        try:
            has_messages = len(db.messages) > 0
        except Exception:
            has_messages = False
        healthy = has_messages
        return JSONResponse(
            {"status": "ok" if healthy else "error", "dbc_loaded": has_messages},
            status_code=200 if healthy else 503,
        )

    # Read-only live dashboard: a static page (below) polling this SSE stream.
    # Only shows data when a simulator shares this process's virtual bus
    # (i.e. `mcp-can demo`) -- see live_state.py.
    @mcp.custom_route("/dashboard", methods=["GET"])
    async def _dashboard(_: Request) -> HTMLResponse:
        return HTMLResponse(_DASHBOARD_HTML)

    @mcp.custom_route("/dashboard/stream", methods=["GET"])
    async def _dashboard_stream(_: Request) -> StreamingResponse:
        async def events() -> AsyncIterator[str]:
            while True:
                yield f"data: {json.dumps(live_state.snapshot())}\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(events(), media_type="text/event-stream")

    # CORS so browser-based MCP hosts (Inspector) can reach SSE. Origins
    # default to "*" for the zero-friction demo experience; see
    # Settings.cors_allow_origins. Credentials are only allowed once that's
    # narrowed to specific origins -- wildcard-origin + allow_credentials is
    # a combination browsers reject outright, so enabling it for "*" would
    # just be a sloppy default with no actual browser benefit.
    original_sse_app = mcp.sse_app
    cors_origins = settings.cors_allow_origins
    cors_credentials = cors_origins != ["*"]

    def _cors_sse_app(self: FastMCP, *args: Any, **kwargs: Any):
        # Forward args/kwargs as-is: FastMCP.sse_app()'s signature has changed
        # across mcp SDK versions (e.g. an added `mount_path` param), so this
        # stays compatible without pinning to one exact shape.
        app = original_sse_app(*args, **kwargs)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=cors_credentials,
        )
        return app

    mcp.sse_app = types.MethodType(_cors_sse_app, mcp)  # type: ignore[method-assign]

    return mcp


def _mcp_sdk_version() -> str:
    try:
        return version("mcp")
    except PackageNotFoundError:
        return "unknown"


def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    mcp = create_app()
    mcp.settings.port = settings.mcp_port
    # Ensure accessible outside container/host
    mcp.settings.host = "0.0.0.0"
    logger.info(
        "Starting MCP-CAN server on %s:%s (transport=%s)",
        mcp.settings.host,
        mcp.settings.port,
        settings.mcp_transport,
    )
    try:
        mcp.run(transport=settings.mcp_transport)  # type: ignore[arg-type]
    except ValueError:
        if settings.mcp_transport != "sse":
            logger.error(
                "Transport %r is not supported by the installed mcp SDK (%s). "
                "Set MCP_CAN_MCP_TRANSPORT=sse, or upgrade the mcp package.",
                settings.mcp_transport,
                _mcp_sdk_version(),
            )
        raise
