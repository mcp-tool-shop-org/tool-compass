---
title: Handbook
description: Everything you need to know about Tool Compass.
sidebar:
  order: 0
---

Welcome to the Tool Compass handbook.

## What's inside

- **[Beginners](/tool-compass/handbook/beginners/)** — First-time setup walkthrough and core concepts
- **[Getting Started](/tool-compass/handbook/getting-started/)** — Install, build the index, run the gateway (plus the new `tool-compass` CLI subcommands)
- **[Tools](/tool-compass/handbook/tools/)** — All 9 gateway tools in detail
- **[Architecture](/tool-compass/handbook/architecture/)** — How semantic search works under the hood (with Mermaid diagrams)
- **[Configuration](/tool-compass/handbook/configuration/)** — Environment variables, Docker, and troubleshooting
- **[Operations](/tool-compass/handbook/operations/)** — `/ready`, `/metrics`, trace IDs, graceful Ollama-offline behavior

## What changed in v2.2

- **`tool-compass` CLI shell** — `search`, `describe`, `sync`, `doctor`, `serve` subcommands. Default (no args) still launches the MCP server.
- **Graceful Ollama-offline** — `compass()` falls back to keyword search over the SQLite index, marks results `degraded: true`, and tells you what to start.
- **Trace IDs** — every MCP call returns an 8-char `trace_id` threaded through logs + responses for grepable bug reports.
- **`/ready` + `/metrics`** — deep readiness probe and Prometheus-format metrics for Fly.io / Kubernetes / any operator dashboard.
- **Embedding cache** — re-sync no longer re-embeds tool descriptions that haven't changed.
- **Multi-arch Docker** — linux/amd64 and linux/arm64 from the same GHCR tag.

Full list in [CHANGELOG](https://github.com/mcp-tool-shop-org/tool-compass/blob/main/CHANGELOG.md).

[Back to landing page](/tool-compass/)
