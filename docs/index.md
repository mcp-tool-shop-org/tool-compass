# Tool Compass

**Semantic navigator for MCP tools -- find the right tool by intent, not memory.**

Tool Compass uses local Ollama embeddings and HNSW vector search to match
natural-language intents to the right MCP tool, cutting context tokens by ~95%.

## Quick links

| Resource | Link |
|----------|------|
| Repository | [github.com/mcp-tool-shop-org/tool-compass](https://github.com/mcp-tool-shop-org/tool-compass) |
| PyPI | [pypi.org/project/tool-compass](https://pypi.org/project/tool-compass/) |
| Issues | [GitHub Issues](https://github.com/mcp-tool-shop-org/tool-compass/issues) |
| Discussions | [GitHub Discussions](https://github.com/mcp-tool-shop-org/tool-compass/discussions) |

## How it works

1. **Index** -- Tool Compass syncs tool definitions from your MCP servers and
   embeds them with `nomic-embed-text` via Ollama.
2. **Search** -- When Claude needs a tool, it calls `compass(intent)` instead of
   loading every tool definition into context.
3. **Disclose** -- Results come back ranked by semantic similarity. Call
   `describe()` for the full schema, then `execute()` to run it.

## Install

```bash
# Prerequisites: Ollama with nomic-embed-text
ollama pull nomic-embed-text

pip install tool-compass
```

Or run with Docker:

```bash
git clone https://github.com/mcp-tool-shop-org/tool-compass.git
cd tool-compass
docker-compose up
```

## Part of the Compass Suite

- [File Compass](https://github.com/mcp-tool-shop-org/file-compass) -- Semantic file search
- [Integradio](https://github.com/mcp-tool-shop-org/integradio) -- Vector-embedded Gradio components
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) -- Headless LLM fine-tuning
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) -- ComfyUI without the complexity

## License

[MIT](https://github.com/mcp-tool-shop-org/tool-compass/blob/main/LICENSE)
