"""Cost synchronization tasks.

These tasks pull cost and usage data from cloud provider APIs and persist
them to the Atlas database.
"""

from __future__ import annotations

import structlog
from celery import Task
from tenacity import retry
from tenacity import stop_after_attempt
from tenacity import wait_exponential

from worker.main import app

logger = structlog.get_logger(__name__)


class BaseTask(Task):  # type: ignore[misc]
    """Base task class with structured logging."""

    abstract = True

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple,  # type: ignore[type-arg]
        kwargs: dict,  # type: ignore[type-arg]
        einfo: object,
    ) -> None:
        logger.error(
            "task_failed",
            task=self.name,
            task_id=task_id,
            error=str(exc),
        )

    def on_success(self, retval: object, task_id: str, args: tuple, kwargs: dict) -> None:  # type: ignore[type-arg]
        logger.info("task_succeeded", task=self.name, task_id=task_id)


@app.task(
    base=BaseTask,
    bind=True,
    name="worker.tasks.cost_sync.sync_all_accounts",
    max_retries=3,
    default_retry_delay=60,
)
def sync_all_accounts(self: Task) -> dict[str, int]:  # type: ignore[type-arg]
    """Fan out cost sync jobs for every active cloud account.

    Returns:
        Dict mapping provider name to number of accounts queued.
    """
    log = logger.bind(task_id=self.request.id)
    log.info("sync_all_accounts_start")

    # TODO: query DB for all active CloudAccount records
    # For now returns stub counts
    queued: dict[str, int] = {"aws": 0, "gcp": 0, "azure": 0}

    # Example fan-out:
    # accounts = db.query(CloudAccount).filter_by(is_active=True).all()
    # for account in accounts:
    #     sync_account_costs.delay(account_id=str(account.id))
    #     queued[account.provider] += 1

    log.info("sync_all_accounts_complete", queued=queued)
    return queued


@app.task(
    base=BaseTask,
    bind=True,
    name="worker.tasks.cost_sync.sync_account_costs",
    max_retries=5,
    default_retry_delay=120,
)
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    reraise=True,
)
def sync_account_costs(self: Task, account_id: str) -> dict[str, object]:  # type: ignore[type-arg]
    """Pull cost & usage data for a single cloud account.

    Args:
        account_id: UUID of the CloudAccount record.

    Returns:
        Summary of records upserted.
    """
    log = logger.bind(task_id=self.request.id, account_id=account_id)
    log.info("sync_account_costs_start")

    # TODO: implement provider-specific sync logic
    # 1. Load account + credentials from DB
    # 2. Call AWS Cost Explorer / GCP Billing / Azure Cost Management API
    # 3. Upsert CostRecord rows
    # 4. Trigger refresh_recommendations for the account

    result = {"account_id": account_id, "records_upserted": 0, "status": "stub"}
    log.info("sync_account_costs_complete", **result)
    return result
