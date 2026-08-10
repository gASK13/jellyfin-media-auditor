from __future__ import annotations

import os
import sys
from pathlib import Path

# Add project root directory to sys.path so app module is found
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
from sqlalchemy import func, select

from app.config import load_config
from app.db.database import make_session_factory
from app.db.models import AudioTrack, ManualOverride, Movie, MovieStatus, Subtitle
from app.jobs.queue import enqueue
from app.media.language import audio_tags

config = load_config(os.getenv("AUDITOR_CONFIG", "config.yaml"))
Session = make_session_factory(config.db_path)

st.set_page_config(page_title="Jellyfin Media Auditor", layout="wide")
st.title("Jellyfin Media Auditor")
st.caption("Audio classification and Jellyfin audio tags are active. Subtitle automation is currently disabled.")


def queue_movie(movie_id: int) -> None:
    with Session.begin() as session:
        enqueue(session, movie_id)


def save_override(movie_id: int, stream_index: int, language: str, reason: str) -> None:
    with Session.begin() as session:
        override = session.scalar(select(ManualOverride).where(ManualOverride.movie_id == movie_id, ManualOverride.audio_stream_index == stream_index))
        if override:
            override.language = language
            override.reason = reason or None
        else:
            session.add(ManualOverride(movie_id=movie_id, audio_stream_index=stream_index, language=language, reason=reason or None))
        enqueue(session, movie_id)


def delete_override(movie_id: int, stream_index: int) -> None:
    with Session.begin() as session:
        override = session.scalar(select(ManualOverride).where(ManualOverride.movie_id == movie_id, ManualOverride.audio_stream_index == stream_index))
        if override:
            session.delete(override)
            enqueue(session, movie_id)


with Session() as session:
    counts = dict(session.execute(select(Movie.status, func.count(Movie.id)).where(Movie.active.is_(True)).group_by(Movie.status)).all())
    tracks = list(session.scalars(select(AudioTrack).join(Movie).where(Movie.active.is_(True))))
    by_movie: dict[int, list[str | None]] = {}
    for track in tracks:
        by_movie.setdefault(track.movie_id, []).append(track.normalized_language)
    classifications = [audio_tags(languages) for languages in by_movie.values()]
    metrics = [
        ("Total movies", sum(counts.values())), ("Queued", counts.get(MovieStatus.QUEUED, 0)),
        ("Processing", counts.get(MovieStatus.PROCESSING, 0)), ("Processed", counts.get(MovieStatus.PROCESSED, 0)),
        ("Unsure", counts.get(MovieStatus.UNSURE, 0)), ("Errors", counts.get(MovieStatus.ERROR, 0)),
        ("Audio Czech", sum("CZ Audio" in value for value in classifications)),
        ("Audio English", sum("EN Audio" in value for value in classifications)),
        ("Audio Other", sum("OTHER Audio" in value for value in classifications)),
    ]
    for column, (label, value) in zip(st.columns(3) * 3, metrics):
        column.metric(label, value)

    left, right = st.columns([1, 3])
    with left:
        status_filter = st.selectbox("Processing status", ["All", *[status.value for status in MovieStatus]])
        library_filter = st.selectbox("Library", ["All", *sorted({movie.library_name for movie in session.scalars(select(Movie).where(Movie.active.is_(True)))} )])
    query = select(Movie).where(Movie.active.is_(True)).order_by(Movie.updated_at.desc())
    if status_filter != "All": query = query.where(Movie.status == MovieStatus(status_filter))
    if library_filter != "All": query = query.where(Movie.library_name == library_filter)
    movies = list(session.scalars(query.limit(500)))
    with right:
        st.subheader("Movies")
        st.dataframe([{
            "Title": movie.title, "Year": movie.year, "Status": movie.status.value,
            "Audio languages": ", ".join(sorted(language for language in by_movie.get(movie.id, []) if language)) or "—",
            "Audio tags": ", ".join(sorted(audio_tags(by_movie.get(movie.id, [])))) or "—",
            "Last processed": movie.last_processed_at,
        } for movie in movies], use_container_width=True, hide_index=True)

    selected_id = st.selectbox("Movie detail", [None, *[movie.id for movie in movies]], format_func=lambda movie_id: "Choose a movie" if movie_id is None else next(movie.title for movie in movies if movie.id == movie_id))
    if selected_id is not None:
        movie = session.get(Movie, selected_id)
        st.subheader(f"{movie.title} ({movie.year or 'unknown year'})")
        st.code(movie.worker_path, language=None)
        st.write(f"Status: `{movie.status.value}`")
        if movie.error_message: st.error(movie.error_message)
        audio_tracks = list(session.scalars(select(AudioTrack).where(AudioTrack.movie_id == movie.id).order_by(AudioTrack.stream_index)))
        overrides = {override.audio_stream_index: override for override in session.scalars(select(ManualOverride).where(ManualOverride.movie_id == movie.id))}
        subtitles = list(session.scalars(select(Subtitle).where(Subtitle.movie_id == movie.id)))
        st.write("Audio streams")
        st.dataframe([{
            "Stream": track.stream_index, "Metadata": track.metadata_language or "und", "Effective": track.normalized_language or "UNKNOWN",
            "Detected": track.detected_language or "—", "Confidence": track.confidence, "Method": track.detection_method,
            "Title": track.title or "—", "Override": overrides.get(track.stream_index).language if track.stream_index in overrides else "—",
        } for track in audio_tracks], use_container_width=True, hide_index=True)
        if subtitles:
            st.write("Subtitles (automation disabled)")
            st.dataframe([{"Language": subtitle.language, "Status": subtitle.status.value, "Path": subtitle.path or "—", "Error": subtitle.error_message or "—"} for subtitle in subtitles], use_container_width=True, hide_index=True)

        action_col, override_col = st.columns(2)
        with action_col:
            if st.button("Queue audio reprocessing", key=f"queue-{movie.id}"):
                queue_movie(movie.id); st.success("Queued; refresh the page for updated state.")
        with override_col:
            if audio_tracks:
                stream = st.selectbox("Audio stream to override", [track.stream_index for track in audio_tracks], key=f"stream-{movie.id}")
                current = overrides.get(stream)
                with st.form(f"override-{movie.id}"):
                    language = st.selectbox("Manual language", ["cs", "en", "sk", "de", "fr", "it", "es", "other"], index=0 if not current else max(0, ["cs", "en", "sk", "de", "fr", "it", "es", "other"].index(current.language) if current.language in ["cs", "en", "sk", "de", "fr", "it", "es", "other"] else 0))
                    reason = st.text_input("Reason", value=current.reason or "" if current else "")
                    if st.form_submit_button("Save override"):
                        save_override(movie.id, stream, language, reason); st.success("Override saved and movie queued.")
                if current and st.button("Remove selected override", key=f"remove-{movie.id}"):
                    delete_override(movie.id, stream); st.success("Override removed and movie queued.")

st.divider()
with st.expander("Manual item ID queue"):
    manual_id = st.text_input("Jellyfin item ID")
    if st.button("Queue known item") and manual_id:
        with Session() as session:
            movie = session.scalar(select(Movie).where(Movie.jellyfin_item_id == manual_id))
        if movie:
            queue_movie(movie.id); st.success("Queued")
        else:
            st.warning("This item is not in the local database yet. Run reconciliation or wait for the periodic scan.")
