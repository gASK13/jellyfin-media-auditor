from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class AudioStream:
    index: int; codec: str | None; channels: int | None; language: str | None; title: str | None; is_default: bool; is_forced: bool

@dataclass(frozen=True)
class SubtitleStream:
    index: int; codec: str | None; language: str | None; title: str | None; is_default: bool; is_forced: bool

def _streams(path: Path) -> list[dict]:
    command = ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)]
    try:
        raw = subprocess.run(command, check=True, capture_output=True, text=True, timeout=90).stdout
    except FileNotFoundError as exc: raise RuntimeError("ffprobe is not installed") from exc
    except subprocess.CalledProcessError as exc: raise RuntimeError(exc.stderr.strip() or "ffprobe failed") from exc
    return json.loads(raw).get("streams", [])

def inspect_media(path: Path) -> tuple[list[AudioStream], str]:
    streams = _streams(path)
    audio = [AudioStream(index=s["index"], codec=s.get("codec_name"), channels=s.get("channels"), language=s.get("tags", {}).get("language"), title=s.get("tags", {}).get("title"), is_default=bool(s.get("disposition", {}).get("default")), is_forced=bool(s.get("disposition", {}).get("forced"))) for s in streams if s.get("codec_type") == "audio"]
    signature = "|".join(f"{s.index}:{s.codec}:{s.channels}:{s.language}:{s.title}" for s in audio)
    return audio, signature

def inspect_subtitle_streams(path: Path) -> list[SubtitleStream]:
    return [SubtitleStream(index=s["index"], codec=s.get("codec_name"), language=s.get("tags", {}).get("language"), title=s.get("tags", {}).get("title"), is_default=bool(s.get("disposition", {}).get("default")), is_forced=bool(s.get("disposition", {}).get("forced"))) for s in _streams(path) if s.get("codec_type") == "subtitle"]
