from __future__ import annotations
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.config import Config
from app.db.models import AudioTrack, Job, JobStatus, ManualOverride, Movie, MovieStatus, Subtitle, SubtitleStatus
from app.jobs.queue import finish
from app.media.ffprobe import inspect_media
from app.media.detector import FasterWhisperLanguageDetector
from app.media.language import normalize_language, required_subtitle_languages
from app.subtitles.files import find_local_subtitle
from app.jellyfin.tags import reconcile_movie_tags
from app.subtitles.pipeline import SubtitlePipeline
from app.subtitles.inspection import inspect_available_subtitles

log=logging.getLogger(__name__)


def recover_stale_jobs(session: Session, stale_after_minutes: int, *, recover_all: bool = False) -> tuple[int, int]:
    """Recover interrupted claims without reprocessing movies that already reached a terminal state."""
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=stale_after_minutes)
    query = select(Job).where(Job.status == JobStatus.PROCESSING)
    if not recover_all:
        query = query.where(Job.started_at.is_not(None), Job.started_at < cutoff)
    completed = pending = 0
    for job in session.scalars(query):
        movie = session.get(Movie, job.movie_id)
        if movie and movie.status in {MovieStatus.PROCESSED, MovieStatus.UNSURE, MovieStatus.ERROR}:
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(UTC).replace(tzinfo=None)
            job.error_message = "Recovered stale claim; movie already reached a terminal state"
            completed += 1
        else:
            job.status = JobStatus.PENDING
            job.started_at = None
            job.error_message = "Recovered stale claim; queued for retry"
            pending += 1
    if completed or pending:
        log.warning("Recovered stale jobs: %d completed, %d returned to pending", completed, pending)
    return completed, pending

class LanguageDetector:
    """Interface intentionally isolated so a faster-whisper implementation can be injected."""
    def detect(self, media_path: Path, stream_index: int, duration: float | None) -> tuple[str | None, float]: raise NotImplementedError

class Worker:
    def __init__(self, config: Config, detector: LanguageDetector | None = None, jellyfin_client=None):
        self.config=config
        self.detector=detector or FasterWhisperLanguageDetector(config.whisper_model, config.whisper_device, config.whisper_compute_type, config.initial_sample_count, config.fallback_sample_count, config.sample_duration_seconds, config.confidence_threshold)
        self.jellyfin_client=jellyfin_client
    def process(self, session: Session, job: Job) -> None:
        # The queue claim is deliberately committed before the potentially long
        # media work starts.  Re-load the job in this transaction: the object
        # handed to us by the claim transaction is detached, and mutating it
        # would otherwise leave it stuck in PROCESSING forever.
        job_id = job.id
        job = session.get(Job, job_id)
        if job is None:
            log.warning("job=%s disappeared before processing", job_id)
            return
        movie=session.get(Movie, job.movie_id)
        if not movie or not movie.active:
            finish(session, job)
            session.commit()
            return
        movie.status=MovieStatus.PROCESSING
        try:
            self._audit_audio(session, movie)
            languages=[track.normalized_language for track in session.scalars(select(AudioTrack).where(AudioTrack.movie_id == movie.id))]
            # Audio inspection may run Whisper.  Persist it before any remote
            # calls so this connection no longer owns SQLite's writer lock.
            session.commit()
            if any(lang is None for lang in languages): movie.status=MovieStatus.UNSURE
            else:
                if self.jellyfin_client:
                    reconcile_movie_tags(self.jellyfin_client, movie_id=movie.jellyfin_item_id, languages=languages)
                # Local sidecars and embedded streams are recorded even when downloads are disabled.
                inspect_available_subtitles(session, movie, languages)
                # ffprobe inspection is complete; release any subtitle writes
                # before OpenSubtitles or ffsubsync can take a long time.
                session.commit()
                if self.config.subtitles_enabled:
                    if SubtitlePipeline(self.config).process_movie(session, movie, languages) and self.jellyfin_client:
                        self.jellyfin_client.refresh_item(movie.jellyfin_item_id)
                movie.status=MovieStatus.PROCESSED; movie.last_processed_at=datetime.now(UTC).replace(tzinfo=None); movie.error_message=None
            finish(session, job)
            session.commit()
        except FileNotFoundError:
            session.rollback()
            movie=session.get(Movie, job.movie_id)
            job=session.get(Job, job.id)
            movie.status=MovieStatus.ERROR; movie.error_message="Media file is missing"; finish(session, job, movie.error_message)
            session.commit()
        except Exception as exc:
            session.rollback()
            movie=session.get(Movie, job.movie_id)
            job=session.get(Job, job.id)
            log.exception("job=%s movie=%s processing failed", job.id, movie.jellyfin_item_id)
            movie.status=MovieStatus.ERROR; movie.error_message=str(exc)
            delay=min(3600, 30 * (2 ** min(job.attempts, 6)))
            finish(session, job, str(exc), delay if job.attempts < self.config.max_attempts else None)
            session.commit()
    def _audit_audio(self, session: Session, movie: Movie) -> None:
        path=Path(movie.worker_path)
        if not path.is_file(): raise FileNotFoundError(path)
        streams, signature=inspect_media(path)
        if not streams: raise RuntimeError("No usable audio streams")
        overrides={override.audio_stream_index: override.language for override in session.scalars(select(ManualOverride).where(ManualOverride.movie_id == movie.id))}
        # Skip whisper re-detection if file is unchanged AND no overrides exist — but always re-apply if overrides are set
        existing={track.stream_index: track for track in session.scalars(select(AudioTrack).where(AudioTrack.movie_id == movie.id))}
        cached = movie.media_signature == signature and bool(existing)
        for stream in streams:
            track=existing.get(stream.index) or AudioTrack(movie_id=movie.id, stream_index=stream.index)
            if track not in session: session.add(track)
            track.codec=stream.codec; track.channels=stream.channels; track.metadata_language=stream.language; track.title=stream.title; track.is_default=stream.is_default; track.is_forced=stream.is_forced
            if stream.index in overrides:
                # Always apply manual overrides, even on cache hit
                track.normalized_language=normalize_language(overrides[stream.index]); track.detection_method="manual"; track.confidence=1.0
            elif cached:
                pass  # File unchanged and no override for this stream — keep existing detection
            elif (language:=normalize_language(stream.language)): track.normalized_language=language; track.detection_method="metadata"; track.confidence=1.0
            elif self.detector:
                language, confidence=self.detector.detect(path, stream.index, movie.duration); track.detected_language=normalize_language(language); track.confidence=confidence; track.normalized_language=track.detected_language if confidence >= self.config.confidence_threshold else None; track.detection_method="whisper"
            else: track.normalized_language=None; track.detection_method="unknown"; track.confidence=None
        movie.media_signature=signature
    def _inspect_existing_subtitles(self, session: Session, movie: Movie, languages: list[str | None]) -> None:
        for language in required_subtitle_languages(languages):
            subtitle=session.scalar(select(Subtitle).where(Subtitle.movie_id == movie.id, Subtitle.language == language)) or Subtitle(movie_id=movie.id, language=language)
            if subtitle not in session: session.add(subtitle)
            local=find_local_subtitle(Path(movie.worker_path), language)
            if local: subtitle.path=str(local); subtitle.status=SubtitleStatus.READY
            elif subtitle.status not in (SubtitleStatus.NOT_FOUND, SubtitleStatus.READY): subtitle.status=SubtitleStatus.SEARCHING
