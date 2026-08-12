.PHONY: help install install-uv dev test test-cov lint lint-fix format type-check pre-commit clean run migrate migration check

# Default target
help:
	@echo "Available commands:"
	@echo "  make install        - Install dependencies using uv (required)"
	@echo "  make dev            - Set up development environment"
	@echo "  make test           - Run tests"
	@echo "  make test-cov       - Run tests with coverage"
	@echo "  make lint           - Run linter (Ruff)"
	@echo "  make format         - Format code (Ruff)"
	@echo "  make type-check     - Run type checker (mypy)"
	@echo "  make pre-commit     - Run all pre-commit hooks"
	@echo "  make clean          - Clean cache and temporary files"
	@echo "  make run            - Run the FastAPI application"
	@echo "  make migrate        - Run database migrations"

# Install dependencies using uv (required)
install:
	uv pip install -e ".[dev]"

# Set up development environment (requires uv)
dev:
	@echo "Setting up development environment..."
	uv pip install -e ".[dev]"
	pre-commit install
	@echo ""
	@echo "Development environment ready!"
	@echo "Next steps:"
	@echo "  1. Copy .env.example to .env and configure"
	@echo "  2. Run 'make migrate' to set up the database"
	@echo "  3. Run 'make run' to start the application"

# Run tests
test:
	pytest

# Run tests with coverage
test-cov:
	pytest --cov=src --cov-report=term-missing --cov-report=html

# Run linter
lint:
	ruff check .

# Run linter with auto-fix
lint-fix:
	ruff check . --fix

# Format code
format:
	ruff format .

# Run type checker
type-check:
	mypy src/

# Run all pre-commit hooks
pre-commit:
	pre-commit run --all-files

# Clean cache and temporary files
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf build/ dist/ htmlcov/ .coverage 2>/dev/null || true
	@echo "Cleaned cache and temporary files"

# Run the FastAPI application
run:
	uvicorn src.main:app --reload

# Run database migrations
migrate:
	alembic upgrade head

# Create a new migration
migration:
	@read -p "Enter migration message: " msg; \
	alembic revision --autogenerate -m "$$msg"

# Check code quality (lint + type-check + tests)
check: lint type-check test
	@echo "All checks passed!"
