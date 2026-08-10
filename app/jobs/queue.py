from __future__ import annotations

from datetime import UTC, datetime, timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import Job, JobStatus

def utcnow() -> datetime: return datetime.now(UTC).replace(tzinfo=None)

def enqueue(session: Session, movie_id: int, job_type: str = "PROCESS_MOVIE", delay_seconds: int = 0) -> Job:
    existing = session.scalar(select(Job).where(Job.movie_id == movie_id, Job.job_type == job_type, Job.status.in_([JobStatus.PENDING, JobStatus.PROCESSING])))
    if existing: return existing
    job = Job(movie_id=movie_id, job_type=job_type, available_at=utcnow() + timedelta(seconds=delay_seconds))
    session.add(job); session.flush(); return job

def claim_next(session: Session) -> Job | None:
    # BEGIN IMMEDIATE serializes SQLite writers; re-checking status makes claims safe between processes.
    now = utcnow()
    job = session.scalar(select(Job).where(Job.status == JobStatus.PENDING, Job.available_at <= now).order_by(Job.available_at, Job.id).limit(1))
    if not job: return None
    job.status = JobStatus.PROCESSING; job.started_at = now; job.attempts += 1; session.flush(); return job

def finish(session: Session, job: Job, error: str | None = None, retry_delay_seconds: int | None = None) -> None:
    if retry_delay_seconds is not None:
        job.status = JobStatus.PENDING; job.available_at = utcnow() + timedelta(seconds=retry_delay_seconds); job.error_message = error
    else:
        job.status = JobStatus.FAILED if error else JobStatus.COMPLETED; job.error_message = error; job.completed_at = utcnow()
