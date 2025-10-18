.PHONY: help format lint test build clean install dev

help:
	@echo "Available targets:"
	@echo "  make format    - Format code with black and isort"
	@echo "  make lint      - Run ruff linter and mypy type checker"
	@echo "  make test      - Run test suite with pytest"
	@echo "  make build     - Build wheel and source distribution"
	@echo "  make clean     - Remove build artifacts and cache files"
	@echo "  make install   - Install package in editable mode"
	@echo "  make dev       - Install package with dev dependencies"
	@echo "  make check     - Run format, lint, and test (CI pipeline)"

format:
	@echo "Running isort..."
	isort glogformat/ tests/
	@echo "Running black..."
	black glogformat/ tests/
	@echo "✓ Formatting complete"

lint:
	@echo "Running pylint..."
	pylint glogformat/ tests/
	@echo "Running mypy..."
	mypy glogformat/ tests/
	@echo "✓ Linting complete"

test:
	@echo "Running pytest..."
	pytest tests/ -v --cov=glogformat --cov-report=term-missing
	@echo "✓ Tests complete"

build: clean
	@echo "Building distribution..."
	python -m build
	@echo "✓ Build complete - see dist/"

clean:
	@echo "Cleaning build artifacts..."
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf htmlcov/
	rm -f .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.log" -delete
	@echo "✓ Clean complete"

install:
	@echo "Installing package in editable mode..."
	pip install -e .
	@echo "✓ Install complete"

dev:
	@echo "Installing package with dev dependencies..."
	pip install -e ".[test,dev]"
	@echo "✓ Dev install complete"

check: format lint test
	@echo "✓ All checks passed!"
