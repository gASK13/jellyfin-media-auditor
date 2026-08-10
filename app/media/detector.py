from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from app.media.language import aggregate_detections


class FasterWhisperLanguageDetector:
    """Detect a single audio stream using evenly distributed speech samples."""

    def __init__(self, model_name: str, device: str, compute_type: str, initial_sample_count: int, fallback_sample_count: int, sample_duration_seconds: int, confidence_threshold: float):
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.initial_sample_count = initial_sample_count
        self.fallback_sample_count = fallback_sample_count
        self.sample_duration_seconds = sample_duration_seconds
        self.confidence_threshold = confidence_threshold
        self._model = None

    def _model_instance(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type)
        return self._model

    def _positions(self, duration: float | None, count: int, phase: int) -> list[float]:
        if not duration or duration <= self.sample_duration_seconds:
            return [0.0]
        # Exclude the first and last 10% where logos/credits commonly dominate.
        usable_start, usable_end = duration * 0.10, duration * 0.90 - self.sample_duration_seconds
        count = min(count, max(1, int((usable_end - usable_start) / self.sample_duration_seconds) + 1))
        # Different fractions for the fallback avoid re-sampling initial locations.
        fractions = [(index + 1) / (count + 1) for index in range(count)] if phase == 0 else [(index + 0.5) / count for index in range(count)]
        return [usable_start + (usable_end - usable_start) * fraction for fraction in fractions]

    def detect(self, media_path: Path, stream_index: int, duration: float | None) -> tuple[str | None, float]:
        results: list[tuple[str | None, float]] = []
        with tempfile.TemporaryDirectory(prefix="jellyfin-auditor-") as temporary_directory:
            for phase, sample_count in enumerate((self.initial_sample_count, self.fallback_sample_count)):
                if phase and aggregate_detections(results, self.confidence_threshold).language:
                    break
                for index, start in enumerate(self._positions(duration, sample_count, phase)):
                    sample = Path(temporary_directory) / f"sample-{phase}-{index}.wav"
                    command = ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{start:.3f}", "-t", str(self.sample_duration_seconds), "-i", str(media_path), "-map", f"0:{stream_index}", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-y", str(sample)]
                    completed = subprocess.run(command, capture_output=True, text=True, timeout=180)
                    if completed.returncode or not sample.exists() or not sample.stat().st_size:
                        continue
                    try:
                        _, info = self._model_instance().transcribe(str(sample), beam_size=1, vad_filter=True, condition_on_previous_text=False)
                        results.append((info.language, float(info.language_probability)))
                    except Exception:
                        # One music/silence-heavy sample must not fail an otherwise usable audit.
                        continue
        aggregate = aggregate_detections(results, self.confidence_threshold)
        return aggregate.language, aggregate.confidence
