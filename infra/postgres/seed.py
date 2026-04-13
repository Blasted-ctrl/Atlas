#!/usr/bin/env python3
"""
Atlas — Postgres Seed Script
=============================
Generates:
  • 10 000 cloud resources  (resources table)
  •  1 000 000 usage records (usage_metrics — partitioned)
  •  ~2 000 optimization runs + ~25 000 recommendations

Performance approach:
  - All bulk inserts use psycopg2 COPY (server-side binary stream)
    for maximum throughput (~100k rows/s on a local Postgres).
  - Resources are inserted first so FK constraints on usage_metrics
    and recommendations are satisfied.
  - Partitions covering the seed date range are created before
    usage_metrics data is written.

Usage:
    pip install psycopg2-binary faker tqdm
    python seed.py [--dsn "postgresql://atlas:atlas@localhost:5432/atlas"]
"""

from __future__ import annotations

import argparse
import io
import math
import random
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Generator

import psycopg2
import psycopg2.extras
from faker import Faker

# Optional pretty progress bars — falls back to plain print if unavailable
try:
    from tqdm import tqdm as _tqdm

    def progress(iterable, **kw):
        return _tqdm(iterable, **kw)

    def progress_bar(total: int, desc: str):
        return _tqdm(total=total, desc=desc, unit=" rows")

except ImportError:
    class _FakeBar:
        def __init__(self, total=0, desc=""):
            self._desc = desc
            self._total = total
            self._n = 0

        def update(self, n=1):
            self._n += n
            pct = 100 * self._n / max(self._total, 1)
            print(f"\r{self._desc}: {self._n}/{self._total} ({pct:.1f}%)", end="", flush=True)

        def close(self):
            print()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.close()

    def progress(iterable, **kw):
        desc = kw.get("desc", "")
        items = list(iterable)
        bar = _FakeBar(total=len(items), desc=desc)
        for item in items:
            bar.update()
            yield item
        bar.close()

    def progress_bar(total: int, desc: str):
        return _FakeBar(total=total, desc=desc)


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_DSN = "postgresql://atlas:atlas@localhost:5432/atlas"

NUM_RESOURCES    = 10_000
NUM_USAGE        = 1_000_000
USAGE_BATCH_SIZE = 50_000      # rows per COPY batch
REC_PER_RUN_MAX  = 20          # max recommendations per optimization run
NUM_RUNS         = 2_000

# Seed date window (usage_metrics will span this range)
SEED_DAYS_BACK = 30
NOW_UTC = datetime.now(tz=timezone.utc).replace(second=0, microsecond=0)
SEED_START = NOW_UTC - timedelta(days=SEED_DAYS_BACK)

fake = Faker()
rng = random.Random(42)  # reproducible

# ─────────────────────────────────────────────────────────────────────────────
# Domain constants
# ─────────────────────────────────────────────────────────────────────────────

PROVIDERS = ["aws", "gcp", "azure"]

RESOURCE_TYPES = [
    "ec2_instance",
    "rds_instance",
    "rds_cluster",
    "elasticache_cluster",
    "lambda_function",
    "s3_bucket",
    "eks_node_group",
    "elb",
    "ebs_volume",
    "cloudfront_distribution",
    "nat_gateway",
]

RESOURCE_STATUSES = ["running", "stopped", "terminated", "pending", "unknown"]
STATUS_WEIGHTS    = [0.70, 0.12, 0.08, 0.05, 0.05]

REGIONS: dict[str, list[str]] = {
    "aws":   ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1", "ap-northeast-1"],
    "gcp":   ["us-central1", "europe-west1", "asia-east1"],
    "azure": ["eastus", "westeurope", "southeastasia"],
}

INSTANCE_TYPES: dict[str, list[str]] = {
    "aws": [
        "t3.micro", "t3.small", "t3.medium", "t3.large",
        "m5.large", "m5.xlarge", "m5.2xlarge", "m5.4xlarge",
        "c5.large", "c5.xlarge", "c5.2xlarge",
        "r5.large", "r5.xlarge", "r5.2xlarge",
        "i3.large", "i3.xlarge",
        "db.t3.medium", "db.m5.large", "db.r5.xlarge",
    ],
    "gcp": [
        "n1-standard-1", "n1-standard-2", "n1-standard-4", "n1-standard-8",
        "n2-standard-2", "n2-standard-4",
        "e2-medium", "e2-standard-4",
    ],
    "azure": [
        "Standard_B1s", "Standard_B2s", "Standard_D2s_v3",
        "Standard_D4s_v3", "Standard_E2s_v3", "Standard_F4s_v2",
    ],
}

# Instance type → approximate hourly cost (USD)
INSTANCE_COST_HOURLY: dict[str, float] = {
    "t3.micro": 0.0104, "t3.small": 0.0208, "t3.medium": 0.0416,
    "t3.large": 0.0832, "m5.large": 0.096, "m5.xlarge": 0.192,
    "m5.2xlarge": 0.384, "m5.4xlarge": 0.768,
    "c5.large": 0.085, "c5.xlarge": 0.17, "c5.2xlarge": 0.34,
    "r5.large": 0.126, "r5.xlarge": 0.252, "r5.2xlarge": 0.504,
    "i3.large": 0.156, "i3.xlarge": 0.312,
    "db.t3.medium": 0.068, "db.m5.large": 0.171, "db.r5.xlarge": 0.48,
}

METRIC_NAMES = [
    "cpu_utilization",
    "memory_utilization",
    "network_in_bytes",
    "network_out_bytes",
    "disk_read_ops",
    "disk_write_ops",
]

GRANULARITIES = ["1m", "5m", "15m", "1h", "6h", "1d"]
GRANULARITY_WEIGHTS = [0.05, 0.10, 0.10, 0.60, 0.10, 0.05]

REC_TYPES = [
    "resize_down", "resize_up", "terminate", "schedule",
    "reserved_instance", "savings_plan", "graviton_migration",
]
REC_TYPE_WEIGHTS = [0.40, 0.05, 0.15, 0.15, 0.15, 0.05, 0.05]

REC_STATUSES = ["pending", "accepted", "rejected", "applied", "dismissed", "expired"]
REC_STATUS_WEIGHTS = [0.50, 0.15, 0.10, 0.10, 0.10, 0.05]

ENVIRONMENTS = ["production", "staging", "development", "qa", "sandbox"]
TEAMS = ["platform", "backend", "data", "ml", "frontend", "devops", "security"]

ACCOUNT_IDS = [str(rng.randint(100_000_000_000, 999_999_999_999)) for _ in range(20)]


# ─────────────────────────────────────────────────────────────────────────────
# Helper generators
# ─────────────────────────────────────────────────────────────────────────────

def random_tags() -> dict[str, str]:
    return {
        "Environment": rng.choice(ENVIRONMENTS),
        "Team":        rng.choice(TEAMS),
        "Project":     fake.slug(),
        "ManagedBy":   rng.choice(["terraform", "pulumi", "cloudformation", "manual"]),
    }


def random_monthly_cost(instance_type: str | None, resource_type: str) -> float:
    if instance_type and instance_type in INSTANCE_COST_HOURLY:
        hourly = INSTANCE_COST_HOURLY[instance_type]
        return round(hourly * 24 * 30 * rng.uniform(0.6, 1.0), 4)
    # Flat estimates for non-compute resources
    costs = {
        "s3_bucket":              rng.uniform(5, 500),
        "ebs_volume":             rng.uniform(8, 200),
        "cloudfront_distribution": rng.uniform(20, 600),
        "nat_gateway":            rng.uniform(32, 200),
        "lambda_function":        rng.uniform(0.5, 50),
        "elb":                    rng.uniform(16, 80),
    }
    return round(costs.get(resource_type, rng.uniform(10, 300)), 4)


def random_specs(resource_type: str, instance_type: str | None) -> dict:
    if resource_type in ("ec2_instance", "rds_instance", "rds_cluster"):
        vcpus = rng.choice([1, 2, 4, 8, 16, 32])
        return {
            "vcpus": vcpus,
            "memory_gib": vcpus * rng.choice([2, 4, 8]),
            "storage_gib": rng.choice([20, 50, 100, 200, 500, 1000]),
            "architecture": rng.choice(["x86_64", "arm64"]),
        }
    if resource_type == "ebs_volume":
        return {"size_gib": rng.choice([20, 50, 100, 500, 1000, 2000])}
    if resource_type == "s3_bucket":
        return {"size_gb": round(rng.uniform(0.1, 50_000), 2)}
    return {}


def generate_resources(n: int) -> list[dict]:
    rows = []
    used_external_ids: set[str] = set()
    for _ in range(n):
        provider = rng.choice(PROVIDERS)
        region = rng.choice(REGIONS[provider])
        rtype = rng.choices(RESOURCE_TYPES, weights=[
            20, 12, 5, 5, 15, 10, 5, 5, 10, 5, 8
        ])[0]
        status = rng.choices(RESOURCE_STATUSES, weights=STATUS_WEIGHTS)[0]
        account_id = rng.choice(ACCOUNT_IDS)

        # Compute instance type
        if rtype in ("ec2_instance", "rds_instance", "rds_cluster",
                     "elasticache_cluster", "eks_node_group"):
            instance_type = rng.choice(INSTANCE_TYPES[provider])
        else:
            instance_type = None

        # Deduplicated external ID
        while True:
            if provider == "aws":
                prefix = {"ec2_instance": "i-", "rds_instance": "db-",
                          "ebs_volume": "vol-", "elb": "arn:aws:elb:"}.get(rtype, "res-")
                ext_id = prefix + fake.hexify("????????????????")
            else:
                ext_id = fake.uuid4()
            key = (provider, account_id, ext_id)
            if key not in used_external_ids:
                used_external_ids.add(key)
                break

        now = datetime.now(tz=timezone.utc)
        created = fake.date_time_between(
            start_date="-2y", end_date="-7d", tzinfo=timezone.utc
        )
        monthly_cost = random_monthly_cost(instance_type, rtype)
        specs = random_specs(rtype, instance_type)
        network = {
            "vpc_id":          f"vpc-{fake.hexify('????????')}",
            "subnet_id":       f"subnet-{fake.hexify('????????')}",
            "security_groups": [f"sg-{fake.hexify('????????')}" for _ in range(rng.randint(1, 3))],
            "private_ip":      fake.ipv4_private(),
            "public_ip":       fake.ipv4_public() if rng.random() < 0.4 else None,
        } if rtype not in ("s3_bucket", "lambda_function") else {}

        rows.append({
            "id":                str(uuid.uuid4()),
            "external_id":       ext_id,
            "name":              f"{rng.choice(ENVIRONMENTS)}-{rtype.replace('_', '-')}-{rng.randint(1, 99):02d}",
            "type":              rtype,
            "provider":          provider,
            "account_id":        account_id,
            "region":            region,
            "availability_zone": f"{region}{'abc'[rng.randint(0, 2)]}" if rtype != "s3_bucket" else None,
            "status":            status,
            "instance_type":     instance_type,
            "tags":              psycopg2.extras.Json(random_tags()),
            "specs":             psycopg2.extras.Json(specs),
            "network":           psycopg2.extras.Json(network),
            "monthly_cost_usd":  monthly_cost,
            "created_at":        created,
            "updated_at":        created,
            "last_seen_at":      now - timedelta(minutes=rng.randint(0, 60)),
            "deleted_at":        None,
        })
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# COPY-based bulk insert helpers
# ─────────────────────────────────────────────────────────────────────────────

def copy_resources(cur, rows: list[dict]) -> None:
    """Bulk-insert resources via COPY."""
    buf = io.StringIO()
    cols = [
        "id", "external_id", "name", "type", "provider", "account_id",
        "region", "availability_zone", "status", "instance_type",
        "tags", "specs", "network", "monthly_cost_usd",
        "created_at", "updated_at", "last_seen_at", "deleted_at",
    ]

    for row in rows:
        line_values = []
        for col in cols:
            val = row[col]
            if val is None:
                line_values.append(r"\N")
            elif isinstance(val, psycopg2.extras.Json):
                # Escape JSON string for COPY text format
                json_str = val.adapted if hasattr(val, "adapted") else str(val)
                # Use psycopg2 to adapt
                escaped = str(val).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")
                line_values.append(escaped)
            elif isinstance(val, datetime):
                line_values.append(val.isoformat())
            else:
                line_values.append(str(val).replace("\t", "\\t").replace("\n", "\\n"))
        buf.write("\t".join(line_values) + "\n")

    buf.seek(0)
    cur.copy_from(buf, "resources", columns=cols, null=r"\N")


def usage_metrics_batch_generator(
    resource_ids: list[str],
    total: int,
    batch_size: int,
) -> Generator[io.StringIO, None, None]:
    """
    Yields StringIO buffers suitable for COPY FROM, each with `batch_size` rows.
    Distributes usage records across resource IDs, metrics, and timestamps.
    """
    per_resource = max(1, total // len(resource_ids))
    emitted = 0

    buf = io.StringIO()
    buf_rows = 0

    for resource_id in resource_ids:
        n_points = per_resource
        # Distribute over time window
        if n_points == 0:
            continue

        metric = rng.choices(METRIC_NAMES)[0]
        gran = rng.choices(GRANULARITIES, weights=GRANULARITY_WEIGHTS)[0]

        # Typical utilisation baseline for this resource (realistic variance)
        baseline = rng.uniform(5, 85)
        noise_std = baseline * 0.2

        step_minutes = {
            "1m": 1, "5m": 5, "15m": 15, "1h": 60, "6h": 360, "1d": 1440,
        }[gran]

        ts = SEED_START + timedelta(
            minutes=rng.randint(0, step_minutes)
        )

        for _ in range(n_points):
            if emitted >= total:
                break
            value = max(0.0, round(rng.gauss(baseline, noise_std), 4))
            unit = "Percent" if "utilization" in metric else (
                "Bytes" if "bytes" in metric else "Count"
            )
            row = "\t".join([
                r"\N",               # id (serial — let Postgres assign)
                resource_id,
                metric,
                gran,
                ts.isoformat(),
                str(value),
                unit,
                ts.isoformat(),     # created_at
            ])
            buf.write(row + "\n")
            buf_rows += 1
            emitted += 1

            ts += timedelta(minutes=step_minutes)
            if ts > NOW_UTC:
                ts = SEED_START + timedelta(
                    minutes=rng.randint(0, step_minutes)
                )

            if buf_rows >= batch_size:
                buf.seek(0)
                yield buf
                buf = io.StringIO()
                buf_rows = 0

        if emitted >= total:
            break

    if buf_rows > 0:
        buf.seek(0)
        yield buf


def generate_optimization_runs(n: int) -> list[dict]:
    rows = []
    statuses = ["queued", "running", "completed", "failed"]
    status_weights = [0.05, 0.05, 0.85, 0.05]
    for _ in range(n):
        status = rng.choices(statuses, weights=status_weights)[0]
        created = fake.date_time_between(
            start_date=SEED_START, end_date=NOW_UTC, tzinfo=timezone.utc
        )
        started_at = created + timedelta(seconds=rng.randint(1, 30)) if status != "queued" else None
        completed_at = (
            started_at + timedelta(seconds=rng.randint(30, 300))
            if status in ("completed", "failed") and started_at
            else None
        )
        rows.append({
            "id":                       str(uuid.uuid4()),
            "status":                   status,
            "scope":                    psycopg2.extras.Json({"account_id": rng.choice(ACCOUNT_IDS)}),
            "options":                  psycopg2.extras.Json({"observation_period_days": rng.choice([7, 14, 30])}),
            "started_at":               started_at,
            "completed_at":             completed_at,
            "recommendations_generated": rng.randint(0, REC_PER_RUN_MAX) if status == "completed" else 0,
            "resources_analyzed":        rng.randint(10, 500) if status == "completed" else 0,
            "total_savings_found_usd":   round(rng.uniform(100, 50_000), 4) if status == "completed" else 0,
            "error_message":            "worker timeout" if status == "failed" else None,
            "created_at":               created,
            "updated_at":               completed_at or started_at or created,
        })
    return rows


def generate_recommendations(
    resource_ids: list[str], run_ids: list[str], n: int
) -> list[dict]:
    rows = []
    for _ in range(n):
        resource_id = rng.choice(resource_ids)
        run_id = rng.choice(run_ids + [None] * 5)  # some unlinked
        rec_type = rng.choices(REC_TYPES, weights=REC_TYPE_WEIGHTS)[0]
        status = rng.choices(REC_STATUSES, weights=REC_STATUS_WEIGHTS)[0]
        savings = round(rng.uniform(1, 1_500), 4)
        confidence = round(rng.uniform(0.60, 0.99), 4)
        created = fake.date_time_between(
            start_date=SEED_START, end_date=NOW_UTC, tzinfo=timezone.utc
        )
        expires = created + timedelta(days=30)
        applied_at = (created + timedelta(days=rng.randint(1, 5))
                      if status == "applied" else None)
        dismissed_at = (created + timedelta(days=rng.randint(1, 14))
                        if status == "dismissed" else None)

        rows.append({
            "id":                   str(uuid.uuid4()),
            "resource_id":          resource_id,
            "optimization_run_id":  run_id,
            "type":                 rec_type,
            "status":               status,
            "title":                _rec_title(rec_type),
            "description":          fake.sentence(nb_words=12),
            "savings_usd_monthly":  savings,
            "confidence":           confidence,
            "details":              psycopg2.extras.Json(_rec_details(rec_type)),
            "expires_at":           expires,
            "applied_at":           applied_at,
            "dismissed_at":         dismissed_at,
            "rejection_reason":     fake.sentence() if status == "rejected" else None,
            "created_at":           created,
            "updated_at":           created,
            "deleted_at":           None,
        })
    return rows


def _rec_title(rec_type: str) -> str:
    titles = {
        "resize_down":       "Downsize to smaller instance type",
        "resize_up":         "Upsize to prevent performance issues",
        "terminate":         "Terminate idle resource",
        "schedule":          "Schedule resource to stop outside business hours",
        "reserved_instance": "Purchase Reserved Instance for cost savings",
        "savings_plan":      "Apply Compute Savings Plan",
        "graviton_migration": "Migrate to Graviton (ARM) instance type",
    }
    return titles.get(rec_type, "Optimization opportunity detected")


def _rec_details(rec_type: str) -> dict:
    if rec_type in ("resize_down", "resize_up", "graviton_migration"):
        cur = rng.choice(["m5.xlarge", "m5.2xlarge", "c5.xlarge", "r5.large"])
        rec = rng.choice(["m5.large", "t3.large", "m6g.large", "c6g.large"])
        return {
            "current_instance_type": cur,
            "recommended_instance_type": rec,
            "avg_cpu_utilization_percent": round(rng.uniform(1, 25), 2),
            "avg_memory_utilization_percent": round(rng.uniform(5, 40), 2),
            "observation_period_days": rng.choice([7, 14, 30]),
        }
    if rec_type == "terminate":
        return {
            "avg_cpu_utilization_percent": round(rng.uniform(0, 3), 2),
            "last_active_days_ago": rng.randint(14, 90),
        }
    if rec_type == "schedule":
        return {
            "start_cron": "0 8 * * MON-FRI",
            "stop_cron": "0 20 * * MON-FRI",
            "timezone": "America/New_York",
            "observation_period_days": 30,
        }
    return {"observation_period_days": 30}


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed Atlas Postgres database")
    parser.add_argument(
        "--dsn",
        default=DEFAULT_DSN,
        help=f"Postgres DSN (default: {DEFAULT_DSN})",
    )
    parser.add_argument(
        "--resources", type=int, default=NUM_RESOURCES,
        help=f"Number of resources to generate (default: {NUM_RESOURCES})",
    )
    parser.add_argument(
        "--usage", type=int, default=NUM_USAGE,
        help=f"Number of usage metric rows to generate (default: {NUM_USAGE})",
    )
    parser.add_argument(
        "--runs", type=int, default=NUM_RUNS,
        help=f"Number of optimization runs (default: {NUM_RUNS})",
    )
    parser.add_argument(
        "--truncate", action="store_true",
        help="Truncate all tables before seeding (dangerous — use only in dev/test)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print(f"Connecting to {args.dsn} …")
    conn = psycopg2.connect(args.dsn)
    conn.autocommit = False
    psycopg2.extras.register_uuid()

    with conn.cursor() as cur:

        # ── Optional truncate ────────────────────────────────────────────────
        if args.truncate:
            print("⚠  Truncating all tables …")
            cur.execute("""
                TRUNCATE usage_metrics, recommendations, optimization_runs, resources
                RESTART IDENTITY CASCADE;
            """)
            conn.commit()

        # ── Ensure partitions exist for the seed date window ─────────────────
        print(f"Creating partitions [{SEED_START.date()} → {NOW_UTC.date()}] …")
        cur.execute(
            "SELECT create_usage_metric_partitions(%s::DATE, %s::DATE)",
            (SEED_START.date(), NOW_UTC.date()),
        )
        created_partitions = cur.fetchone()[0]
        print(f"  {created_partitions} new partitions created.")
        conn.commit()

        # ── Resources ─────────────────────────────────────────────────────────
        t0 = time.perf_counter()
        print(f"\nGenerating {args.resources:,} resources …")
        resources = generate_resources(args.resources)
        resource_ids = [r["id"] for r in resources]

        with progress_bar(total=len(resources), desc="  INSERT resources") as bar:
            CHUNK = 1000
            for i in range(0, len(resources), CHUNK):
                chunk = resources[i : i + CHUNK]
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO resources (
                        id, external_id, name, type, provider, account_id,
                        region, availability_zone, status, instance_type,
                        tags, specs, network, monthly_cost_usd,
                        created_at, updated_at, last_seen_at, deleted_at
                    ) VALUES %s
                    ON CONFLICT (provider, account_id, external_id) DO NOTHING
                    """,
                    [
                        (
                            r["id"], r["external_id"], r["name"], r["type"],
                            r["provider"], r["account_id"], r["region"],
                            r["availability_zone"], r["status"], r["instance_type"],
                            r["tags"], r["specs"], r["network"],
                            r["monthly_cost_usd"], r["created_at"],
                            r["updated_at"], r["last_seen_at"], r["deleted_at"],
                        )
                        for r in chunk
                    ],
                    page_size=500,
                )
                bar.update(len(chunk))
        conn.commit()
        print(f"  Done in {time.perf_counter() - t0:.1f}s")

        # ── Optimization runs ─────────────────────────────────────────────────
        t0 = time.perf_counter()
        print(f"\nGenerating {args.runs:,} optimization runs …")
        runs = generate_optimization_runs(args.runs)
        run_ids = [r["id"] for r in runs]

        CHUNK = 500
        with progress_bar(total=len(runs), desc="  INSERT runs") as bar:
            for i in range(0, len(runs), CHUNK):
                chunk = runs[i : i + CHUNK]
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO optimization_runs (
                        id, status, scope, options,
                        started_at, completed_at,
                        recommendations_generated, resources_analyzed,
                        total_savings_found_usd, error_message,
                        created_at, updated_at
                    ) VALUES %s
                    """,
                    [
                        (
                            r["id"], r["status"], r["scope"], r["options"],
                            r["started_at"], r["completed_at"],
                            r["recommendations_generated"], r["resources_analyzed"],
                            r["total_savings_found_usd"], r["error_message"],
                            r["created_at"], r["updated_at"],
                        )
                        for r in chunk
                    ],
                    page_size=500,
                )
                bar.update(len(chunk))
        conn.commit()
        print(f"  Done in {time.perf_counter() - t0:.1f}s")

        # ── Recommendations ───────────────────────────────────────────────────
        num_recs = min(args.runs * 12, 25_000)
        t0 = time.perf_counter()
        print(f"\nGenerating {num_recs:,} recommendations …")
        recs = generate_recommendations(resource_ids, run_ids, num_recs)

        with progress_bar(total=len(recs), desc="  INSERT recommendations") as bar:
            for i in range(0, len(recs), CHUNK):
                chunk = recs[i : i + CHUNK]
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO recommendations (
                        id, resource_id, optimization_run_id,
                        type, status, title, description,
                        savings_usd_monthly, confidence, details,
                        expires_at, applied_at, dismissed_at, rejection_reason,
                        created_at, updated_at, deleted_at
                    ) VALUES %s
                    """,
                    [
                        (
                            r["id"], r["resource_id"], r["optimization_run_id"],
                            r["type"], r["status"], r["title"], r["description"],
                            r["savings_usd_monthly"], r["confidence"], r["details"],
                            r["expires_at"], r["applied_at"], r["dismissed_at"],
                            r["rejection_reason"], r["created_at"], r["updated_at"],
                            r["deleted_at"],
                        )
                        for r in chunk
                    ],
                    page_size=500,
                )
                bar.update(len(chunk))
        conn.commit()
        print(f"  Done in {time.perf_counter() - t0:.1f}s")

        # ── Usage metrics (COPY for maximum throughput) ────────────────────────
        t0 = time.perf_counter()
        print(f"\nStreaming {args.usage:,} usage_metrics rows via COPY …")

        usage_cols = (
            "id", "resource_id", "metric", "granularity",
            "ts", "value", "unit", "created_at"
        )

        total_inserted = 0
        with progress_bar(total=args.usage, desc="  COPY usage_metrics") as bar:
            for batch_buf in usage_metrics_batch_generator(
                resource_ids, args.usage, USAGE_BATCH_SIZE
            ):
                # COPY text format: tab-delimited, \N for NULL
                cur.copy_from(
                    batch_buf,
                    "usage_metrics",
                    columns=usage_cols,
                    null=r"\N",
                    sep="\t",
                )
                rows_in_batch = batch_buf.tell() - batch_buf.seek(0) or USAGE_BATCH_SIZE
                # Approximate: each row ends with \n
                n = batch_buf.read().count("\n")
                batch_buf.seek(0)
                conn.commit()   # commit per batch to avoid long transactions
                total_inserted += n
                bar.update(n)

        print(f"  Done in {time.perf_counter() - t0:.1f}s  ({total_inserted:,} rows committed)")

    conn.close()
    print("\n✓ Seed complete.")


if __name__ == "__main__":
    main()
