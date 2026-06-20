---
title: Handbook
description: Everything you need to know about Tool Compass.
sidebar:
  order: 0
---

Welcome to the Tool Compass handbook.

## What's inside

The handbook is organized by what you need to do, following the [Diátaxis](https://diataxis.fr/) framework.

### Tutorials — learn by doing
- **[Beginners](/tool-compass/handbook/beginners/)** — First-time setup walkthrough and core concepts
- **[Getting Started](/tool-compass/handbook/getting-started/)** — Install, build the index, run the gateway (plus the new `tool-compass` CLI subcommands)
  - **[Register with your MCP client](/tool-compass/handbook/getting-started/#register-with-your-mcp-client)** — copy-paste config recipes for Claude Desktop, Cursor, and Cline

### How-To Guides — accomplish a specific task
- **[Operations](/tool-compass/handbook/operations/)** — `/ready`, `/metrics`, trace IDs, graceful Ollama-offline behavior in production

### Reference — propositional facts
- **[Tools](/tool-compass/handbook/tools/)** — All 9 gateway MCP tools in detail (compass, describe, execute, status, audit, sync, analytics, chains, categories)
- **[Configuration](/tool-compass/handbook/configuration/)** — Environment variables, Docker, and the `compass_config.json` schema

### Explanation — understand the design
- **[Architecture](/tool-compass/handbook/architecture/)** — How semantic search works under the hood (with Mermaid diagrams)

## What's new in v2.3

- **`tool-compass init`** — first-run onboarding. Scaffolds a `compass_config.json` at your platform config path (refuses to clobber without `--force`), then prints next steps and a ready-to-paste Claude Desktop MCP snippet. See [Register with your MCP client](/tool-compass/handbook/getting-started/#register-with-your-mcp-client) for Cursor + Cline recipes.
- **`npx @mcptoolshop/tool-compass`** — zero-prerequisite install. SHA256-verified binaries downloaded on first run, cached locally. No Python toolchain required.
- **6 new CLI subcommands** — `tool-compass ui`, `status`, `categories`, `audit`, `analytics`, `chains` mirror the MCP surface for terminal users. All support `--json`.
- **RFC 9457 error envelope** — every error includes `code`, `category`, `retryable`, and (where applicable) `nearest_tools[]` suggestions. Backward-compatible: the legacy `error: <str>` field stays alongside.
- **OTel `gen_ai.*` metrics** — circuit-breaker transitions, fallback invocations, HNSW search latency histogram, embedder inflight, queue wait. Plus `degraded: true` flag on responses served from lexical fallback.
- **Rich-powered CLI** — `--json` everywhere, NO_COLOR/`--no-color` honored, progress spinners on `doctor` + `sync`, actionable error messages with hints.
- **Golden-set Recall@k benchmark** — frozen 38-query regression test running on every commit. Detects retrieval-quality drift before users do.

## What changed in v2.2

- **`tool-compass` CLI shell** — `search`, `describe`, `sync`, `doctor`, `serve` subcommands. Default (no args) still launches the MCP server.
- **Graceful Ollama-offline** — `compass()` falls back to keyword search over the SQLite index, marks results `degraded: true`, and tells you what to start.
- **Trace IDs** — every MCP call returns an 8-char `trace_id` threaded through logs + responses for grepable bug reports.
- **`/ready` + `/metrics`** — deep readiness probe and Prometheus-format metrics for Fly.io / Kubernetes / any operator dashboard.
- **Embedding cache** — re-sync no longer re-embeds tool descriptions that haven't changed.
- **Multi-arch Docker** — linux/amd64 and linux/arm64 from the same GHCR tag.

Full list in [CHANGELOG](https://github.com/mcp-tool-shop-org/tool-compass/blob/main/CHANGELOG.md).

[Back to landing page](/tool-compass/)
