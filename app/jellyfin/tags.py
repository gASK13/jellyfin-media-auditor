from __future__ import annotations

from dataclasses import dataclass

from app.media.language import audio_tags

MANAGED_AUDIO_TAGS = {"CZ Audio", "EN Audio", "OTHER Audio"}


@dataclass(frozen=True)
class TagChange:
    name: str
    add: bool


def reconcile_movie_tags(client, *, movie_id: str, languages: list[str | None]) -> list[TagChange]:
    desired = audio_tags(languages)
    existing = set(client.item_tags(movie_id))
    additions = desired - existing
    removals = (existing & MANAGED_AUDIO_TAGS) - desired
    if additions or removals:
        if hasattr(client, "update_tags"):
            new_tags = (existing - MANAGED_AUDIO_TAGS) | desired
            client.update_tags(movie_id, new_tags)
        else:
            client.add_tags(movie_id, additions)
            client.remove_tags(movie_id, removals)
    return [*(TagChange(tag, True) for tag in sorted(additions)), *(TagChange(tag, False) for tag in sorted(removals))]
