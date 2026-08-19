import asyncio
import os

from mcp_can.server.fastmcp_server import create_app


def _make_app():
    dbc_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "vehicle.dbc"))
    os.environ["MCP_CAN_DBC_PATH"] = dbc_path
    return create_app()


def test_create_app_returns_fastmcp():
    # Ensure DBC path is resolvable during CI/test runs
    app = _make_app()
    # Avoid running the server; just ensure creation works
    assert hasattr(app, "tool") and hasattr(app, "run")


def test_expected_tools_are_registered():
    app = _make_app()
    tools = asyncio.run(app.list_tools())
    names = {t.name for t in tools}
    assert {
        "read_can_frames",
        "decode_can_frame",
        "filter_frames",
        "monitor_signal",
        "send_obd_request",
        "send_diagnostic_request",
    }.issubset(names)
