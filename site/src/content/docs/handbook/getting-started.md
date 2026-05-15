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

# Build the search index from your configured backends
tool-compass sync

# Start the MCP server (or `tool-compass serve`)
tool-compass
```

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
tool-compass-ui

# Custom port
tool-compass-ui --port 7861
```

### Public share links require GRADIO_AUTH

`--share` creates a public Gradio tunnel that anyone with the URL can reach. Tool Compass requires basic-auth credentials before it will start in shared mode — set `GRADIO_AUTH="user:pass"` in your environment, or the launcher exits with code 2:

```bash
export GRADIO_AUTH="user:secret"
tool-compass-ui --share
```

Without `GRADIO_AUTH` set, `--share` is refused.

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Skip integration tests (no Ollama required)
pytest -m "not integration"
```
