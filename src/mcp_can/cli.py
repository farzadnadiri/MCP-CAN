import json
import os
import threading
import time as _time
from typing import List, Optional

import can
import typer
from rich.console import Console
from rich.table import Table

from . import j1939
from .bus import make_bus, read_frames, shutdown_bus
from .config import configure_logging, get_settings
from .dbc import decode_frame, load_dbc, signal_int
from .diagnostics import (
    REQUEST_MESSAGE,
    RESPONSE_MESSAGES,
    ecu_name_from_response_message,
    response_code_name,
)
from .obd import build_request, decode_response, parse_response
from .server.fastmcp_server import main as run_server
from .simulator.faults import FAULT_ACK_ID, PRESETS, build_control_frame
from .simulator.runner import run_simulator

app = typer.Typer(help="MCP-CAN: simulate, inspect and serve CAN data over MCP.")
console = Console()


@app.callback()
def _main_callback() -> None:
    configure_logging()


def _parse_int(value: str) -> int:
    return int(value, 16) if value.lower().startswith("0x") else int(value)


@app.command()
def server(
    port: Optional[int] = typer.Option(None, help="MCP server port (default from env)"),
    transport: Optional[str] = typer.Option(
        None, help="MCP transport: sse | streamable-http | stdio (default from env)"
    ),
) -> None:
    if port is not None:
        os.environ["MCP_CAN_MCP_PORT"] = str(port)
    if transport is not None:
        os.environ["MCP_CAN_MCP_TRANSPORT"] = transport
    run_server()


@app.command()
def simulate() -> None:
    """Run the ECU simulator using the configured DBC."""
    run_simulator()


@app.command()
def frames(seconds: float = typer.Option(1.0, help="Duration to listen on CAN bus")) -> None:
    """Capture raw CAN frames for a period and print JSON."""
    settings = get_settings()
    bus = make_bus(settings.can_interface, settings.can_channel)
    try:
        frames_list = read_frames(bus, seconds)
        out = [
            {
                "timestamp": f.timestamp,
                "arbitration_id": hex(f.arbitration_id),
                "data": list(f.data),
            }
            for f in frames_list
        ]
        typer.echo(json.dumps(out, indent=2))
    finally:
        shutdown_bus(bus)


@app.command()
def decode(
    id: str,
    data: str,
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON instead of a table"),
) -> None:
    """Decode a CAN frame given an ID and data bytes.

    id: CAN ID in hex (e.g. 0x100) or decimal.
    data: comma-separated bytes (e.g. 01,02,03,04) or space-separated hex (e.g. 01 02 03 04)
    """
    settings = get_settings()
    db = load_dbc(settings.dbc_path)
    arb_id = _parse_int(id)
    bytes_list: List[int] = []
    if "," in data:
        bytes_list = [
            int(x.strip(), 16 if x.strip().startswith("0x") else 10)
            for x in data.split(",")
            if x.strip()
        ]
    else:
        parts = [p for p in data.replace(",", " ").split(" ") if p]
        bytes_list = [
            int(x.strip(), 16 if all(c in "0123456789abcdefABCDEF" for c in x) else 10)
            for x in parts
        ]
    decoded = decode_frame(db, arb_id, bytes(bytes_list))
    if json_output:
        typer.echo(json.dumps(decoded, indent=2))
        return
    message = db.get_message_by_frame_id(arb_id)
    unit_by_name = {sig.name: sig.unit for sig in message.signals}
    table = Table(title=f"{message.name}  (id={id})")
    table.add_column("Signal")
    table.add_column("Value")
    table.add_column("Unit")
    for name, value in decoded.items():
        table.add_row(name, str(value), unit_by_name.get(name) or "-")
    console.print(table)


@app.command()
def monitor(
    signal: str,
    seconds: float = typer.Option(2.0, help="Duration to listen"),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON instead of live output"),
) -> None:
    """Monitor a specific signal and print timestamped values."""
    settings = get_settings()
    db = load_dbc(settings.dbc_path)
    bus = make_bus(settings.can_interface, settings.can_channel)
    end = _time.time() + seconds
    out: List[dict] = []
    try:
        if not json_output:
            console.print(f"[bold cyan]Monitoring {signal} for {seconds}s...[/bold cyan]")
        while _time.time() < end:
            msg = bus.recv(timeout=0.1)
            if msg:
                try:
                    decoded = decode_frame(db, msg.arbitration_id, msg.data)
                    if signal in decoded:
                        sample = {"timestamp": msg.timestamp, "value": decoded[signal]}
                        out.append(sample)
                        if not json_output:
                            console.print(
                                f"  [dim]{sample['timestamp']:.3f}[/dim]  "
                                f"{signal} = [green]{sample['value']}[/green]"
                            )
                except Exception:
                    pass
        if json_output:
            typer.echo(json.dumps(out, indent=2))
        elif out:
            values = [s["value"] for s in out if isinstance(s["value"], (int, float))]
            summary = f"[bold]{len(out)} sample(s)[/bold]"
            if values:
                avg = sum(values) / len(values)
                summary += f", min={min(values)} max={max(values)} avg={avg:.2f}"
            console.print(summary)
        else:
            console.print("[yellow]No samples observed.[/yellow]")
    finally:
        shutdown_bus(bus)


@app.command()
def snapshot(
    seconds: float = typer.Option(1.0, help="How long to listen before reporting"),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON instead of a table"),
) -> None:
    """Listen briefly and report the latest value seen for every signal.

    CLI counterpart to the `get_vehicle_snapshot` MCP tool -- since this runs
    as its own process rather than inside the server, it builds its own
    short-lived snapshot instead of reading the server's history buffer.
    """
    settings = get_settings()
    db = load_dbc(settings.dbc_path)
    bus = make_bus(settings.can_interface, settings.can_channel)
    latest: dict = {}
    end = _time.time() + seconds
    try:
        while _time.time() < end:
            msg = bus.recv(timeout=0.1)
            if msg:
                try:
                    decoded = decode_frame(db, msg.arbitration_id, msg.data)
                    message = db.get_message_by_frame_id(msg.arbitration_id)
                except Exception:
                    continue
                unit_by_name = {sig.name: sig.unit for sig in message.signals}
                for name, value in decoded.items():
                    latest[name] = {
                        "value": value,
                        "unit": unit_by_name.get(name) or "",
                        "message": message.name,
                    }
        if json_output:
            typer.echo(json.dumps(latest, indent=2, default=str))
            return
        if not latest:
            console.print("[yellow]No signals observed.[/yellow]")
            return
        table = Table(title=f"Vehicle Snapshot (last {seconds}s)")
        table.add_column("Signal")
        table.add_column("Value")
        table.add_column("Unit")
        table.add_column("Message")
        for name in sorted(latest):
            info = latest[name]
            table.add_row(name, str(info["value"]), info["unit"] or "-", info["message"])
        console.print(table)
    finally:
        shutdown_bus(bus)


@app.command("dbc-info")
def dbc_info_cmd(
    message: Optional[str] = typer.Argument(None, help="Show only this message's signals"),
) -> None:
    """Pretty-print the loaded DBC's messages and signals."""
    settings = get_settings()
    db = load_dbc(settings.dbc_path)
    messages = [m for m in db.messages if message is None or m.name == message]
    if not messages:
        console.print(f"[red]No message named '{message}' found in {settings.dbc_path}[/red]")
        raise typer.Exit(code=1)
    for msg in messages:
        table = Table(title=f"{msg.name}  (id=0x{msg.frame_id:03x}, {msg.length} bytes)")
        table.add_column("Signal")
        table.add_column("Bits")
        table.add_column("Scale")
        table.add_column("Offset")
        table.add_column("Range")
        table.add_column("Unit")
        for sig in msg.signals:
            rng = f"{sig.minimum}..{sig.maximum}" if sig.minimum is not None else "-"
            table.add_row(
                sig.name,
                f"{sig.start}:{sig.length}",
                str(sig.scale),
                str(sig.offset),
                rng,
                sig.unit or "-",
            )
        console.print(table)


@app.command("obd-request")
def obd_request(
    service: str = typer.Option(..., "--service", "-s", help="Service ID (hex like 0x01)"),
    pid: Optional[str] = typer.Option(None, "--pid", "-p", help="PID hex like 0x0D"),
    timeout: float = 1.0,
) -> None:
    """Send a basic OBD-II (SAE J1979) request and print the first response as JSON."""
    settings = get_settings()
    bus = make_bus(settings.can_interface, settings.can_channel)
    svc = _parse_int(service)
    parsed_pid: Optional[int] = _parse_int(pid) if pid is not None else None
    arb_id, data = build_request(svc, parsed_pid)
    req = can.Message(arbitration_id=arb_id, data=data, is_extended_id=False)
    bus.send(req)
    msg = bus.recv(timeout=timeout)
    try:
        if not msg:
            typer.echo(json.dumps({"status": "timeout"}))
            raise typer.Exit(code=1)
        response_service, resp_pid, value_bytes = parse_response(msg.data)
        out = {
            "arbitration_id": hex(msg.arbitration_id),
            "data": [int(b) for b in msg.data],
            "decoded": decode_response(response_service, resp_pid, value_bytes),
        }
        typer.echo(json.dumps(out, indent=2))
    finally:
        shutdown_bus(bus)


@app.command("diag-request")
def diag_request(
    service_id: str = typer.Option(
        ..., "--service-id", "-s", help="Diagnostic service ID (hex like 0x22)"
    ),
    parameter_id: str = typer.Option(
        "0x00", "--parameter-id", "-p", help="Parameter ID (hex like 0x01)"
    ),
    data_field: str = typer.Option("0x00", "--data-field", help="Request data field (hex/int)"),
    timeout: float = 2.0,
) -> None:
    """Send a UDS-style diagnostic request (see vehicle.dbc DIAGNOSTIC_REQUEST) and
    print every ECU's response as JSON."""
    settings = get_settings()
    db = load_dbc(settings.dbc_path)
    bus = make_bus(settings.can_interface, settings.can_channel)
    try:
        request_msg = db.get_message_by_name(REQUEST_MESSAGE)
        response_frame_ids = {
            db.get_message_by_name(name).frame_id: name for name in RESPONSE_MESSAGES
        }
        payload = request_msg.encode(
            {
                "SERVICE_ID": _parse_int(service_id),
                "PARAMETER_ID": _parse_int(parameter_id),
                "DATA_FIELD": _parse_int(data_field),
            }
        )
        bus.send(
            can.Message(arbitration_id=request_msg.frame_id, data=payload, is_extended_id=False)
        )
        responses = []
        end = _time.time() + timeout
        while _time.time() < end:
            msg = bus.recv(timeout=0.1)
            if msg and msg.arbitration_id in response_frame_ids:
                decoded = decode_frame(db, msg.arbitration_id, msg.data)
                ecu = ecu_name_from_response_message(response_frame_ids[msg.arbitration_id])
                responses.append(
                    {
                        "ecu": ecu,
                        "service_id": signal_int(decoded.get("SERVICE_ID", 0)),
                        "parameter_id": signal_int(decoded.get("PARAMETER_ID", 0)),
                        "response_code": response_code_name(
                            signal_int(decoded.get("RESPONSE_CODE", 0))
                        ),
                        "data_field": signal_int(decoded.get("DATA_FIELD", 0)),
                    }
                )
        if not responses:
            typer.echo(json.dumps({"status": "timeout"}))
            raise typer.Exit(code=1)
        typer.echo(json.dumps({"status": "success", "responses": responses}, indent=2))
    finally:
        shutdown_bus(bus)


@app.command("fault")
def fault_scenario(
    preset: str = typer.Argument(
        ..., help="Scenario name to activate, 'clear' to deactivate, or 'list'"
    ),
    timeout: float = 1.0,
) -> None:
    """Activate (or clear) a fault-injection scenario in a running simulator.

    Requires `mcp-can simulate`/`demo` to already be running: this sends a
    control frame over the bus and waits for the simulator to ack it, the
    same round-trip pattern as `obd-request`/`diag-request`.
    """
    if preset == "list":
        table = Table(title="Fault scenarios")
        table.add_column("Name")
        table.add_column("Description")
        table.add_column("DTCs")
        for p in PRESETS.values():
            table.add_row(p.name, p.description, ", ".join(p.dtcs) or "-")
        console.print(table)
        return
    target: Optional[str] = None if preset == "clear" else preset
    if target is not None and target not in PRESETS:
        console.print(
            f"[red]Unknown scenario '{preset}'. Run 'mcp-can fault list' to see options.[/red]"
        )
        raise typer.Exit(code=1)
    settings = get_settings()
    bus = make_bus(settings.can_interface, settings.can_channel)
    try:
        arb_id, data = build_control_frame(target)
        bus.send(can.Message(arbitration_id=arb_id, data=data, is_extended_id=False))
        end = _time.time() + timeout
        while _time.time() < end:
            msg = bus.recv(timeout=0.1)
            if msg and msg.arbitration_id == FAULT_ACK_ID:
                console.print(f"[green]Scenario now active: {target or '(cleared)'}[/green]")
                return
        console.print("[yellow]No ack from simulator -- is it running?[/yellow]")
        raise typer.Exit(code=1)
    finally:
        shutdown_bus(bus)


def _parse_data_bytes(data: str) -> List[int]:
    """Parse "01 02 0x03" / "1,2,3" style byte lists (shared by j1939 commands)."""
    parts = [p for p in data.replace(",", " ").split(" ") if p]
    return [
        int(x, 16 if x.lower().startswith("0x") or not x.isdigit() else 10) for x in parts
    ]


@app.command("j1939-decode")
def j1939_decode(
    id: str = typer.Argument(..., help="29-bit extended CAN ID (hex like 0x18F00400)"),
    data: str = typer.Argument(..., help="Payload bytes, space- or comma-separated"),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON instead of a table"),
) -> None:
    """Decompose a J1939 29-bit ID (priority / PGN / addresses) and decode known SPNs."""
    arb_id = _parse_int(id)
    payload = bytes(_parse_data_bytes(data))
    parsed = j1939.parse_can_id(arb_id)
    definition = j1939.PGN_CATALOG.get(parsed.pgn)
    signals = j1939.decode_pgn(parsed.pgn, payload)
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "priority": parsed.priority,
                    "pgn": parsed.pgn,
                    "pgn_hex": f"0x{parsed.pgn:04X}",
                    "pgn_name": definition.name if definition else None,
                    "source_address": parsed.source_address,
                    "destination_address": parsed.destination_address,
                    "is_broadcast": parsed.is_broadcast,
                    "signals": signals,
                },
                indent=2,
                default=str,
            )
        )
        return
    header = definition.name if definition else "unknown PGN"
    table = Table(title=f"J1939  {header}  (PGN 0x{parsed.pgn:04X})")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("priority", str(parsed.priority))
    table.add_row("source address", f"0x{parsed.source_address:02X}")
    da = parsed.destination_address
    table.add_row("destination", "broadcast" if da is None else f"0x{da:02X}")
    for name, value in signals.items():
        table.add_row(name, str(value))
    console.print(table)


@app.command("j1939-pgns")
def j1939_pgns() -> None:
    """List the J1939 PGNs/SPNs this project can decode."""
    for pgn, definition in j1939.PGN_CATALOG.items():
        if not definition.spns:
            continue
        table = Table(title=f"{definition.acronym} - {definition.name}  (PGN 0x{pgn:04X})")
        table.add_column("SPN")
        table.add_column("Name")
        table.add_column("Bits")
        table.add_column("Scale")
        table.add_column("Offset")
        table.add_column("Unit")
        for s in definition.spns:
            table.add_row(
                str(s.spn),
                s.name,
                f"{s.start_bit}:{s.length_bits}",
                str(s.scale),
                str(s.offset),
                s.unit or "-",
            )
        console.print(table)


@app.command("j1939-request")
def j1939_request(
    pgn: str = typer.Argument(..., help="PGN to request (hex like 0xF004 or decimal)"),
    timeout: float = 2.0,
) -> None:
    """Send a J1939 Request PGN (0xEA00) and print every decoded response."""
    requested = _parse_int(pgn)
    settings = get_settings()
    bus = make_bus(settings.can_interface, settings.can_channel)
    try:
        can_id, data = j1939.build_request_pgn(requested)
        bus.send(can.Message(arbitration_id=can_id, data=data, is_extended_id=True))
        responses = []
        end = _time.time() + timeout
        while _time.time() < end:
            msg = bus.recv(timeout=0.1)
            if not msg or not getattr(msg, "is_extended_id", False):
                continue
            parsed = j1939.parse_can_id(msg.arbitration_id)
            if parsed.pgn != requested:
                continue
            responses.append(
                {
                    "source_address": parsed.source_address,
                    "signals": j1939.decode_pgn(parsed.pgn, bytes(msg.data)),
                }
            )
        if not responses:
            typer.echo(json.dumps({"status": "timeout"}))
            raise typer.Exit(code=1)
        typer.echo(json.dumps({"status": "success", "responses": responses}, indent=2, default=str))
    finally:
        shutdown_bus(bus)


@app.command("j1939-dtcs")
def j1939_dtcs(seconds: float = typer.Option(3.0, help="How long to listen for a DM1")) -> None:
    """Listen for a J1939 DM1 broadcast and print its active trouble codes."""
    settings = get_settings()
    bus = make_bus(settings.can_interface, settings.can_channel)
    try:
        latest = None
        end = _time.time() + seconds
        while _time.time() < end:
            msg = bus.recv(timeout=0.1)
            if not msg or not getattr(msg, "is_extended_id", False):
                continue
            if j1939.parse_can_id(msg.arbitration_id).pgn == j1939.PGN_DM1:
                latest = msg
        if latest is None:
            typer.echo(json.dumps({"status": "timeout"}))
            raise typer.Exit(code=1)
        lamps, dtcs = j1939.parse_dm1(bytes(latest.data))
        typer.echo(
            json.dumps(
                {"status": "success", "lamps": lamps, "dtcs": [d.as_dict() for d in dtcs]},
                indent=2,
            )
        )
    finally:
        shutdown_bus(bus)


@app.command("demo")
def demo(
    port: Optional[int] = typer.Option(
        None,
        help="Run simulator + server in one process (shared virtual bus)",
    ),
    transport: Optional[str] = typer.Option(
        None, help="MCP transport: sse | streamable-http | stdio (default from env)"
    ),
) -> None:
    """Run simulator in a background thread and start the MCP server.

    Helps on Windows with virtual backend.
    """
    sim_thread = threading.Thread(target=run_simulator, daemon=True)
    sim_thread.start()
    if port is not None:
        os.environ["MCP_CAN_MCP_PORT"] = str(port)
    if transport is not None:
        os.environ["MCP_CAN_MCP_TRANSPORT"] = transport
    run_server()
