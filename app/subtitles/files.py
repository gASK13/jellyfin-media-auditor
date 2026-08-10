from __future__ import annotations
from pathlib import Path
from app.media.language import normalize_language

def final_subtitle_path(media_path: Path, language: str) -> Path:
    return media_path.with_suffix(f".{language}.srt")

def find_local_subtitle(media_path: Path, language: str) -> Path | None:
    language = normalize_language(language)
    for path in media_path.parent.glob(f"{media_path.stem}.*.srt"):
        suffixes=path.name.removesuffix(".srt").split(".")
        if suffixes and normalize_language(suffixes[-1]) == language and path.stat().st_size > 0: return path
    return None
