---
title: Tools
description: All 9 gateway tools in detail.
sidebar:
  order: 2
---

Every handler here also returns a `trace_id` (8-char hex) in its success
and error envelopes. Use it in bug reports — the same id appears in the
gateway log lines for that request. See the
[Operations page](/tool-compass/handbook/operations/) for more.

## compass

Semantic search for tools. Describe what you want to do and get back only the relevant tools. Also searches for matching tool chains (workflows).

:::note
When Ollama is unreachable, `compass()` falls back to SQLite `LIKE`
lexical search over the same index. Results are marked `degraded: true`
and the response gains a `warnings[]` array telling you what to start.
See [Degraded modes](/tool-compass/handbook/operations/#degraded-modes).
:::

```python
compass(
    intent="I need to generate an AI image from a text description",
    top_k=3,
    category=None,
    server=None,
    min_confidence=0.3,
    include_chains=True
)
```

| Parameter | Required | Description |
|-----------|----------|-------------|
| `intent` | yes | Natural language description of your task |
| `top_k` | no | Maximum results to return (1-10, default 5) |
| `category` | no | Filter by category (`file`, `git`, `database`, `ai`, `search`, `analysis`, etc.) |
| `server` | no | Filter by server (`bridge`, `doc`, `comfy`, `video`, `chat`) |
| `min_confidence` | no | Minimum similarity score (0-1, default 0.3) |
| `include_chains` | no | Also search for matching workflows (default true) |

Returns matched tools with confidence scores, token savings, hints, and any matching chains.

## describe

Get the full JSON schema for a specific tool before calling it. This is the second step in the progressive disclosure flow.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `tool_name` | yes | Fully qualified tool name (e.g., `comfy:comfy_generate`) |

Returns full tool schema including parameters, types, examples, and a hint for next steps.

## execute

Run any indexed tool directly through the gateway. This proxies the call to the appropriate MCP backend server.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `tool_name` | yes | Tool to execute (e.g., `bridge:read_file`) |
| `arguments` | no | Arguments to pass to the tool as a dictionary |

## compass_categories

List all tool categories and connected MCP servers. Use this to understand what kinds of tools are available before searching. Takes no arguments.

## compass_status

System health and configuration overview. Returns index stats, backend connection status, hot cache status, sync status, and chain info. Takes no arguments.

## compass_analytics

Usage statistics, accuracy metrics, and performance data.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `timeframe` | no | Time window (`1h`, `24h`, `7d`, `30d`, default `24h`) |
| `include_failures` | no | Include details about failed tool calls (default true) |

Returns search stats, top tools, success rates, failure details, chain stats, and hot cache info.

## compass_chains

Discover and manage common multi-tool workflows. Chains are auto-detected from usage patterns or manually defined.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `action` | no | `list` (default), `create`, or `detect` |
| `chain_name` | for create | Name for the new chain |
| `tools` | for create | Ordered list of tool names |
| `description` | no | Description for the new chain |

## compass_sync

Rebuild the HNSW search index from connected backends. Normally sync happens automatically on startup.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `force` | no | Force full rebuild even if no changes detected (default false) |

## compass_audit

Comprehensive system diagnostic covering index integrity, backend health, hot cache, chains, analytics, and configuration.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `include_tools` | no | Include full list of all indexed tools (default false) |
| `timeframe` | no | Timeframe for analytics (`1h`, `24h`, `7d`, `30d`, default `24h`) |
