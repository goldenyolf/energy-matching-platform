.DEFAULT_GOAL := help
BIN := .venv/bin
PYTHON := $(BIN)/python
MONTHS := 12

.PHONY: help install seed seed-taipower test lint format typecheck run dashboard \
        migrate revision docker-up docker-down docker-seed clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Create venv (uv preferred) and install deps
	@command -v uv >/dev/null 2>&1 && uv venv --python 3.12 && uv pip install -e ".[dashboard,dev]" || \
	  (python3 -m venv .venv && $(BIN)/pip install --upgrade pip && $(BIN)/pip install -e ".[dashboard,dev]")

seed: ## Load demo data (drops & recreates tables first)
	$(PYTHON) -m scripts.seed --reset

seed-taipower: ## Full Taipower scenario: demo + real wind (--fetch) + TPC contracts & demand. Override months: make seed-taipower MONTHS=24
	$(PYTHON) -m scripts.seed --reset --source sample
	$(PYTHON) -m scripts.seed --source taipower --fetch --months $(MONTHS)
	$(PYTHON) -m scripts.seed_taipower_contracts
	$(PYTHON) -m scripts.seed_taipower_demand

test: ## Run tests with coverage on the matching core
	$(BIN)/pytest --cov=app.matching --cov=app.services --cov-report=term-missing

lint: ## Ruff + black check + mypy
	$(BIN)/ruff check app tests
	$(BIN)/black --check app tests
	$(BIN)/mypy app

format: ## Auto-format (black) and auto-fix (ruff)
	$(BIN)/black app tests
	$(BIN)/ruff check --fix app tests

typecheck: ## Static type checking
	$(BIN)/mypy app

run: ## Start the FastAPI backend (http://localhost:8000)
	$(BIN)/uvicorn app.main:app --reload

dashboard: ## Start the Streamlit dashboard (http://localhost:8501)
	PYTHONPATH=. $(BIN)/streamlit run dashboard/Home.py

migrate: ## Apply DB migrations
	$(BIN)/alembic upgrade head

revision: ## Autogenerate a migration: make revision m="message"
	$(BIN)/alembic revision --autogenerate -m "$(m)"

docker-up: ## Build and start the full stack
	docker compose up --build

docker-down: ## Stop the stack
	docker compose down

docker-seed: ## Seed demo data inside the running api container
	docker compose exec api python -m scripts.seed --reset

clean: ## Remove caches and local sqlite DBs
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage *.db
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
