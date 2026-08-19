import json
import os
import threading
import time as _time
from typing import List, Optional

import can
import typer
from rich.console import Console
from rich.table import Table

from .bus import make_bus, read_frames, shutdown_bus
from .config import configure_logging, get_settings
from .dbc import decode_frame, load_dbc, signal_int
from .diagnostics import (
    REQUEST_MESSAGE,
    RESPONSE_MESSAGES,
    ecu_name_from_response_message,
    response_code_name,
)
from .obd import build_request, decode_pid_value, parse_response
from .server.fastmcp_server import main as run_server
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
            "decoded": decode_pid_value(resp_pid, value_bytes),
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
