from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pysubs2


class SyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class SyncResult:
    path: Path
    synchronized: bool


def validate_srt(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise SyncError("Subtitle is empty")
    try:
        subtitles = pysubs2.load(str(path))
    except Exception as exc:
        raise SyncError(f"Subtitle is not a valid SRT file: {exc}") from exc
    if not subtitles:
        raise SyncError("Subtitle has no timed entries")


class SubtitleSynchronizer:
    def synchronize(self, media_path: Path, source_path: Path, final_path: Path) -> SyncResult:
        """Create a validated synchronized sidecar atomically; source_path is retained on failure."""
        validate_srt(source_path)
        with tempfile.TemporaryDirectory(prefix="jellyfin-auditor-sync-", dir=final_path.parent) as temporary_directory:
            output = Path(temporary_directory) / final_path.name
            executable = Path(sys.executable).parent / "ffsubsync"
            command = [str(executable if executable.is_file() else "ffsubsync"), str(media_path), "-i", str(source_path), "-o", str(output)]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=900)
            if completed.returncode:
                raise SyncError(completed.stderr.strip() or "ffsubsync failed")
            validate_srt(output)
            output.replace(final_path)
        return SyncResult(path=final_path, synchronized=True)
