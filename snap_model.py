from __future__ import annotations

import json
import math
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

APP_DIR = Path(__file__).resolve().parent
MODEL_PATH = APP_DIR / "snap_model.json"
MODEL_VERSION = 2
EVENT_SECONDS = 0.22
PRE_PEAK_SECONDS = 0.055


def extract_event_window(
    samples: np.ndarray,
    sample_rate: int,
    event_seconds: float = EVENT_SECONDS,
    pre_peak_seconds: float = PRE_PEAK_SECONDS,
) -> np.ndarray:
    samples = np.asarray(samples, dtype=np.float32).reshape(-1)
    target = max(256, int(round(event_seconds * sample_rate)))
    if samples.size == 0:
        return np.zeros(target, dtype=np.float32)

    centered = samples - float(np.mean(samples))
    peak_index = int(np.argmax(np.abs(centered)))
    pre = int(round(pre_peak_seconds * sample_rate))
    start = peak_index - pre

    output = np.zeros(target, dtype=np.float32)
    source_start = max(0, start)
    source_end = min(len(centered), start + target)
    target_start = source_start - start
    if source_end > source_start:
        output[target_start : target_start + source_end - source_start] = centered[
            source_start:source_end
        ]
    return output


def event_levels(samples: np.ndarray, sample_rate: int) -> tuple[float, float]:
    event = extract_event_window(samples, sample_rate)
    event = event - float(np.mean(event))
    peak = float(np.max(np.abs(event)))
    rms = math.sqrt(float(np.mean(event * event)) + 1e-12)
    return peak, rms


def _frame_rms(samples: np.ndarray, frame_count: int = 16) -> np.ndarray:
    chunks = np.array_split(samples, frame_count)
    values = np.asarray(
        [math.sqrt(float(np.mean(chunk * chunk)) + 1e-12) for chunk in chunks],
        dtype=np.float64,
    )
    scale = float(np.max(values)) + 1e-12
    return np.log1p(30.0 * values / scale)


def _band_energies(
    power: np.ndarray, frequencies: np.ndarray, band_count: int = 20
) -> np.ndarray:
    upper = max(1_000.0, min(18_000.0, float(frequencies[-1])))
    edges = np.geomspace(60.0, upper, band_count + 1)
    total = float(np.sum(power)) + 1e-12
    values: list[float] = []
    for low, high in zip(edges[:-1], edges[1:]):
        mask = (frequencies >= low) & (frequencies < high)
        energy = float(np.sum(power[mask])) if np.any(mask) else 0.0
        values.append(math.log1p(200.0 * energy / total))
    return np.asarray(values, dtype=np.float64)


def feature_vector(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    event = extract_event_window(samples, sample_rate)
    event = event - float(np.mean(event))
    absolute = np.abs(event)
    peak = float(np.max(absolute)) + 1e-12
    rms = math.sqrt(float(np.mean(event * event)) + 1e-12)
    peak_index = int(np.argmax(absolute))

    normalized = event / peak
    window = np.hanning(len(normalized)).astype(np.float32)
    spectrum = np.abs(np.fft.rfft(normalized * window)) ** 2
    frequencies = np.fft.rfftfreq(len(normalized), 1.0 / sample_rate)
    spectral_total = float(np.sum(spectrum)) + 1e-12

    centroid = float(np.sum(frequencies * spectrum) / spectral_total)
    bandwidth = math.sqrt(
        float(np.sum(((frequencies - centroid) ** 2) * spectrum) / spectral_total)
    )
    cumulative = np.cumsum(spectrum)
    rolloff_index = int(np.searchsorted(cumulative, 0.90 * cumulative[-1]))
    rolloff = float(frequencies[min(rolloff_index, len(frequencies) - 1)])
    positive_power = spectrum[spectrum > 1e-16]
    flatness = (
        float(
            np.exp(np.mean(np.log(positive_power)))
            / (np.mean(positive_power) + 1e-12)
        )
        if positive_power.size
        else 0.0
    )

    threshold = 0.20 * peak
    active = np.flatnonzero(absolute >= threshold)
    impulse_width = (
        float(active[-1] - active[0] + 1) / len(event) if active.size else 1.0
    )
    pre_energy = float(np.sum(event[:peak_index] ** 2)) + 1e-12
    post_energy = float(np.sum(event[peak_index + 1 :] ** 2)) + 1e-12
    total_energy = pre_energy + post_energy
    zero_crossing = float(np.mean(np.signbit(event[1:]) != np.signbit(event[:-1])))

    nyquist = sample_rate / 2.0
    globals_ = np.asarray(
        [
            math.log10(peak),
            math.log10(rms + 1e-12),
            min(30.0, peak / (rms + 1e-12)) / 30.0,
            peak_index / max(1, len(event) - 1),
            impulse_width,
            pre_energy / total_energy,
            post_energy / total_energy,
            zero_crossing,
            centroid / nyquist,
            bandwidth / nyquist,
            rolloff / nyquist,
            flatness,
        ],
        dtype=np.float64,
    )
    return np.concatenate(
        [globals_, _frame_rms(event), _band_energies(spectrum, frequencies)]
    )


def _nearest_mean(reference: np.ndarray, query: np.ndarray, k: int) -> float:
    distances = np.sum((reference - query) ** 2, axis=1)
    k = max(1, min(k, len(distances)))
    nearest = np.partition(distances, k - 1)[:k]
    return float(np.mean(nearest))


def _choose_threshold(
    positive_margins: np.ndarray, negative_margins: np.ndarray
) -> float:
    all_values = np.unique(np.concatenate([positive_margins, negative_margins]))
    candidates = [float(all_values[0] - 1e-6), float(all_values[-1] + 1e-6)]
    candidates.extend(
        float((a + b) / 2.0) for a, b in zip(all_values[:-1], all_values[1:])
    )

    best_threshold = candidates[-1]
    best_key = (-float("inf"), -float("inf"), -float("inf"))
    for threshold in candidates:
        recall = float(np.mean(positive_margins >= threshold))
        false_positive_rate = float(np.mean(negative_margins >= threshold))
        utility = recall - 10.0 * false_positive_rate
        key = (utility, -false_positive_rate, recall)
        if key > best_key:
            best_key = key
            best_threshold = threshold
    return float(best_threshold)


def train_model(
    positive_windows: Iterable[np.ndarray],
    negative_windows: Iterable[np.ndarray],
    sample_rate: int,
) -> dict[str, Any]:
    positive_list = [np.asarray(x, dtype=np.float32) for x in positive_windows]
    negative_list = [np.asarray(x, dtype=np.float32) for x in negative_windows]
    if len(positive_list) < 10:
        raise ValueError("En az 10 geçerli şıklatma örneği gerekli.")
    if len(negative_list) < 60:
        raise ValueError("En az 60 negatif ses örneği gerekli.")

    positive_features = np.vstack(
        [feature_vector(x, sample_rate) for x in positive_list]
    )
    negative_features = np.vstack(
        [feature_vector(x, sample_rate) for x in negative_list]
    )
    combined = np.vstack([positive_features, negative_features])
    mean = np.mean(combined, axis=0)
    std = np.std(combined, axis=0)
    std[std < 1e-5] = 1.0

    positive_scaled = (positive_features - mean) / std
    negative_scaled = (negative_features - mean) / std
    k = max(1, min(3, len(positive_scaled) - 1, len(negative_scaled) - 1))

    positive_distances: list[float] = []
    positive_margins: list[float] = []
    for index, query in enumerate(positive_scaled):
        own = np.delete(positive_scaled, index, axis=0)
        positive_distance = _nearest_mean(own, query, k)
        negative_distance = _nearest_mean(negative_scaled, query, k)
        positive_distances.append(positive_distance)
        positive_margins.append(negative_distance - positive_distance)

    negative_margins: list[float] = []
    for index, query in enumerate(negative_scaled):
        own = np.delete(negative_scaled, index, axis=0)
        positive_distance = _nearest_mean(positive_scaled, query, k)
        negative_distance = _nearest_mean(own, query, k)
        negative_margins.append(negative_distance - positive_distance)

    positive_distances_array = np.asarray(positive_distances, dtype=np.float64)
    positive_margins_array = np.asarray(positive_margins, dtype=np.float64)
    negative_margins_array = np.asarray(negative_margins, dtype=np.float64)
    threshold = _choose_threshold(positive_margins_array, negative_margins_array)
    max_positive_distance = max(
        1e-6, float(np.quantile(positive_distances_array, 0.95) * 1.65)
    )
    spread = max(
        1e-6,
        float(np.std(np.concatenate([positive_margins_array, negative_margins_array]))),
    )

    positive_levels = np.asarray(
        [event_levels(x, sample_rate) for x in positive_list], dtype=np.float64
    )
    positive_peaks = positive_levels[:, 0]
    positive_rms = positive_levels[:, 1]

    return {
        "version": MODEL_VERSION,
        "sample_rate": int(sample_rate),
        "event_seconds": EVENT_SECONDS,
        "feature_mean": mean.tolist(),
        "feature_std": std.tolist(),
        "positive_examples": positive_scaled.tolist(),
        "negative_examples": negative_scaled.tolist(),
        "k": int(k),
        "threshold": float(threshold),
        "max_positive_distance": float(max_positive_distance),
        "score_spread": float(spread),
        "candidate_peak": max(
            5e-6, float(np.quantile(positive_peaks, 0.10) * 0.30)
        ),
        "candidate_rms": max(
            1e-6, float(np.quantile(positive_rms, 0.10) * 0.25)
        ),
        "training": {
            "positive_count": len(positive_list),
            "negative_count": len(negative_list),
            "estimated_recall": float(
                np.mean(
                    (positive_margins_array >= threshold)
                    & (positive_distances_array <= max_positive_distance)
                )
            ),
            "estimated_false_positive_rate": float(
                np.mean(negative_margins_array >= threshold)
            ),
            "positive_peak_min": float(np.min(positive_peaks)),
            "positive_peak_median": float(np.median(positive_peaks)),
            "positive_peak_max": float(np.max(positive_peaks)),
        },
    }


@dataclass(slots=True)
class SnapModel:
    sample_rate: int
    feature_mean: np.ndarray
    feature_std: np.ndarray
    positive_examples: np.ndarray
    negative_examples: np.ndarray
    k: int
    threshold: float
    max_positive_distance: float
    score_spread: float
    candidate_peak: float
    candidate_rms: float
    training: dict[str, Any]

    @classmethod
    def load(cls, path: Path = MODEL_PATH) -> "SnapModel":
        if not path.exists():
            raise RuntimeError(
                "Kişisel şıklatma modeli bulunamadı. Önce calibrate.bat çalıştır."
            )
        raw = json.loads(path.read_text(encoding="utf-8"))
        if int(raw.get("version", 0)) != MODEL_VERSION:
            raise RuntimeError(
                "Şıklatma modeli eski. calibrate.bat ile yeniden kalibre et."
            )
        return cls(
            sample_rate=int(raw["sample_rate"]),
            feature_mean=np.asarray(raw["feature_mean"], dtype=np.float64),
            feature_std=np.asarray(raw["feature_std"], dtype=np.float64),
            positive_examples=np.asarray(raw["positive_examples"], dtype=np.float64),
            negative_examples=np.asarray(raw["negative_examples"], dtype=np.float64),
            k=int(raw["k"]),
            threshold=float(raw["threshold"]),
            max_positive_distance=float(raw["max_positive_distance"]),
            score_spread=float(raw.get("score_spread", 1.0)),
            candidate_peak=float(raw["candidate_peak"]),
            candidate_rms=float(raw["candidate_rms"]),
            training=dict(raw.get("training", {})),
        )

    def classify(
        self, samples: np.ndarray, sample_rate: int
    ) -> tuple[bool, dict[str, float]]:
        if sample_rate != self.sample_rate:
            raise RuntimeError(
                f"Model {self.sample_rate} Hz için kalibre edilmiş; "
                f"mikrofon {sample_rate} Hz kullanıyor."
            )

        peak, rms = event_levels(samples, sample_rate)
        query = (feature_vector(samples, sample_rate) - self.feature_mean) / self.feature_std
        positive_distance = _nearest_mean(self.positive_examples, query, self.k)
        negative_distance = _nearest_mean(self.negative_examples, query, self.k)
        score = negative_distance - positive_distance

        margin_ok = score >= self.threshold
        distance_ok = positive_distance <= self.max_positive_distance
        level_ok = peak >= self.candidate_peak and rms >= self.candidate_rms
        accepted = margin_ok and distance_ok and level_ok

        normalized_margin = max(
            -20.0, min(20.0, (score - self.threshold) / self.score_spread)
        )
        margin_confidence = 1.0 / (1.0 + math.exp(-normalized_margin))
        distance_confidence = max(
            0.0, min(1.0, 1.0 - positive_distance / (self.max_positive_distance + 1e-9))
        )
        confidence = margin_confidence * (0.35 + 0.65 * distance_confidence)

        return accepted, {
            "classifier_score": float(score),
            "classifier_threshold": float(self.threshold),
            "classifier_confidence": float(confidence),
            "positive_distance": float(positive_distance),
            "max_positive_distance": float(self.max_positive_distance),
            "negative_distance": float(negative_distance),
            "event_peak": float(peak),
            "event_rms": float(rms),
            "margin_ok": float(margin_ok),
            "distance_ok": float(distance_ok),
            "level_ok": float(level_ok),
        }


def save_model(model: dict[str, Any], path: Path = MODEL_PATH) -> None:
    path.write_text(
        json.dumps(model, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())


def sliding_windows(
    audio: np.ndarray,
    sample_rate: int,
    step_seconds: float = 0.11,
    max_count: int | None = None,
) -> list[np.ndarray]:
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    total = int(EVENT_SECONDS * sample_rate)
    step = max(1, int(step_seconds * sample_rate))
    if len(audio) < total:
        return [extract_event_window(audio, sample_rate)]

    starts = list(range(0, len(audio) - total + 1, step))
    if max_count is not None and len(starts) > max_count:
        indices = np.linspace(0, len(starts) - 1, max_count).astype(int)
        starts = [starts[i] for i in indices]
    return [audio[start : start + total].copy() for start in starts]


def peak_windows(
    audio: np.ndarray,
    sample_rate: int,
    count: int,
    min_gap_seconds: float = 0.10,
) -> list[np.ndarray]:
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    frame = max(64, int(0.005 * sample_rate))
    hop = max(32, frame // 2)
    positions: list[tuple[float, int]] = []
    for index in range(0, max(0, len(audio) - frame), hop):
        peak = float(np.max(np.abs(audio[index : index + frame])))
        positions.append((peak, index + frame // 2))

    selected: list[int] = []
    min_gap = int(min_gap_seconds * sample_rate)
    for _, center in sorted(positions, reverse=True):
        if all(abs(center - existing) >= min_gap for existing in selected):
            selected.append(center)
        if len(selected) >= count:
            break

    pre = int(PRE_PEAK_SECONDS * sample_rate)
    total = int(EVENT_SECONDS * sample_rate)
    windows: list[np.ndarray] = []
    for center in sorted(selected):
        start = center - pre
        segment = np.zeros(total, dtype=np.float32)
        source_start = max(0, start)
        source_end = min(len(audio), start + total)
        target_start = source_start - start
        if source_end > source_start:
            segment[target_start : target_start + source_end - source_start] = audio[
                source_start:source_end
            ]
        windows.append(segment)
    return windows
