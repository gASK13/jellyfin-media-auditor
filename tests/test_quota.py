from pathlib import Path
from app.db.database import make_session_factory
from app.subtitles.quota import downloads_remaining, record_download

def test_download_quota_is_local_and_idempotently_counted(tmp_path: Path):
    Session = make_session_factory(tmp_path / "test.sqlite")
    with Session.begin() as session:
        assert downloads_remaining(session, 2) == 2
        record_download(session); record_download(session)
        assert downloads_remaining(session, 2) == 0
