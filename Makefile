.DEFAULT_GOAL := help
SERVICES := gateway service-a service-b

.PHONY: help install lint fmt typecheck test check up down logs build run-%

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
	uv run mypy libs/common/src services/*/src

test: ## Run all tests
	uv run pytest

check: lint typecheck test ## Everything CI runs

run-%: ## Run one service locally with reload, e.g. make run-service-a
	@case "$*" in \
	  gateway)   pkg=gateway;   port=8000 ;; \
	  service-a) pkg=service_a; port=8001 ;; \
	  service-b) pkg=service_b; port=8002 ;; \
	  *) echo "unknown service: $*"; exit 1 ;; \
	esac; \
	uv run uvicorn $$pkg.main:app --reload --port $$port

build: ## Build all service images
	docker compose build

up: ## Start the full stack in the background
	docker compose up --build -d

down: ## Stop the stack
	docker compose down

logs: ## Tail logs from all services
	docker compose logs -f
