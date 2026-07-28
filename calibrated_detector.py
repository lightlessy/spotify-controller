from __future__ import annotations

import logging
import math
import time
from collections import deque

import numpy as np

import spotify_snap as core
import spotify_snap_feedback as app
from overlay_notification import OverlayNotificationService
from snap_model import MODEL_PATH, SnapModel


class CalibratedSnapDetector:
    """Transient onset detector followed by a user-trained, OOD-gated verifier."""

    def __init__(self, settings: core.Settings) -> None:
        self.settings = settings
        self.model = SnapModel.load()
        self.model_mtime_ns = self._model_mtime_ns()
        self.next_model_check = 0.0
        self.blocks: deque[np.ndarray] = deque(maxlen=16)
        self.pending_blocks = 0
        self.last_detection = 0.0
        self.candidate_lockout_until = 0.0
        self.warmup_until = time.monotonic() + 2.5
        self.noise_peak = max(1e-7, self.model.candidate_peak * 0.35)
        self.noise_rms = max(1e-8, self.model.candidate_rms * 0.35)
        self.window = np.hanning(settings.block_size).astype(np.float32)

    @staticmethod
    def _model_mtime_ns() -> int:
        try:
            return MODEL_PATH.stat().st_mtime_ns
        except OSError:
            return 0

    def _reload_model_if_changed(self, now: float) -> None:
        if now < self.next_model_check:
            return
        self.next_model_check = now + 0.75
        current_mtime = self._model_mtime_ns()
        if current_mtime <= self.model_mtime_ns:
            return
        try:
            model = SnapModel.load()
        except Exception:
            logging.exception("Güncellenen kişisel model yüklenemedi; eski model korunuyor.")
            return
        self.model = model
        self.model_mtime_ns = current_mtime
        self.noise_peak = max(1e-8, self.noise_peak)
        self.noise_rms = max(1e-9, self.noise_rms)
        logging.info("Kişisel model canlı olarak güncellendi.")

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

    def _update_noise(self, metrics: dict[str, float], rate: float = 0.02) -> None:
        peak_cap = max(self.model.candidate_peak, self.noise_peak * 2.5)
        rms_cap = max(self.model.candidate_rms, self.noise_rms * 2.0)
        self.noise_peak = (1.0 - rate) * self.noise_peak + rate * min(
            metrics["peak"], peak_cap
        )
        self.noise_rms = (1.0 - rate) * self.noise_rms + rate * min(
            metrics["rms"], rms_cap
        )

    def analyze(
        self, samples: np.ndarray
    ) -> tuple[bool, dict[str, float]]:
        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        self.blocks.append(samples.copy())
        metrics = self._metrics(samples)
        now = time.monotonic()
        self._reload_model_if_changed(now)

        if now < self.warmup_until:
            self._update_noise(metrics, rate=0.12)
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
            metrics["peak"] = classifier_metrics["event_peak"]
            metrics["rms"] = classifier_metrics["event_rms"]

            self.candidate_lockout_until = now + 0.12
            if (
                accepted
                and now - self.last_detection
                > self.settings.refractory_time
            ):
                self.last_detection = now
                self.blocks.clear()
                return True, metrics

            self._update_noise(metrics, rate=0.01)
            return False, metrics

        if now < self.candidate_lockout_until:
            self._update_noise(metrics)
            return False, metrics

        peak_threshold = max(
            self.model.candidate_peak, self.noise_peak * 2.8
        )
        rms_threshold = max(
            self.model.candidate_rms, self.noise_rms * 1.55
        )
        candidate = (
            metrics["peak"] >= peak_threshold
            and metrics["rms"] >= rms_threshold
            and metrics["crest"] >= 1.45
        )
        metrics["candidate_peak_threshold"] = peak_threshold
        metrics["candidate_rms_threshold"] = rms_threshold

        if candidate:
            self.pending_blocks = 5
        else:
            self._update_noise(metrics)
        return False, metrics


core.SnapDetector = CalibratedSnapDetector
app.NotificationService = OverlayNotificationService


if __name__ == "__main__":
    raise SystemExit(app.main())
