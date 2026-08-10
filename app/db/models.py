from __future__ import annotations

import enum
from datetime import UTC, datetime
from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class MovieStatus(str, enum.Enum):
    UNSCANNED="UNSCANNED"; QUEUED="QUEUED"; WAITING_FOR_METADATA="WAITING_FOR_METADATA"; PROCESSING="PROCESSING"; PROCESSED="PROCESSED"; UNSURE="UNSURE"; ERROR="ERROR"
class JobStatus(str, enum.Enum): PENDING="PENDING"; PROCESSING="PROCESSING"; COMPLETED="COMPLETED"; FAILED="FAILED"
class SubtitleStatus(str, enum.Enum): NOT_REQUIRED="NOT_REQUIRED"; NOT_FOUND="NOT_FOUND"; SEARCHING="SEARCHING"; DOWNLOADED="DOWNLOADED"; SYNCING="SYNCING"; READY="READY"; SYNC_FAILED="SYNC_FAILED"; ERROR="ERROR"

class Movie(Base):
    __tablename__="movies"
    id: Mapped[int] = mapped_column(primary_key=True)
    jellyfin_item_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    library_id: Mapped[str] = mapped_column(String, index=True); library_name: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String); year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    path: Mapped[str] = mapped_column(Text); jellyfin_root_path: Mapped[str] = mapped_column(Text); worker_path: Mapped[str] = mapped_column(Text)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True); file_mtime: Mapped[float | None] = mapped_column(Float, nullable=True); duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    media_signature: Mapped[str | None] = mapped_column(String, nullable=True); imdb_id: Mapped[str | None] = mapped_column(String, nullable=True); tmdb_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[MovieStatus] = mapped_column(Enum(MovieStatus), default=MovieStatus.UNSCANNED, index=True); active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True); last_processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True); error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)); updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), onupdate=lambda: datetime.now(UTC).replace(tzinfo=None))

class AudioTrack(Base):
    __tablename__="audio_tracks"; __table_args__=(UniqueConstraint("movie_id", "stream_index"),)
    id: Mapped[int] = mapped_column(primary_key=True); movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id"), index=True); stream_index: Mapped[int] = mapped_column(Integer)
    codec: Mapped[str | None] = mapped_column(String, nullable=True); channels: Mapped[int | None] = mapped_column(Integer, nullable=True); metadata_language: Mapped[str | None] = mapped_column(String, nullable=True); normalized_language: Mapped[str | None] = mapped_column(String, nullable=True); detected_language: Mapped[str | None] = mapped_column(String, nullable=True); confidence: Mapped[float | None] = mapped_column(Float, nullable=True); detection_method: Mapped[str | None] = mapped_column(String, nullable=True); title: Mapped[str | None] = mapped_column(String, nullable=True); is_default: Mapped[bool] = mapped_column(Boolean, default=False); is_forced: Mapped[bool] = mapped_column(Boolean, default=False)

class Subtitle(Base):
    __tablename__="subtitles"; __table_args__=(UniqueConstraint("movie_id", "language"),)
    id: Mapped[int] = mapped_column(primary_key=True); movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id"), index=True); language: Mapped[str] = mapped_column(String)
    path: Mapped[str | None] = mapped_column(Text, nullable=True); source: Mapped[str | None] = mapped_column(String, nullable=True); opensubtitles_file_id: Mapped[str | None] = mapped_column(String, nullable=True); status: Mapped[SubtitleStatus] = mapped_column(Enum(SubtitleStatus), default=SubtitleStatus.NOT_REQUIRED); sync_status: Mapped[str | None] = mapped_column(String, nullable=True); sync_score: Mapped[float | None] = mapped_column(Float, nullable=True); downloaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True); synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True); error_message: Mapped[str | None] = mapped_column(Text, nullable=True); last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class Job(Base):
    __tablename__="jobs"; __table_args__=(Index("ix_jobs_status_available", "status", "available_at"),)
    id: Mapped[int] = mapped_column(primary_key=True); movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id"), index=True); job_type: Mapped[str] = mapped_column(String); status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.PENDING, index=True); attempts: Mapped[int] = mapped_column(Integer, default=0); available_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), index=True); started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True); completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True); error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

class ManualOverride(Base):
    __tablename__="manual_overrides"; __table_args__=(UniqueConstraint("movie_id", "audio_stream_index"),)
    id: Mapped[int] = mapped_column(primary_key=True); movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id"), index=True); audio_stream_index: Mapped[int] = mapped_column(Integer); language: Mapped[str] = mapped_column(String); reason: Mapped[str | None] = mapped_column(Text, nullable=True); created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)); updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), onupdate=lambda: datetime.now(UTC).replace(tzinfo=None))

class ApiUsage(Base):
    __tablename__="api_usage"; __table_args__=(UniqueConstraint("provider", "usage_date"),)
    id: Mapped[int] = mapped_column(primary_key=True); provider: Mapped[str] = mapped_column(String); usage_date: Mapped[str] = mapped_column(String); downloads: Mapped[int] = mapped_column(Integer, default=0); updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), onupdate=lambda: datetime.now(UTC).replace(tzinfo=None))
