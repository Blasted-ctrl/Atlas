# ─── Base ────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ─── System deps ─────────────────────────────────────────────────────────────
FROM base AS system-deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ─── Python deps ─────────────────────────────────────────────────────────────
FROM system-deps AS python-deps
COPY pyproject.toml ./
RUN pip install hatch && pip install -e .

# ─── Development ─────────────────────────────────────────────────────────────
FROM python-deps AS development
COPY . .
EXPOSE 9465
CMD ["celery", "-A", "worker.main", "worker", "--loglevel=info", "--concurrency=2"]

# ─── Production ──────────────────────────────────────────────────────────────
FROM python-deps AS production

RUN addgroup --system --gid 1001 atlas && \
    adduser --system --uid 1001 --gid 1001 atlas

COPY --chown=atlas:atlas . .
USER atlas

EXPOSE 9465
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD celery -A worker.main inspect ping -d "celery@$HOSTNAME" || exit 1

CMD ["celery", \
     "-A", "worker.main", \
     "worker", \
     "--loglevel=info", \
     "--concurrency=4", \
     "--queues=default,low_priority"]
