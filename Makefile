.PHONY: verify test lint build dev dev-ui scorecard verify-scorecard

verify: lint test build
	@echo "✓ All checks passed"

test:
	pytest --cov=. --cov-report=term-missing --cov-fail-under=60 -m "not integration"

lint:
	ruff check .

build:
	python -m build --sdist --wheel

# CDS-FT-002: fast local loop. `make dev` installs in editable mode with the
# `all` extra and starts the gateway in HTTP mode on PORT=8000. Warns if
# Ollama isn't reachable — doesn't hard-fail so users can develop offline.
dev:
	pip install -e .[all]
	@curl -sf http://localhost:11434/api/tags > /dev/null || echo "⚠️  Ollama not reachable at http://localhost:11434 — start with 'ollama serve'"
	@echo "Starting gateway in HTTP mode on PORT=8000..."
	PORT=8000 python gateway.py

dev-ui:
	pip install -e .[all]
	python ui.py

# CDS-FT-001: regenerate SCORECARD.md from shipcheck audit output.
# `verify-scorecard` fails if SCORECARD.md drifts from what shipcheck emits.
# CI currently runs this as a soft-fail (continue-on-error) while the
# shipcheck markdown format settles — flip to hard-fail once stable.
scorecard:
	npx @mcptoolshop/shipcheck audit --format markdown > SCORECARD.md
	@echo "Regenerated SCORECARD.md"

verify-scorecard:
	npx @mcptoolshop/shipcheck audit --format markdown > /tmp/scorecard-generated.md
	@diff -u SCORECARD.md /tmp/scorecard-generated.md || { echo "SCORECARD.md is out of sync — run 'make scorecard'"; exit 1; }
