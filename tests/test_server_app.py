import asyncio
import json
import os
import time

import can
from starlette.testclient import TestClient

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
        "get_vehicle_snapshot",
        "activate_fault_scenario",
    }.issubset(names)


def test_healthz_and_dashboard_routes():
    app = _make_app()
    client = TestClient(app.sse_app())

    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["dbc_loaded"] is True

    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    assert "text/html" in dashboard.headers["content-type"]
    assert "MCP-CAN Live Dashboard" in dashboard.text


def test_cors_defaults_to_wildcard_without_credentials():
    app = _make_app()
    client = TestClient(app.sse_app())
    resp = client.get("/healthz", headers={"Origin": "http://example.com"})
    assert resp.headers.get("access-control-allow-origin") == "*"
    # Wildcard origin + allow_credentials is a combination browsers reject
    # outright, so the middleware shouldn't be asked to send it at all.
    assert "access-control-allow-credentials" not in resp.headers


def test_cors_allows_credentials_once_origins_are_narrowed():
    os.environ["MCP_CAN_CORS_ALLOW_ORIGINS"] = '["http://example.com"]'
    try:
        app = _make_app()
        client = TestClient(app.sse_app())
        resp = client.get("/healthz", headers={"Origin": "http://example.com"})
        assert resp.headers.get("access-control-allow-origin") == "http://example.com"
        assert resp.headers.get("access-control-allow-credentials") == "true"
    finally:
        del os.environ["MCP_CAN_CORS_ALLOW_ORIGINS"]


def test_read_can_frames_served_from_history_buffer():
    # create_app() starts LiveState's listener on the same virtual channel;
    # a frame sent from an independent bus instance should still show up in
    # read_can_frames -- proving the tool reads the shared history buffer
    # rather than racing its own (now-removed) fresh bus connection.
    app = _make_app()
    time.sleep(0.2)  # let the listener thread come up

    sender = can.ThreadSafeBus(interface="virtual", channel="bus0")
    try:
        sender.send(
            can.Message(
                arbitration_id=0x100,
                data=[1, 2, 3, 4, 5, 6, 7, 8],
                is_extended_id=False,
            )
        )
        time.sleep(0.3)  # let the listener pick it up
    finally:
        sender.shutdown()

    result = asyncio.run(app.call_tool("read_can_frames", {"duration_s": 5.0}))
    # FastMCP emits one content block per returned list item, not one block
    # containing a JSON array.
    frames = [json.loads(block.text) for block in result]
    assert any(
        f["arbitration_id"] == "0x100" and f["data"] == [1, 2, 3, 4, 5, 6, 7, 8]
        for f in frames
    )

    # arbitration_id 0x100 is ENGINE_STATUS in vehicle.dbc, so the same
    # frame should also have updated get_vehicle_snapshot's signal state.
    snap_result = asyncio.run(app.call_tool("get_vehicle_snapshot", {}))
    snapshot = json.loads(snap_result[0].text)
    assert "ENGINE_SPEED" in snapshot["signals"]
    assert snapshot["signals"]["ENGINE_SPEED"]["message"] == "ENGINE_STATUS"
    assert snapshot["frame_count"] >= 1
