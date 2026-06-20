---
title: Getting Started
description: Install and run Tool Compass.
sidebar:
  order: 1
---

## The problem

MCP servers expose dozens or hundreds of tools. Loading all tool definitions into context wastes tokens and slows down responses.

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

## Option 1: Install from PyPI (v2.2+)

```bash
# Prerequisites: Ollama with nomic-embed-text
ollama pull nomic-embed-text

# Install the CLI + gateway
pip install tool-compass

# Scaffold a config + print MCP-client setup (first-run onboarding)
tool-compass init

# Edit backends in the printed config path, then build the index
tool-compass sync

# Start the MCP server (or `tool-compass serve`)
tool-compass
```

`tool-compass init` writes a `compass_config.json` to your platform config
directory (see [Configuration](/tool-compass/handbook/configuration/) for the
exact path), refuses to clobber an existing one unless you pass `--force`, and
prints a ready-to-paste Claude Desktop snippet. Jump to
[Register with your MCP client](#register-with-your-mcp-client) for Cursor and
Cline recipes too.

`tool-compass` with no arguments starts the MCP server — same as the
pre-2.2 `python gateway.py` entry point. New subcommands are available:

```bash
tool-compass search "generate an AI image" --top 3 --json
tool-compass describe comfy:comfy_generate
tool-compass sync --force
tool-compass doctor              # diagnostic dump (config, Ollama probe, DB stats)
```

## Option 1b: Clone from source

```bash
# Prerequisites: Ollama with nomic-embed-text
ollama pull nomic-embed-text

# Clone and setup
git clone https://github.com/mcp-tool-shop-org/tool-compass.git
cd tool-compass

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies (editable — gives you the `tool-compass` CLI too)
pip install -e .[all]

# Build the search index and start the MCP server
tool-compass sync
tool-compass
```

## Option 2: Docker

```bash
git clone https://github.com/mcp-tool-shop-org/tool-compass.git
cd tool-compass

# Start with Docker Compose (requires Ollama running locally)
docker-compose up

# Or include Ollama in the stack
docker-compose --profile with-ollama up

# Access the UI at http://localhost:7860
```

## CLI reference

`tool-compass` exposes both the MCP server and a set of one-shot subcommands.

| Subcommand | Purpose |
|------------|---------|
| `tool-compass init [--force] [--json]` | Scaffold `compass_config.json` + print MCP-client setup |
| `tool-compass` (no args) | Start the MCP server — same as `serve` |
| `tool-compass serve [--http]` | Start the MCP server explicitly |
| `tool-compass search <intent> [--top N] [--json]` | One-shot semantic search |
| `tool-compass describe <tool> [--json]` | Print a tool's schema and examples |
| `tool-compass sync [--force]` | Rebuild the HNSW index from configured backends |
| `tool-compass doctor` | Diagnostic dump: version, config (secrets redacted), index path + size, analytics schema version, Ollama reachability |

The underlying `gateway.py` also accepts admin flags for backward compat:

| Flag | Description |
|------|-------------|
| `--sync` | Same as `tool-compass sync` |
| `--test` | Run semantic search tests to verify index quality |
| `--config` | Display current configuration |
| `--verbose` / `-v` | Enable DEBUG-level output |

## Register with your MCP client

Tool Compass speaks MCP over stdio, so any MCP-capable client can launch it.
Each recipe below registers a server named `tool-compass` that runs
`tool-compass serve`. `tool-compass init` prints the Claude Desktop block for
you; the Cursor and Cline forms are the same shape.

Two invocation styles work everywhere:

- **npx** (`npx -y @mcptoolshop/tool-compass serve`) — zero-prerequisite, no
  Python toolchain needed. Binaries are SHA256-verified and cached on first run.
- **pip / CLI** (`tool-compass serve`) — if you installed via `pip install
  tool-compass`, the `tool-compass` console script is already on your `PATH`.

Keep secrets out of these blocks — backends and any tokens belong in
`compass_config.json`, never in your client config.

### Claude Desktop

Edit `claude_desktop_config.json` (macOS:
`~/Library/Application Support/Claude/claude_desktop_config.json`; Windows:
`%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "tool-compass": {
      "command": "npx",
      "args": ["-y", "@mcptoolshop/tool-compass", "serve"]
    }
  }
}
```

pip / CLI form (after `pip install tool-compass`):

```json
{
  "mcpServers": {
    "tool-compass": {
      "command": "tool-compass",
      "args": ["serve"]
    }
  }
}
```

Restart Claude Desktop, then look for the tools icon — `compass` and its
sibling tools should be listed.

### Cursor

Cursor reads `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (per-project).
The schema is the same `mcpServers` map:

```json
{
  "mcpServers": {
    "tool-compass": {
      "command": "npx",
      "args": ["-y", "@mcptoolshop/tool-compass", "serve"]
    }
  }
}
```

pip / CLI form:

```json
{
  "mcpServers": {
    "tool-compass": {
      "command": "tool-compass",
      "args": ["serve"]
    }
  }
}
```

Open **Cursor Settings → MCP** to confirm the server connected.

### Cline (VS Code)

Cline stores its MCP servers in `cline_mcp_settings.json` (open it via the
Cline panel → **MCP Servers → Configure**). Same `mcpServers` shape, with
Cline's optional `disabled` / `autoApprove` fields:

```json
{
  "mcpServers": {
    "tool-compass": {
      "command": "npx",
      "args": ["-y", "@mcptoolshop/tool-compass", "serve"],
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

pip / CLI form:

```json
{
  "mcpServers": {
    "tool-compass": {
      "command": "tool-compass",
      "args": ["serve"],
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

Before connecting from any client, run `tool-compass sync` once so the search
index exists — otherwise `compass` queries return a "run sync first" hint.

## HTTP mode

Set `PORT` to switch from stdio to streamable-http transport. By default
the server binds to `127.0.0.1` (loopback only) — set `HOST=0.0.0.0`
**only behind an authenticated reverse proxy**:

```bash
PORT=8080 tool-compass             # stdio → streamable-http on 127.0.0.1:8080
PORT=8080 HOST=0.0.0.0 tool-compass # exposed on all interfaces (see warnings)
```

HTTP mode adds three routes: `/health` (liveness), `/ready` (deep probe),
and `/metrics` (Prometheus). See [Operations](/tool-compass/handbook/operations/)
for details.

## Fast local loop

If you've cloned the repo and just want to iterate, the Makefile has two
one-shot targets that install + run in a single command:

```bash
make dev        # Install + start gateway in HTTP mode (PORT=8000)
make dev-ui     # Install + launch the Gradio UI
```

`make dev` warns (but doesn't hard-fail) if Ollama isn't reachable at
`http://localhost:11434` — start it with `ollama serve` when you need
real embedding queries.

## Gradio UI

Tool Compass includes a Gradio web interface for interactive exploration. Install the UI extra first:

```bash
pip install "tool-compass[ui]"

# Launch on default port 7860 (binds to 127.0.0.1)
tool-compass ui

# Custom port
tool-compass ui --port 7861
```

(The original `tool-compass-ui` console script is still installed and works
identically — `tool-compass ui` is just the subcommand alias added in Wave-11
so the CLI surface matches the README.)

### Public share links require GRADIO_AUTH

`--share` creates a public Gradio tunnel that anyone with the URL can reach. Tool Compass requires basic-auth credentials before it will start in shared mode — pass `--auth user:pass` to the subcommand (or export `GRADIO_AUTH="user:pass"` directly), or the launcher exits with code 2:

```bash
# Inline auth — sets GRADIO_AUTH for you
tool-compass ui --share --auth user:secret

# Equivalent: export the env var first
export GRADIO_AUTH="user:secret"
tool-compass ui --share
```

Without `GRADIO_AUTH` set (or `--auth` passed), `--share` is refused.

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Skip integration tests (no Ollama required)
pytest -m "not integration"
```
