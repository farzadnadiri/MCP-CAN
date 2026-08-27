import json
import time

from typer.testing import CliRunner

from mcp_can import cli as cli_module
from mcp_can import j1939

runner = CliRunner()


class FakeMsg:
    def __init__(self, arbitration_id, data, is_extended_id=True, timestamp=None):
        self.arbitration_id = arbitration_id
        self.data = bytes(data)
        self.is_extended_id = is_extended_id
        self.timestamp = time.time() if timestamp is None else timestamp


class FakeBus:
    def __init__(self, messages):
        self._messages = list(messages)
        self.sent = []

    def recv(self, timeout=None):
        return self._messages.pop(0) if self._messages else None

    def send(self, msg):
        self.sent.append(msg)


def test_j1939_decode_engine_speed():
    can_id = j1939.build_can_id(j1939.PGN_EEC1, source_address=0, priority=3)
    data = j1939.encode_pgn(j1939.PGN_EEC1, {"ENGINE_SPEED": 1500.0})
    result = runner.invoke(
        cli_module.app,
        ["j1939-decode", hex(can_id), " ".join(f"{b:02x}" for b in data), "--json"],
    )
    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout)
    assert out["pgn_hex"] == "0xF004"
    assert out["source_address"] == 0
    assert out["signals"]["ENGINE_SPEED"] == 1500.0


def test_j1939_pgns_lists_catalog():
    result = runner.invoke(cli_module.app, ["j1939-pgns"])
    assert result.exit_code == 0, result.output
    assert "EEC1" in result.output
    assert "ENGINE_SPEED" in result.output


def test_j1939_request_returns_decoded_response(monkeypatch):
    can_id = j1939.build_can_id(j1939.PGN_ET1, source_address=0, priority=6)
    data = j1939.encode_pgn(j1939.PGN_ET1, {"ENGINE_COOLANT_TEMPERATURE": 95.0})
    fake = FakeBus([FakeMsg(can_id, data)])
    monkeypatch.setattr(cli_module, "make_bus", lambda *a, **k: fake)

    result = runner.invoke(cli_module.app, ["j1939-request", "0xFEEE", "--timeout", "0.2"])
    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout)
    assert out["status"] == "success"
    assert out["responses"][0]["signals"]["ENGINE_COOLANT_TEMPERATURE"] == 95.0
    # A Request PGN frame went out on the bus.
    assert fake.sent and fake.sent[0].is_extended_id


def test_j1939_dtcs_reads_dm1(monkeypatch):
    dtc = j1939.J1939Dtc(spn=110, fmi=0, oc=2)
    dm1_id = j1939.build_can_id(j1939.PGN_DM1, source_address=0, priority=6)
    fake = FakeBus([FakeMsg(dm1_id, j1939.build_dm1([dtc], mil_on=True))])
    monkeypatch.setattr(cli_module, "make_bus", lambda *a, **k: fake)

    result = runner.invoke(cli_module.app, ["j1939-dtcs", "--seconds", "0.2"])
    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout)
    assert out["status"] == "success"
    assert out["lamps"]["malfunction_indicator"] == "on"
    assert out["dtcs"][0]["spn"] == 110 and out["dtcs"][0]["fmi"] == 0
