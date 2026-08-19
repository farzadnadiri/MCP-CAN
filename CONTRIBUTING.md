# Contributing to MCP-CAN

Thanks for taking a look. This project is intentionally small and educational —
keep contributions in that spirit: prefer clarity over cleverness, and reuse
the existing patterns (see `src/mcp_can/`'s layout) rather than introducing
new ones for a one-off feature.

## Local setup

```bash
python -m venv .venv
.venv/Scripts/activate   # or `source .venv/bin/activate` on Linux/macOS
pip install -r requirements.txt
pip install -e .
pip install pytest ruff mypy
```

Windows note: if your checkout lives under a cloud-synced folder (OneDrive,
Dropbox, etc.) and `pip install -e .` or `git` commands fail with odd
`FileNotFoundError`/`Permission denied` errors on file creation, that's the
sync client interfering with the filesystem — try pausing sync for that
folder or working from a local (non-synced) path.

## Before opening a PR

```bash
ruff check .
mypy src
pytest -q
```

All three must pass — this mirrors `.github/workflows/ci.yml` exactly
(Python 3.10 and 3.11). If you add a new module, keep `mypy`'s zero-error bar:
this codebase deliberately keeps `strict`-ish settings clean rather than
suppressing errors with blanket `# type: ignore`s.

For a live sanity check beyond the test suite, run the actual server and
call a tool through a real MCP client:

```bash
mcp-can demo --port 6278
```

then, in another shell, use the MCP Inspector (`npx @modelcontextprotocol/inspector`,
connect to `http://localhost:6278/sse`) or a small script with
`mcp.client.sse.sse_client` / `ClientSession` to call a tool end-to-end.
Unit tests mock the CAN bus (see `tests/test_cli.py`'s `FakeBus`); nothing in
the suite starts a real server or virtual bus, so this manual pass is the
only thing that catches wiring/transport-level regressions.

## Code layout

- `src/mcp_can/bus.py`, `dbc.py`, `obd.py`, `diagnostics.py` — protocol/bus
  logic, no MCP or CLI awareness. New protocol behavior belongs here, not in
  `server/` or `cli.py`.
- `src/mcp_can/server/fastmcp_server.py` — MCP tool/resource definitions;
  `server/schemas.py` — the Pydantic models those tools return.
- `src/mcp_can/simulator/runner.py` — the ECU simulator threads
  (`SimThread`, `OBDResponderThread`, `DiagnosticResponderThread`). Each
  bus *listener* thread needs its **own** `make_bus(...)` instance — a
  single `python-can` `Bus` instance's `recv()` queue is consumed once per
  message, so two threads sharing one instance will silently steal frames
  from each other instead of each seeing every frame. (This was a real bug
  caught while adding the diagnostic responder — see `run_simulator()`'s
  comment.)
- `src/mcp_can/cli.py` — the `mcp-can` Typer CLI; mirrors the MCP tool
  surface where practical so both interfaces stay in sync.

## Adding a new MCP tool

1. Add the protocol logic (encode/decode/whatever) to a plain module first —
   testable without any bus or MCP machinery.
2. Add a Pydantic return model to `server/schemas.py`.
3. Register the tool in `server/fastmcp_server.py::create_app()`, following
   the existing tools' shape (open a bus with `make_bus()`, always
   `shutdown_bus()` in a `finally`, cap any `duration_s`/`timeout_s` against
   `settings.max_duration_s`).
4. If the CLI should expose the same capability, mirror it as a Typer
   command in `cli.py`.
5. Add a test: pure-logic tests belong next to the module they test (see
   `tests/test_diagnostics.py`, `tests/test_obd.py`); if the tool touches
   the bus, prefer a `FakeBus`-style unit test (see `tests/test_cli.py`)
   over spinning up a real server in the suite.

## Releasing to PyPI

`.github/workflows/release.yml` builds and publishes on any `v*.*.*` tag
push, via `pypa/gh-action-pypi-publish`. As of this writing that workflow
has never been triggered (no tags/releases exist yet, and the package isn't
on PyPI) — before using it for the first time, confirm a `PYPI_API_TOKEN`
repository secret is configured, then:

```bash
git tag v0.1.0
git push origin v0.1.0
```

## Reporting issues

Open a GitHub issue. Include your OS, Python version, and — if it's a CAN/MCP
issue — whether you're using the virtual backend or real hardware
(`MCP_CAN_CAN_INTERFACE`).
