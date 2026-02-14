# Contributing to Tool Compass

First off, thank you for considering contributing to Tool Compass! This semantic search gateway for MCP tools is built by the community, and we welcome your help.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Running Tests](#running-tests)
- [Making Changes](#making-changes)
- [Pull Request Process](#pull-request-process)
- [Style Guide](#style-guide)
- [Architecture Overview](#architecture-overview)

## Code of Conduct

This project follows the [Contributor Covenant](https://www.contributor-covenant.org/). By participating, you are expected to uphold this code. Please report unacceptable behavior to the project maintainers.

## Getting Started

### Prerequisites

- **Python 3.10+**
- **Ollama** with `nomic-embed-text` model
- **Git** for version control

### Quick Start

```bash
# Clone the repository
git clone https://github.com/mcp-tool-shop-org/tool-compass.git
cd tool-compass/tool_compass

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # Development dependencies

# Start Ollama and pull embedding model
ollama pull nomic-embed-text

# Build the search index
python gateway.py --sync

# Run tests
pytest
```

## Development Setup

### Environment Variables

Tool Compass uses environment variables for cross-platform configuration:

| Variable | Description | Default |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | Project root directory | Parent of tool_compass |
| `TOOL_COMPASS_PYTHON` | Python executable path | Auto-detected |
| `TOOL_COMPASS_CONFIG` | Config file path | `./compass_config.json` |
| `OLLAMA_URL` | Ollama server URL | `http://localhost:11434` |

### Project Structure

```
tool_compass/
├── gateway.py           # MCP server with 9 tools
├── indexer.py           # HNSW index management
├── embedder.py          # Ollama embedding integration
├── analytics.py         # Usage tracking and hot cache
├── chain_indexer.py     # Workflow/chain detection
├── sync_manager.py      # Backend synchronization
├── config.py            # Configuration schema
├── ui.py                # Gradio web interface
├── backend_client.py    # MCP backend connections
├── tool_manifest.py     # Tool definitions
├── tests/               # Test suite
│   ├── conftest.py      # Shared fixtures
│   ├── test_config.py
│   ├── test_indexer.py
│   ├── test_analytics.py
│   └── test_gateway.py
└── db/                  # Index and analytics data
    ├── compass.hnsw     # HNSW vector index
    ├── tools.db         # Tool metadata
    └── compass_analytics.db
```

## Running Tests

### Unit Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/test_indexer.py

# Run specific test
pytest tests/test_indexer.py::TestCompassIndex::test_search_basic

# Run with verbose output
pytest -v
```

### Integration Tests

Integration tests require Ollama to be running:

```bash
# Run only integration tests
pytest -m integration

# Skip integration tests
pytest -m "not integration"
```

### Test Markers

- `@pytest.mark.asyncio` - Async tests (auto-applied)
- `@pytest.mark.integration` - Requires external services
- `@pytest.mark.slow` - Long-running tests

## Making Changes

### Branch Naming

- `feature/description` - New features
- `fix/description` - Bug fixes
- `docs/description` - Documentation
- `refactor/description` - Code refactoring

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
type(scope): description

[optional body]

[optional footer]
```

Examples:
```
feat(indexer): add dynamic tool insertion without rebuild
fix(gateway): handle concurrent initialization race condition
docs(readme): add Docker deployment instructions
test(analytics): add chain detection tests
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

### Development Workflow

1. **Create a branch** from `main`
2. **Make changes** with tests
3. **Run tests** locally: `pytest`
4. **Format code**: `black . && isort .`
5. **Lint**: `ruff check .`
6. **Commit** with descriptive message
7. **Push** and create PR

## Pull Request Process

### Before Submitting

- [ ] Tests pass locally (`pytest`)
- [ ] Code is formatted (`black`, `isort`)
- [ ] No linting errors (`ruff`)
- [ ] Documentation updated if needed
- [ ] Commit messages follow convention

### PR Template

```markdown
## Summary
Brief description of changes.

## Changes
- Added X
- Fixed Y
- Updated Z

## Testing
How to test these changes.

## Checklist
- [ ] Tests added/updated
- [ ] Documentation updated
- [ ] No breaking changes (or documented)
```

### Review Process

1. Maintainers will review within 3-5 business days
2. Address feedback in new commits (don't force-push)
3. Once approved, maintainer will merge

## Style Guide

### Python Style

- **Formatter**: [Black](https://black.readthedocs.io/) (line length 100)
- **Import sorting**: [isort](https://pycqa.github.io/isort/)
- **Linting**: [Ruff](https://docs.astral.sh/ruff/)
- **Type hints**: Required for public APIs

```python
# Good
async def search(
    self,
    query: str,
    top_k: int = 5,
    category_filter: Optional[str] = None,
) -> List[SearchResult]:
    """
    Search for tools matching the query intent.

    Args:
        query: Natural language description of task
        top_k: Maximum results to return
        category_filter: Optional category to filter by

    Returns:
        List of SearchResult ordered by relevance
    """
```

### Async Patterns

Use double-checked locking for async singletons:

```python
_instance: Optional[MyClass] = None
_lock = asyncio.Lock()

async def get_instance() -> MyClass:
    global _instance

    # Fast path
    if _instance is not None:
        return _instance

    # Slow path with lock
    async with _lock:
        if _instance is not None:
            return _instance
        _instance = MyClass()

    return _instance
```

### MCP Server Rules

- **Never print to stdout** - corrupts JSON-RPC protocol
- Use `logging` or `file=sys.stderr` for diagnostics
- Return structured dicts from tool functions
- Include `hint` field for user guidance

## Architecture Overview

### Core Components

```
                    ┌─────────────────┐
                    │   Claude/LLM    │
                    └────────┬────────┘
                             │ MCP Protocol
                    ┌────────▼────────┐
                    │    Gateway      │
                    │ (compass tools) │
                    └────────┬────────┘
           ┌─────────────────┼─────────────────┐
           │                 │                 │
    ┌──────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐
    │   Indexer   │   │  Analytics  │   │  Backends   │
    │  (HNSW +    │   │ (hot cache, │   │ (MCP server │
    │   SQLite)   │   │  chains)    │   │  proxying)  │
    └─────────────┘   └─────────────┘   └─────────────┘
```

### Data Flow

1. **Query**: User intent → Embedder → HNSW search → Results
2. **Execute**: Tool name → Backend manager → MCP call → Response
3. **Analytics**: Every operation → SQLite → Hot cache update

### Key Patterns

- **Progressive Disclosure**: compass → describe → execute
- **Semantic Search**: HNSW + nomic-embed-text embeddings
- **Token Reduction**: 95% savings vs loading all tool schemas

## Need Help?

- **Questions**: Open a [Discussion](https://github.com/mcp-tool-shop-org/tool-compass/discussions)
- **Bugs**: Open an [Issue](https://github.com/mcp-tool-shop-org/tool-compass/issues)
- **Security**: Use [GitHub Security Advisories](https://github.com/mcp-tool-shop-org/tool-compass/security/advisories/new) (do not open public issues)

---

Thank you for contributing! 🧭
