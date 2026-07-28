from __future__ import annotations

import json

import spotify_snap as core
import spotify_snap_feedback as app


class BoundedSnapDetector(core.SnapDetector):
    """Reject sounds that are too loud/long to be this user's finger snap."""

    def __init__(self, settings: core.Settings) -> None:
        super().__init__(settings)
        try:
            raw = json.loads(core.CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}

        self.max_peak = float(raw.get("max_peak", 0.0035))
        self.max_rms = float(raw.get("max_rms", 0.0012))

    def analyze(self, samples):
        previous_detection = self.last_detection
        accepted, metrics = super().analyze(samples)

        too_loud = (
            metrics["peak"] > self.max_peak
            or metrics["rms"] > self.max_rms
        )
        if accepted and too_loud:
            # A rejected voice/noise block must not trigger the refractory timer.
            self.last_detection = previous_detection
            accepted = False

        metrics["max_peak"] = self.max_peak
        metrics["max_rms"] = self.max_rms
        return accepted, metrics


core.SnapDetector = BoundedSnapDetector


if __name__ == "__main__":
    raise SystemExit(app.main())
