# hortum-et-bibliotheca

> *Si hortum in bibliotheca habes, deerit nihil.* — Cicero

A study tool for quiz bowl: search a topic, see the clues that matter most, and learn it through summaries, buzzer practice and flashcards. It's built as Python microservices (FastAPI) plus an offline data pipeline, managed as a [uv](https://docs.astral.sh/uv/) workspace.

The full design and build plan are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Architecture

```
                         ┌──────────────┐
  browser ─────────────▶ │   gateway    │ :8000
                         └──────┬───────┘
         /api/catalog/*         │ /api/content/*       /api/study/*
        ┌───────────────────────┼──────────────────────┐
        ▼                       ▼                      ▼
 ┌─────────────┐         ┌─────────────┐        ┌─────────────┐
 │   catalog   │ :8001   │   content   │ :8002  │    study    │ :8003
 └──────┬──────┘         └──────┬──────┘        └──────┬──────┘
   corpus.db              content.db              study.db
 (built by pipeline)   (fetched + generated)    (your progress)
```

| Component  | Port | Responsibility                                                         |
|------------|------|------------------------------------------------------------------------|
| `gateway`  | 8000 | Single entry point. Routes `/api/{catalog,content,study}/...`.          |
| `catalog`  | 8001 | Search and precomputed topic data from the read-only `corpus.db`.       |
| `content`  | 8002 | Wikipedia, books, videos and AI-written sections, cached per topic.     |
| `study`    | 8003 | Flashcards, review scheduling and buzz history.                        |
| `pipeline` | —    | Offline CLI that builds `corpus.db` from `data/raw/tossups.json`.       |

Every service gets these from `libs/common` (`hortum_common`):

- `/healthz` (liveness) and `/readyz` (readiness, with pluggable checks)
- `X-Request-ID` propagation across service hops, plus access logging
- Plain-text or JSON structured logging (`<PREFIX>_LOG_JSON=true`)
- Environment-driven config via `pydantic-settings`, with a per-service prefix

## Layout

```
.
├── data/                    # gitignored: raw dump, caches, built databases
├── docs/ARCHITECTURE.md     # design and build plan
├── libs/common/             # shared app factory, settings, logging, health, middleware
├── pipeline/                # hortum-pipeline CLI (one subcommand per stage)
├── services/
│   ├── gateway/
│   ├── catalog/
│   ├── content/
│   └── study/
│       ├── src/<package>/   # main.py (build_app factory), config.py, ...
│       ├── tests/
│       ├── Dockerfile       # build context = repo root
│       └── pyproject.toml
├── docker-compose.yml
├── Makefile
└── pyproject.toml           # workspace root + ruff/mypy/pytest config
```

## Getting started

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/getting-started/installation/), Docker. Put the raw dump at `data/raw/tossups.json`.

```sh
make install           # uv sync --all-packages
make check             # lint + typecheck + tests

make pipeline          # build data/build/corpus.db (stages arrive phase by phase)
make up                # full stack via docker compose
curl localhost:8000/healthz
make down
```

To run one service with auto-reload outside Docker:

```sh
make run-gateway       # :8000
make run-catalog       # :8001
make run-content       # :8002
make run-study         # :8003
```

Each service serves interactive API docs at `/docs`.

## Building the corpus

```sh
uv run hortum-pipeline all --gui          # every stage, with a progress window
uv run hortum-pipeline parse-answers --gui # just re-parse answers
uv run hortum-pipeline review-answers      # fix low-confidence answers by hand
uv run hortum-pipeline all --from group    # rebuild topics after fixing answers
uv run hortum-pipeline link --max-requests 2000  # link in chunks; cached requests are free
```

The review window lists answer lines the parser wasn't sure about, most-asked first, with
similar answers from the data as suggestions. Fixes are saved to
`pipeline/overrides/answers.jsonl` (commit it) and re-applied on every run. **Rerun
corrected** writes just those fixes into `corpus.db`.

Linking needs contact details in `PIPELINE_WIKIMEDIA_USER_AGENT` (see `.env.example`):
Wikimedia refuses requests without them.

## Configuration

Settings come from environment variables (or a `.env` file; see `.env.example`). Each service has its own prefix:

| Component  | Prefix      | Notable settings                                         |
|------------|-------------|----------------------------------------------------------|
| `gateway`  | `GATEWAY_`  | `CATALOG_URL`, `CONTENT_URL`, `STUDY_URL`, `UPSTREAM_TIMEOUT_SECONDS` |
| `catalog`  | `CATALOG_`  | `CORPUS_PATH`                                            |
| `content`  | `CONTENT_`  | `DB_PATH`, `CATALOG_URL`                                 |
| `study`    | `STUDY_`    | `DB_PATH`, `BACKUP_DIR`                                  |
| `pipeline` | `PIPELINE_` | `DATA_DIR`, `WIKIMEDIA_USER_AGENT`                       |

Common to all: `ENVIRONMENT`, `LOG_LEVEL`, `LOG_JSON`.

## Adding a service

1. Copy `services/study` to `services/<name>` and rename the package under `src/`.
2. Update `name`, `packages`, and the uvicorn module in the new `pyproject.toml` and `Dockerfile`.
3. Give it its own `env_prefix` in `config.py`.
4. Add it to `docker-compose.yml`, the CI image matrix, and (if it should be public) `Settings.upstreams()` in the gateway.
5. Add the package to `known-first-party` and `mypy_path` in the root `pyproject.toml`.

## License

Apache 2.0. See [LICENSE](LICENSE).
