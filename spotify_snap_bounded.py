from __future__ import annotations

import math
import time
from collections import deque

import numpy as np

import spotify_snap as core
import spotify_snap_feedback as app
from snap_model import SnapModel


class CalibratedSnapDetector:
    """Broad transient candidate detector followed by a user-trained verifier."""

    def __init__(self, settings: core.Settings) -> None:
        self.settings = settings
        self.model = SnapModel.load()
        self.blocks: deque[np.ndarray] = deque(maxlen=14)
        self.pending_blocks = 0
        self.last_detection = 0.0
        self.warmup_until = time.monotonic() + 1.8
        self.noise_peak = max(1e-7, self.model.candidate_peak * 0.5)
        self.noise_rms = max(1e-8, self.model.candidate_rms * 0.5)
        self.window = np.hanning(settings.block_size).astype(np.float32)

    def _metrics(self, samples: np.ndarray) -> dict[str, float]:
        samples = np.asarray(samples, dtype=np.float32)
        samples = samples - float(np.mean(samples))
        rms = math.sqrt(float(np.mean(samples * samples)) + 1e-12)
        peak = float(np.max(np.abs(samples)))
        crest = peak / (rms + 1e-12)
        window = (
            self.window
            if len(samples) == len(self.window)
            else np.hanning(len(samples))
        )
        spectrum = np.abs(np.fft.rfft(samples * window)) ** 2
        frequencies = np.fft.rfftfreq(
            len(samples), 1.0 / self.settings.sample_rate
        )
        total = float(np.sum(spectrum)) + 1e-12
        high = float(
            np.sum(
                spectrum[
                    frequencies >= self.settings.high_frequency_cutoff_hz
                ]
            )
            / total
        )
        return {
            "rms": rms,
            "peak": peak,
            "crest": crest,
            "high_ratio": high,
            "noise_floor": self.noise_rms,
        }

    def analyze(
        self, samples: np.ndarray
    ) -> tuple[bool, dict[str, float]]:
        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        self.blocks.append(samples.copy())
        metrics = self._metrics(samples)
        now = time.monotonic()

        if now < self.warmup_until:
            self.noise_peak = (
                0.90 * self.noise_peak + 0.10 * metrics["peak"]
            )
            self.noise_rms = 0.90 * self.noise_rms + 0.10 * metrics["rms"]
            metrics["warmup"] = 1.0
            return False, metrics

        if self.pending_blocks > 0:
            self.pending_blocks -= 1
            if self.pending_blocks > 0:
                return False, metrics

            event_audio = np.concatenate(tuple(self.blocks))
            accepted, classifier_metrics = self.model.classify(
                event_audio, self.settings.sample_rate
            )
            metrics.update(classifier_metrics)
            if (
                accepted
                and now - self.last_detection
                > self.settings.refractory_time
            ):
                self.last_detection = now
                return True, metrics
            return False, metrics

        peak_threshold = max(
            self.model.candidate_peak, self.noise_peak * 1.8
        )
        rms_threshold = max(
            self.model.candidate_rms, self.noise_rms * 1.20
        )
        candidate = (
            metrics["peak"] >= peak_threshold
            and metrics["rms"] >= rms_threshold
            and metrics["crest"] >= 1.6
        )
        metrics["candidate_peak_threshold"] = peak_threshold
        metrics["candidate_rms_threshold"] = rms_threshold

        if candidate:
            self.pending_blocks = 4
        else:
            self.noise_peak = 0.985 * self.noise_peak + 0.015 * min(
                metrics["peak"], peak_threshold
            )
            self.noise_rms = 0.985 * self.noise_rms + 0.015 * min(
                metrics["rms"], rms_threshold
            )
        return False, metrics


core.SnapDetector = CalibratedSnapDetector


if __name__ == "__main__":
    raise SystemExit(app.main())
