.DEFAULT_GOAL := help
SERVICES := gateway catalog content study

.PHONY: help install lint fmt typecheck test check pipeline up down logs build run-% web web-dev web-check

help: ## Show available targets
	@grep -E '^[a-zA-Z_%-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install all workspace packages + dev tools into .venv
	uv sync --all-packages

lint: ## Lint with ruff
	uv run ruff check .
	uv run ruff format --check .

fmt: ## Auto-format and fix lint issues
	uv run ruff format .
	uv run ruff check --fix .

typecheck: ## Type-check with mypy
	uv run mypy libs/common/src pipeline/src services/*/src

test: ## Run all tests
	uv run pytest

check: lint typecheck test ## Everything CI runs (Python; see web-check)

web: ## Build the frontend into web/dist (the gateway serves it: GATEWAY_WEB_DIST=web/dist)
	cd web && npm ci && npm run build

web-dev: ## Frontend dev server on :5173, proxying /api to the gateway on :8000
	cd web && npm run dev

web-check: ## Type-check, lint and test the frontend
	cd web && npm run typecheck && npm run lint && npm test

run-%: ## Run one service locally with reload, e.g. make run-catalog
	@case "$*" in \
	  gateway) pkg=gateway; port=8000 ;; \
	  catalog) pkg=catalog; port=8001 ;; \
	  content) pkg=content; port=8002 ;; \
	  study)   pkg=study;   port=8003 ;; \
	  *) echo "unknown service: $*"; exit 1 ;; \
	esac; \
	uv run uvicorn $$pkg.main:app --reload --port $$port

pipeline: ## Run every pipeline stage to build data/build/corpus.db
	uv run hortum-pipeline all

build: ## Build all service images
	docker compose build

up: ## Start the full stack in the background
	docker compose up --build -d

down: ## Stop the stack
	docker compose down

logs: ## Tail logs from all services
	docker compose logs -f
