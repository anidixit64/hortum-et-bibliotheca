# syntax=docker/dockerfile:1.7
# Build context is the repository root: docker build -f services/gateway/Dockerfile .
# The frontend, built once and served by the gateway.
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
RUN npm run build

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never VIRTUAL_ENV=/opt/venv
WORKDIR /build
RUN uv venv /opt/venv
COPY libs/common libs/common
COPY services/gateway services/gateway
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --no-sources ./libs/common ./services/gateway

FROM python:3.12-slim AS runtime
RUN useradd --create-home --uid 10001 app
COPY --from=builder /opt/venv /opt/venv
COPY --from=web /web/dist /srv/web
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    GATEWAY_WEB_DIST=/srv/web
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"]
CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
