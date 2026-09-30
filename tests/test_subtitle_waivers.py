from pathlib import Path

from app.config import Config
from app.db.database import make_session_factory
from app.db.models import Movie, Subtitle, SubtitleWaiver
from app.subtitles.pipeline import SubtitlePipeline


class NoSearchClient:
    def search(self, **_: object):
        raise AssertionError("an exempt subtitle language must not be searched")


def test_subtitle_waiver_skips_download_pipeline(tmp_path: Path, monkeypatch):
    media = tmp_path / "Movie.mkv"
    media.touch()
    Session = make_session_factory(tmp_path / "test.sqlite")
    config = Config(jellyfin_url="http://jellyfin", jellyfin_api_key="key", jellyfin_user_id=None, webhook_token=None, jellyfin_root=tmp_path, worker_root=tmp_path, libraries=[])
    monkeypatch.setattr("app.subtitles.pipeline.inspect_available_subtitles", lambda *_: False)
    with Session.begin() as session:
        movie = Movie(jellyfin_item_id="waived", library_id="movies", library_name="Movies", title="Movie", path=str(media), jellyfin_root_path=str(tmp_path), worker_path=str(media))
        session.add(movie)
        session.flush()
        session.add(SubtitleWaiver(movie_id=movie.id, language="cs", reason="Intentional omission"))
        changed = SubtitlePipeline(config, client=NoSearchClient()).process_movie(session, movie, ["cs"])
        assert not changed
        assert session.query(Subtitle).filter_by(movie_id=movie.id, language="cs").first() is None
