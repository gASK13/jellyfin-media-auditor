from datetime import datetime, timedelta
from pathlib import Path
from app.db.database import make_session_factory
from app.db.models import Movie
from app.jobs.queue import claim_next, enqueue

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
