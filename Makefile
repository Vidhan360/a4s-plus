# A4S+ — AI-Assisted Altitude Safety System
# Team: The Third Eye — "From detection -> prediction -> prevention"
#
# Everything below runs against SIMULATED data. No real sensors, aircraft,
# people or terrain surveys are involved anywhere in this repository.

SHELL := /bin/bash
BACKEND := backend
FRONTEND := frontend
PY ?= python
COMPOSE ?= docker compose

.DEFAULT_GOAL := help
.PHONY: help install install-backend install-frontend migrate seed train \
        dev-api dev-web lint lint-backend lint-frontend format typecheck \
        test test-backend test-frontend e2e e2e-install verify \
        up down logs build-images honesty-scan clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1m%-18s\033[0m %s\n", $$1, $$2}'

# ------------------------------------------------------------------ setup
install: install-backend install-frontend ## Install backend + frontend dependencies

install-backend: ## Install Python dependencies (dev extras included)
	cd $(BACKEND) && $(PY) -m pip install -r requirements-dev.txt

install-frontend: ## Install Node dependencies
	cd $(FRONTEND) && npm ci

migrate: ## Apply Alembic migrations to the configured database
	cd $(BACKEND) && alembic upgrade head

seed: ## Seed demo users, personnel, terrain, config + 90 min of history
	cd $(BACKEND) && $(PY) -m seeds.seed --history 90

train: ## Train + compare rule baseline, LSTM and gradient boosting
	cd $(BACKEND) && $(PY) -m ml.train --subjects 480 --epochs 30

# ------------------------------------------------------------------ run
dev-api: ## Run the API with reload on 127.0.0.1:8000
	cd $(BACKEND) && uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

dev-web: ## Run the Next.js dev server on 127.0.0.1:3000
	cd $(FRONTEND) && npm run dev

# ------------------------------------------------------------------ quality
lint: lint-backend lint-frontend ## Lint both tiers

lint-backend: ## ruff check + format check
	cd $(BACKEND) && ruff check . && ruff format --check .

lint-frontend: ## next lint
	cd $(FRONTEND) && npm run lint

format: ## Auto-format both tiers
	cd $(BACKEND) && ruff format . && ruff check --fix .
	cd $(FRONTEND) && npx prettier --write "src/**/*.{ts,tsx,css}" "e2e/**/*.ts"

typecheck: ## mypy (strict) + tsc --noEmit
	cd $(BACKEND) && mypy app ml seeds
	cd $(FRONTEND) && npx tsc --noEmit

test: test-backend test-frontend ## Run unit/integration tests for both tiers

test-backend: ## Pytest (needs Postgres + Redis reachable)
	cd $(BACKEND) && $(PY) -m pytest -q

test-frontend: ## Vitest component/unit tests
	cd $(FRONTEND) && npx vitest run

e2e-install: ## Download the Playwright Chromium build
	cd $(FRONTEND) && npm run e2e:install

e2e: ## Playwright end-to-end suite (needs API + web running)
	cd $(FRONTEND) && npx playwright test

verify: lint typecheck test honesty-scan ## Full local gate, mirrors CI
	@echo "verify: OK"

honesty-scan: ## Fail on unjustified TODO/FIXME/placeholder markers
	@bash scripts/honesty-scan.sh

# ------------------------------------------------------------------ docker
up: ## Bring the full stack up with Docker Compose
	$(COMPOSE) up --build

down: ## Tear the stack down (keeps volumes)
	$(COMPOSE) down

logs: ## Follow API + frontend logs
	$(COMPOSE) logs -f api frontend

build-images: ## Build both container images without starting them
	$(COMPOSE) build

clean: ## Remove caches and build output
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.mypy_cache $(BACKEND)/.ruff_cache
	find $(BACKEND) -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf $(FRONTEND)/.next $(FRONTEND)/test-results $(FRONTEND)/playwright-report