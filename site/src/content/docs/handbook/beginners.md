---
title: Beginners
description: First-time setup walkthrough and core concepts for Tool Compass.
sidebar:
  order: 99
---

## What is Tool Compass?

Tool Compass is a semantic navigator for MCP tools. Instead of loading every tool definition into your LLM context (wasting thousands of tokens), Tool Compass indexes your tools and lets you search for the right one by describing what you want to do.

A single `compass()` call replaces loading dozens of tool schemas. The result: around 95% fewer tokens per request with no loss of capability.

## Prerequisites

Before installing Tool Compass you need two things:

1. **Python 3.10 or newer** -- check with `python --version`
2. **Ollama** running locally with the `nomic-embed-text` model -- this generates the vector embeddings that power semantic search

Install Ollama from [ollama.com](https://ollama.com) and pull the embedding model:

```bash
ollama pull nomic-embed-text
```

Verify Ollama is running:

```bash
curl http://localhost:11434/api/tags
```

## Installation

Install Tool Compass from PyPI:

```bash
pip install tool-compass
```

Or clone the repository for local development:

```bash
git clone https://github.com/mcp-tool-shop-org/tool-compass.git
cd tool-compass

python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

pip install -e .
```

Build the search index (this embeds all tool descriptions into vectors):

```bash
tool-compass sync
```

Start the MCP gateway server:

```bash
tool-compass
```

If you prefer Docker, see the [Getting Started](/tool-compass/handbook/getting-started/) page for Docker Compose instructions.

To explore tools interactively in a browser, install the UI extra and launch the Gradio surface:

```bash
pip install "tool-compass[ui]"
tool-compass-ui
```

This opens a web interface at `http://localhost:7860` where you can search, browse categories, and view analytics.

## Core concepts

Tool Compass is built around three ideas:

**Semantic search** -- Tool descriptions are embedded into 768-dimensional vectors using Ollama. When you search, your intent is embedded the same way and compared against all indexed tools using HNSW approximate nearest-neighbor search. This means you can describe what you want in natural language and get back relevant tools even if you do not know their exact names.

**Progressive disclosure** -- Instead of dumping full JSON schemas for every tool, Compass uses a three-step flow that loads detail only when needed:

```
compass("generate an image")   -> summaries + confidence scores (~2K tokens)
describe("comfy:comfy_generate") -> full parameter schema (~500 tokens)
execute("comfy:comfy_generate", {...}) -> run the tool
```

**Tool chains** -- Common multi-tool workflows (like "read file, modify, write back") are detected from usage patterns and made searchable alongside individual tools.

## First steps after install

Once the gateway is running, try these calls to explore what is available:

1. **Search for tools** -- call `compass()` with a natural language intent:

   ```python
   compass(intent="read a file from disk")
   ```

2. **Browse categories** -- call `compass_categories()` to see what kinds of tools exist (file, git, database, ai, search, analysis, etc.)

3. **Inspect a tool** -- pick a tool name from compass results and call `describe()` to see its full schema:

   ```python
   describe(tool_name="bridge:read_file")
   ```

4. **Run a tool** -- pass arguments to `execute()`:

   ```python
   execute(tool_name="bridge:read_file", arguments={"filepath": "README.md"})
   ```

5. **Check system health** -- call `compass_status()` to see index size, backend connections, and configuration

## Common tasks

**Filtering searches by category** -- If you know you need a git tool, narrow the results:

```python
compass(intent="commit my changes", category="git")
```

**Viewing analytics** -- See how tools are being used over the last 24 hours:

```python
compass_analytics(timeframe="24h")
```

**Working with tool chains** -- List pre-defined workflows:

```python
compass_chains(action="list")
```

Create a custom workflow:

```python
compass_chains(
    action="create",
    chain_name="code_review",
    tools=["bridge:read_file", "doc:scan", "doc:report"],
    description="Read a file, scan for issues, generate report"
)
```

**Rebuilding the index** -- If you add new backend servers, sync the index:

```python
compass_sync(force=True)
```

## Glossary

| Term | Meaning |
|------|---------|
| **Backend** | An MCP server that provides tools (e.g., bridge, comfy, doc, video, chat) |
| **Compass index** | The HNSW vector index that stores tool embeddings for fast similarity search |
| **Chain** | A named sequence of tools that form a workflow |
| **Confidence score** | A 0-1 similarity score indicating how well a tool matches your intent |
| **Gateway** | The Tool Compass MCP server that proxies searches and tool calls to backends |
| **Hot cache** | The top 10 most frequently used tools, kept in memory for instant access |
| **HNSW** | Hierarchical Navigable Small World -- the algorithm used for approximate nearest-neighbor vector search |
| **Intent** | The natural language description you pass to `compass()` |
| **nomic-embed-text** | The Ollama embedding model that converts text into 768-dimensional vectors |
| **Progressive disclosure** | The three-step pattern: `compass()` then `describe()` then `execute()` |
| **Qualified name** | A tool name in `server:tool` format (e.g., `bridge:read_file`) |
| **Sync** | The process of discovering tools from backends and rebuilding the search index |

## What's next

- **[Tools reference](/tool-compass/handbook/tools/)** — Detailed parameter tables for all 9 gateway tools
- **[Architecture](/tool-compass/handbook/architecture/)** — How the HNSW index, embedder, sync manager, and analytics engine work together
- **[Configuration](/tool-compass/handbook/configuration/)** — All config file options, environment variables, Docker setup, and troubleshooting
