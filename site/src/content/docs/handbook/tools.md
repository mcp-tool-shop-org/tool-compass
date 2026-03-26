---
title: Tools
description: All 9 gateway tools in detail.
sidebar:
  order: 2
---

## compass

Semantic search for tools. Describe what you want to do and get back only the relevant tools.

```python
compass(
    intent="I need to generate an AI image from a text description",
    top_k=3,
    category=None,  # Optional: "file", "git", "database", "ai", etc.
    min_confidence=0.3
)
```

Returns matched tools with confidence scores, token savings, and hints.

## describe

Get full JSON schema for a specific tool before calling it.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `tool_name` | yes | Fully qualified tool name (e.g., `comfy:comfy_generate`) |

## execute

Run any indexed tool directly through the gateway.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `tool_name` | yes | Tool to execute |
| `args` | yes | Arguments to pass to the tool |

## compass_categories

List all tool categories and connected MCP servers. Takes no arguments.

## compass_status

System health and config — index size, model status, configuration. Takes no arguments.

## compass_analytics

Usage statistics, accuracy metrics, and performance data.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `timeframe` | no | Time window for analytics (e.g., `24h`, `7d`) |

## compass_chains

Discover and manage common multi-tool workflows.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `action` | yes | Action to perform on chain data |

## compass_sync

Rebuild the HNSW search index from connected backends.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `force` | no | Force full rebuild even if index exists |

## compass_audit

Full system diagnostic — index integrity, server health, configuration validation. Takes no arguments.
