from __future__ import annotations

import argparse
import logging

from app.config import load_config
from app.jellyfin.client import JellyfinClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def clear_library_movie_tags(client: JellyfinClient, library_id: str, dry_run: bool) -> tuple[int, int]:
    items = client.movies(library_id)
    changed = tags = 0
    for item in items:
        existing = set(client.item_tags(item["Id"]))
        if not existing:
            continue
        changed += 1; tags += len(existing)
        logging.info("%s: %d tags%s", item.get("Name", item["Id"]), len(existing), " (dry run)" if dry_run else "")
        if not dry_run:
            client.remove_tags(item["Id"], existing)
    return changed, tags


def main() -> None:
    parser = argparse.ArgumentParser(description="Jellyfin Media Auditor maintenance commands")
    parser.add_argument("command", choices=["clear-library-movie-tags"])
    parser.add_argument("--library-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    config = load_config()
    client = JellyfinClient(config.jellyfin_url, config.jellyfin_api_key, config.jellyfin_user_id)
    changed, tags = clear_library_movie_tags(client, args.library_id, args.dry_run)
    logging.info("%s movies, %s tags %s", changed, tags, "would be removed" if args.dry_run else "removed")


if __name__ == "__main__":
    main()
