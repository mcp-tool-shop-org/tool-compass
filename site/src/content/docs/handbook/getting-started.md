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

## Option 1: Local installation

```bash
# Prerequisites: Ollama with nomic-embed-text
ollama pull nomic-embed-text

# Clone and setup
git clone https://github.com/mcp-tool-shop-org/tool-compass.git
cd tool-compass

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Build the search index
python gateway.py --sync

# Run the MCP server
python gateway.py
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

## CLI flags

The gateway accepts several flags for administration tasks:

| Flag | Description |
|------|-------------|
| `--sync` | Discover tools from backend MCP servers and rebuild the HNSW index |
| `--test` | Run semantic search tests to verify index quality |
| `--config` | Display current configuration including backends and settings |
| `--verbose` / `-v` | Enable verbose (DEBUG-level) output |

Running `python gateway.py` with no flags starts the MCP server in stdio mode by default. Set the `PORT` environment variable to switch to HTTP (streamable-http) transport for remote deployment (e.g., Fly.io):

```bash
PORT=8080 python gateway.py
```

## Gradio UI

Tool Compass includes a Gradio web interface for interactive exploration:

```bash
# Launch on default port 7860
python ui.py

# Custom port or public share link
python ui.py --port 7861
python ui.py --share
```

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Skip integration tests (no Ollama required)
pytest -m "not integration"
```
