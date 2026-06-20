---
title: Architecture
description: How semantic search works under the hood.
sidebar:
  order: 3
---

## Overview

Tool Compass uses three components working together:

```
┌─────────────────────────────────────────────────────────┐
│                     TOOL COMPASS                         │
│                                                          │
│  ┌──────────────┐    ┌──────────────┐   ┌──────────────┐│
│  │   Ollama     │    │   hnswlib    │   │   SQLite     ││
│  │   Embedder   │───▶│    HNSW      │◀──│   Metadata   ││
│  │  (nomic)     │    │   Index      │   │   Store      ││
│  └──────────────┘    └──────────────┘   └──────────────┘│
│                              │                           │
│                              ▼                           │
│                    ┌──────────────────┐                  │
│                    │  Gateway          │                  │
│                    │  (9 MCP tools)    │                  │
│                    └──────────────────┘                  │
└─────────────────────────────────────────────────────────┘
```

## Component graph

The runtime wires together five long-lived singletons. `Gateway` is the
top-level coordinator that every MCP tool call passes through; it delegates
to the index/backend/analytics subsystems.

```
   ┌──────────────────────┐
   │       Embedder       │
   │   nomic-embed-text   │
   └──────────┬───────────┘
              │
   ┌──────────────────────┐        ┌──────────────────────┐
   │   BackendManager     │───────▶│     SyncManager      │
   └──────────┬───────────┘        └──────────┬───────────┘
              │                               │
              │                               ▼
              │                    ┌──────────────────────┐
              │                    │    CompassIndex      │◀── Embedder
              │                    │   (HNSW + SQLite)    │
              │                    └──────────┬───────────┘
              │                               │
              ▼                               ▼
   ┌──────────────────────────────────────────────────────┐
   │                       Gateway                         │
   │                   (MCP entrypoint)                    │
   └──────────────────────────────────────────────────────┘
              ▲                  ▲
              │                  │
   ┌──────────┴───────┐  ┌───────┴──────────┐
   │   ChainIndexer   │  │ CompassAnalytics │
   └──────────────────┘  └──────────────────┘
```

Flow: `Embedder` and `BackendManager` feed `CompassIndex` (via
`SyncManager`); `Gateway` is the MCP entrypoint that the index, backends,
`ChainIndexer`, and `CompassAnalytics` all report into.

## Request sequence

What actually happens when a client calls `compass("generate an image")`:

```
 Client      Gateway       CompassIndex      Embedder        Ollama
   │            │                │               │              │
   │ compass(intent)             │               │              │
   ├───────────▶│                │               │              │
   │            │ search(intent, top_k)          │              │
   │            ├───────────────▶│               │              │
   │            │                │ embed_query(intent)          │
   │            │                ├──────────────▶│              │
   │            │                │               │ POST /api/embeddings
   │            │                │               ├─────────────▶│
   │            │                │               │  768-dim vector
   │            │                │               │◀─────────────┤
   │            │                │   vector      │              │
   │            │                │◀──────────────┤              │
   │            │ top-k matches  │               │              │
   │            │◀───────────────┤               │              │
   │ {tools: [...], confidence}  │               │              │
   │◀───────────┤                │               │              │
   │            │                │               │              │
```

## How it works

1. **Indexing** — Tool descriptions from connected MCP servers are embedded into 768-dim vectors using Ollama's `nomic-embed-text` model
2. **Storage** — Vectors are stored in an HNSW index for fast approximate nearest-neighbor search. Metadata lives in SQLite
3. **Search** — When `compass(intent)` is called, the intent is embedded and compared against the index. Top-k matches are returned with confidence scores
4. **Progressive disclosure** — `compass()` returns summaries. `describe()` loads full schemas. `execute()` runs the tool. Each step adds detail only when needed

## Progressive disclosure flow

```
compass("generate an image")
  → 3 matches, ~2K tokens

describe("comfy:comfy_generate")
  → full JSON schema, ~500 tokens

execute("comfy:comfy_generate", {prompt: "..."})
  → result from backend
```

## Subsystems

Beyond the core search pipeline, Tool Compass includes several runtime subsystems:

**Backend client** (`backend_client_simple.py`) — Manages subprocess-based MCP server connections using direct JSON-RPC over stdin/stdout. Includes connection pooling, automatic reconnection, and retry logic. A secondary SDK-based client (`backend_client_mcp.py`) exists for reference but is not used at runtime to avoid anyio task group conflicts.

**Sync manager** (`sync_manager.py`) — Detects when backend servers have added or changed tools by comparing hash digests of tool lists. Supports three strategies: hash-based change detection, on-demand startup check, and optional background polling at a configurable interval.

**Analytics** (`analytics.py`) — Tracks search queries, tool executions, success/failure rates, and latencies in a local SQLite database (`compass_analytics.db`). Arguments are hashed (never stored in plain text). Maintains a hot cache of the top N most-used tools for instant access.

**Chain indexer** (`chain_indexer.py`) — Makes multi-tool workflows (chains) searchable via their own HNSW index. Chains can be manually defined or auto-detected from usage patterns recorded by the analytics engine.

**Embedder** (`embedder.py`) — Async HTTP client for Ollama's embedding API. Uses the `search_document:` prefix when embedding tool descriptions and `search_query:` when embedding user intents, following nomic-embed-text best practices for retrieval tasks. Also provides a `SyncEmbedder` wrapper safe for use inside running event loops (e.g., Gradio callbacks).

## Backend types

Configuration supports three backend connection types, defined in `config.py`:

| Type | Description |
|------|-------------|
| `stdio` | Spawns an MCP server as a subprocess and communicates via stdin/stdout JSON-RPC. This is the default and recommended type. |
| `http` | Connects to a remote MCP server over HTTP/SSE. |
| `import` | Imports an MCP server module directly into the same Python process. |

Only `stdio` backends are implemented at runtime. `http` and `import` types are defined in the configuration schema for future use.

## Features

- **Hot cache** — The top 10 most frequently used tools are kept in memory for instant access
- **Chain detection** — Automatically discovers common tool workflows from usage patterns, indexing them for semantic search
- **Analytics** — Tracks search queries, tool calls, success rates, and latencies in local SQLite
- **Auto-sync** — Detects backend tool changes on startup via hash comparison and rebuilds affected index portions
- **Cross-platform** — Works on Windows, macOS, and Linux with platform-specific subprocess handling

## Performance

| Metric | Value |
|--------|-------|
| Index build time | linear in tool count — sub-second per tool on local Ollama |
| Query latency | ~15ms (including embedding) |
| Token savings | ~95% versus loading every tool schema upfront |
| Accuracy@3 | ~95% (correct tool in top 3) |

Tool count is auto-discovered from connected backends at sync time. The exact number depends on which backends are wired up — there is no canonical "Tool Compass has N tools" claim.
