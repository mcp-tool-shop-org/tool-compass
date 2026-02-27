# Changelog

All notable changes to Tool Compass will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[Unreleased]: https://github.com/mcp-tool-shop-org/tool-compass/compare/v2.0.3...HEAD
[2.0.3]: https://github.com/mcp-tool-shop-org/tool-compass/compare/v2.0.2...v2.0.3
[2.0.2]: https://github.com/mcp-tool-shop-org/tool-compass/compare/v2.0.1...v2.0.2
[2.0.1]: https://github.com/mcp-tool-shop-org/tool-compass/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/mcp-tool-shop-org/tool-compass/compare/v1.1.0...v2.0.0
[1.1.0]: https://github.com/mcp-tool-shop-org/tool-compass/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/mcp-tool-shop-org/tool-compass/releases/tag/v1.0.0
