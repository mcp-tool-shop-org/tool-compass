<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center"><img src="https://raw.githubusercontent.com/mcp-tool-shop-org/brand/main/logos/tool-compass/readme.png" alt="Tool Compass Logo" width="400"></p>

<p align="center">
  <strong>Semantic navigator for MCP tools — find the right tool by intent, not memory.</strong>
</p>

<p align="center">
  <a href="https://www.npmjs.com/package/@mcptoolshop/tool-compass"><img src="https://img.shields.io/npm/v/@mcptoolshop/tool-compass?style=flat-square" alt="npm"></a>
  <a href="https://pypi.org/project/tool-compass/"><img src="https://img.shields.io/pypi/v/tool-compass?style=flat-square&label=pypi" alt="PyPI"></a>
  <a href="https://github.com/mcp-tool-shop-org/tool-compass/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="License"></a>
  <a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Handbook-live-blue?style=flat-square" alt="Handbook"></a>
</p>

---

## Zero-prerequisite install

```bash
npx @mcptoolshop/tool-compass --help
```

This package is an `npx`-friendly launcher for the [`tool-compass`](https://github.com/mcp-tool-shop-org/tool-compass) Python CLI. It downloads the verified platform-specific binary from the GitHub Release, caches it locally, and runs it with full argument passthrough.

**No Python install required.** The binary is self-contained.

## What is Tool Compass?

MCP servers expose dozens or hundreds of tools. Loading every tool definition into an LLM context wastes tokens and slows responses.

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

Tool Compass uses **semantic search** to find relevant tools from a natural-language description. Instead of loading every tool, the LLM calls `compass()` with an intent and gets back only the matching tools.

## Quick start

### Run the MCP gateway

```bash
npx @mcptoolshop/tool-compass serve
```

### Launch the Gradio UI

```bash
npx @mcptoolshop/tool-compass ui
```

### Diagnose your setup

```bash
npx @mcptoolshop/tool-compass doctor
```

### Sync the index against your backends

```bash
npx @mcptoolshop/tool-compass sync
```

## What gets installed

Nothing global. The launcher downloads the verified binary on first run, caches it under:

| OS      | Cache path                                       |
|---------|--------------------------------------------------|
| Linux   | `~/.cache/mcptoolshop/tool-compass/<version>/`   |
| macOS   | `~/.cache/mcptoolshop/tool-compass/<version>/`   |
| Windows | `%LOCALAPPDATA%\mcptoolshop\tool-compass\<version>\` |

Every binary is SHA256-verified against `checksums-<version>.txt` from the GitHub Release. Mismatches abort execution and the file is deleted.

## Configuration

Configuration lives in `compass_config.json` in the working directory. Start from the [example](https://github.com/mcp-tool-shop-org/tool-compass/blob/main/compass_config.example.json):

```json
{
  "backends": [
    {
      "name": "my-mcp-server",
      "command": "python",
      "args": ["-m", "my_server"]
    }
  ]
}
```

See the [Configuration handbook page](https://mcp-tool-shop-org.github.io/tool-compass/handbook/configuration/) for the full schema.

## MCP client setup

Add this to your Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "compass": {
      "command": "npx",
      "args": ["-y", "@mcptoolshop/tool-compass", "serve"]
    }
  }
}
```

## How the launcher works

```
npx @mcptoolshop/tool-compass serve
        │
        ▼
  wrapper sets MCPTOOLSHOP_LAUNCH_CONFIG
        │
        ▼
  npm-launcher resolves your platform (linux-x64, darwin-arm64, win-x64)
        │
        ▼
  checks local cache
        │
        ├─ cached → run binary
        │
        └─ not cached:
             fetch checksums-<version>.txt
             download tool-compass-<version>-<os>-<arch>[.exe]
             verify SHA256
             cache + chmod +x
             run binary
```

## Security & threat model

The npm wrapper downloads and executes a binary from GitHub Releases. Here's what it touches:

- **Network:** HTTPS only, to `github.com` and GitHub's CDN.
- **Filesystem:** Writes to the local cache only. Does not modify system files.
- **Verification:** SHA256-checked against the official Release checksums.
- **No telemetry.** No credentials handled.
- **No elevated permissions.**

See [SECURITY.md](https://github.com/mcp-tool-shop-org/tool-compass/blob/main/SECURITY.md) for the full disclosure policy.

## Alternative installs

- **PyPI:** `pip install tool-compass`
- **Docker:** `docker run ghcr.io/mcp-tool-shop-org/tool-compass:latest`
- **From source:** clone + `pip install -e .` — see [CONTRIBUTING.md](https://github.com/mcp-tool-shop-org/tool-compass/blob/main/CONTRIBUTING.md)

## Documentation

| Resource | Where |
|----------|-------|
| Handbook | https://mcp-tool-shop-org.github.io/tool-compass/handbook/ |
| Source repo | https://github.com/mcp-tool-shop-org/tool-compass |
| Changelog | https://github.com/mcp-tool-shop-org/tool-compass/blob/main/CHANGELOG.md |
| Issues | https://github.com/mcp-tool-shop-org/tool-compass/issues |

## License

[MIT](https://github.com/mcp-tool-shop-org/tool-compass/blob/main/LICENSE) — same as the source repo.

---

Built by [MCP Tool Shop](https://mcp-tool-shop.github.io/).
