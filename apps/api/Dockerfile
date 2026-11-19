# EASA API image (P8-M5, ADR-039). Built by compose.yaml (profile "app"):
#   docker compose --profile app up -d --build
# Base images are pinned by digest; dependencies come only from uv.lock.

FROM ghcr.io/astral-sh/uv:0.12.9@sha256:8b940d3a9d65bed080436972241af2e21c84b5e8c9193f7014ed71479ee795ff AS uv

FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
# The synthetic evaluation data: the demo loads documents from it, and the
# evaluations can run inside the container.
COPY eval ./eval

FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f
RUN groupadd --system --gid 10001 easa \
    && useradd --system --uid 10001 --gid easa --home-dir /app --shell /usr/sbin/nologin easa \
    && mkdir -p /data/uploads \
    && chown easa:easa /data/uploads
COPY --from=build /opt/venv /opt/venv
COPY --from=build /app /app
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    EASA_STORAGE_DIR=/data/uploads
WORKDIR /app
USER easa
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=12 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"]
# Migrations run on every start (idempotent). Uvicorn does not trust
# X-Forwarded-For itself; proxy trust is EASA_TRUSTED_PROXIES (ADR-035).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --no-access-log --no-proxy-headers"]
