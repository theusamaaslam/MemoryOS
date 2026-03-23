from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.core.cache import dequeue_job, enqueue_job
from app.core.config import settings
from app.core.db import session_scope
from app.models.domain import Scope
from app.models.persistence import JobModel


class JobService:
    def enqueue_reflection(self, scope: Scope, reason: str = "manual") -> dict[str, str]:
        now = datetime.now(UTC)
        job = {
            "job_id": str(uuid4()),
            "job_type": "reflection",
            "status": "queued",
            "org_id": scope.org_id,
            "app_id": scope.app_id,
            "user_id": scope.user_id,
            "session_id": scope.session_id,
            "payload_json": {"reason": reason},
            "result_json": {},
            "attempts": 0,
            "max_attempts": settings.job_max_retries,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        with session_scope() as session:
            session.add(
                JobModel(
                    job_id=job["job_id"],
                    job_type=job["job_type"],
                    status=job["status"],
                    org_id=job["org_id"],
                    app_id=job["app_id"],
                    user_id=job["user_id"],
                    session_id=job["session_id"],
                    payload_json=job["payload_json"],
                    result_json={},
                    attempts=0,
                    max_attempts=settings.job_max_retries,
                    last_error=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        enqueue_job(job)
        return {"job_id": job["job_id"], "status": "queued", "summary": "Reflection job queued"}

    def fetch_next_job(self) -> dict | None:
        return dequeue_job()

    def mark_job(self, job_id: str, status: str, result: dict[str, str]) -> None:
        with session_scope() as session:
            job = session.get(JobModel, job_id)
            if job is None:
                return
            job.status = status
            job.result_json = result
            job.updated_at = datetime.now(UTC)
            if status == "completed":
                job.last_error = None

    def get_job(self, job_id: str) -> dict | None:
        with session_scope() as session:
            job = session.get(JobModel, job_id)
            if job is None:
                return None
            return {
                "job_id": job.job_id,
                "status": job.status,
                "summary": job.result_json.get("summary", ""),
            }

    def requeue_job(self, job: dict, error: str) -> bool:
        attempts = int(job.get("attempts", 0)) + 1
        if attempts >= int(job.get("max_attempts", settings.job_max_retries)):
            with session_scope() as session:
                row = session.get(JobModel, job["job_id"])
                if row is None:
                    return False
                row.status = "dead_letter"
                row.attempts = attempts
                row.last_error = error
                row.result_json = {"summary": error}
                row.updated_at = datetime.now(UTC)
            return False

        with session_scope() as session:
            row = session.get(JobModel, job["job_id"])
            if row is None:
                return False
            row.status = "queued"
            row.attempts = attempts
            row.last_error = error
            row.updated_at = datetime.now(UTC)
        job["attempts"] = attempts
        enqueue_job(job)
        return True


job_service = JobService()
