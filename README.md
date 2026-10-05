# hortum-et-bibliotheca

> *Si hortum in bibliotheca habes, deerit nihil.* — Cicero

A Python microservices monorepo: FastAPI services, a shared library, and an API gateway, managed as a [uv](https://docs.astral.sh/uv/) workspace.

## Architecture

```
                 ┌──────────────┐
  client ──────▶ │   gateway    │ :8000
                 └──────┬───────┘
          /api/a/*      │      /api/b/*
            ┌───────────┴───────────┐
            ▼                       ▼
     ┌─────────────┐         ┌─────────────┐
     │  service-a  │ ◀────── │  service-b  │
     │   :8001     │  HTTP   │   :8002     │
     └─────────────┘         └─────────────┘
```

| Service     | Port | Responsibility                                                |
|-------------|------|---------------------------------------------------------------|
| `gateway`   | 8000 | Single entry point. Routes `/api/{a,b}/...` to backends.      |
| `service-a` | 8001 | Example resource owner (`/items`, in-memory store).           |
| `service-b` | 8002 | Example consumer: builds `/summary` by calling `service-a`.   |

Every service gets these from `libs/common` (`hortum_common`):

- `/healthz` (liveness) and `/readyz` (readiness, with pluggable checks)
- `X-Request-ID` propagation across service hops, plus access logging
- Plain-text or JSON structured logging (`<PREFIX>_LOG_JSON=true`)
- Environment-driven config via `pydantic-settings`, with a per-service prefix

## Layout

```
.
├── libs/
│   └── common/              # shared app factory, settings, logging, health, middleware
├── services/
│   ├── gateway/
│   ├── service-a/
│   └── service-b/
│       ├── src/<package>/   # main.py, config.py, routes.py, ...
│       ├── tests/
│       ├── Dockerfile       # build context = repo root
│       └── pyproject.toml
├── docker-compose.yml
├── Makefile
└── pyproject.toml           # workspace root + ruff/mypy/pytest config
```

## Getting started

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/getting-started/installation/), Docker.

```sh
make install           # uv sync --all-packages
make check             # lint + typecheck + tests

make up                # full stack via docker compose
curl -X POST localhost:8000/api/a/items -H 'content-type: application/json' -d '{"name":"widget"}'
curl localhost:8000/api/b/summary
make down
```

To run one service with auto-reload outside Docker:

```sh
make run-service-a     # :8001
make run-service-b     # :8002
make run-gateway       # :8000
```

Each service serves interactive API docs at `/docs`.

## Configuration

Settings come from environment variables (or a `.env` file; see `.env.example`). Each service has its own prefix:

| Service     | Prefix        | Notable settings                               |
|-------------|---------------|------------------------------------------------|
| `gateway`   | `GATEWAY_`    | `SERVICE_A_URL`, `SERVICE_B_URL`, `UPSTREAM_TIMEOUT_SECONDS` |
| `service-a` | `SERVICE_A_`  |                                                |
| `service-b` | `SERVICE_B_`  | `SERVICE_A_URL`, `HTTP_TIMEOUT_SECONDS`        |

Common to all: `ENVIRONMENT`, `LOG_LEVEL`, `LOG_JSON`.

## Adding a service

1. Copy `services/service-a` to `services/<name>` and rename the package under `src/`.
2. Update `name`, `packages`, and the uvicorn module in the new `pyproject.toml` and `Dockerfile`.
3. Give it its own `env_prefix` in `config.py`.
4. Add it to `docker-compose.yml`, the CI image matrix, and (if it should be public) `Settings.upstreams()` in the gateway.
5. Add the package to `known-first-party` and `mypy_path` in the root `pyproject.toml`.

## License

Apache 2.0. See [LICENSE](LICENSE).
