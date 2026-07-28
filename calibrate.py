from __future__ import annotations

import json
import time
from datetime import datetime

import numpy as np
import sounddevice as sd

import spotify_snap as core
from snap_model import (
    MODEL_PATH,
    find_peak_centers,
    save_model,
    train_model,
    windows_from_centers,
    write_wav,
)

CALIBRATION_DIR = core.APP_DIR / "training_data" / "calibration"


def countdown() -> None:
    for value in (3, 2, 1):
        print(f"{value}...")
        time.sleep(1)


def record_phase(label: str, seconds: float, settings: core.Settings) -> np.ndarray:
    print(f"\n{label}")
    input("Hazır olduğunda Enter'a bas: ")
    countdown()
    print("KAYIT BAŞLADI")
    audio = sd.rec(
        int(seconds * settings.sample_rate),
        samplerate=settings.sample_rate,
        channels=1,
        dtype="float32",
        device=settings.input_device,
        blocking=True,
    )
    print("KAYIT BİTTİ")
    return np.asarray(audio[:, 0], dtype=np.float32)


def main() -> int:
    settings = core.load_settings()
    print("Spotify Snap kişisel kalibrasyonu")
    print("---------------------------------")
    print("Bu işlem yalnızca bilgisayarında çalışır; kayıtlar yerel kalır.")
    print("Mikrofona normal kullanım mesafende otur.")

    positive_audio = record_phase(
        "10 saniye içinde 12 kez NET şıklat. Aralarında yaklaşık yarım saniye bırak; konuşma ve klavye sesi çıkarma.",
        11.5,
        settings,
    )
    negative_audio = record_phase(
        "12 saniye boyunca normal konuş ve klavyede yaz. Şıklatma yapma. Birkaç Enter/Space tuşuna da bas.",
        13.5,
        settings,
    )

    positive_centers = find_peak_centers(
        positive_audio,
        settings.sample_rate,
        count=12,
        min_gap_seconds=0.35,
    )
    negative_centers = find_peak_centers(
        negative_audio,
        settings.sample_rate,
        count=60,
        min_gap_seconds=0.08,
    )
    positive_windows = windows_from_centers(
        positive_audio, positive_centers, settings.sample_rate
    )
    negative_windows = windows_from_centers(
        negative_audio, negative_centers, settings.sample_rate
    )

    model = train_model(
        positive_windows, negative_windows, settings.sample_rate
    )
    save_model(model, MODEL_PATH)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    write_wav(
        CALIBRATION_DIR / f"{stamp}-snaps.wav",
        positive_audio,
        settings.sample_rate,
    )
    write_wav(
        CALIBRATION_DIR / f"{stamp}-negatives.wav",
        negative_audio,
        settings.sample_rate,
    )
    (CALIBRATION_DIR / f"{stamp}-summary.json").write_text(
        json.dumps(model["training"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    training = model["training"]
    print("\n[OK] Kişisel model kaydedildi.")
    print(f"Pozitif örnek: {training['positive_count']}")
    print(f"Negatif örnek: {training['negative_count']}")
    print(
        f"Kalibrasyon içi yakalama: %{100 * training['estimated_recall']:.0f}"
    )
    print(
        "Kalibrasyon içi yanlış alarm: "
        f"%{100 * training['estimated_false_positive_rate']:.1f}"
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
