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
│                    │  Gateway (9 tools)│                 │
│                    └──────────────────┘                  │
└─────────────────────────────────────────────────────────┘
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

## Features

- **Hot cache** — Frequently used tools are pre-loaded for instant access
- **Chain detection** — Automatically discovers common tool workflows from usage patterns
- **Analytics** — Tracks usage patterns, accuracy metrics, and performance data in local SQLite
- **Cross-platform** — Works on Windows, macOS, and Linux

## Performance

| Metric | Value |
|--------|-------|
| Index build time | ~5s for 44 tools |
| Query latency | ~15ms (including embedding) |
| Token savings | ~95% (38K → 2K) |
| Accuracy@3 | ~95% (correct tool in top 3) |
