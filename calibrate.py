from __future__ import annotations

import json
import math
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any

import numpy as np
import sounddevice as sd

import spotify_snap as core
from snap_model import (
    MODEL_PATH,
    event_levels,
    extract_event_window,
    peak_windows,
    save_model,
    sliding_windows,
    train_model,
    write_wav,
)

CALIBRATION_DIR = core.APP_DIR / "training_data" / "calibration"


class ContinuousRecorder:
    """Keep the microphone open so Windows/driver warm-up is paid only once."""

    def __init__(self, settings: core.Settings, buffer_seconds: float = 16.0) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        max_blocks = max(
            8,
            math.ceil(
                buffer_seconds * settings.sample_rate / settings.block_size
            )
            + 8,
        )
        self._blocks: deque[np.ndarray] = deque(maxlen=max_blocks)
        self._stream: sd.InputStream | None = None

    def _callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: Any,
        status: Any,
    ) -> None:
        if status:
            print(f"\n[Mikrofon] {status}")
        mono = np.asarray(indata[:, 0], dtype=np.float32).copy()
        with self._lock:
            self._blocks.append(mono)

    def __enter__(self) -> "ContinuousRecorder":
        self._stream = sd.InputStream(
            device=self.settings.input_device,
            samplerate=self.settings.sample_rate,
            blocksize=self.settings.block_size,
            channels=1,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()
        print("Mikrofon açıldı; sürücü dengeleniyor...")
        time.sleep(2.0)
        self.clear()
        print("Mikrofon hazır.")
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def clear(self) -> None:
        with self._lock:
            self._blocks.clear()

    def snapshot(self, seconds: float) -> np.ndarray:
        target = max(1, int(round(seconds * self.settings.sample_rate)))
        with self._lock:
            if self._blocks:
                audio = np.concatenate(tuple(self._blocks)).astype(
                    np.float32, copy=False
                )
            else:
                audio = np.empty(0, dtype=np.float32)

        if audio.size >= target:
            return audio[-target:].copy()

        output = np.zeros(target, dtype=np.float32)
        if audio.size:
            output[-audio.size :] = audio
        return output

    def record(self, seconds: float) -> np.ndarray:
        self.clear()
        time.sleep(seconds)
        return self.snapshot(seconds)


def record_single_snap(
    index: int,
    settings: core.Settings,
    recorder: ContinuousRecorder,
) -> np.ndarray:
    """Record one user-confirmed snap without reopening the microphone."""

    while True:
        input(f"\n[{index}/12] Hazır olunca Enter'a bas: ")
        recorder.clear()
        print("0,5 saniye sonra ŞİMDİ yazacak.")
        time.sleep(0.50)
        print("ŞİMDİ — bir kez net şıklat!")
        time.sleep(0.85)

        samples = recorder.snapshot(1.35)
        search_start = int(0.42 * settings.sample_rate)
        candidate = samples[search_start:]
        event = extract_event_window(candidate, settings.sample_rate)
        peak, rms = event_levels(event, settings.sample_rate)

        print(f"Ölçüm: peak={peak:.6f}, rms={rms:.6f}")
        answer = input(
            "Bu denemede gerçekten bir kez şıklattıysan Enter; "
            "tekrar için R yaz: "
        ).strip().lower()
        if answer not in {"r", "retry", "tekrar"}:
            return event

        print("Örnek yeniden alınacak.")


def countdown() -> None:
    for value in (3, 2, 1):
        print(f"{value}...")
        time.sleep(1)


def record_phase(
    label: str,
    seconds: float,
    recorder: ContinuousRecorder,
) -> np.ndarray:
    print(f"\n{label}")
    input("Hazır olduğunda yalnızca Enter'a bas: ")
    countdown()
    print("KAYIT BAŞLADI")
    audio = recorder.record(seconds)
    print("KAYIT BİTTİ")
    return audio


def main() -> int:
    settings = core.load_settings()
    print("Spotify Snap kişisel kalibrasyonu v2")
    print("------------------------------------")
    print("Kayıtlar yalnızca bu bilgisayarda tutulur.")
    print("Mikrofon tüm işlem boyunca açık kalır; başlangıçtaki sıfır kayıtlar elenir.")
    print("Her şıklatma ayrı alınır ve senin onayınla etiketlenir.")
    print("Peak değeri yalnızca bilgi amaçlıdır; bağırma veya masaya vurma.")

    with ContinuousRecorder(settings) as recorder:
        positive_windows = [
            record_single_snap(index, settings, recorder)
            for index in range(1, 13)
        ]

        silence_audio = record_phase(
            "5 saniye sessiz kal. Şıklatma, konuşma ve klavye sesi çıkarma.",
            5.0,
            recorder,
        )
        speech_audio = record_phase(
            "10 saniye normal sesle konuş. Şıklatma ve klavye sesi çıkarma.",
            10.0,
            recorder,
        )
        keyboard_audio = record_phase(
            "8 saniye klavyede normal hızda yaz; Enter ve Space'e de bas. "
            "Konuşma ve şıklatma yapma.",
            8.0,
            recorder,
        )

    negative_windows: list[np.ndarray] = []
    negative_windows.extend(
        sliding_windows(silence_audio, settings.sample_rate, 0.10, max_count=45)
    )
    negative_windows.extend(
        sliding_windows(speech_audio, settings.sample_rate, 0.13, max_count=55)
    )
    negative_windows.extend(
        sliding_windows(keyboard_audio, settings.sample_rate, 0.11, max_count=55)
    )
    negative_windows.extend(
        peak_windows(speech_audio, settings.sample_rate, count=35)
    )
    negative_windows.extend(
        peak_windows(keyboard_audio, settings.sample_rate, count=35)
    )

    model = train_model(positive_windows, negative_windows, settings.sample_rate)
    save_model(model, MODEL_PATH)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    positive_audio = np.concatenate(positive_windows)
    write_wav(
        CALIBRATION_DIR / f"{stamp}-snaps.wav",
        positive_audio,
        settings.sample_rate,
    )
    write_wav(
        CALIBRATION_DIR / f"{stamp}-silence.wav",
        silence_audio,
        settings.sample_rate,
    )
    write_wav(
        CALIBRATION_DIR / f"{stamp}-speech.wav",
        speech_audio,
        settings.sample_rate,
    )
    write_wav(
        CALIBRATION_DIR / f"{stamp}-keyboard.wav",
        keyboard_audio,
        settings.sample_rate,
    )
    (CALIBRATION_DIR / f"{stamp}-summary.json").write_text(
        json.dumps(model["training"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    training = model["training"]
    print("\n[OK] Kişisel model v2 kaydedildi.")
    print(f"Pozitif örnek: {training['positive_count']}")
    print(f"Negatif örnek: {training['negative_count']}")
    print(f"Kalibrasyon içi yakalama: %{100 * training['estimated_recall']:.0f}")
    print(
        "Kalibrasyon içi yanlış alarm: "
        f"%{100 * training['estimated_false_positive_rate']:.1f}"
    )
    print(
        "Şıklatma peak aralığı: "
        f"{training['positive_peak_min']:.6f} – "
        f"{training['positive_peak_max']:.6f}"
    )
    print("Şimdi start.bat ile gerçek ortam testini yap.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nKalibrasyon iptal edildi.")
        raise SystemExit(1)
    except Exception as exc:
        print(f"\n[HATA] Kalibrasyon tamamlanamadı: {exc}")
        raise SystemExit(1)
