from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

_ALIASES = {"en": "en", "eng": "en", "english": "en", "cs": "cs", "cz": "cs", "ces": "cs", "cze": "cs", "czech": "cs"}
_UNKNOWN = {"", "und", "unknown", "unk", "null", "none", "n/a"}

def normalize_language(value: str | None) -> str | None:
    if value is None: return None
    code = value.strip().lower()
    if code in _UNKNOWN: return None
    return _ALIASES.get(code, code if len(code) in (2, 3) and code.isalpha() else None)

@dataclass(frozen=True)
class Detection: language: str | None; confidence: float; samples: int

def aggregate_detections(samples: Iterable[tuple[str | None, float]], threshold: float) -> Detection:
    totals: dict[str, float] = defaultdict(float); count = 0
    for language, confidence in samples:
        language = normalize_language(language)
        if language and confidence > 0:
            totals[language] += confidence; count += 1
    if not totals or not count: return Detection(None, 0.0, count)
    language, weight = max(totals.items(), key=lambda pair: pair[1])
    # A winning language must be both individually credible and materially dominant.
    confidence = weight / count
    if confidence < threshold or weight / sum(totals.values()) < 0.70: return Detection(None, confidence, count)
    return Detection(language, confidence, count)

def audio_tags(languages: Iterable[str | None]) -> set[str]:
    known = {language for item in languages if (language := normalize_language(item))}
    result = set()
    if "cs" in known: result.add("CZ Audio")
    if "en" in known: result.add("EN Audio")
    if known - {"cs", "en"}: result.add("OTHER Audio")
    return result

def required_subtitle_languages(languages: Iterable[str | None]) -> set[str]:
    known = {normalize_language(language) for language in languages}
    return {"cs", *( ["en"] if "en" in known else [])}
