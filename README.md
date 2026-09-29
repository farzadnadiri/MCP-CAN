# 🚗 MCP-CAN: Vehicle CAN Bus, OBD-II and J1939 Diagnostics for LLMs (Model Context Protocol)

🔌 Virtual CAN + MCP Server

**MCP-CAN** is a [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server that exposes automotive **CAN bus**, **OBD-II** (SAE J1979), **UDS**, and **SAE J1939** diagnostic data to LLMs and AI agents. It ships a built-in **virtual CAN bus** with an **ECU simulator**, decodes traffic via a **DBC** database (`cantools`), and serves MCP tools over SSE or streamable-HTTP. No CAN hardware, adapter, or vehicle is required by default; optional SocketCAN/vCAN on Linux.

Use it to let an LLM read live CAN frames, decode signals, run OBD-II PID and UDS diagnostic requests, inspect J1939 PGNs/SPNs and DM1 trouble codes, and drive fault-injection scenarios, all against a simulated vehicle.

**Keywords:** MCP server, Model Context Protocol, CAN bus, CANbus, OBD-II, OBD2, on-board diagnostics, SAE J1939, UDS, ECU simulator, vehicle diagnostics, automotive, DBC, python-can, cantools, SocketCAN, LLM tools, AI agents.

---

## ✨ Highlights
- MCP server for CAN/OBD/UDS-diagnostics/J1939 → LLM/SLM (tools + DBC metadata, SSE or streamable-HTTP).
- Virtual CAN backend (python-can) out of the box; optional SocketCAN/vCAN on Linux.
- DBC-driven encoding/decoding via `cantools`.
- ECU simulator that streams multiple messages, plus OBD-II, UDS-style, and SAE J1939 responders.
- SAE J1939 (heavy-duty, 29-bit extended IDs): ID decomposition (priority/PGN/source+destination address), a curated PGN/SPN catalog (EEC1, EEC2, ET1, CCVS1, LFE1, DD1), Request PGN (`0xEA00`) round trips, and DM1 active-DTC (SPN/FMI) broadcasts. Runs alongside the 11-bit bus; toggle with `MCP_CAN_J1939_ENABLED`.
- Correlated driving-dynamics signal generation, plus named fault-injection scenarios (`overheat`, `abs_fault`, `low_fuel`) with matching DTCs.
- Typer CLI: `mcp-can` (simulate, server, demo, frames, decode, monitor, dbc-info, obd-request, diag-request, fault, j1939-decode, j1939-pgns, j1939-request, j1939-dtcs).
- Structured tool output (typed Pydantic models), duration-capped tool calls, `/healthz`, colorized logging.
- Read-only live web dashboard (`/dashboard`): signal values and recent frames, updated over SSE.
- Dockerfile + docker compose for server + simulator.
- Unit tests, type hints, lint config (ruff, mypy); see `CONTRIBUTING.md`.

## 📁 Repository Layout
- `src/mcp_can/`
  - `cli.py` – Typer commands
  - `bus.py` – python-can helpers
  - `dbc.py` – DBC loading/decoding
  - `obd.py` – OBD-II (SAE J1979) request/response helpers
  - `diagnostics.py` – UDS-style diagnostic service/response-code logic
  - `j1939.py` – SAE J1939: 29-bit ID decomposition, PGN/SPN catalog, DM1 DTCs, Request PGN
  - `config.py` – env settings (`MCP_CAN_*`) + logging setup
  - `models.py` – internal bus-layer dataclass (`Frame`)
  - `simulator/runner.py` – ECU simulator + OBD/diagnostic responders
  - `simulator/j1939_runner.py` – J1939 broadcasters (EEC1/ET1/CCVS1/…), Request PGN responder, DM1 emitter
  - `simulator/state.py` – correlated driving-dynamics state (RPM/speed/throttle/etc.)
  - `simulator/faults.py` – named fault-injection presets + activation protocol
  - `server/fastmcp_server.py` – MCP tools/resources + dashboard routes
  - `server/schemas.py` – Pydantic models for MCP tool structured output
  - `server/live_state.py` – background bus listener backing the dashboard
  - `server/templates/dashboard.html` – the dashboard page itself
- `src/mcp_can/data/vehicle.dbc` – sample CAN database bundled with the package (incl. a UDS-like diagnostic schema)
- `simulate-ecus.py`, `can-mcp.py` – standalone run-without-installing entrypoints
- `docker/compose.yml`, `Dockerfile`
- `tests/` – unit tests
- `CONTRIBUTING.md`, `CHANGELOG.md`

## ✅ Prerequisites
- Python 3.10+
- (Optional) Docker / Docker Compose
- (Optional) Ollama if you want a local LLM backend

## 📦 Install (Python)
From [PyPI](https://pypi.org/project/mcp-can/):
```bash
pip install mcp-can
mcp-can demo          # simulator + MCP server in one process, no hardware needed
```
Or run it without installing into your environment: `pipx run mcp-can demo` / `uvx mcp-can demo`.

The sample `vehicle.dbc` ships inside the package, so this works from any directory; point `MCP_CAN_DBC_PATH` at your own DBC to use it instead.

From a checkout (for development):
```bash
pip install -e ".[dev]"
```

## 🚀 Quickstart (Simulator + MCP Server)
Two terminals:
```bash
# Terminal A: start ECU simulator on virtual bus0
mcp-can simulate

# Terminal B: start MCP server (SSE on 6278)
mcp-can server --port 6278
```

Single-process (helps on Windows if virtual backend doesn't share across processes):
```bash
mcp-can demo --port 6278
```

Sample interactions:
```bash
mcp-can frames --seconds 2
mcp-can decode 0x100 "01 02 03 04 05 06 07 08"       # pretty table by default, --json for scripting
mcp-can dbc-info                                      # table of every message/signal in the DBC
mcp-can monitor ENGINE_SPEED --seconds 3
mcp-can obd-request --service 0x01 --pid 0x0D
mcp-can diag-request --service-id 0x22 --parameter-id 0x05   # READ_DATA_BY_ID
mcp-can j1939-pgns                                            # J1939 PGN/SPN catalog
mcp-can j1939-request 0xF004                                  # ask ECUs to send EEC1 (engine speed)
mcp-can j1939-dtcs                                            # read the latest DM1 active-DTC broadcast
```

## 📊 Live Dashboard
With `mcp-can demo` (or `server`) running, open `http://localhost:6278/dashboard` in a browser: live signal values grouped by ECU message, and a scrolling feed of recent frames, updating ~2x/second over Server-Sent Events. It's read-only (view only, no controls to send frames) and self-contained: no build step, no external assets, works offline. Like everything bus-related here, it only shows data when the simulator shares the *same process* as the server (`mcp-can demo`); pointed at a bare `mcp-can server` with no simulator, it just shows "waiting for CAN traffic."

![MCP-CAN live dashboard showing grouped ECU signal values and a recent-frames feed](docs/images/dashboard.png)

## 🛠️ Available MCP Tools & Resources
| Name | Type | Description |
|---|---|---|
| `read_can_frames` | tool | Raw frames from the last `duration_s` seconds. Returns instantly (served from a continuously-running history buffer, not a fresh listen window). |
| `decode_can_frame` | tool | Decode one frame's bytes into named signals. |
| `filter_frames` | tool | Like `read_can_frames`, filtered by arbitration ID and/or signal. |
| `monitor_signal` | tool | Timestamped samples of one decoded signal, from the same history buffer. |
| `get_vehicle_snapshot` | tool | Last known value of every signal seen so far, one entry per signal (not per frame) with an `age_s` freshness indicator: a single-call overview instead of decoding a frame stream yourself. |
| `send_obd_request` | tool | Standard OBD-II (SAE J1979) request; decodes known PIDs (coolant temp, speed, fuel level, fuel type). |
| `send_diagnostic_request` | tool | UDS-style diagnostic request (`vehicle.dbc`'s `DIAGNOSTIC_REQUEST`); collects every ECU's response. |
| `activate_fault_scenario` | tool | Activate (or clear) a named fault-injection preset (`overheat`, `abs_fault`, `low_fuel`) in the running simulator; see below. |
| `decode_j1939_frame` | tool | Decompose a 29-bit J1939 ID (priority / PGN / source + destination address) and decode known SPNs from the payload. |
| `list_j1939_pgns` | tool | The J1939 PGN/SPN catalog this server can decode and request (bit layout, scaling, units). |
| `request_j1939_pgn` | tool | Send a J1939 Request PGN (`0xEA00`) and return the decoded responses (needs a simulator on this process's bus). |
| `read_j1939_dtcs` | tool | Most recent J1939 DM1 broadcast: lamp status plus every active SPN/FMI. Served from the frame history buffer. |
| `dbc_info` | resource (`file://vehicle.dbc`) | Full DBC dump: nodes, messages, signals. |

`read_can_frames`/`filter_frames`/`monitor_signal`/`read_j1939_dtcs` are served from a single continuously-running history buffer (`server/live_state.py`) rather than each opening its own bus listener: they return immediately and won't miss frames sent between calls. `send_obd_request`/`send_diagnostic_request`/`request_j1939_pgn` are request/response and still wait live for a reply. In both cases, `duration_s`/`timeout_s` is capped by `MCP_CAN_MAX_DURATION_S` (default 30s; the history buffer retains at least that much, or 60s, whichever is larger). All tools return typed, structured content (see `server/schemas.py`) rather than ad-hoc JSON.

### 🩺 About the diagnostic responder
`vehicle.dbc` defines a UDS-like diagnostic schema: `DIAGNOSTIC_REQUEST` (one shared request frame) and four `DIAGNOSTIC_RESPONSE_<ECU>` messages, one per ECU, but the request has no per-ECU target field. The simulator treats every request as functionally addressed to *all four* ECUs, so `send_diagnostic_request`/`diag-request` may return more than one response. Supported services: `START_DIAGNOSTIC_SESSION` (0x10) and `RESET_ECU` (0x11) are acknowledged OK; `READ_DATA_BY_ID` (0x22) returns a deterministic canned value derived from the parameter ID; `ROUTINE_CONTROL`/`READ_MEMORY`/`WRITE_MEMORY` and anything unrecognized return `SERVICE_NOT_SUPPORTED`; see `diagnostics.py::handle_service`.

### ⚠️ Fault injection
Three named scenarios (`simulator/faults.py::PRESETS`) let you force the simulator into a specific fault state instead of waiting on random signal generation:
- `overheat` – `ENGINE_TEMP` pinned to its hottest reportable value, `SYSTEM_STATUS` set to `FAULT_PRESENT`, DTC `P0217` (Engine Overtemp Condition).
- `abs_fault` – all four `WHEEL_SPEED_*` signals stuck at zero, `SYSTEM_STATUS` set to `FAULT_PRESENT`, DTC `C0035` (Left Front Wheel Speed Sensor Circuit).
- `low_fuel` – `FUEL_LEVEL` pinned critically low; no DTC (a low-fuel light isn't a stored trouble code on a real vehicle either).

Activating a scenario sends a small control frame on the bus (like OBD/diagnostic requests, this is a round trip to whichever process is running the simulator, so it needs `mcp-can demo`/`simulate` already running) and overrides the named signals until cleared. Any DTCs the active scenario sets show up in `send_obd_request`/`obd-request`'s Mode 03 (service=3) response. Use `mcp-can fault list` or the `activate_fault_scenario` tool's docstring to see the current preset descriptions; pass `preset=None` (CLI: `clear`) to deactivate.

### 🚛 SAE J1939 (heavy-duty)
Alongside the light-vehicle 11-bit bus, the simulator also speaks **SAE J1939** — the protocol on trucks, buses and off-highway equipment. J1939 rides 29-bit *extended* CAN IDs whose arbitration field is itself structured data: a 3-bit priority, an 18-bit Parameter Group Number (PGN), and an 8-bit source address (plus, for peer-to-peer "PDU1" PGNs, a destination address). `src/mcp_can/j1939.py` is a self-contained implementation of that layer (not DBC-driven — `vehicle.dbc` models an 11-bit light-vehicle bus).

What's simulated (`simulator/j1939_runner.py`), driven by the same correlated driving-dynamics state as the 11-bit signals:

| PGN | Acronym | Contents |
|---|---|---|
| `0xF004` | EEC1 | Engine speed (SPN 190), actual engine percent torque (SPN 513) |
| `0xF003` | EEC2 | Accelerator pedal position (SPN 91), percent load (SPN 92) |
| `0xFEEE` | ET1 | Engine coolant temperature (SPN 110), fuel temperature (SPN 174) |
| `0xFEF1` | CCVS1 | Wheel-based vehicle speed (SPN 84) |
| `0xFEF2` | LFE1 | Engine fuel rate (SPN 183), throttle valve position (SPN 51) |
| `0xFEFC` | DD1 | Fuel level (SPN 96) |
| `0xFECA` | DM1 | Active diagnostic trouble codes (SPN + FMI), broadcast at 1 Hz |

- **Request PGN (`0xEA00`):** `request_j1939_pgn` / `mcp-can j1939-request <pgn>` send a request; the simulator re-broadcasts the requested PGN once.
- **DM1 / DTCs:** `read_j1939_dtcs` / `mcp-can j1939-dtcs` read the latest DM1. The fault-injection presets map to J1939 DTCs too — `overheat` → SPN 110 FMI 0, `abs_fault` → SPN 84 FMI 5, `low_fuel` → SPN 96 FMI 18 — and the malfunction-indicator lamp turns on while a preset is active.
- J1939 signals also appear in `get_vehicle_snapshot` and the dashboard, grouped under `J1939:<acronym>`.
- Set `MCP_CAN_J1939_ENABLED=false` for an 11-bit-only bus.

## 🔍 MCP Inspector (GUI for your tools)
Use the official Inspector to explore and call your MCP tools without writing a host:
```bash
npx @modelcontextprotocol/inspector
```
When prompted, connect to your server:
- URL: `http://localhost:6278/sse`

You can then list tools/resources and call one (e.g. monitor `ENGINE_SPEED` for 5 seconds) and view structured output live.

## 🤖 Using with Ollama (local LLM)
Ollama runs the model but can't connect to MCP servers on its own, so you need a small client in between. [`ollmcp`](https://github.com/jonigl/mcp-client-for-ollama) is the quickest option.

1. Pull a model that supports **tool calling**, e.g. `ollama pull qwen3` (`llama3.1` and `gemma4` also work). To check a model, run `ollama show <model>` and look for `tools` under *Capabilities*. Models without it (e.g. the original `llama3`) can chat but can't call the CAN tools.
2. Terminal A: start the simulator and server:
   ```bash
   mcp-can demo
   ```
3. Terminal B: connect Ollama to it:
   ```bash
   pip install ollmcp
   ollmcp -u http://localhost:6278/sse -m qwen3
   ```
   `ollmcp` should list the 12 MCP-CAN tools on startup.
4. Type questions into the `ollmcp` chat. It's a conversation with the model, not a shell, so don't type commands there.
   - "What's the engine speed and coolant temperature right now?"
   - "Read the OBD-II trouble codes."
   - "Activate the overheat fault, then read the J1939 DTCs."
   - "List the J1939 PGNs you can request."

Tips:
- `ollmcp` asks before every tool call. Answer `s` to allow tool calls for the rest of the session.
- Watch the same signals live at `http://localhost:6278` while you chat.
- Small models sometimes pick a roundabout tool. If an answer looks off, name the tool: "use get_vehicle_snapshot". Tools that take IDs (PGNs, CAN IDs, OBD PIDs, UDS services) accept hex strings like `"0xF004"` and J1939 acronyms like `"EEC1"`, so models don't have to convert hex to decimal (a common source of wrong requests).
- Other MCP hosts work too: [Open WebUI](https://docs.openwebui.com/) can use Ollama models with MCP tools, and VS Code, Cursor, Windsurf and Claude Desktop can connect to `http://localhost:6278/sse` directly, using their own models.

## ⌨️ CLI Reference
- `mcp-can simulate` – start ECU simulator using the configured DBC (bundled `vehicle.dbc` by default).
- `mcp-can server [--port 6278] [--transport sse|streamable-http|stdio]` – run the MCP server.
- `mcp-can demo [--port] [--transport]` – simulator + server in one process.
- `mcp-can frames --seconds 1.0` – capture raw frames as JSON.
- `mcp-can decode <id> <data> [--json]` – decode a single frame (table by default; `id` hex/decimal, `data` space/comma-separated bytes).
- `mcp-can snapshot --seconds 1.0 [--json]` – latest value of every signal seen while listening.
- `mcp-can dbc-info [message]` – table of every message/signal in the DBC, or just one message's.
- `mcp-can monitor <signal> --seconds 2.0 [--json]` – watch one signal (live output by default).
- `mcp-can obd-request --service <hex|int> [--pid <hex|int>]` – OBD-II request; response includes a decoded value for known PIDs.
- `mcp-can diag-request --service-id <hex|int> [--parameter-id] [--data-field]` – UDS-style diagnostic request; prints every ECU's response.
- `mcp-can fault <preset|clear|list>` – activate/clear a fault-injection scenario in a running simulator, or list available presets.
- `mcp-can j1939-decode <id> <data> [--json]` – decompose a 29-bit J1939 ID and decode known SPNs.
- `mcp-can j1939-pgns` – list the J1939 PGNs/SPNs this project can decode.
- `mcp-can j1939-request <pgn> [--timeout 2.0]` – send a J1939 Request PGN (`0xEA00`) and print decoded responses; `pgn` can be an acronym (`EEC1`), hex (`0xF004`) or decimal.
- `mcp-can j1939-dtcs [--seconds 3.0]` – listen for a J1939 DM1 broadcast and print its active trouble codes.

`server`/`demo`/`simulate` all print colorized logs (via `rich`) instead of raw text.

## ⚙️ Configuration
Env vars (prefix `MCP_CAN_`):
- `CAN_INTERFACE` (default `virtual`)
- `CAN_CHANNEL` (default `bus0`)
- `DBC_PATH` (default: the `vehicle.dbc` bundled with the package)
- `MCP_PORT` (default `6278`)
- `MCP_TRANSPORT` (default `sse`; `streamable-http` requires a newer `mcp` SDK; the server logs a clear error and exits if the installed version doesn't support it, rather than crashing on an SDK traceback)
- `MAX_DURATION_S` (default `30.0`) – caps every tool's `duration_s`/`timeout_s`
- `J1939_ENABLED` (default `true`) – run the SAE J1939 side of the simulator alongside the 11-bit signals
- `LOG_LEVEL` (default `INFO`)
- `CORS_ALLOW_ORIGINS` (default `["*"]`, JSON array e.g. `["https://your-host.example"]`) – allowed browser origins for the SSE endpoint. Credentialed requests (`allow_credentials`) are only enabled once this is narrowed to specific origins; wildcard + credentials is a combination browsers reject outright, so it's never turned on for the default `"*"`. Override before any real deployment.

You can also set these in a `.env` file in the working directory.

## 🐳 Docker
Build:
```bash
docker build -t mcp-can .
```
Run (combined server + simulator):
```bash
docker run -d --name mcp-can -p 6278:6278 -p 5000:5000 -p 8080:8080 mcp-can
```
Compose (from `docker/`):
```bash
docker compose up -d --build
```
> The compose file currently runs `server` and `simulator` as separate containers; like running them as two separate local processes, they won't share the virtual CAN bus unless the host provides a real shared `vcan0` interface. For a working combined setup today, use the single-container Dockerfile above (`mcp-can demo`).

## 🧪 Development & Testing
See `CONTRIBUTING.md` for the full guide. Quick version:
```bash
pip install -e ".[dev]"

ruff check .
mypy src
pytest -q
```

## 🔧 Troubleshooting
- No frames? Ensure both simulator and server use the same interface/channel (`virtual`/`bus0` by default), and, on Windows, that they're the same process (`mcp-can demo`) rather than two separate ones.
- DBC missing? Unset `MCP_CAN_DBC_PATH` to fall back to the bundled sample, or point it at an existing `.dbc` file.
- Docker networking: expose `6278` so your MCP host can reach it.
- `streamable-http` transport fails immediately? Your installed `mcp` package predates its support; the log line tells you. Switch to `sse` or `pip install -U mcp` (staying below `2.0.0`).

## 📄 License
MIT (see `LICENSE`). Educational/prototyping use only; use certified hardware for real automotive work.
