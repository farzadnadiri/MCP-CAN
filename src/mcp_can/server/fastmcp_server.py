import time
import types
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context, FastMCP
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..bus import make_bus, shutdown_bus
from ..config import get_settings
from ..dbc import decode_frame, load_dbc


def create_app() -> FastMCP:
    """Create a FastMCP server exposing CAN tools and DBC metadata."""
    settings = get_settings()
    mcp = FastMCP("Vehicle CAN MCP")
    db = load_dbc(settings.dbc_path)

    @mcp.tool()
    async def read_can_frames(
        duration_s: float = 1.0,
        ctx: Context | None = None,
    ) -> List[Dict[str, Any]]:
        bus = make_bus(settings.can_interface, settings.can_channel)
        try:
            frames: List[Dict[str, Any]] = []
            end = time.time() + duration_s
            count = 0
            while time.time() < end:
                msg = bus.recv(timeout=0.1)
                if msg:
                    frames.append(
                        {
                            "timestamp": msg.timestamp,
                            "arbitration_id": hex(msg.arbitration_id),
                            "data": list(msg.data),
                        }
                    )
                    count += 1
                    if ctx:
                        await ctx.report_progress(count)
            return frames
        finally:
            shutdown_bus(bus)

    @mcp.tool()
    def decode_can_frame(arbitration_id: int, data: List[int]) -> Dict[str, Any]:
        try:
            decoded = decode_frame(db, arbitration_id, bytes(data))
            return {"status": "success", "signals": decoded}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @mcp.tool()
    async def filter_frames(
        arbitration_id: Optional[int] = None,
        signal_name: Optional[str] = None,
        duration_s: float = 1.0,
        ctx: Context | None = None,
    ) -> List[Dict[str, Any]]:
        bus = make_bus(settings.can_interface, settings.can_channel)
        try:
            end = time.time() + duration_s
            results: List[Dict[str, Any]] = []
            count = 0
            while time.time() < end:
                msg = bus.recv(timeout=0.1)
                if msg:
                    if arbitration_id is not None and msg.arbitration_id != arbitration_id:
                        continue
                    frame_info: Dict[str, Any] = {
                        "timestamp": msg.timestamp,
                        "arbitration_id": hex(msg.arbitration_id),
                        "data": list(msg.data),
                    }
                    if signal_name:
                        try:
                            decoded = decode_frame(db, msg.arbitration_id, msg.data)
                            if signal_name in decoded:
                                frame_info["signal_value"] = decoded[signal_name]
                                results.append(frame_info)
                        except Exception:
                            pass
                    else:
                        results.append(frame_info)
                    count += 1
                    if ctx:
                        await ctx.report_progress(count)
            return results
        finally:
            shutdown_bus(bus)

    @mcp.tool()
    async def monitor_signal(
        signal_name: str,
        duration_s: float = 2.0,
        ctx: Context | None = None,
    ) -> List[Dict[str, Any]]:
        bus = make_bus(settings.can_interface, settings.can_channel)
        try:
            end = time.time() + duration_s
            results: List[Dict[str, Any]] = []
            count = 0
            while time.time() < end:
                msg = bus.recv(timeout=0.1)
                if msg:
                    try:
                        decoded = decode_frame(db, msg.arbitration_id, msg.data)
                        if signal_name in decoded:
                            results.append(
                                {
                                    "timestamp": msg.timestamp,
                                    "value": decoded[signal_name],
                                }
                            )
                            count += 1
                            if ctx:
                                await ctx.report_progress(count)
                    except Exception:
                        pass
            return results
        finally:
            shutdown_bus(bus)

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

    # Enable permissive CORS so browser-based MCP hosts (Inspector) can reach SSE.
    original_sse_app = mcp.sse_app

    def _cors_sse_app(self: FastMCP, *args: Any, **kwargs: Any):
        # Forward args/kwargs as-is: FastMCP.sse_app()'s signature has changed
        # across mcp SDK versions (e.g. an added `mount_path` param), so this
        # stays compatible without pinning to one exact shape.
        app = original_sse_app(*args, **kwargs)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=True,
        )
        return app

    mcp.sse_app = types.MethodType(_cors_sse_app, mcp)  # type: ignore[method-assign]

    return mcp


def main() -> None:
    settings = get_settings()
    mcp = create_app()
    mcp.settings.port = settings.mcp_port
    # Ensure accessible outside container/host
    mcp.settings.host = "0.0.0.0"
    mcp.run(transport="sse")
