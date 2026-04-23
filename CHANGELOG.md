# Changelog

All notable changes to Tool Compass will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.2.2] - 2026-04-23

Patch release. Fixes the Docker image so the `tool-compass` console script
is actually installed inside the container (was missing in v2.2.0/v2.2.1).

### Fixed
- Docker image now runs `pip install --no-deps .` during build, so
  `docker run ghcr.io/mcp-tool-shop-org/tool-compass:2.2.2 tool-compass --version`
  (or any subcommand) works out of the box. v2.2.0/v2.2.1 images only
  shipped the source tree; the console script was never registered on
  PATH.
- Dockerfile `LABEL version` bumped 2.0.7 → 2.2.2.

## [2.2.1] - 2026-04-23

Patch release. Fixes the v2.2.0 release-smoke defect.

### Fixed
- `tool-compass --version` now prints the version and exits. v2.2.0's new
  CLI subcommand shell (MCC-FT-001) forgot to wire `--version` on the root
  parser, so the publish-time release-smoke check failed even though the
  artifacts themselves were valid. Purely a CLI ergonomics fix.

## [2.2.0] - 2026-04-23

Dogfood swarm release: Stage A bug/security health pass + Stage B/C humanization
+ Feature Pass. Shipcheck 17/17 retained.

### Added
- **Per-backend stdout reader** — isolated log streams per MCP backend so a noisy
  child process can't crowd out siblings in the combined view
- **`/ready` + `/metrics` HTTP endpoints** — readiness probe + Prometheus-style
  metrics surface for operators running the gateway behind a load balancer
- **Embedding cache** — LRU cache in `Embedder` so repeated identical queries
  skip the Ollama round-trip
- **Diffing sync** — `SyncManager` now emits a structured diff (added / removed /
  changed) instead of a full rebuild signal; downstream consumers can act on
  partial changes
- **`tool-compass` CLI subcommand shell** (`cli.py`) — top-level entry point now
  dispatches to `serve` (gateway), `ui` (Gradio), `doctor` (config health),
  `sync`, `test`, and `config`. `python gateway.py` still works unchanged.
- **`deprecated_aliases` in tool manifest** — lets backends rename tools without
  breaking old callers; the compass surfaces both names and marks legacy ones
- **`make scorecard` + `make verify-scorecard`** (CDS-FT-001) — regenerate
  SCORECARD.md from shipcheck output; CI soft-fails on drift
- **`make dev` + `make dev-ui`** (CDS-FT-002) — one-shot install + run targets
  for the fast local loop, with a warning if Ollama isn't reachable
- **Nightly Hypothesis fuzz job** (TST-FT-002) — `nightly-fuzz` runs Mon/Wed/Fri
  at 09:00 UTC in `ci.yml` (no new workflow file), auto-opens a tracking issue
  on failure
- **Coverage floor** (TST-FT-001) — `[tool.coverage.report] fail_under = 60`
  and `--cov-fail-under=60` in `make test`; conservative first gate
- **Architecture Mermaid diagrams** (CDS-FT-005) — component graph + request
  sequence diagrams in `site/src/content/docs/handbook/architecture.md`

### Changed
- `tool-compass` console script now targets `cli:main` (was `gateway:main`).
  `python gateway.py` remains fully supported for direct invocation.
- Wheel bundle includes `cli.py`

### Fixed (Stage A — 23 HIGH bug/security)
- Misc security, bug, and error-shape fixes surfaced by the health pass

### Humanized (Stage B/C — 15 HIGH + 14 MED)
- **Ollama-down lexical fallback** — compass returns keyword matches when the
  embedding backend is unreachable, with a clear degraded-mode marker
- **`trace_id` correlation** — every request carries a trace ID end-to-end for
  log stitching
- **Circuit breaker** on the embedder — opens after N consecutive failures,
  half-opens after a cooldown
- **Corrupt-config recovery** — malformed `compass_config.json` no longer
  crashes startup; loader falls back to defaults with a warning
- **`tool-compass doctor`** — diagnoses Ollama reachability, index presence,
  backend health, and prints actionable fixes

## [2.0.7] - 2026-03-25

### Added
- 5 version consistency tests (semver, >= 1.0.0, CHANGELOG, pyproject parse, CLI)

### Security
- SHA-pinned all GitHub Actions across 3 workflows (ci, pages, publish)

## [2.0.6] - 2026-02-27

### Added
- SHIP_GATE.md and SCORECARD.md (Shipcheck compliance)
- Makefile with `verify` target (lint + test + build)
- Security & Data Scope section and scorecard in README
- Standard email in SECURITY.md

### Changed
- Removed redundant h1 heading (logo already contains name)
- Replaced footer with standard MCP Tool Shop link
- Scorecard 46/50 → 50/50
- Bumped to 2.0.6

## [2.0.3] - 2026-02-14

### Fixed
- `categorize_tool()` now falls back to description matching when name has no category keywords
- `analytics.last_success_at` stores real timestamps instead of the literal string "CURRENT_TIMESTAMP"
- `SyncEmbedder` no longer crashes when called from inside a running event loop (Gradio, FastMCP)
- UI `run_async` helper replaced with deterministic loop detection (no more `RuntimeError` roulette)
- Removed discarded `sequence_hash` read in chain detection

### Changed
- Private `_backends` dict access replaced with public `is_backend_connected()` API
- `backend_client.py` renamed to `backend_client_mcp.py` (experimental; not used at runtime)
- Version reporting unified via `_version.py` module (reads from `importlib.metadata` or `pyproject.toml`)
- UI singletons protected with `threading.Lock` (Gradio is multi-threaded)
- Runtime assumptions documented in `gateway.py`

### Infrastructure
- Python 3.13 added to CI test matrix (3.10–3.13, 12 matrix jobs)
- `actions/checkout` normalized to v6 across all workflows
- `pip-audit` dependency vulnerability scan added (warn-only)
- `scripts/**` added to CI path triggers

### Tests
- 23 new tests: `backend_client_simple.py` API, `run_async` loop safety, `SyncEmbedder` loop safety, `_version.py` (387 → 410 tests)

## [2.0.2] - 2026-02-14

### Fixed
- Windows subprocess stability with `SimpleBackendManager` (#11)
- Auto-fix lint issues with ruff (#13)

### Changed
- Migrated all repository URLs to `mcp-tool-shop-org` GitHub organization
- Updated CI actions to latest major versions (checkout v6, setup-python v6, codecov v5)

### Infrastructure
- Added GHCR Docker publish workflow
- Added `llms.txt` for LLM discoverability
- Added social preview assets
- Updated dependency version ranges (black, pytest, pytest-cov, isort, gradio)

## [2.0.1] - 2026-01-18

### Added
- `pyproject.toml` for modern Python packaging (PEP 517/518)
- PyPI publishing workflow (GitHub Actions)
- Optional dependencies: `[ui]`, `[dev]`, `[all]`

### Changed
- Fixed CI workflow paths for standalone repository
- Removed hardcoded paths from documentation

### Infrastructure
- Published to PyPI as `tool-compass`
- Added `PYPI_API_TOKEN` secret for automated releases

## [2.0.0] - 2026-01-17

### Added
- **Gradio Web UI** (`ui.py`) - Interactive browser for tool discovery
  - Semantic search with confidence scores and text labels
  - Tool browser with server/category filtering
  - Workflow search and visualization
  - Analytics dashboard with usage metrics
  - System status with health checks
- **User-friendly error handling** - Graceful degradation when services unavailable
  - Ollama connection errors show helpful recovery steps
  - Missing index errors provide rebuild instructions
  - All errors include collapsible technical details
- **Input sanitization** - Query validation and length limits
- **Empty states** - Helpful guidance when no results/data
- **Text truncation** - Long names/descriptions truncate gracefully with tooltips

### Changed
- Confidence scores now show text labels ("Excellent/Good/Fair/Low") alongside percentages
- Improved responsive layout with flex-wrap for mobile
- System status tab now shows real-time Ollama health check

### Fixed
- Fixed `get_backend_tools()` method that was missing from `CompassIndex`
- Fixed potential SQL injection in tool search (was already safe, added explicit parameterization)

## [1.1.0] - 2026-01-16

### Added
- **Chain Indexer** (`chain_indexer.py`) - Workflow detection from usage patterns
  - Auto-detects common tool sequences
  - HNSW index for semantic workflow search
  - Manual workflow definition support
- **Analytics System** (`analytics.py`) - Usage tracking and hot cache
  - Search query tracking
  - Tool call success/failure rates
  - Latency monitoring
  - Hot cache for frequently used tools
- **Sync Manager** (`sync_manager.py`) - Backend synchronization
  - Multi-backend tool discovery
  - Incremental index updates
  - Connection pooling

### Changed
- Gateway now supports progressive disclosure (core tools first)
- Improved embedding generation with batching

## [1.0.0] - 2026-01-15

### Added
- **Core Gateway** (`gateway.py`) - MCP server with 9 tools
  - `compass(intent)` - Semantic tool search
  - `describe(tool_name)` - Get tool schema
  - `execute(tool_name, args)` - Run tools
  - `compass_categories()` - List categories
  - `compass_analytics()` - Usage stats
  - `compass_chains()` - Workflow management
  - `compass_sync()` - Rebuild index
  - `compass_audit()` - System report
- **HNSW Indexer** (`indexer.py`) - Vector search for tools
  - O(log n) approximate nearest neighbor search
  - SQLite metadata storage
  - Dynamic tool addition/removal
- **Ollama Embedder** (`embedder.py`) - nomic-embed-text integration
  - 768-dimensional embeddings
  - Async batch processing
  - Health checks and auto-recovery
- **Backend Client** (`backend_client.py`) - MCP backend proxy
  - stdio, HTTP, and import modes
  - Connection pooling
  - Timeout handling
- **Configuration** (`config.py`) - Environment-driven settings
  - YAML/JSON config files
  - Environment variable overrides
  - Sensible defaults
- **Tool Manifest** (`tool_manifest.py`) - Tool definitions
  - 44 tools across 5 backends
  - Category and server metadata
  - Example usage strings

### Infrastructure
- Dockerfile with multi-stage build
- docker-compose.yml for development
- GitHub Actions CI/CD pipeline
- pytest test suite with async support
- MIT License

---

## Version History

| Version | Date | Highlights |
|---------|------|------------|
| 2.0.3 | 2026-02-14 | Bug fixes, async safety, CI hygiene, 410 tests |
| 2.0.2 | 2026-02-14 | Org migration, CI updates, Windows fix |
| 2.0.0 | 2026-01-17 | Gradio UI, error handling, polish |
| 1.1.0 | 2026-01-16 | Workflows, analytics, sync |
| 1.0.0 | 2026-01-15 | Initial release |

[Unreleased]: https://github.com/mcp-tool-shop-org/tool-compass/compare/v2.2.0...HEAD
[2.2.0]: https://github.com/mcp-tool-shop-org/tool-compass/compare/v2.0.7...v2.2.0
[2.0.7]: https://github.com/mcp-tool-shop-org/tool-compass/compare/v2.0.6...v2.0.7
[2.0.6]: https://github.com/mcp-tool-shop-org/tool-compass/compare/v2.0.3...v2.0.6
[2.0.3]: https://github.com/mcp-tool-shop-org/tool-compass/compare/v2.0.2...v2.0.3
[2.0.2]: https://github.com/mcp-tool-shop-org/tool-compass/compare/v2.0.1...v2.0.2
[2.0.1]: https://github.com/mcp-tool-shop-org/tool-compass/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/mcp-tool-shop-org/tool-compass/compare/v1.1.0...v2.0.0
[1.1.0]: https://github.com/mcp-tool-shop-org/tool-compass/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/mcp-tool-shop-org/tool-compass/releases/tag/v1.0.0
