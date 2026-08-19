# MCP-CAN: Virtual CAN + MCP Server

An MCP server purpose-built to surface vehicle CAN/OBD data to an LLM/SLM. It simulates ECUs on a virtual CAN bus, decodes via a DBC, and exposes MCP tools over SSE—no hardware required by default.

---

## Highlights
- MCP server for CAN/OBD → LLM/SLM (tools + DBC metadata over SSE).
- Virtual CAN backend (python-can) out of the box; optional SocketCAN/vCAN on Linux.
- DBC-driven encoding/decoding via `cantools`.
- ECU simulator that streams multiple messages plus demo OBD-II responses.
- MCP server (SSE) exposing tools for frames, filtering, monitoring, and DBC info.
- Typer CLI: `mcp-can` (simulate, server, frames, decode, monitor, obd-request).
- Dockerfile + docker compose for server + simulator.
- Unit tests, type hints, lint config (ruff, mypy).

## Repository Layout
- `src/mcp_can/`
  - `cli.py` – Typer commands
  - `bus.py` – python-can helpers
  - `dbc.py` – DBC loading/decoding
  - `config.py` – env settings (`MCP_CAN_*`)
  - `models.py` – simple dataclasses
  - `simulator/runner.py` – ECU simulator + OBD responder
  - `server/fastmcp_server.py` – MCP tools (SSE)
  - `obd.py` – minimal OBD-II request/response helpers
- `vehicle.dbc` – sample CAN database
- `simulate-ecus.py`, `can-mcp.py` – entrypoints
- `docker/compose.yml`, `Dockerfile`
- `tests/` – unit tests

## Prerequisites
- Python 3.10+
- (Optional) Docker / Docker Compose
- (Optional) Ollama if you want a local LLM backend

## Install (Python)
From repo root:
```bash
pip install -r requirements.txt
pip install -e .
```

## Quickstart (Simulator + MCP Server)
Two terminals:
```bash
# Terminal A: start ECU simulator on virtual bus0
mcp-can simulate

# Terminal B: start MCP server (SSE on 6278)
mcp-can server --port 6278
```

Single-process (helps on Windows if virtual backend doesn’t share across processes):
```bash
mcp-can demo --port 6278
```

Sample interactions:
```bash
mcp-can frames --seconds 2
mcp-can decode 0x100 "01 02 03 04 05 06 07 08"
mcp-can monitor ENGINE_SPEED --seconds 3
mcp-can obd-request --service 0x01 --pid 0x0D
```

## MCP Inspector (GUI for your tools)
Use the official Inspector to explore and call your MCP tools without writing a host:
```bash
npx @modelcontextprotocol/inspector
```
When prompted, connect to your server:
- URL: `http://localhost:6278/sse`

You can then:
- List tools and resources (`read_can_frames`, `decode_can_frame`, `filter_frames`, `monitor_signal`, `dbc_info`).
- Call a tool (e.g., monitor `ENGINE_SPEED` for 5 seconds) and view JSON output live.

## Using with Ollama (local LLM)
1) Ensure Ollama is running: `ollama serve` and pull a model: `ollama pull llama3`
2) Run simulator + MCP server (see Quickstart).
3) Point your MCP-capable host at `http://localhost:6278/sse` and configure its model endpoint to `http://localhost:11434` with your model name (e.g., `llama3`).
4) Prompt the host: “Monitor ENGINE_SPEED for 5 seconds” or “List all DBC messages.”

If you need a minimal host, pair `@modelcontextprotocol/sdk` with Ollama (see SDK docs) or use Inspector for manual tool calls.

Example host config (OpenAI-compatible endpoint to local Ollama):
```json
{
  "model": {
    "type": "openai-compatible",
    "baseUrl": "http://localhost:11434/v1",
    "model": "llama3"
  },
  "mcpServers": {
    "can-mcp-server": {
      "serverUrl": "http://localhost:6278/sse"
    }
  }
}
```

## CLI Reference
- `mcp-can simulate` – start ECU simulator using `vehicle.dbc`.
- `mcp-can server [--port 6278]` – run MCP SSE server.
- `mcp-can frames --seconds 1.0` – capture raw frames as JSON.
- `mcp-can decode <id> <data>` – decode a single frame (`id` hex/decimal, `data` space/comma-separated bytes).
- `mcp-can monitor <signal> --seconds 2.0` – watch one signal.
- `mcp-can obd-request --service <hex|int> [--pid <hex|int>]` – demo OBD-II request.

## Configuration
Env vars (prefix `MCP_CAN_`):
- `CAN_INTERFACE` (default `virtual`)
- `CAN_CHANNEL` (default `bus0`)
- `DBC_PATH` (default `vehicle.dbc`)
- `MCP_PORT` (default `6278`)

You can set these in a `.env` file at repo root.

## Docker
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

## Development & Testing
```bash
pip install -r requirements.txt
pip install -e .
pip install pytest ruff mypy

ruff check .
mypy src
pytest -q
```

## Troubleshooting
- No frames? Ensure both simulator and server use the same interface/channel (`virtual`/`bus0` by default).
- DBC missing? Set `MCP_CAN_DBC_PATH` or place `vehicle.dbc` in repo root.
- Docker networking: expose `6278` so your MCP host can reach SSE.

## License
MIT (see `LICENSE`). Educational/prototyping use only—use certified hardware for real automotive work.
