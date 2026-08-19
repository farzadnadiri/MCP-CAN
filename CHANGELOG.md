# Changelog

All notable changes to this project are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
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
- `requires-python` corrected from `>=3.8` to `>=3.10` (the code already
  used `X | None` union syntax that only works natively on 3.10+).
- Removed redundant `mcp-can-server`/`mcp-can-sim` console-script entries —
  `mcp-can server`/`mcp-can simulate` are the one canonical entrypoint.
- Removed dead code (`models.FrameView`/`frame_to_view`, unused since
  introduction).
