---
title: Configuration
description: Environment variables, config file, Docker, and troubleshooting.
sidebar:
  order: 4
---

## Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | Project root directory | Auto-detected from module location |
| `TOOL_COMPASS_PYTHON` | Python executable path | Current interpreter or venv auto-detect |
| `TOOL_COMPASS_CONFIG` | Path to config JSON file | `./compass_config.json` |
| `OLLAMA_URL` | Ollama server URL | `http://localhost:11434` |
| `COMFYUI_URL` | ComfyUI server URL (used by the comfy backend) | `http://localhost:8188` |
| `PORT` | Set to enable HTTP (streamable-http) transport instead of stdio | unset (stdio mode) |

## Config file

Tool Compass reads settings from a JSON file at startup. The resolution order for the config path is:

1. `TOOL_COMPASS_CONFIG` environment variable
2. `./compass_config.json` in the tool-compass directory

If no config file is found, built-in defaults are used. See `compass_config.example.json` in the repository for a complete example.

### All config options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `backends` | object | (built-in defaults) | Backend server connections keyed by name |
| `embedding_model` | string | `nomic-embed-text` | Ollama embedding model name |
| `ollama_url` | string | `http://localhost:11434` | Ollama API base URL |
| `index_dir` | string | `./db` | Directory for HNSW index and SQLite databases |
| `auto_sync` | bool | `true` | Enable automatic tool discovery from backends |
| `default_top_k` | int | `5` | Default number of results for compass searches |
| `min_confidence` | float | `0.3` | Default minimum similarity threshold |
| `progressive_disclosure` | bool | `true` | Return summaries only from compass (use describe for full schemas) |
| `sync_check_on_startup` | bool | `true` | Check for backend changes on first compass call |
| `sync_polling_interval` | int | `300` | Background polling interval in seconds (0 = disabled) |
| `analytics_enabled` | bool | `true` | Track search queries and tool calls in local SQLite |
| `hot_cache_size` | int | `10` | Number of frequently used tools to keep in memory |
| `chain_indexing_enabled` | bool | `true` | Enable tool chain detection and indexing |
| `chain_detection_min_occurrences` | int | `3` | Minimum pattern occurrences before promoting to a chain |
| `top_chains_cache_size` | int | `5` | Number of top chains to keep in memory cache |

### Variable substitution

The config file supports `${VAR}` substitution. Values are resolved from environment variables first, then from a `defaults` block in the config file:

```json
{
  "defaults": {
    "BASE": "/home/user/project"
  },
  "backends": {
    "bridge": {
      "type": "stdio",
      "command": "python",
      "args": ["-u", "${BASE}/app/mcp/bridge_mcp_server.py"]
    }
  }
}
```

## Docker

```bash
# Start with Docker Compose
docker-compose up

# Include Ollama in the stack
docker-compose --profile with-ollama up
```

The Gradio UI is available at `http://localhost:7860` when running in Docker.

## Troubleshooting

### MCP server not connecting

If Claude Desktop logs show JSON parse errors like:

```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**Cause:** `print()` statements corrupt the JSON-RPC protocol.

**Fix:** Use logging or write to stderr:

```python
import sys
print("Debug message", file=sys.stderr)
```

### Ollama connection failed

```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Pull the embedding model
ollama pull nomic-embed-text
```

### Index not found

Rebuild the index:

```bash
python gateway.py --sync
```

### Backend not connecting

If a backend fails to connect, verify:

1. The command in your config file is correct and the script exists
2. The backend MCP server starts successfully when run standalone
3. Check gateway logs with `--verbose` for detailed connection errors

## Security and data scope

- **Data touched:** Tool descriptions indexed in local HNSW vector DB, search queries logged to local SQLite, embeddings generated via local Ollama
- **Data NOT touched:** No user code, no file contents, no credentials. Tool call arguments are hashed, not stored in plain text
- **Network:** Connects to local Ollama for embeddings. Optional Gradio UI binds to localhost. No external telemetry
