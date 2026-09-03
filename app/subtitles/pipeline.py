from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Config
from app.db.models import Movie, Subtitle, SubtitleStatus
from app.media.language import required_subtitle_languages
from app.subtitles.files import final_subtitle_path, find_local_subtitle
from app.subtitles.opensubtitles import OpenSubtitlesClient
from app.subtitles.quota import downloads_remaining, record_download
from app.subtitles.sync import SubtitleSynchronizer
from app.subtitles.inspection import inspect_available_subtitles


class SubtitlePipeline:
    def __init__(self, config: Config, client: OpenSubtitlesClient | None = None, synchronizer: SubtitleSynchronizer | None = None):
        self.config = config
        self.client = client or OpenSubtitlesClient(config)
        self.synchronizer = synchronizer or SubtitleSynchronizer()

    def process_movie(self, session: Session, movie: Movie, languages: list[str | None]) -> bool:
        changed = inspect_available_subtitles(session, movie, languages)
        for language in required_subtitle_languages(languages):
            changed |= self._process_language(session, movie, language)
        return changed

    def _record(self, session: Session, movie_id: int, language: str) -> Subtitle:
        return session.scalar(select(Subtitle).where(Subtitle.movie_id == movie_id, Subtitle.language == language)) or Subtitle(movie_id=movie_id, language=language)

    def _process_language(self, session: Session, movie: Movie, language: str) -> bool:
        subtitle = self._record(session, movie.id, language)
        if subtitle not in session:
            session.add(subtitle)
        existing = find_local_subtitle(Path(movie.worker_path), language)
        if existing:
            changed = subtitle.path != str(existing) or subtitle.status != SubtitleStatus.READY
            subtitle.path = str(existing); subtitle.status = SubtitleStatus.READY; subtitle.error_message = None
            return changed
        if subtitle.status == SubtitleStatus.READY:
            return False
        if subtitle.status == SubtitleStatus.NOT_FOUND and subtitle.last_attempt_at and subtitle.last_attempt_at > datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=self.config.not_found_retry_hours):
            return False
        if downloads_remaining(session, self.config.max_downloads_per_day) <= 0:
            subtitle.status = SubtitleStatus.SEARCHING
            subtitle.error_message = "OpenSubtitles daily download quota reached; retry next day"
            subtitle.last_attempt_at = datetime.now(UTC).replace(tzinfo=None)
            return False
        subtitle.status = SubtitleStatus.SEARCHING; subtitle.last_attempt_at = datetime.now(UTC).replace(tzinfo=None)
        result = self.client.search(language=language, imdb_id=movie.imdb_id, tmdb_id=movie.tmdb_id, filename=Path(movie.worker_path).stem)
        if not result:
            subtitle.status = SubtitleStatus.NOT_FOUND; subtitle.error_message = "No suitable OpenSubtitles result"; return False
        final_path = final_subtitle_path(Path(movie.worker_path), language)
        downloaded_path = final_path.with_suffix(".downloaded.srt")
        try:
            self.client.download_srt(result.candidate.file_id, downloaded_path)
            record_download(session)
            subtitle.status = SubtitleStatus.DOWNLOADED; subtitle.opensubtitles_file_id = str(result.candidate.file_id); subtitle.source = "OpenSubtitles"; subtitle.downloaded_at = datetime.now(UTC).replace(tzinfo=None)
            subtitle.status = SubtitleStatus.SYNCING
            sync = self.synchronizer.synchronize(Path(movie.worker_path), downloaded_path, final_path)
            subtitle.path = str(sync.path); subtitle.status = SubtitleStatus.READY; subtitle.sync_status = "SYNCED"; subtitle.synced_at = datetime.now(UTC).replace(tzinfo=None); subtitle.error_message = None
            downloaded_path.unlink(missing_ok=True)
            return True
        except Exception as exc:
            subtitle.status = SubtitleStatus.SYNC_FAILED if downloaded_path.exists() else SubtitleStatus.ERROR
            subtitle.error_message = str(exc)
            return False
