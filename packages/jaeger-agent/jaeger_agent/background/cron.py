"""Natural Language & Periodic Cron Scheduler for JaegerAI.

Adapted from Hermes Agent (`cron/scheduler.py`).
Allows scheduling natural language tasks and periodic background jobs (e.g. daily audits, check-ins).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CronJob:
    """Represents a background scheduled task."""
    id: str
    name: str
    schedule: str  # Cron string or interval specifier e.g. "@hourly", "300s"
    prompt: str
    enabled: bool = True
    last_run: float = 0.0
    next_run: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class BackgroundCronScheduler:
    """Periodic task scheduler for running background agent loops."""

    def __init__(self, task_executor: Optional[Callable[[CronJob], Any]] = None):
        self.jobs: Dict[str, CronJob] = {}
        self.task_executor = task_executor
        self._running = False
        self._loop_task: Optional[asyncio.Task] = None

    def add_job(self, job_id: str, name: str, schedule: str, prompt: str) -> CronJob:
        """Register a new scheduled cron job."""
        job = CronJob(
            id=job_id,
            name=name,
            schedule=schedule,
            prompt=prompt,
            next_run=time.time() + 60.0,
        )
        self.jobs[job_id] = job
        logger.info(f"Cron job added: {job_id} ('{name}') -> schedule {schedule}")
        return job

    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job by ID."""
        if job_id in self.jobs:
            del self.jobs[job_id]
            logger.info(f"Cron job removed: {job_id}")
            return True
        return False

    def list_jobs(self) -> List[Dict[str, Any]]:
        """List registered cron jobs."""
        return [
            {
                "id": j.id,
                "name": j.name,
                "schedule": j.schedule,
                "prompt": j.prompt,
                "enabled": j.enabled,
                "last_run": j.last_run,
                "next_run": j.next_run,
            }
            for j in self.jobs.values()
        ]

    async def start(self) -> None:
        """Start the background cron loop."""
        if self._running:
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._cron_loop())
        logger.info("Background Cron Scheduler started.")

    async def stop(self) -> None:
        """Stop the background cron loop."""
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            self._loop_task = None
        logger.info("Background Cron Scheduler stopped.")

    async def _cron_loop(self) -> None:
        while self._running:
            now = time.time()
            for job in list(self.jobs.values()):
                if job.enabled and now >= job.next_run:
                    job.last_run = now
                    job.next_run = now + 300.0  # Default 5-min interval
                    if self.task_executor:
                        try:
                            if asyncio.iscoroutinefunction(self.task_executor):
                                await self.task_executor(job)
                            else:
                                self.task_executor(job)
                        except Exception as e:
                            logger.error(f"Error executing cron job {job.id}: {e}")
            await asyncio.sleep(10.0)
