from pathlib import Path

from sqlalchemy import select

from app.db.database import make_session_factory
from app.db.models import Movie, Subtitle, SubtitleStatus
from app.media.ffprobe import SubtitleStream
from app.subtitles.inspection import inspect_available_subtitles


def test_embedded_subtitle_satisfies_requirement_without_sidecar(tmp_path: Path, monkeypatch):
    media = tmp_path / "Movie.mkv"; media.touch()
    Session = make_session_factory(tmp_path / "test.sqlite")
    monkeypatch.setattr("app.subtitles.inspection.inspect_subtitle_streams", lambda _: [SubtitleStream(4, "subrip", "ces", None, False, False)])
    with Session.begin() as session:
        movie = Movie(jellyfin_item_id="embedded", library_id="movies", library_name="Movies", title="Movie", path=str(media), jellyfin_root_path=str(tmp_path), worker_path=str(media))
        session.add(movie); session.flush()
        assert inspect_available_subtitles(session, movie, ["en", "cs"])
        subtitle = session.scalar(select(Subtitle).where(Subtitle.movie_id == movie.id, Subtitle.language == "cs"))
        assert subtitle.status == SubtitleStatus.READY
        assert subtitle.source == "embedded"
        assert subtitle.sync_status == "EMBEDDED"
        assert subtitle.path.endswith("#stream=4")
