from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class SubtitleCandidate:
    file_id: int; language: str; moviehash_match: bool=False; imdb_match: bool=False; release_match: bool=False; fps_match: bool=False; hearing_impaired: bool=False; downloads: int=0; rating: float=0

def rank_candidate(candidate: SubtitleCandidate) -> tuple:
    # Identity match is deliberately more important than popularity.
    return (candidate.moviehash_match, candidate.imdb_match, candidate.release_match, candidate.fps_match, not candidate.hearing_impaired, candidate.rating, candidate.downloads)

def choose_candidate(candidates: list[SubtitleCandidate]) -> SubtitleCandidate | None:
    return max(candidates, key=rank_candidate, default=None)
