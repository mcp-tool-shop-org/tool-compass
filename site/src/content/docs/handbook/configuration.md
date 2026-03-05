---
title: Configuration
description: Environment variables, Docker, and troubleshooting.
sidebar:
  order: 4
---

## Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | Project root | Auto-detected |
| `TOOL_COMPASS_PYTHON` | Python executable | Auto-detected |
| `TOOL_COMPASS_CONFIG` | Config file path | `./compass_config.json` |
| `OLLAMA_URL` | Ollama server URL | `http://localhost:11434` |
| `COMFYUI_URL` | ComfyUI server | `http://localhost:8188` |

See `.env.example` in the repository for all options.

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

## Security and data scope

- **Data touched:** Tool descriptions indexed in local HNSW vector DB, search queries logged to local SQLite, embeddings generated via local Ollama
- **Data NOT touched:** No user code, no file contents, no credentials. Tool call arguments are hashed, not stored in plain text
- **Network:** Connects to local Ollama for embeddings. Optional Gradio UI binds to localhost. No external telemetry
