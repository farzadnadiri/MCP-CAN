import asyncio
import json
import os
import time

import can
from starlette.testclient import TestClient

from mcp_can.config import DEFAULT_DBC_PATH
from mcp_can.server.fastmcp_server import create_app


def _make_app():
    os.environ["MCP_CAN_DBC_PATH"] = DEFAULT_DBC_PATH
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
        "decode_j1939_frame",
        "list_j1939_pgns",
        "request_j1939_pgn",
        "read_j1939_dtcs",
    }.issubset(names)


def test_decode_j1939_frame_tool():
    from mcp_can import j1939

    app = _make_app()
    can_id = j1939.build_can_id(j1939.PGN_EEC1, source_address=0, priority=3)
    data = list(j1939.encode_pgn(j1939.PGN_EEC1, {"ENGINE_SPEED": 1200.0}))
    result = asyncio.run(
        app.call_tool("decode_j1939_frame", {"arbitration_id": can_id, "data": data})
    )
    decoded = json.loads(result[0].text)
    assert decoded["pgn_hex"] == "0xF004"
    assert decoded["signals"]["ENGINE_SPEED"] == 1200.0


def test_list_j1939_pgns_tool():
    app = _make_app()
    result = asyncio.run(app.call_tool("list_j1939_pgns", {}))
    catalog = json.loads(result[0].text)
    acronyms = {p["acronym"] for p in catalog["pgns"]}
    assert {"EEC1", "ET1", "CCVS1"}.issubset(acronyms)


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


def test_root_redirects_to_dashboard():
    app = _make_app()
    client = TestClient(app.sse_app())
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/dashboard"


class _FakeMsg:
    def __init__(self, arbitration_id, data):
        self.arbitration_id = arbitration_id
        self.data = bytes(data)
        self.is_extended_id = True


class _FakeBus:
    def __init__(self, messages):
        self._messages = list(messages)
        self.sent = []

    def recv(self, timeout=None):
        return self._messages.pop(0) if self._messages else None

    def send(self, msg):
        self.sent.append(msg)

    def shutdown(self):
        pass


def test_request_j1939_pgn_accepts_acronym(monkeypatch):
    # Small local models get hex->decimal conversion wrong (asking for 39652
    # instead of 0xF004 = 61444), so the tool takes "EEC1" / "0xF004" as-is.
    from mcp_can import j1939
    from mcp_can.server import fastmcp_server

    can_id = j1939.build_can_id(j1939.PGN_EEC1, source_address=0, priority=3)
    data = j1939.encode_pgn(j1939.PGN_EEC1, {"ENGINE_SPEED": 1500.0})
    fake = _FakeBus([_FakeMsg(can_id, data)])
    monkeypatch.setattr(fastmcp_server, "make_bus", lambda *a, **k: fake)
    monkeypatch.setattr(fastmcp_server, "shutdown_bus", lambda bus: None)

    app = _make_app()
    result = asyncio.run(
        app.call_tool("request_j1939_pgn", {"pgn": "EEC1", "timeout_s": 0.3})
    )
    out = json.loads(result[0].text)
    assert out["status"] == "success", out
    assert out["requested_pgn_hex"] == "0xF004"
    assert out["responses"][0]["signals"]["ENGINE_SPEED"] == 1500.0
    # The Request PGN frame on the bus carries 0xF004, little-endian.
    assert list(fake.sent[0].data[:3]) == [0x04, 0xF0, 0x00]


def test_request_j1939_pgn_timeout_lists_known_pgns(monkeypatch):
    from mcp_can.server import fastmcp_server

    monkeypatch.setattr(fastmcp_server, "make_bus", lambda *a, **k: _FakeBus([]))
    monkeypatch.setattr(fastmcp_server, "shutdown_bus", lambda bus: None)

    app = _make_app()
    result = asyncio.run(
        app.call_tool("request_j1939_pgn", {"pgn": 39652, "timeout_s": 0.2})
    )
    out = json.loads(result[0].text)
    assert out["status"] == "timeout"
    assert "0x9AE4" in out["message"]
    assert "EEC1=0xF004" in out["message"]


def test_obd_and_decode_tools_accept_hex_strings():
    app = _make_app()
    result = asyncio.run(
        app.call_tool(
            "decode_can_frame",
            {"arbitration_id": "0x100", "data": [0, 0, 0, 0, 0, 0, 0, 0]},
        )
    )
    out = json.loads(result[0].text)
    assert out["status"] == "success", out
    assert "ENGINE_SPEED" in out["signals"]
