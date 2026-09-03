from __future__ import annotations

import argparse
from dataclasses import replace

from sqlalchemy import select

from app.config import load_config
from app.db.database import make_session_factory
from app.db.models import Job, Movie, Subtitle
from app.jellyfin.client import JellyfinClient
from app.jellyfin.scanner import upsert_item
from app.jobs.worker import Worker


def main() -> None:
    parser = argparse.ArgumentParser(description="Run subtitle automation for one Jellyfin movie only")
    parser.add_argument("--item-id", required=True, help="Jellyfin item ID")
    args = parser.parse_args()

    config = replace(load_config(), subtitles_enabled=True)
    Session = make_session_factory(config.db_path)
    client = JellyfinClient(config.jellyfin_url, config.jellyfin_api_key, config.jellyfin_user_id)
    with Session() as session:
        movie = session.scalar(select(Movie).where(Movie.jellyfin_item_id == args.item_id))
        if movie is None:
            item = client.get_item(args.item_id)
            library = next((library for library in config.libraries if library.jellyfin_id == item.get("ParentId")), None)
            if library is None:
                raise SystemExit("Movie does not belong to a configured library")
            movie = upsert_item(session, config, library, item, queue_changed=False)
        job = Job(movie_id=movie.id, job_type="SUBTITLE_TEST")
        session.add(job); session.flush()
        Worker(config, jellyfin_client=client).process(session, job)
        subtitles = list(session.scalars(select(Subtitle).where(Subtitle.movie_id == movie.id).order_by(Subtitle.language)))
        print(f"movie={movie.title} status={movie.status.value}")
        for subtitle in subtitles:
            print(f"language={subtitle.language} status={subtitle.status.value} path={subtitle.path or '-'} error={subtitle.error_message or '-'}")


if __name__ == "__main__":
    main()
