<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="https://raw.githubusercontent.com/mcp-tool-shop-org/brand/main/logos/tool-compass/readme.png" alt="Tool Compass Logo" width="400"></p>

**Semantic navigator for MCP tools - Find the right tool by intent, not memory**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>

*95% fewer tokens. Find tools by describing what you want to do.*

[Installation](#quick-start) • [Usage](#usage) • [Docker](#option-2-docker) • [Performance](#performance) • [Contributing](#contributing)

</div>

---

## The Problem

MCP servers expose dozens or hundreds of tools. Loading all tool definitions into context wastes tokens and slows down responses.

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

## The Solution

Tool Compass uses **semantic search** to find relevant tools from a natural language description. Instead of loading all tools, Claude calls `compass()` with an intent and gets back only the relevant tools.

<!--
## Demo

<p align="center">
  <img src="docs/assets/demo.gif" alt="Tool Compass Demo" width="600">
</p>
-->

## Quick Start

### Option 1: Local Installation

```bash
# Prerequisites: Ollama with nomic-embed-text
ollama pull nomic-embed-text

# Clone and setup
git clone https://github.com/mcp-tool-shop-org/tool-compass.git
cd tool-compass/tool_compass

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Build the search index
python gateway.py --sync

# Run the MCP server
python gateway.py

# Or launch the Gradio UI
python ui.py
```

### Option 2: Docker

```bash
# Clone the repo
git clone https://github.com/mcp-tool-shop-org/tool-compass.git
cd tool-compass/tool_compass

# Start with Docker Compose (requires Ollama running locally)
docker-compose up

# Or include Ollama in the stack
docker-compose --profile with-ollama up

# Access the UI at http://localhost:7860
```

## Features

- **Semantic Search** - Find tools by describing what you want to do
- **Progressive Disclosure** - `compass()` → `describe()` → `execute()`
- **Hot Cache** - Frequently used tools are pre-loaded
- **Chain Detection** - Automatically discovers common tool workflows
- **Analytics** - Track usage patterns and tool performance
- **Cross-Platform** - Windows, macOS, Linux
- **Docker Ready** - One-command deployment

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     TOOL COMPASS                            │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   Ollama     │    │   hnswlib    │    │   SQLite     │  │
│  │   Embedder   │───▶│    HNSW      │◀───│   Metadata   │  │
│  │  (nomic)     │    │   Index      │    │   Store      │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│                              │                              │
│                              ▼                              │
│                    ┌──────────────────┐                    │
│                    │  Gateway (9 tools)│                   │
│                    │  compass, describe│                   │
│                    │  execute, etc.    │                   │
│                    └──────────────────┘                    │
└─────────────────────────────────────────────────────────────┘
```

## Usage

### The `compass()` Tool

```python
compass(
    intent="I need to generate an AI image from a text description",
    top_k=3,
    category=None,  # Optional: "file", "git", "database", "ai", etc.
    min_confidence=0.3
)
```

Returns:
```json
{
  "matches": [
    {
      "tool": "comfy:comfy_generate",
      "description": "Generate image from text prompt using AI",
      "category": "ai",
      "confidence": 0.912
    }
  ],
  "total_indexed": 44,
  "tokens_saved": 20500,
  "hint": "Found: comfy:comfy_generate. Use describe() for full schema."
}
```

### Available Tools

| Tool | Description |
|------|-------------|
| `compass(intent)` | Semantic search for tools |
| `describe(tool_name)` | Get full schema for a tool |
| `execute(tool_name, args)` | Run a tool on its backend |
| `compass_categories()` | List categories and servers |
| `compass_status()` | System health and config |
| `compass_analytics(timeframe)` | Usage statistics |
| `compass_chains(action)` | Manage tool workflows |
| `compass_sync(force)` | Rebuild index from backends |
| `compass_audit()` | Full system report |

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | Project root | Auto-detected |
| `TOOL_COMPASS_PYTHON` | Python executable | Auto-detected |
| `TOOL_COMPASS_CONFIG` | Config file path | `./compass_config.json` |
| `OLLAMA_URL` | Ollama server URL | `http://localhost:11434` |
| `COMFYUI_URL` | ComfyUI server | `http://localhost:8188` |

See [`.env.example`](.env.example) for all options.

## Performance

| Metric | Value |
|--------|-------|
| Index build time | ~5s for 44 tools |
| Query latency | ~15ms (including embedding) |
| Token savings | ~95% (38K → 2K) |
| Accuracy@3 | ~95% (correct tool in top 3) |

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Skip integration tests (no Ollama required)
pytest -m "not integration"
```

## Troubleshooting

### MCP Server Not Connecting

If Claude Desktop logs show JSON parse errors:
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**Cause**: `print()` statements corrupt JSON-RPC protocol.

**Fix**: Use logging or `file=sys.stderr`:
```python
import sys
print("Debug message", file=sys.stderr)
```

### Ollama Connection Failed

```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Pull the embedding model
ollama pull nomic-embed-text
```

### Index Not Found

```bash
python gateway.py --sync
```

## Related Projects

Part of the **Compass Suite** for AI-powered development:

- [File Compass](https://github.com/mcp-tool-shop-org/file-compass) - Semantic file search
- [Integradio](https://github.com/mcp-tool-shop-org/integradio) - Vector-embedded Gradio components
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - Headless LLM fine-tuning
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - ComfyUI without the complexity

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Security & Data Scope

Tool Compass is a **local-first** development tool. See [SECURITY.md](SECURITY.md) for full policy.

- **Data touched:** tool descriptions indexed in local HNSW vector DB, search queries logged to local SQLite (`compass_analytics.db`), embeddings generated via local Ollama.
- **Data NOT touched:** no user code, no file contents, no credentials. Tool call arguments are hashed, not stored in plain text.
- **Network:** connects to local Ollama for embeddings. Optional Gradio UI binds to localhost. No external telemetry.
- **No telemetry:** collects nothing externally. Analytics are local-only.

## Scorecard

| Category | Score | Notes |
|----------|-------|-------|
| A. Security | 10/10 | SECURITY.md, local-only, no telemetry, parameterized SQL |
| B. Error Handling | 10/10 | Structured results, graceful Ollama fallback |
| C. Operator Docs | 10/10 | README, CHANGELOG, CONTRIBUTING, API docs |
| D. Shipping Hygiene | 10/10 | CI (lint + 413 tests + coverage + pip-audit + Docker), verify script |
| E. Identity | 10/10 | Logo, translations, landing page |
| **Total** | **50/50** | |

## License

[MIT](LICENSE) - see LICENSE file for details.

---

<p align="center">
  Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
</p>
