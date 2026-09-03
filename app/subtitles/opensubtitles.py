from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from app.config import Config
from app.subtitles.search import SubtitleCandidate, choose_candidate


class OpenSubtitlesError(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchResult:
    candidate: SubtitleCandidate
    release: str | None = None


class OpenSubtitlesClient:
    """Small OpenSubtitles v1 client. Downloads only occur through download_srt()."""

    base_url = "https://api.opensubtitles.com/api/v1"
    user_agent = "jellyfin-media-auditor v1.0"

    def __init__(self, config: Config):
        if not config.opensubtitles_api_key:
            raise OpenSubtitlesError("OpenSubtitles API key is not configured")
        if not config.opensubtitles_username or not config.opensubtitles_password:
            raise OpenSubtitlesError("OpenSubtitles username/password are not configured")
        self.api_key = config.opensubtitles_api_key
        self.username = config.opensubtitles_username
        self.password = config.opensubtitles_password
        self.session = requests.Session()
        self.session.headers.update({"Api-Key": self.api_key, "User-Agent": self.user_agent, "Accept": "application/json"})
        self.token: str | None = None
        self._login_failure: OpenSubtitlesError | None = None

    def _login(self) -> None:
        if self._login_failure:
            raise self._login_failure
        response = self.session.post(f"{self.base_url}/login", json={"username": self.username, "password": self.password}, timeout=30)
        if response.status_code == 429:
            self._login_failure = OpenSubtitlesError("OpenSubtitles login is rate-limited; retry later")
            raise self._login_failure
        if response.status_code == 401:
            self._login_failure = OpenSubtitlesError("OpenSubtitles credentials were rejected")
            raise self._login_failure
        response.raise_for_status()
        payload = response.json()
        self.token = payload["token"]
        base_url = payload.get("base_url")
        if base_url:
            self.base_url = f"https://{base_url.rstrip('/')}" + ("" if base_url.endswith("/api/v1") else "/api/v1")
        self.session.headers["Authorization"] = f"Bearer {self.token}"

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        response = self.session.get(f"{self.base_url}{path}", params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def search(self, *, language: str, imdb_id: str | None, tmdb_id: str | None, filename: str) -> SearchResult | None:
        params: dict[str, Any] = {"languages": language, "type": "movie", "query": filename}
        if imdb_id:
            params["imdb_id"] = imdb_id.removeprefix("tt")
        elif tmdb_id:
            params["tmdb_id"] = tmdb_id
        data = self._get("/subtitles", **params).get("data", [])
        candidates: list[tuple[SubtitleCandidate, str | None]] = []
        for row in data:
            attributes = row.get("attributes", {})
            if attributes.get("language") != language:
                continue
            files = attributes.get("files") or []
            if not files:
                continue
            details = attributes.get("feature_details") or {}
            matched_imdb = bool(imdb_id and str(details.get("imdb_id", "")).removeprefix("tt") == imdb_id.removeprefix("tt"))
            candidate = SubtitleCandidate(
                file_id=int(files[0]["file_id"]), language=language, imdb_match=matched_imdb,
                release_match=filename.lower() in (attributes.get("release") or "").lower(),
                hearing_impaired=bool(attributes.get("hearing_impaired")),
                downloads=int(attributes.get("download_count") or 0), rating=float(attributes.get("ratings") or 0),
            )
            candidates.append((candidate, attributes.get("release")))
        chosen = choose_candidate([candidate for candidate, _ in candidates])
        if not chosen:
            return None
        return next(SearchResult(candidate, release) for candidate, release in candidates if candidate == chosen)

    def download_srt(self, file_id: int, destination: Path) -> None:
        if not self.token:
            self._login()
        response = self.session.post(f"{self.base_url}/download", json={"file_id": file_id, "sub_format": "srt", "file_name": destination.name}, timeout=30)
        response.raise_for_status()
        link = response.json().get("link")
        if not link:
            raise OpenSubtitlesError("OpenSubtitles did not provide a download link")
        content = self.session.get(link, timeout=60)
        content.raise_for_status()
        if not content.content:
            raise OpenSubtitlesError("OpenSubtitles returned an empty subtitle")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp", delete=False) as temporary:
            temporary.write(content.content)
            temporary_path = Path(temporary.name)
        try:
            temporary_path.replace(destination)
        finally:
            temporary_path.unlink(missing_ok=True)
