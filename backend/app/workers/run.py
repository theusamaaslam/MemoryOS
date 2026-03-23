from __future__ import annotations

import logging
import time

from app.core.db import initialize_database
from app.core.metrics import REFLECTION_JOBS
from app.models.domain import Scope
from app.services.jobs import job_service
from app.services.memory import memory_service


def main() -> None:
    initialize_database()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    while True:
        job = job_service.fetch_next_job()
        if job is None:
            time.sleep(1)
            continue
        try:
            if job["job_type"] == "reflection":
                scope = Scope(
                    org_id=job["org_id"],
                    app_id=job["app_id"],
                    user_id=job["user_id"],
                    session_id=job["session_id"],
                )
                result = memory_service.reflect(scope)
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
