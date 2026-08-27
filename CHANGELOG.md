# Changelog

All notable changes to this project are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **SAE J1939 support** (heavy-duty / 29-bit extended IDs), alongside the
  existing 11-bit light-vehicle bus:
  - `src/mcp_can/j1939.py` — self-contained protocol logic (not DBC-driven):
    29-bit ID decomposition (priority / PGN / source + destination address,
    PDU1 vs PDU2), a curated PGN/SPN catalog (EEC1, EEC2, ET1, CCVS1, LFE1,
    DD1) with encode/decode, J1939-73 DM1 diagnostic trouble codes
    (SPN/FMI/OC/CM pack + lamp status), and the Request PGN (`0xEA00`) helper.
  - `src/mcp_can/simulator/j1939_runner.py` — J1939 simulator threads:
    periodic PGN broadcasters driven by the same `VehicleState` as the 11-bit
    signals, a Request PGN responder, and a 1 Hz DM1 emitter. Fault-injection
    presets map to J1939 DTCs (`overheat` → SPN 110 FMI 0, `abs_fault` → SPN
    84 FMI 5, `low_fuel` → SPN 96 FMI 18) and drive the MIL lamp.
  - Four MCP tools: `decode_j1939_frame`, `list_j1939_pgns`,
    `request_j1939_pgn`, `read_j1939_dtcs`, plus matching CLI commands
    `mcp-can j1939-decode|j1939-pgns|j1939-request|j1939-dtcs`.
  - `live_state.py` now also decodes J1939 (29-bit) frames, so J1939 signals
    show up in `get_vehicle_snapshot` and the dashboard under
    `J1939:<acronym>`.
  - `MCP_CAN_J1939_ENABLED` setting (default `true`) to turn the J1939 side
    of the simulator off.
- `Settings.cors_allow_origins` (default `["*"]`, override via
  `MCP_CAN_CORS_ALLOW_ORIGINS`) so the SSE endpoint's CORS origins are
  configurable instead of hardcoded.
- Fault injection (`simulator/faults.py`): three named scenario presets
  (`overheat`, `abs_fault`, `low_fuel`) that force specific signals to
  fault-condition values and, where applicable, populate a matching DTC
  (`P0217`, `C0035`) visible in `send_obd_request`'s Mode 03 response.
  Activated via the new `activate_fault_scenario` MCP tool or `mcp-can
  fault <preset|clear|list>` CLI command; both round-trip a small control
  frame to the simulator process, the same pattern already used by
  OBD/diagnostic requests. `obd.py` gained `encode_dtc`/`decode_dtc`
  (J2012-style 2-byte DTC wire format) and `decode_response` (dispatches
  Mode 03 responses to DTC decoding instead of `decode_pid_value`, which
  only handles PID'd responses).
- Correlated, plausible signal generation (`simulator/state.py`): a
  background `VehicleState` ticks a small set of driving-dynamics variables
  (throttle, RPM, speed, engine temp, fuel level) with realistic lag and
  relationships between them, instead of `SimThread` drawing every signal
  independently at random. `ENGINE_SPEED`/`ENGINE_LOAD` now track throttle,
  `WHEEL_SPEED_*` tracks a common vehicle speed with small per-wheel jitter,
  `FUEL_LEVEL` only decreases, `ENGINE_TEMP` warms toward operating
  temperature over time (capped at 87.5, the actual ceiling its 8-bit width
  can encode -- see `ENGINE_TEMP_MAX_C` -- rather than the DBC's declared
  but unencodable 127.5 max). Signals with no correlation rule (doors,
  seatbelts, fault flags, etc.) keep the previous independent-random
  behavior. `SimThread` also gained a general clamp-to-encodable-range step
  for correlated/fault-overridden signal values, so a value outside what a
  signal's bit width can hold gets saturated instead of raising out of
  `Message.encode` and silently dropping that frame.
- `get_vehicle_snapshot` MCP tool (plus `mcp-can snapshot` CLI command):
  the last known value of every signal seen so far, one entry per signal
  with an `age_s` freshness indicator, instead of decoding a stream of raw
  frames yourself. Built on top of the frame history buffer's signal
  tracking (`live_state.py`), so it's effectively free given that already
  existed for the dashboard.
- Read-only live web dashboard at `/dashboard` (`server/live_state.py` +
  `server/templates/dashboard.html`): signal values grouped by ECU message
  and a recent-frames feed, updated over Server-Sent Events. Self-contained
  single page, no build step or external assets.
- UDS-style diagnostic responder (`DiagnosticResponderThread`) implementing
  the `DIAGNOSTIC_REQUEST`/`DIAGNOSTIC_RESPONSE_*` messages `vehicle.dbc`
  already defined but nothing previously answered.
- Two new MCP tools: `send_obd_request` and `send_diagnostic_request`,
  exposing OBD-II and the new diagnostic protocol to LLM clients (previously
  OBD-II was CLI-only).
- Matching CLI commands: `mcp-can diag-request`, plus a decoded-value field
  added to `mcp-can obd-request`'s output.
- `mcp-can dbc-info` command — pretty-printed table of a DBC's
  messages/signals, for discovery without reading the full JSON resource.
- `--json` flag on `decode`/`monitor` (default output is now a Rich table);
  `--transport` flag on `server`/`demo`.
- Structured MCP tool output: all tools now return typed Pydantic models
  (`server/schemas.py`) instead of ad-hoc dicts.
- Optional `streamable-http` transport (`MCP_CAN_MCP_TRANSPORT`), alongside
  the existing `sse`. Falls back with a clear error, rather than a raw SDK
  traceback, if the installed `mcp` version doesn't support it.
- `max_duration_s` setting (default 30s) capping every tool's
  `duration_s`/`timeout_s`, so a client can't tie up a listener indefinitely.
- Colorized, leveled logging via `rich.logging.RichHandler` in place of bare
  `print()` calls throughout the simulator and server.
- `/healthz` endpoint.
- `CONTRIBUTING.md`.

### Fixed
- Dashboard values with a `scale`/`offset` (e.g. `58 * 0.4`) could display
  IEEE-754 noise like `23.200000000000003`; `live_state.py` now rounds
  float values for display.
- **Diagnostic/OBD responder message theft**: two threads calling `.recv()`
  on the *same* `python-can` `Bus` instance silently split incoming messages
  between them instead of each seeing every message — the diagnostic
  responder would work or not depending on which thread happened to dequeue
  a given frame first. Each listener thread now gets its own bus instance.
- `int()` on a choice-decoded signal (e.g. `SERVICE_ID`, `RESPONSE_CODE`,
  which `cantools` decodes to a `NamedSignalValue` for known enum values)
  raised `TypeError`; added `dbc.signal_int()` to unwrap it consistently.
- `mcp>=1.7.0` had no upper bound, allowing `pip install` to resolve the
  breaking `mcp` 2.0 line, which removed the `fastmcp` API this project is
  built on; pinned `<2.0.0`.
- CORS `sse_app` monkey-patch crashed on newer `mcp` SDK versions that pass
  a `mount_path` argument the patch didn't accept.

### Changed
- CORS no longer sends `allow_credentials=True` unconditionally: it's now
  tied to `Settings.cors_allow_origins` and only enabled once that's
  narrowed away from the default `"*"`, since browsers reject the
  wildcard-origin + credentials combination outright anyway.
- `requires-python` corrected from `>=3.8` to `>=3.10` (the code already
  used `X | None` union syntax that only works natively on 3.10+).
- Removed redundant `mcp-can-server`/`mcp-can-sim` console-script entries —
  `mcp-can server`/`mcp-can simulate` are the one canonical entrypoint.
- Removed dead code (`models.FrameView`/`frame_to_view`, unused since
  introduction).
- `read_can_frames`, `filter_frames`, `monitor_signal` no longer open a
  fresh bus listener per call (each racing the risk of missing frames sent
  between calls, or being stolen by a competing listener on a shared bus
  instance). They now read from `live_state.py`'s continuously-running
  frame history buffer — same background listener that backs the
  dashboard — so they return near-instantly instead of blocking for
  `duration_s`, and no longer accept a `ctx` progress-reporting parameter
  (there's no longer a live poll loop to report progress on).
