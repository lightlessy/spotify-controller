from __future__ import annotations

import unittest

import numpy as np

from snap_model import SnapModel, train_model


SAMPLE_RATE = 48_000
WINDOW_SAMPLES = int(0.22 * SAMPLE_RATE)


def make_snap(rng: np.random.Generator, amplitude: float) -> np.ndarray:
    samples = rng.normal(0.0, 2e-5, WINDOW_SAMPLES).astype(np.float32)
    center = int(0.055 * SAMPLE_RATE) + int(rng.integers(-80, 81))
    pulse = amplitude * np.asarray([0.2, -0.5, 1.0, -0.45, 0.16], dtype=np.float32)
    samples[center : center + len(pulse)] += pulse
    t = np.arange(120, dtype=np.float32) / SAMPLE_RATE
    samples[center + 5 : center + 125] += (
        amplitude
        * 0.25
        * np.exp(-t * 5_000)
        * np.sin(2 * np.pi * 6_500 * t)
    )
    return samples


def model_from_dict(raw: dict) -> SnapModel:
    return SnapModel(
        sample_rate=int(raw["sample_rate"]),
        feature_mean=np.asarray(raw["feature_mean"], dtype=np.float64),
        feature_std=np.asarray(raw["feature_std"], dtype=np.float64),
        positive_examples=np.asarray(raw["positive_examples"], dtype=np.float64),
        negative_examples=np.asarray(raw["negative_examples"], dtype=np.float64),
        k=int(raw["k"]),
        threshold=float(raw["threshold"]),
        max_positive_distance=float(raw["max_positive_distance"]),
        score_spread=float(raw["score_spread"]),
        candidate_peak=float(raw["candidate_peak"]),
        candidate_rms=float(raw["candidate_rms"]),
        training=dict(raw["training"]),
    )


class SnapModelRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        rng = np.random.default_rng(42)
        positives = [
            make_snap(rng, float(rng.uniform(0.0012, 0.0030)))
            for _ in range(12)
        ]

        negatives: list[np.ndarray] = []
        negatives.extend(
            rng.normal(0.0, 3e-5, WINDOW_SAMPLES).astype(np.float32)
            for _ in range(100)
        )
        t = np.arange(WINDOW_SAMPLES, dtype=np.float32) / SAMPLE_RATE
        negatives.extend(
            (
                float(rng.uniform(0.0002, 0.0030))
                * np.sin(2 * np.pi * float(rng.uniform(100, 800)) * t)
                + rng.normal(0.0, 2e-5, WINDOW_SAMPLES)
            ).astype(np.float32)
            for _ in range(60)
        )

        raw = train_model(positives, negatives, SAMPLE_RATE)
        cls.model = model_from_dict(raw)

    def test_near_silence_is_never_accepted(self) -> None:
        rng = np.random.default_rng(7)
        detections = 0
        for _ in range(100):
            silence = rng.normal(0.0, 3e-5, WINDOW_SAMPLES).astype(np.float32)
            detections += int(self.model.classify(silence, SAMPLE_RATE)[0])
        self.assertEqual(detections, 0)

    def test_unseen_snaps_are_mostly_accepted(self) -> None:
        rng = np.random.default_rng(99)
        detections = 0
        total = 30
        for _ in range(total):
            snap = make_snap(rng, float(rng.uniform(0.0012, 0.0030)))
            detections += int(self.model.classify(snap, SAMPLE_RATE)[0])
        self.assertGreaterEqual(detections, 27)


if __name__ == "__main__":
    unittest.main()
