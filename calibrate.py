from __future__ import annotations

import json
import time
from datetime import datetime

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


def record_audio(seconds: float, settings: core.Settings) -> np.ndarray:
    audio = sd.rec(
        int(seconds * settings.sample_rate),
        samplerate=settings.sample_rate,
        channels=1,
        dtype="float32",
        device=settings.input_device,
        blocking=True,
    )
    return np.asarray(audio[:, 0], dtype=np.float32)


def record_single_snap(index: int, settings: core.Settings) -> np.ndarray:
    """Record one user-confirmed snap sample.

    Automatic peak/noise-ratio validation is intentionally avoided here.
    Laptop microphone processing can make a real snap quieter than startup
    noise, while speech or a desk impact can be much louder. The user knows
    whether they snapped during the prompted window, so explicit confirmation
    is the reliable calibration label.
    """
    while True:
        input(f"\n[{index}/12] Hazır olunca Enter'a bas: ")
        print("Kayıt açıldı... 0,5 saniye sonra ŞİMDİ yazacak.")
        audio = sd.rec(
            int(1.35 * settings.sample_rate),
            samplerate=settings.sample_rate,
            channels=1,
            dtype="float32",
            device=settings.input_device,
            blocking=False,
        )
        time.sleep(0.50)
        print("ŞİMDİ — bir kez net şıklat!")
        sd.wait()
        samples = np.asarray(audio[:, 0], dtype=np.float32)

        search_start = int(0.38 * settings.sample_rate)
        search_end = int(1.28 * settings.sample_rate)
        candidate = samples[search_start:search_end]
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


def record_phase(label: str, seconds: float, settings: core.Settings) -> np.ndarray:
    print(f"\n{label}")
    input("Hazır olduğunda yalnızca Enter'a bas: ")
    countdown()
    print("KAYIT BAŞLADI")
    audio = record_audio(seconds, settings)
    print("KAYIT BİTTİ")
    return audio


def main() -> int:
    settings = core.load_settings()
    print("Spotify Snap kişisel kalibrasyonu v2")
    print("------------------------------------")
    print("Kayıtlar yalnızca bu bilgisayarda tutulur.")
    print("Her şıklatma ayrı alınır ve senin onayınla etiketlenir.")
    print("Peak değeri yalnızca bilgi amaçlıdır; bağırma veya masaya vurma.")

    positive_windows = [
        record_single_snap(index, settings) for index in range(1, 13)
    ]

    silence_audio = record_phase(
        "5 saniye sessiz kal. Şıklatma, konuşma ve klavye sesi çıkarma.",
        5.0,
        settings,
    )
    speech_audio = record_phase(
        "10 saniye normal sesle konuş. Şıklatma ve klavye sesi çıkarma.",
        10.0,
        settings,
    )
    keyboard_audio = record_phase(
        "8 saniye klavyede normal hızda yaz; Enter ve Space'e de bas. Konuşma ve şıklatma yapma.",
        8.0,
        settings,
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
