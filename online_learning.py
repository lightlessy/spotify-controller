from __future__ import annotations

import json
import os
import time
import wave
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

import numpy as np

from snap_model import (
    MODEL_PATH,
    MODEL_VERSION,
    extract_event_window,
    feature_vector,
    peak_windows,
    sliding_windows,
)

MAX_NEGATIVE_EXAMPLES = 900
MODEL_LOCK_PATH = MODEL_PATH.with_suffix(".learn.lock")


@contextmanager
def _model_write_lock(timeout_seconds: float = 6.0) -> Iterator[None]:
    """Serialize learning writes from multiple popup processes."""

    deadline = time.monotonic() + timeout_seconds
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(
                MODEL_LOCK_PATH,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError("Model başka bir feedback işlemi tarafından güncelleniyor.")
            time.sleep(0.05)

    try:
        os.write(descriptor, str(os.getpid()).encode("ascii", errors="ignore"))
        yield
    finally:
        os.close(descriptor)
        MODEL_LOCK_PATH.unlink(missing_ok=True)


def read_wav_mono(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frames = wav_file.readframes(wav_file.getnframes())

    if sample_width != 2:
        raise ValueError("Yalnızca 16-bit PCM WAV destekleniyor.")

    audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return audio.reshape(-1), int(sample_rate)


def negative_windows_from_audio(
    audio: np.ndarray,
    sample_rate: int,
    *,
    peak_count: int = 14,
    sliding_count: int = 18,
) -> list[np.ndarray]:
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    windows: list[np.ndarray] = [
        # Always retain the strongest centred event from the exact feedback WAV.
        extract_event_window(audio, sample_rate)
    ]
    windows.extend(
        peak_windows(
            audio,
            sample_rate,
            count=peak_count,
            min_gap_seconds=0.055,
        )
    )
    windows.extend(
        sliding_windows(
            audio,
            sample_rate,
            step_seconds=0.075,
            max_count=sliding_count,
        )
    )
    return windows


def append_negative_windows(
    windows: Iterable[np.ndarray],
    sample_rate: int,
    *,
    source: str,
    model_path: Path = MODEL_PATH,
) -> int:
    window_list = [np.asarray(window, dtype=np.float32) for window in windows]
    if not window_list:
        return 0

    with _model_write_lock():
        raw = json.loads(model_path.read_text(encoding="utf-8"))
        if int(raw.get("version", 0)) != MODEL_VERSION:
            raise RuntimeError("Kişisel model eski; calibrate.bat ile yeniden kalibre et.")
        if int(raw["sample_rate"]) != int(sample_rate):
            raise RuntimeError(
                f"Model {raw['sample_rate']} Hz, yeni kayıt {sample_rate} Hz."
            )

        mean = np.asarray(raw["feature_mean"], dtype=np.float64)
        std = np.asarray(raw["feature_std"], dtype=np.float64)
        new_features = np.vstack(
            [feature_vector(window, sample_rate) for window in window_list]
        )
        new_scaled = (new_features - mean) / std

        existing = np.asarray(raw["negative_examples"], dtype=np.float64)
        if existing.ndim != 2:
            raise RuntimeError("Modeldeki negatif örnekler okunamadı.")

        accepted: list[np.ndarray] = []
        reference = existing
        for row in new_scaled:
            min_distance = float(np.min(np.sum((reference - row) ** 2, axis=1)))
            if min_distance < 1e-8:
                continue
            accepted.append(row)
            reference = np.vstack([reference, row])

        if not accepted:
            return 0

        combined = np.vstack([existing, np.vstack(accepted)])
        training = dict(raw.get("training", {}))
        base_count = int(training.get("base_negative_count", len(existing)))
        base_count = max(0, min(base_count, len(combined)))
        training["base_negative_count"] = base_count

        if len(combined) > MAX_NEGATIVE_EXAMPLES:
            base = combined[:base_count]
            online_capacity = max(0, MAX_NEGATIVE_EXAMPLES - len(base))
            online = combined[base_count:]
            combined = (
                np.vstack([base, online[-online_capacity:]])
                if online_capacity
                else base
            )

        training["negative_count"] = int(len(combined))
        training["online_negative_count"] = int(max(0, len(combined) - base_count))
        training["last_learning_source"] = source
        training["last_learning_at"] = datetime.now(timezone.utc).isoformat()

        raw["negative_examples"] = combined.tolist()
        raw["training"] = training

        temp_path = model_path.with_suffix(model_path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temp_path, model_path)
        return len(accepted)


def learn_from_wav(path: Path, *, source: str) -> int:
    audio, sample_rate = read_wav_mono(path)
    windows = negative_windows_from_audio(audio, sample_rate)
    return append_negative_windows(
        windows,
        sample_rate,
        source=source,
    )
