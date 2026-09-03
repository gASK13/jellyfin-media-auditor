from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Movie, Subtitle, SubtitleStatus
from app.media.ffprobe import inspect_subtitle_streams
from app.media.language import normalize_language, required_subtitle_languages
from app.subtitles.files import find_local_subtitle


def inspect_available_subtitles(session: Session, movie: Movie, languages: list[str | None]) -> bool:
    """Persist usable local sidecars and embedded streams without any network/download action."""
    changed = False
    media_path = Path(movie.worker_path)
    embedded = {normalize_language(stream.language): stream for stream in inspect_subtitle_streams(media_path) if normalize_language(stream.language)}
    for language in required_subtitle_languages(languages):
        subtitle = session.scalar(select(Subtitle).where(Subtitle.movie_id == movie.id, Subtitle.language == language))
        external = find_local_subtitle(media_path, language)
        stream = embedded.get(language)
        if external:
            if subtitle is None:
                subtitle = Subtitle(movie_id=movie.id, language=language); session.add(subtitle)
            if subtitle.path != str(external) or subtitle.status != SubtitleStatus.READY:
                subtitle.path = str(external); subtitle.source = "local"; subtitle.status = SubtitleStatus.READY; subtitle.sync_status = subtitle.sync_status or "EXISTING"; subtitle.error_message = None; changed = True
        elif stream:
            path = f"embedded://{media_path}#stream={stream.index}"
            if subtitle is None:
                subtitle = Subtitle(movie_id=movie.id, language=language); session.add(subtitle)
            if subtitle.path != path or subtitle.status != SubtitleStatus.READY:
                subtitle.path = path; subtitle.source = "embedded"; subtitle.status = SubtitleStatus.READY; subtitle.sync_status = "EMBEDDED"; subtitle.error_message = None; changed = True
    return changed
