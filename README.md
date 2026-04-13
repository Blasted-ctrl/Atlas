# Atlas — Cloud Cost Intelligence Platform

A full-stack multi-cloud cost optimization platform. Atlas connects to your AWS, GCP, and Azure environments, maps spend to individual services and resources, and uses AI to surface the exact optimizations worth acting on.

[![CI](https://github.com/Blasted-ctrl/atlas/actions/workflows/ci.yml/badge.svg)](https://github.com/Blasted-ctrl/atlas/actions/workflows/ci.yml)

---

## What it does

- **Cost visibility** — Unified spend tracking across AWS, GCP, and Azure with daily breakdowns by service and environment
- **AI recommendations** — Enter your cloud profile and get prioritized, specific savings opportunities with confidence scores and estimated monthly impact
- **Resource inventory** — Track VMs, databases, and serverless functions with CPU/memory utilization to spot over-provisioning
- **Cost forecasting** — Project your 30-day trajectory using time-series models (ARIMA/SARIMA via Celery workers)
- **Rightsizing engine** — Constraint-based optimization solver identifying instances running below capacity

---

## Live demo flow

1. Visit the landing page and click **Get started**
2. Complete the 4-step onboarding wizard with your actual cloud spend and top services
3. The dashboard reflects your real data — no hardcoded numbers
4. Navigate to **Recommendations** and click **Generate AI insights**
5. Atlas AI analyzes your specific profile (providers, services, goals, pain points) and returns 5 tailored recommendations with savings estimates

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14 (App Router), TypeScript, Tailwind CSS, Framer Motion, Recharts |
| AI | Anthropic API (via Next.js Route Handler, key never exposed to browser) |
| Backend API | FastAPI (Python 3.11), SQLAlchemy 2.0, asyncpg |
| Task Queue | Celery 5, Redis broker |
| Forecasting | ARIMA/SARIMA (statsmodels, numpy, pandas) |
| Optimization | Custom constraint solver with greedy bin-packing |
| Database | PostgreSQL 16 with pgvector, time-series partitioning |
| Object Storage | MinIO (S3-compatible) |
| Observability | OpenTelemetry, Prometheus, Grafana |
| CI/CD | GitHub Actions, Docker multi-stage builds, ghcr.io |

---

## Project structure

```
atlas/
├── apps/
│   ├── web/          # Next.js 14 frontend
│   ├── api/          # FastAPI backend
│   └── worker/       # Celery task workers (forecasting, optimization)
├── packages/
│   ├── config/       # Shared env validation (Zod)
│   └── types/        # Shared TypeScript domain models
├── infra/
│   ├── postgres/     # Database migrations and analytics queries
│   ├── grafana/      # Dashboard provisioning
│   ├── prometheus/   # Scrape config
│   └── otel/         # OpenTelemetry collector config
├── api/
│   └── openapi.yaml  # OpenAPI 3.0 specification
├── .github/
│   └── workflows/    # CI (lint, test, build) + Docker publish
└── docker-compose.yml
```

---

## Getting started

### Option A: Frontend only (recommended for demo)

The frontend runs standalone with AI recommendations. No Docker required.

```bash
# 1. Install dependencies
cd apps/web
pnpm install

# 2. Set your Anthropic API key
cp ../../.env.example .env.local
# Edit .env.local and set ANTHROPIC_API_KEY=sk-ant-...

# 3. Start the dev server
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000). Complete the onboarding wizard, then generate AI recommendations from the dashboard.

### Option B: Full stack with Docker Compose

Runs all services: Next.js, FastAPI, Celery worker, PostgreSQL, Redis, MinIO, Prometheus, Grafana.

```bash
# 1. Copy and fill in environment variables
cp .env.example .env
# Edit .env — required: ANTHROPIC_API_KEY
# Optional: AWS/GCP/Azure credentials for real cost syncing

# 2. Start everything
docker compose up

# Services:
#   Frontend  → http://localhost:3000
#   API       → http://localhost:8000
#   API docs  → http://localhost:8000/docs
#   Grafana   → http://localhost:3001
#   MinIO     → http://localhost:9001
```

### Prerequisites

- Node.js 18+ and pnpm (`npm install -g pnpm`)
- Docker Desktop (for Option B)
- Anthropic API key ([console.anthropic.com](https://console.anthropic.com))

---

## Environment variables

Copy `.env.example` to `.env.local` (frontend) or `.env` (full stack) and fill in the required values.

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Powers AI recommendations |
| `DATABASE_URL` | Full stack only | PostgreSQL connection string |
| `REDIS_URL` | Full stack only | Redis connection string |
| `NEXT_PUBLIC_API_URL` | Full stack only | FastAPI base URL |
| `AWS_ACCESS_KEY_ID` | Optional | For real AWS cost data |
| `GOOGLE_APPLICATION_CREDENTIALS` | Optional | For real GCP cost data |
| `AZURE_TENANT_ID` | Optional | For real Azure cost data |

---

## Architecture

```
Browser
  └── Next.js (port 3000)
        ├── /api/ai/recommendations  →  Anthropic API  (AI insights)
        └── /api/*                   →  FastAPI (port 8000)
                                           ├── PostgreSQL (port 5432)
                                           └── Redis (port 6379)
                                                 └── Celery Worker
                                                       ├── Forecasting (ARIMA/SARIMA)
                                                       └── Optimization engine
```

User profile data (company, providers, spend, services, goals) is stored in `localStorage` on the client. The AI route handler reads this profile, builds a context-rich prompt, and calls the Anthropic API server-side so the key is never exposed.

---

## What's implemented

| Feature | Status |
|---------|--------|
| Landing page with animated hero | Complete |
| 4-step onboarding wizard | Complete |
| Dashboard with real user data | Complete |
| AI recommendations (Anthropic API) | Complete |
| Cost Explorer with charts | Complete (demo data) |
| Resource inventory | Complete (demo data) |
| Cloud accounts page | Complete (demo data) |
| Settings page | Complete |
| FastAPI health endpoint | Complete |
| Database schema and migrations | Complete |
| Celery forecasting pipeline | Complete |
| Constraint-based optimization engine | Complete |
| Docker Compose full stack | Complete |
| CI/CD (GitHub Actions) | Complete |
| Observability stack | Complete |
| Cloud provider cost sync | Planned |
| API CRUD endpoints (/v1/*) | Planned |
| Authentication / multi-tenant | Planned |

---

## Running tests

```bash
# Frontend
cd apps/web
pnpm lint
pnpm build

# FastAPI
cd apps/api
pip install -e ".[dev]"
pytest

# Celery worker
cd apps/worker
pip install -e ".[dev]"
pytest --cov=worker --cov-fail-under=80
```

---

## CI/CD

Every push runs:
1. Python lint (ruff) and tests for API and worker
2. Next.js lint and production build
3. Docker image build for all three services

Pushes to `main` additionally publish images to `ghcr.io/YOUR_USERNAME/atlas-{api,worker,web}`.

---

## Roadmap

- [ ] `/v1/accounts`, `/v1/costs`, `/v1/resources` API endpoints
- [ ] JWT authentication with organization-level multi-tenancy
- [ ] Live AWS Cost Explorer integration (boto3)
- [ ] Live GCP Billing API integration
- [ ] Live Azure Cost Management integration
- [ ] Scheduled cost sync via Celery beat
- [ ] Forecast persistence and trend alerts
- [ ] Slack/email notification webhooks

---

## License

MIT
