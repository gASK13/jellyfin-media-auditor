from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_ENV = re.compile(r"\$\{([^}]+)\}")


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV.sub(lambda match: os.getenv(match.group(1), ""), value)
    if isinstance(value, list):
        return [_expand(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class Library:
    name: str
    jellyfin_id: str


@dataclass(frozen=True)
class Config:
    jellyfin_url: str
    jellyfin_api_key: str
    jellyfin_user_id: str | None
    webhook_token: str | None
    jellyfin_root: Path
    worker_root: Path
    libraries: list[Library]
    db_path: Path = Path("data/auditor.sqlite3")
    scanner_interval_minutes: int = 60
    worker_poll_seconds: int = 5
    max_attempts: int = 5
    scanner_failure_initial_seconds: int = 60
    scanner_failure_max_seconds: int = 3600
    job_stale_after_minutes: int = 180
    whisper_model: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    confidence_threshold: float = 0.75
    initial_sample_count: int = 3
    fallback_sample_count: int = 6
    sample_duration_seconds: int = 30
    opensubtitles_api_key: str = ""
    opensubtitles_username: str = ""
    opensubtitles_password: str = ""
    not_found_retry_hours: int = 168
    max_downloads_per_day: int = 100
    quota_retry_hours: int = 24
    subtitles_enabled: bool = False

    def worker_path(self, jellyfin_path: str) -> Path:
        source = Path(jellyfin_path)
        try:
            return self.worker_root / source.relative_to(self.jellyfin_root)
        except ValueError as exc:
            raise ValueError(f"Path {source} is outside configured Jellyfin root {self.jellyfin_root}") from exc


def _load_env_file(env_path: Path) -> None:
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = val


def load_config(path: str | Path | None = None) -> Config:
    config_path = Path(path or os.getenv("AUDITOR_CONFIG", "config.yaml"))
    _load_env_file(Path(".env"))
    _load_env_file(config_path.parent / ".env")
    _load_env_file(Path("/etc/jellyfin-media-auditor/env"))
    raw = _expand(yaml.safe_load(config_path.read_text()) or {})
    jellyfin, media = raw.get("jellyfin", {}), raw.get("media", {})
    scanner, whisper = raw.get("scanner", {}), raw.get("whisper", {})
    audio, subtitles, opensubtitles = raw.get("audio_detection", {}), raw.get("subtitles", {}), raw.get("opensubtitles", {})
    return Config(
        jellyfin_url=jellyfin["url"].rstrip("/"), jellyfin_api_key=jellyfin["api_key"], jellyfin_user_id=jellyfin.get("user_id") or None,
        webhook_token=jellyfin.get("webhook_token") or None,
        jellyfin_root=Path(media["jellyfin_root"]), worker_root=Path(media["worker_root"]),
        libraries=[Library(**library) for library in raw.get("libraries", [])],
        db_path=Path(raw.get("database", {}).get("path", "data/auditor.sqlite3")),
        scanner_interval_minutes=int(scanner.get("interval_minutes", 60)),
        worker_poll_seconds=int(scanner.get("worker_poll_seconds", 5)), max_attempts=int(scanner.get("max_attempts", 5)), scanner_failure_initial_seconds=int(scanner.get("failure_initial_seconds", 60)), scanner_failure_max_seconds=int(scanner.get("failure_max_seconds", 3600)), job_stale_after_minutes=int(scanner.get("job_stale_after_minutes", 180)),
        whisper_model=whisper.get("model", "base"), whisper_device=whisper.get("device", "cpu"),
        whisper_compute_type=whisper.get("compute_type", "int8"),
        confidence_threshold=float(audio.get("confidence_threshold", 0.75)),
        initial_sample_count=int(audio.get("initial_sample_count", audio.get("sample_count", 3))), fallback_sample_count=int(audio.get("fallback_sample_count", 6)), sample_duration_seconds=int(audio.get("sample_duration_seconds", 30)),
        opensubtitles_api_key=opensubtitles.get("api_key", ""), opensubtitles_username=opensubtitles.get("username", ""),
        opensubtitles_password=opensubtitles.get("password", ""),
        not_found_retry_hours=int(subtitles.get("not_found_retry_hours", 168)), max_downloads_per_day=int(subtitles.get("max_downloads_per_day", 100)), quota_retry_hours=int(subtitles.get("quota_retry_hours", 24)), subtitles_enabled=bool(subtitles.get("enabled", False)),
    )
