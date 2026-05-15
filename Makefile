.PHONY: verify test lint build dev dev-ui scorecard verify-scorecard verify-metrics

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

# CDS-FT-001 / CT-B-017: regenerate the auto-generated block of SCORECARD.md
# from shipcheck audit output, preserving hand-curated sections (Known Gaps,
# Remediation History, operator notes) between the SHIPCHECK-AUTO markers.
# `verify-scorecard` fails if the auto block drifts from what shipcheck emits.
# CI currently runs this as a soft-fail (continue-on-error) while the
# shipcheck markdown format settles — flip to hard-fail once stable.
scorecard:
	bash scripts/regenerate-scorecard.sh

verify-scorecard:
	bash scripts/regenerate-scorecard.sh --check

# CT-B-008: smoke-test the /metrics endpoint Four Golden Signals coverage.
# Boots the gateway briefly, scrapes /metrics, asserts the expected gauges
# and counters are present. Runs without Ollama (the metrics endpoint is
# tolerant of degraded backends).
verify-metrics:
	bash scripts/verify-metrics.sh
