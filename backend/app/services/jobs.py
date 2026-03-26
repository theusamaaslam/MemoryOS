from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.core.cache import dequeue_job, enqueue_job
from app.core.config import settings
from app.core.db import session_scope
from app.models.domain import MemoryScope, Scope
from app.models.persistence import EventModel, JobModel, MemoryModel


class JobService:
    def _normalize_scope_value(self, value: MemoryScope | str | None) -> str:
        if isinstance(value, MemoryScope):
            return value.value
        cleaned = str(value or MemoryScope.CONVERSATION.value).strip().lower()
        return cleaned if cleaned in {item.value for item in MemoryScope} else MemoryScope.CONVERSATION.value

    def _scope_priority(self, value: MemoryScope | str | None) -> int:
        normalized = self._normalize_scope_value(value)
        if normalized == MemoryScope.APP.value:
            return 3
        if normalized == MemoryScope.USER.value:
            return 2
        return 1

    def enqueue_reflection(self, scope: Scope, reason: str = "manual", *, memory_scope: MemoryScope | str | None = None) -> dict[str, str]:
        now = datetime.now(UTC)
        job = {
            "job_id": str(uuid4()),
            "job_type": "reflection",
            "status": "queued",
            "org_id": scope.org_id,
            "app_id": scope.app_id,
            "user_id": scope.user_id,
            "session_id": scope.session_id,
            "payload_json": {"reason": reason, "memory_scope": self._normalize_scope_value(memory_scope)},
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

    def enqueue_reflection_if_due(self, scope: Scope, reason: str = "auto", *, memory_scope: MemoryScope | str | None = None) -> bool:
        if not settings.graph_auto_reflect_enabled:
            return False

        now = datetime.now(UTC)
        debounce_seconds = max(settings.graph_reflect_debounce_seconds, 15)
        with session_scope() as session:
            existing = (
                session.query(JobModel)
                .filter_by(
                    job_type="reflection",
                    org_id=scope.org_id,
                    app_id=scope.app_id,
                    user_id=scope.user_id,
                    session_id=scope.session_id,
                )
                .filter(JobModel.status.in_(["queued", "running"]))
                .order_by(JobModel.updated_at.desc())
                .first()
            )
            if existing is not None:
                return False

            recent = (
                session.query(JobModel)
                .filter_by(
                    job_type="reflection",
                    org_id=scope.org_id,
                    app_id=scope.app_id,
                    user_id=scope.user_id,
                    session_id=scope.session_id,
                    status="completed",
                )
                .order_by(JobModel.updated_at.desc())
                .first()
            )
            if recent is not None:
                age_seconds = (now - recent.updated_at).total_seconds()
                if age_seconds < debounce_seconds:
                    return False

        self.enqueue_reflection(scope, reason, memory_scope=memory_scope)
        return True

    def enqueue_due_reflections(self) -> int:
        if not settings.graph_auto_reflect_enabled:
            return 0

        now = datetime.now(UTC)
        refresh_seconds = max(settings.graph_periodic_refresh_seconds, settings.graph_reflect_debounce_seconds, 60)
        recent_cutoff = now.timestamp() - max(refresh_seconds * 3, 3600)
        discovered_scopes: dict[tuple[str, str, str, str], tuple[Scope, str]] = {}

        with session_scope() as session:
            recent_memories = (
                session.query(MemoryModel)
                .filter(MemoryModel.updated_at.is_not(None))
                .order_by(MemoryModel.updated_at.desc())
                .limit(180)
                .all()
            )
            recent_events = (
                session.query(EventModel)
                .order_by(EventModel.created_at.desc())
                .limit(180)
                .all()
            )
            recent_jobs = (
                session.query(JobModel)
                .filter_by(job_type="reflection", status="completed")
                .order_by(JobModel.updated_at.desc())
                .limit(200)
                .all()
            )

        for row in recent_memories:
            metadata = row.metadata_json or {}
            if row.source == "reflection" or metadata.get("generated_by"):
                continue
            if row.updated_at.timestamp() < recent_cutoff:
                continue
            key = (row.org_id, row.app_id, row.user_id, row.session_id)
            candidate_scope = self._normalize_scope_value(row.memory_scope)
            existing = discovered_scopes.get(key)
            if existing is None or self._scope_priority(candidate_scope) >= self._scope_priority(existing[1]):
                discovered_scopes[key] = (
                    Scope(org_id=row.org_id, app_id=row.app_id, user_id=row.user_id, session_id=row.session_id),
                    candidate_scope,
                )

        for row in recent_events:
            if row.created_at.timestamp() < recent_cutoff:
                continue
            key = (row.org_id, row.app_id, row.user_id, row.session_id)
            existing = discovered_scopes.get(key)
            candidate_scope = MemoryScope.CONVERSATION.value
            if existing is None or self._scope_priority(candidate_scope) >= self._scope_priority(existing[1]):
                discovered_scopes[key] = (
                    Scope(org_id=row.org_id, app_id=row.app_id, user_id=row.user_id, session_id=row.session_id),
                    candidate_scope,
                )

        latest_completed: dict[tuple[str, str, str, str], datetime] = {}
        for row in recent_jobs:
            key = (row.org_id, row.app_id, row.user_id, row.session_id)
            latest_completed.setdefault(key, row.updated_at)

        enqueued = 0
        for key, (scope, memory_scope) in discovered_scopes.items():
            last_completed = latest_completed.get(key)
            if last_completed is not None and (now - last_completed).total_seconds() < refresh_seconds:
                continue
            if self.enqueue_reflection_if_due(scope, "periodic_graph_refresh", memory_scope=memory_scope):
                enqueued += 1
        return enqueued

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
