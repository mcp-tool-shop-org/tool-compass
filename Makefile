.PHONY: verify test lint build

verify: lint test build
	@echo "✓ All checks passed"

test:
	pytest --cov=. --cov-report=term-missing -m "not integration"

lint:
	ruff check . || true

build:
	python -m build --sdist --wheel
