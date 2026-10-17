# A4S+ backend image (FastAPI + PyTorch, CPU only).
#
# Build context: repository root.
#   docker build -f infra/docker/backend.Dockerfile -t a4s-plus/backend .
#
# NOTE: this file has been written but NOT built or executed, because the
# development sandbox used to author A4S+ has no Docker daemon. Treat it as
# reviewed-but-unverified infrastructure.

FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ---------------------------------------------------------------- dependencies
FROM base AS deps

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements-dev.txt ./

# CPU-only torch keeps the image an order of magnitude smaller than the default
# CUDA wheels. The prototype never needs a GPU.
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

# ---------------------------------------------------------------- runtime
FROM base AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 a4s

COPY --from=deps /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

COPY backend/ /app/

RUN mkdir -p /app/ml/artifacts && chown -R a4s:a4s /app

USER a4s

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health || exit 1

# Apply pending database migrations on startup before starting the server
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]