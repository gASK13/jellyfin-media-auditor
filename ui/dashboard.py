from __future__ import annotations

import os
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import load_config
from app.db.database import make_session_factory
from app.db.models import AudioTrack, Job, JobStatus, ManualOverride, Movie, MovieStatus, Subtitle, SubtitleStatus
from app.jobs.queue import enqueue
from app.media.ffprobe import inspect_subtitle_streams
from app.media.language import audio_tags, normalize_language, required_subtitle_languages

config = load_config(os.getenv("AUDITOR_CONFIG", "config.yaml"))
Session = make_session_factory(config.db_path)

st.set_page_config(page_title="Jellyfin Media Auditor", page_icon="🎬", layout="wide")
st.markdown("""
<style>
  .block-container { max-width: 1500px; padding-top: 2rem; }
  [data-testid="stMetric"] { background: #111827; border: 1px solid #293548; border-radius: .7rem; padding: .65rem .8rem; }
  [data-testid="stMetricLabel"] { color: #b7c2d0; }
  [data-testid="stMetricValue"] { color: #f8fafc; }
</style>
""", unsafe_allow_html=True)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def queue_movie(movie_id: int) -> tuple[int, bool]:
    # A short retry protects the UI from a simultaneous scanner/worker commit.
    for attempt in range(3):
        try:
            with Session.begin() as session:
                job = enqueue(session, movie_id)
                return job.id, job.status == JobStatus.PENDING
        except OperationalError:
            if attempt == 2:
                raise
            time.sleep(0.25 * (attempt + 1))
    raise RuntimeError("Queue retry loop ended unexpectedly")


def save_override(movie_id: int, stream_index: int, language: str, reason: str) -> None:
    with Session.begin() as session:
        override = session.scalar(select(ManualOverride).where(ManualOverride.movie_id == movie_id, ManualOverride.audio_stream_index == stream_index))
        if override:
            override.language, override.reason = language, reason or None
        else:
            session.add(ManualOverride(movie_id=movie_id, audio_stream_index=stream_index, language=language, reason=reason or None))
        enqueue(session, movie_id)


def delete_override(movie_id: int, stream_index: int) -> None:
    with Session.begin() as session:
        override = session.scalar(select(ManualOverride).where(ManualOverride.movie_id == movie_id, ManualOverride.audio_stream_index == stream_index))
        if override:
            session.delete(override)
            enqueue(session, movie_id)


def subtitle_state(required: set[str], records: dict[str, Subtitle]) -> tuple[str, list[str]]:
    missing, failed, not_found, searching = [], [], [], []
    for language in sorted(required):
        record = records.get(language)
        if record is None or record.status != SubtitleStatus.READY:
            missing.append(language.upper())
            if record and record.status in {SubtitleStatus.ERROR, SubtitleStatus.SYNC_FAILED}:
                failed.append(language.upper())
            elif record and record.status == SubtitleStatus.NOT_FOUND:
                not_found.append(language.upper())
            elif record and record.status in {SubtitleStatus.SEARCHING, SubtitleStatus.DOWNLOADED, SubtitleStatus.SYNCING}:
                searching.append(language.upper())
    if failed:
        return f"⚠ Failed: {', '.join(failed)}", missing
    if not_found:
        return f"⚠ No match: {', '.join(not_found)}", missing
    if searching:
        return f"↻ Working: {', '.join(searching)}", missing
    if missing:
        return f"○ Not checked: {', '.join(missing)}", missing
    return "✓ Ready", []


@st.dialog("Movie details", width="large")
def show_movie_detail(movie_id: int) -> None:
    with Session() as session:
        movie = session.get(Movie, movie_id)
        if movie is None:
            st.error("This movie no longer exists in the local database.")
            return
        movie_tracks = list(session.scalars(select(AudioTrack).where(AudioTrack.movie_id == movie.id).order_by(AudioTrack.stream_index)))
        records = {subtitle.language: subtitle for subtitle in session.scalars(select(Subtitle).where(Subtitle.movie_id == movie.id))}
        overrides = {override.audio_stream_index: override for override in session.scalars(select(ManualOverride).where(ManualOverride.movie_id == movie.id))}
        active_job = session.scalar(select(Job).where(Job.movie_id == movie.id, Job.status.in_([JobStatus.PENDING, JobStatus.PROCESSING])).order_by(Job.id.desc()))
        languages = [track.normalized_language for track in movie_tracks]
        required = required_subtitle_languages(languages) if movie.status == MovieStatus.PROCESSED else set()
        try:
            embedded = {normalize_language(stream.language): stream for stream in inspect_subtitle_streams(Path(movie.worker_path)) if normalize_language(stream.language)}
        except Exception:
            embedded = {}

        st.subheader(f"{movie.title} · {movie.year or 'Unknown year'}")
        st.caption(f"{movie.library_name} · {movie.worker_path}")
        visible_status = "Processing" if active_job and active_job.status == JobStatus.PROCESSING else "Queued" if active_job else movie.status.value.replace("_", " ").title()
        st.write(f"Processing status: **{visible_status}**")
        if active_job:
            st.caption(f"Job {active_job.id} · attempt {active_job.attempts} · {active_job.job_type.replace('_', ' ').title()}")
        if movie.error_message:
            st.error(movie.error_message)
        audio_col, subtitle_col = st.columns(2)
        with audio_col:
            st.markdown("#### Audio")
            st.dataframe(pd.DataFrame([{
                "Stream": track.stream_index, "Metadata": track.metadata_language or "und", "Effective": (track.normalized_language or "UNKNOWN").upper(),
                "Whisper": (track.detected_language or "—").upper(), "Confidence": track.confidence, "Method": track.detection_method or "—",
                "Title": track.title or "—",
            } for track in movie_tracks]), use_container_width=True, hide_index=True)
            st.caption("Managed tags: " + (", ".join(sorted(audio_tags(languages))) or "none"))
        with subtitle_col:
            st.markdown("#### Subtitles")
            detail_rows = []
            for language in sorted(required | set(records)):
                record = records.get(language)
                embedded_stream = embedded.get(language)
                detail_rows.append({
                    "Language": language.upper(), "Required": "Yes" if language in required else "No",
                    "Status": record.status.value if record else ("EMBEDDED" if embedded_stream else "MISSING"),
                    "Source": record.source if record and record.source else ("embedded" if embedded_stream else "—"),
                    "Sync": record.sync_status if record and record.sync_status else ("EMBEDDED" if embedded_stream else "—"),
                    "Path / stream": record.path if record and record.path else (f"Embedded stream {embedded_stream.index}" if embedded_stream else "—"),
                    "Detail": record.error_message if record and record.error_message else "—",
                })
            st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)
            st.caption("Subtitle automation is " + ("enabled" if config.subtitles_enabled else "disabled") + ". Embedded streams and usable sidecars satisfy a subtitle requirement.")

        st.divider()
        action_col, override_col = st.columns([1, 2])
        with action_col:
            if st.button("Queue reprocessing", type="primary", use_container_width=True):
                try:
                    job_id, queued = queue_movie(movie.id)
                except OperationalError:
                    st.error("The queue is briefly busy. Please try again in a few seconds.")
                    return
                if queued:
                    st.session_state["queue_notice"] = f"Queued job {job_id} for {movie.title}."
                else:
                    st.session_state["queue_notice"] = f"{movie.title} is already queued or processing (job {job_id})."
                # Close this dialog and clear the button event, so the next
                # title can be opened and queued without a stale modal state.
                st.rerun()
            st.caption("Existing audio detection is reused unless media or an override changed.")
        with override_col:
            st.markdown("##### Manual audio override")
            if movie_tracks:
                stream_index = st.selectbox("Audio stream", [track.stream_index for track in movie_tracks], format_func=lambda value: f"Stream {value}", key=f"dialog-stream-{movie.id}")
                current = overrides.get(stream_index)
                with st.form(f"dialog-override-{movie.id}"):
                    language_options = ["cs", "en", "sk", "de", "fr", "it", "es", "other"]
                    language = st.selectbox("Language", language_options, index=language_options.index(current.language) if current and current.language in language_options else 0)
                    reason = st.text_input("Reason (optional)", value=current.reason if current and current.reason else "")
                    if st.form_submit_button("Save and queue"):
                        save_override(movie.id, stream_index, language, reason)
                        st.success("Override saved and movie queued.")
                if current and st.button("Remove this override", key=f"dialog-remove-{movie.id}"):
                    delete_override(movie.id, stream_index)
                    st.success("Override removed and movie queued.")


st.title("🎬 Jellyfin Media Auditor")
st.caption("Audio tags, subtitle readiness, and processing health in one place.")
if notice := st.session_state.pop("queue_notice", None):
    st.toast(notice, icon="✅")

with Session() as session:
    movies = list(session.scalars(select(Movie).where(Movie.active.is_(True)).order_by(Movie.title)))
    tracks_by_movie: dict[int, list[AudioTrack]] = defaultdict(list)
    for track in session.scalars(select(AudioTrack).join(Movie).where(Movie.active.is_(True))):
        tracks_by_movie[track.movie_id].append(track)
    subtitle_by_movie: dict[int, dict[str, Subtitle]] = defaultdict(dict)
    for subtitle in session.scalars(select(Subtitle)):
        subtitle_by_movie[subtitle.movie_id][subtitle.language] = subtitle
    jobs_by_status = dict(session.execute(select(Job.status, func.count(Job.id)).group_by(Job.status)).all())
    active_jobs = {job.movie_id: job.status for job in session.scalars(select(Job).where(Job.status.in_([JobStatus.PENDING, JobStatus.PROCESSING])).order_by(Job.id))}

    rows: list[dict] = []
    missing_czech = missing_english = subtitle_problems = 0
    for movie in movies:
        languages = [track.normalized_language for track in tracks_by_movie[movie.id]]
        tags = audio_tags(languages)
        required = required_subtitle_languages(languages) if movie.status == MovieStatus.PROCESSED else set()
        subtitle_summary, missing = subtitle_state(required, subtitle_by_movie[movie.id]) if required else ("—", [])
        missing_czech += int("CS" in missing)
        missing_english += int("EN" in missing)
        subtitle_problems += int(subtitle_summary.startswith("⚠"))
        active_job_status = active_jobs.get(movie.id)
        visible_status = "Processing" if active_job_status == JobStatus.PROCESSING else "Queued" if active_job_status == JobStatus.PENDING else movie.status.value.replace("_", " ").title()
        rows.append({
            "_id": movie.id,
            "Title": movie.title,
            "Year": movie.year or "—",
            "Status": visible_status,
            "Audio": ", ".join(sorted(language.upper() for language in languages if language)) or "UNKNOWN",
            "Tags": ", ".join(sorted(tags)) or "—",
            "Subtitles": subtitle_summary,
            "Library": movie.library_name,
            "Last processed": movie.last_processed_at,
            "Updated": movie.updated_at,
            "_attention": active_job_status is not None or movie.status in {MovieStatus.UNSCANNED, MovieStatus.QUEUED, MovieStatus.WAITING_FOR_METADATA, MovieStatus.UNSURE, MovieStatus.ERROR} or bool(missing),
        })

    counts = defaultdict(int)
    for movie in movies:
        counts[movie.status] += 1
    attention = sum(row["_attention"] for row in rows)
    last_scan = max((movie.last_scan_at for movie in movies if movie.last_scan_at), default=None)

    status_col, queue_col, subtitle_col = st.columns([1.25, 1, 1.75])
    with status_col:
        if attention:
            st.warning(f"**{attention} movie{'s' if attention != 1 else ''} need attention**\n\nReview unscanned, unsure, errors, and required subtitles.")
        else:
            st.success("**Library is in good shape**\n\nNo movies currently need attention.")
    with queue_col:
        active_jobs = jobs_by_status.get(JobStatus.PENDING, 0) + jobs_by_status.get(JobStatus.PROCESSING, 0)
        st.info(f"**Queue health**\n\n{active_jobs} active job{'s' if active_jobs != 1 else ''}\n\nLast scan: {last_scan.strftime('%d %b %H:%M') if last_scan else 'never'}")
    with subtitle_col:
        if config.subtitles_enabled:
            st.success(f"**Subtitle automation is ON**\n\nNeeds subtitles: CZ {missing_czech} · EN {missing_english}\n\nNo-match / failed: {subtitle_problems}")
        else:
            st.warning(f"**Subtitle automation is OFF**\n\nReady sidecars are shown below. Pending downloads: CZ {missing_czech} · EN {missing_english}.")

    metrics = [
        ("Movies", len(movies)), ("Processed", counts[MovieStatus.PROCESSED]),
        ("Needs attention", attention), ("Unsure", counts[MovieStatus.UNSURE]),
        ("Errors", counts[MovieStatus.ERROR]), ("CZ audio", sum("CZ Audio" in audio_tags([track.normalized_language for track in tracks_by_movie[movie.id]]) for movie in movies)),
        ("EN audio", sum("EN Audio" in audio_tags([track.normalized_language for track in tracks_by_movie[movie.id]]) for movie in movies)),
        ("Other audio", sum("OTHER Audio" in audio_tags([track.normalized_language for track in tracks_by_movie[movie.id]]) for movie in movies)),
    ]
    for column, (label, value) in zip(st.columns(4) * 2, metrics):
        column.metric(label, value)

    st.divider()
    title_col, filter_col, sort_col = st.columns([2.2, 1, 1])
    with title_col:
        st.subheader("Movies")
        st.caption("Click a movie title to open its detail dialog.")
    with filter_col:
        with st.popover("Filters", use_container_width=True):
            title_filter = st.text_input("Title contains", placeholder="Search title")
            status_filter = st.multiselect("Processing status", sorted({row["Status"] for row in rows}))
            tag_filter = st.multiselect("Audio tag", ["CZ Audio", "EN Audio", "OTHER Audio"])
            subtitle_filter = st.multiselect("Subtitle state", ["Ready", "Missing", "Problem"])
            library_filter = st.multiselect("Library", sorted({row["Library"] for row in rows}))
    with sort_col:
        sort_order = st.selectbox("Sort", ["Needs attention first", "Title A–Z", "Recently processed", "Recently updated"], label_visibility="collapsed")

    filtered = rows[:]
    if title_filter:
        filtered = [row for row in filtered if title_filter.casefold() in row["Title"].casefold()]
    if status_filter:
        filtered = [row for row in filtered if row["Status"] in status_filter]
    if tag_filter:
        filtered = [row for row in filtered if all(tag in row["Tags"] for tag in tag_filter)]
    if subtitle_filter:
        def subtitle_matches(row: dict) -> bool:
            state = row["Subtitles"]
            return ("Ready" in subtitle_filter and state == "✓ Ready") or ("Missing" in subtitle_filter and (state.startswith("○") or state.startswith("↻"))) or ("Problem" in subtitle_filter and state.startswith("⚠"))
        filtered = [row for row in filtered if subtitle_matches(row)]
    if library_filter:
        filtered = [row for row in filtered if row["Library"] in library_filter]
    if sort_order == "Needs attention first":
        filtered.sort(key=lambda row: (not row["_attention"], row["Title"].casefold()))
    elif sort_order == "Title A–Z":
        filtered.sort(key=lambda row: row["Title"].casefold())
    elif sort_order == "Recently processed":
        filtered.sort(key=lambda row: row["Last processed"] or datetime.min, reverse=True)
    else:
        filtered.sort(key=lambda row: row["Updated"] or datetime.min, reverse=True)

    display = pd.DataFrame(filtered).drop(columns=["_id", "_attention", "Updated"], errors="ignore")
    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Title": st.column_config.ButtonColumn("Title", width="large", type="tertiary", help="Open movie details", key="movie_title_click"),
            "Status": st.column_config.TextColumn("Status", width="medium"),
            "Subtitles": st.column_config.TextColumn("Subtitles", width="medium"),
            "Last processed": st.column_config.DatetimeColumn("Last processed", format="D MMM YYYY, HH:mm"),
        },
    )
    click = st.session_state.get("movie_title_click")
    if click is not None and click.row < len(filtered):
        show_movie_detail(filtered[click.row]["_id"])

with st.expander("Advanced: queue a known Jellyfin item ID"):
    manual_id = st.text_input("Jellyfin item ID")
    if st.button("Queue known item") and manual_id:
        with Session() as session:
            movie = session.scalar(select(Movie).where(Movie.jellyfin_item_id == manual_id))
        if movie:
            queue_movie(movie.id)
            st.success("Queued")
        else:
            st.warning("This item is not in the local database yet. The webhook or periodic scan will import it.")
