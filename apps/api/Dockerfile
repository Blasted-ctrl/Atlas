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

# Install hatch + project deps
RUN pip install hatch && \
    hatch env create && \
    pip install -e .

# ─── Development ─────────────────────────────────────────────────────────────
FROM python-deps AS development
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ─── Production ──────────────────────────────────────────────────────────────
FROM python-deps AS production
ENV API_RELOAD=false

# Create non-root user
RUN addgroup --system --gid 1001 atlas && \
    adduser --system --uid 1001 --gid 1001 atlas

COPY --chown=atlas:atlas . .
USER atlas

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "4", \
     "--log-config", "/dev/null"]
