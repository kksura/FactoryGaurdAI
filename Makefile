SHELL := /bin/bash
VENV := .venv/bin
PROFILE ?= small
FG_ENVIRONMENT ?= local

.PHONY: setup doctor lint typecheck test test-security test-performance \
        generate-data validate-data train-baseline train-multimodal evaluate \
        serve dashboard up down sbom scan clean help

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

setup: ## Create venv, compile locks, install pinned deps (incl. torch)
	bash scripts/setup_env.sh
	$(VENV)/pre-commit install 2>/dev/null || true

doctor: ## Verify environment health (python, GPU, CUDA, deps, docker)
	$(VENV)/python scripts/doctor.py

lint: ## Ruff lint + format check
	$(VENV)/ruff check src apps pipelines scripts tests
	$(VENV)/ruff format --check src apps pipelines scripts tests

typecheck: ## mypy on src
	$(VENV)/mypy

test: ## Unit + contract tests (fast, no services)
	$(VENV)/pytest tests/unit tests/contract tests/ml -m "not integration and not gpu and not slow"

test-security: ## Security test suite + static scans
	$(VENV)/pytest tests/security -m "not integration"
	$(VENV)/bandit -c pyproject.toml -q -r src apps pipelines scripts
	$(VENV)/pip-audit -r requirements/lock.txt || true

test-performance: ## Performance benchmarks (writes docs/performance/)
	$(VENV)/pytest tests/performance -m "not integration"

generate-data: ## Generate synthetic dataset: make generate-data PROFILE=tiny|small|medium|large
	$(VENV)/python -m pipelines.data.generate --profile $(PROFILE)

validate-data: ## Validate the generated dataset for PROFILE
	$(VENV)/python -m pipelines.data.validate --profile $(PROFILE)

train-baseline: ## Train baseline models on PROFILE
	$(VENV)/python -m pipelines.training.train_baselines --profile $(PROFILE)

train-multimodal: ## Train multimodal fusion models on PROFILE
	$(VENV)/python -m pipelines.training.train_multimodal --profile $(PROFILE)

evaluate: ## Run full evaluation and write reports
	$(VENV)/python -m pipelines.evaluation.evaluate --profile $(PROFILE)

serve: ## Run the API locally (http://127.0.0.1:8000)
	FG_ENVIRONMENT=$(FG_ENVIRONMENT) $(VENV)/uvicorn apps.api.main:app --host 127.0.0.1 --port 8000

dashboard: ## Run the Streamlit dashboard (http://127.0.0.1:8501)
	$(VENV)/streamlit run apps/dashboard/main.py --server.address 127.0.0.1

up: ## Start the full local stack (postgres, minio, mlflow, prometheus, grafana, api)
	docker compose up -d --build

down: ## Stop the local stack
	docker compose down

sbom: ## Generate SBOM (syft via container) into sbom/
	bash scripts/sbom.sh

scan: ## Container + dependency vulnerability scans (trivy via container)
	bash scripts/scan.sh

clean: ## Remove caches (keeps venv and data)
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
