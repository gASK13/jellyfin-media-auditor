from __future__ import annotations
from datetime import UTC, datetime
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import Config, Library
from app.db.models import Movie, MovieStatus
from app.jobs.queue import enqueue

def _fingerprint(item: dict, worker_path: Path) -> tuple[int | None, float | None, float | None]:
    source = (item.get("MediaSources") or [{}])[0]
    size = source.get("Size")
    mtime = worker_path.stat().st_mtime if worker_path.exists() else None
    return size, mtime, item.get("RunTimeTicks", 0) / 10_000_000 if item.get("RunTimeTicks") else None

def upsert_item(session: Session, config: Config, library: Library, item: dict, queue_changed: bool = True) -> Movie:
    jellyfin_path = item.get("Path") or (item.get("MediaSources") or [{}])[0].get("Path")
    if not jellyfin_path: raise ValueError("Movie has no path")
    worker_path=config.worker_path(jellyfin_path); size, mtime, duration = _fingerprint(item, worker_path)
    movie=session.scalar(select(Movie).where(Movie.jellyfin_item_id == item["Id"]))
    changed = not movie or (movie.path, movie.file_size, movie.file_mtime, movie.duration) != (jellyfin_path, size, mtime, duration)
    if not movie:
        movie=Movie(jellyfin_item_id=item["Id"], library_id=library.jellyfin_id, library_name=library.name, title=item.get("Name", item["Id"]), year=item.get("ProductionYear"), path=jellyfin_path, jellyfin_root_path=str(config.jellyfin_root), worker_path=str(worker_path), file_size=size, file_mtime=mtime, duration=duration, imdb_id=item.get("ProviderIds", {}).get("Imdb"), tmdb_id=item.get("ProviderIds", {}).get("Tmdb"), status=MovieStatus.UNSCANNED); session.add(movie); session.flush()
    else:
        movie.active=True; movie.title=item.get("Name", movie.title); movie.year=item.get("ProductionYear"); movie.path=jellyfin_path; movie.worker_path=str(worker_path); movie.file_size=size; movie.file_mtime=mtime; movie.duration=duration
        if changed: movie.status=MovieStatus.UNSCANNED
    movie.last_scan_at=datetime.now(UTC).replace(tzinfo=None)
    if queue_changed and changed: enqueue(session, movie.id)
    return movie

def reconcile(session: Session, config: Config, client) -> int:
    seen=set(); count=0
    for library in config.libraries:
        for item in client.movies(library.jellyfin_id): upsert_item(session, config, library, item); seen.add(item["Id"]); count += 1
    for movie in session.scalars(select(Movie).where(Movie.library_id.in_([x.jellyfin_id for x in config.libraries]), Movie.active.is_(True))):
        if movie.jellyfin_item_id not in seen: movie.active=False
    return count
