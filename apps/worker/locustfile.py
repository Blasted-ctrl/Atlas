from __future__ import annotations

import os
import random
import uuid
from datetime import UTC
from datetime import datetime

from locust import HttpUser
from locust import LoadTestShape
from locust import between
from locust import events
from locust import task

RESOURCE_POPULATION = int(os.getenv("ATLAS_LOCUST_RESOURCE_COUNT", "100000"))
RESOURCE_SAMPLE_SIZE = int(os.getenv("ATLAS_LOCUST_RESOURCE_SAMPLE_SIZE", "500"))
RESOURCE_REGION = os.getenv("ATLAS_LOCUST_REGION", "us-east-1")
RESOURCE_TYPE = os.getenv("ATLAS_LOCUST_RESOURCE_TYPE", "ec2_instance")
JOB_POLL_LIMIT = int(os.getenv("ATLAS_LOCUST_JOB_POLL_LIMIT", "8"))
JOB_POLL_PATH_TEMPLATE = os.getenv("ATLAS_LOCUST_JOB_POLL_PATH_TEMPLATE", "/optimize/{job_id}")
AUTH_HEADER = os.getenv("ATLAS_LOCUST_API_KEY")


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if AUTH_HEADER:
        headers["X-API-Key"] = AUTH_HEADER
    return headers


class ResourceUniverse:
    """Deterministic 100k-resource model used to simulate realistic API access patterns."""

    def __init__(self, size: int) -> None:
        self.size = size
        self._resource_ids = [f"res-{idx:06d}" for idx in range(size)]
        self._hotset = self._resource_ids[: max(1000, min(10000, size // 10))]

    def random_resource_id(self) -> str:
        # Most dashboards repeatedly query the hottest resources rather than uniform random scans.
        if random.random() < 0.8:
            return random.choice(self._hotset)
        return random.choice(self._resource_ids)

    def sample_scope_ids(self, count: int) -> list[str]:
        actual = max(1, min(count, self.size))
        return random.sample(self._resource_ids, actual)


UNIVERSE = ResourceUniverse(RESOURCE_POPULATION)


def _maybe_mark_unimplemented(response, endpoint_name: str) -> None:
    if response.status_code in {404, 405, 501}:
        response.success()
        events.request.fire(
            request_type="meta",
            name=f"{endpoint_name}:unimplemented",
            response_time=0,
            response_length=0,
            exception=None,
            context={"status_code": response.status_code},
        )
        return

    if response.status_code >= 400:
        response.failure(f"{endpoint_name} returned {response.status_code}")


class AtlasBaseUser(HttpUser):
    wait_time = between(0.5, 2.5)
    abstract = True

    def on_start(self) -> None:
        self.headers = _headers()

    def _poll_job(self, job_id: str, endpoint_name: str) -> None:
        for attempt in range(JOB_POLL_LIMIT):
            with self.client.get(
                JOB_POLL_PATH_TEMPLATE.format(job_id=job_id),
                headers=self.headers,
                name=f"{endpoint_name} poll",
                catch_response=True,
            ) as response:
                if response.status_code in {404, 405, 501}:
                    _maybe_mark_unimplemented(response, endpoint_name)
                    return
                if response.status_code >= 400:
                    response.failure(f"{endpoint_name} poll failed with {response.status_code}")
                    return

                payload = response.json()
                status = str(payload.get("status", "")).lower()
                if status in {"completed", "failed"}:
                    response.success()
                    return
                if attempt == JOB_POLL_LIMIT - 1:
                    response.failure("job did not finish within poll budget")


class DashboardUser(AtlasBaseUser):
    weight = 4

    @task(4)
    def health(self) -> None:
        with self.client.get("/health", headers=self.headers, name="GET /health", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"/health returned {response.status_code}")

    @task(3)
    def list_recommendations(self) -> None:
        params = {
            "limit": 100,
            "region": RESOURCE_REGION,
            "resource_id": self._resource_id_batch_csv(25),
            "sort": "savings_desc",
        }
        with self.client.get(
            "/recommendations",
            params=params,
            headers=self.headers,
            name="GET /recommendations",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                _maybe_mark_unimplemented(response, "GET /recommendations")

    @task(2)
    def list_usage(self) -> None:
        params = {
            "resource_id": self._resource_id_batch_csv(10),
            "metric": "cpu_utilization",
            "granularity": "1h",
            "limit": 100,
        }
        with self.client.get(
            "/usage",
            params=params,
            headers=self.headers,
            name="GET /usage",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                _maybe_mark_unimplemented(response, "GET /usage")

    @task(1)
    def get_forecasts(self) -> None:
        params = {
            "resource_id": UNIVERSE.random_resource_id(),
            "granularity": "daily",
            "limit": 30,
        }
        with self.client.get(
            "/forecasts",
            params=params,
            headers=self.headers,
            name="GET /forecasts",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                _maybe_mark_unimplemented(response, "GET /forecasts")

    def _resource_id_batch_csv(self, count: int) -> str:
        return ",".join(UNIVERSE.sample_scope_ids(count))


class OptimizationJobUser(AtlasBaseUser):
    weight = 2

    @task
    def trigger_optimization_job(self) -> None:
        sample_size = random.randint(50, RESOURCE_SAMPLE_SIZE)
        payload = {
            "scope": {
                "region": RESOURCE_REGION,
                "resource_type": RESOURCE_TYPE,
                "resource_ids": UNIVERSE.sample_scope_ids(sample_size),
            },
            "options": {
                "observation_period_days": 30,
                "include_reserved_instances": True,
                "include_savings_plans": True,
                "min_confidence_threshold": 0.7,
            },
            "submitted_at": datetime.now(UTC).isoformat(),
            "request_id": str(uuid.uuid4()),
        }
        with self.client.post(
            "/optimize",
            json=payload,
            headers=self.headers,
            name="POST /optimize",
            catch_response=True,
        ) as response:
            if response.status_code in {200, 202}:
                response.success()
                try:
                    body = response.json()
                except Exception as exc:  # pragma: no cover
                    response.failure(f"invalid optimize response JSON: {exc}")
                    return

                job_id = body.get("job_id") or body.get("id")
                if isinstance(job_id, str) and job_id:
                    self._poll_job(job_id, "POST /optimize")
                return

            _maybe_mark_unimplemented(response, "POST /optimize")


class AtlasLoadShape(LoadTestShape):
    """Ramp to sustained concurrency suitable for 100k-resource simulation."""

    stages = (
        {"duration": 60, "users": 20, "spawn_rate": 5},
        {"duration": 180, "users": 60, "spawn_rate": 10},
        {"duration": 360, "users": 120, "spawn_rate": 15},
        {"duration": 540, "users": 180, "spawn_rate": 20},
        {"duration": 720, "users": 240, "spawn_rate": 20},
    )

    def tick(self) -> tuple[int, int] | None:
        run_time = self.get_run_time()
        for stage in self.stages:
            if run_time < stage["duration"]:
                return stage["users"], stage["spawn_rate"]
        return None


@events.test_start.add_listener
def _announce_test_shape(environment, **_kwargs) -> None:
    environment.runner.greenlet.spawn(_log_population, environment)


def _log_population(environment) -> None:
    environment.events.request.fire(
        request_type="meta",
        name="load-profile",
        response_time=0,
        response_length=RESOURCE_POPULATION,
        exception=None,
        context={
            "resource_population": RESOURCE_POPULATION,
            "resource_scope_sample_size": RESOURCE_SAMPLE_SIZE,
        },
    )
