from datetime import UTC, datetime, timedelta
from pathlib import Path
from sqlalchemy import select
from app.db.database import make_session_factory
from app.db.models import Job, JobStatus, Movie, MovieStatus
from app.jobs.queue import claim_next, enqueue
from app.jobs.worker import recover_stale_jobs

def test_queue_is_idempotent_and_claims_once(tmp_path: Path):
    Session=make_session_factory(tmp_path / "test.sqlite")
    with Session.begin() as session:
        movie=Movie(jellyfin_item_id="one", library_id="lib", library_name="Movies", title="Test", path="/media/a.mkv", jellyfin_root_path="/media", worker_path="/mnt/a.mkv")
        session.add(movie); session.flush()
        first=enqueue(session, movie.id); second=enqueue(session, movie.id)
        assert first.id == second.id
    with Session.begin() as session:
        claimed=claim_next(session); assert claimed is not None
    with Session.begin() as session: assert claim_next(session) is None


def test_queue_accepts_independent_movies(tmp_path: Path):
    """One active movie must never prevent another from being queued."""
    Session = make_session_factory(tmp_path / "test.sqlite")
    with Session.begin() as session:
        first = Movie(jellyfin_item_id="one", library_id="lib", library_name="Movies", title="First", path="/media/one.mkv", jellyfin_root_path="/media", worker_path="/mnt/one.mkv")
        second = Movie(jellyfin_item_id="two", library_id="lib", library_name="Movies", title="Second", path="/media/two.mkv", jellyfin_root_path="/media", worker_path="/mnt/two.mkv")
        session.add_all([first, second]); session.flush()
        first_job = enqueue(session, first.id)
        second_job = enqueue(session, second.id)
        assert first_job.id != second_job.id
    with Session.begin() as session:
        claimed = claim_next(session)
        assert claimed is not None
        assert claimed.movie_id == first.id
        remaining = session.scalar(select(Job).where(Job.id == second_job.id))
        assert remaining is not None and remaining.status == JobStatus.PENDING

def test_stale_terminal_claim_is_completed_not_reprocessed(tmp_path: Path):
    Session=make_session_factory(tmp_path / "test.sqlite")
    with Session.begin() as session:
        movie=Movie(jellyfin_item_id="terminal", library_id="lib", library_name="Movies", title="Done", path="/media/a.mkv", jellyfin_root_path="/media", worker_path="/mnt/a.mkv", status=MovieStatus.PROCESSED)
        session.add(movie); session.flush()
        job=Job(movie_id=movie.id, job_type="PROCESS_MOVIE", status=JobStatus.PROCESSING, started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=4))
        session.add(job); session.flush()
        completed, pending=recover_stale_jobs(session, 180)
        assert (completed, pending) == (1, 0)
        assert job.status == JobStatus.COMPLETED
