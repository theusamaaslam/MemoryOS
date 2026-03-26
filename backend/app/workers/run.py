from __future__ import annotations

import logging
import time

from fastapi import HTTPException

from app.core.config import settings
from app.core.db import initialize_database
from app.core.metrics import REFLECTION_JOBS
from app.models.domain import MemoryScope, Scope
from app.services.conversations import conversation_service
from app.services.jobs import job_service
from app.services.memory import memory_service


def main() -> None:
    initialize_database()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    last_periodic_scan = 0.0
    while True:
        now = time.time()
        if now - last_periodic_scan >= max(settings.graph_periodic_scan_seconds, 30):
            try:
                job_service.enqueue_due_reflections()
            except Exception:
                logging.exception("worker_periodic_reflection_scan_failed")
            last_periodic_scan = now

        job = job_service.fetch_next_job()
        if job is None:
            time.sleep(1)
            continue
        try:
            if job["job_type"] == "reflection":
                payload = job.get("payload_json") or {}
                scope = Scope(
                    org_id=job["org_id"],
                    app_id=job["app_id"],
                    user_id=job["user_id"],
                    session_id=job["session_id"],
                )
                try:
                    result = conversation_service.reflect_conversation_internal(job["session_id"])
                except HTTPException as exc:
                    if exc.status_code != 404:
                        raise
                    requested_scope = str(payload.get("memory_scope") or MemoryScope.APP.value).strip().lower()
                    graph_scope = MemoryScope(requested_scope) if requested_scope in {item.value for item in MemoryScope} else MemoryScope.APP
                    result = memory_service.reflect(scope, memory_scope=graph_scope)
                job_service.mark_job(job["job_id"], "completed", result)
                REFLECTION_JOBS.labels("completed").inc()
            else:
                job_service.mark_job(job["job_id"], "ignored", {"summary": "Unknown job type"})
                REFLECTION_JOBS.labels("ignored").inc()
        except Exception as exc:
            error = str(exc)
            requeued = job_service.requeue_job(job, error)
            REFLECTION_JOBS.labels("retried" if requeued else "failed").inc()
            logging.exception("worker_job_failed")


if __name__ == "__main__":
    main()
