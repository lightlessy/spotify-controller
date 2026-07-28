from __future__ import annotations

from datetime import datetime

import spotify_snap as core
from calibrate import ContinuousRecorder, countdown
from online_learning import append_negative_windows, negative_windows_from_audio
from snap_model import MODEL_PATH, write_wav

HARD_NEGATIVE_DIR = core.APP_DIR / "training_data" / "hard_negatives"


def main() -> int:
    if not MODEL_PATH.exists():
        raise RuntimeError("Önce calibrate.bat ile kişisel model oluştur.")

    settings = core.load_settings()
    print("Alkışları mevcut modele negatif örnek olarak ekle")
    print("------------------------------------------------")
    print("Şıklatma modelin ve pozitif örneklerin değişmeyecek.")
    print("Kayıt sırasında 10-15 kez doğal biçimde alkışla; güçlerini biraz değiştir.")
    input("Hazır olduğunda yalnızca Enter'a bas: ")

    with ContinuousRecorder(settings, buffer_seconds=12.0) as recorder:
        countdown()
        print("KAYIT BAŞLADI — 8 saniye boyunca alkışla")
        audio = recorder.record(8.0)
        print("KAYIT BİTTİ")

    windows = negative_windows_from_audio(
        audio,
        settings.sample_rate,
        peak_count=26,
        sliding_count=30,
    )
    added = append_negative_windows(
        windows,
        settings.sample_rate,
        source="manual_clap_session",
    )

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    wav_path = HARD_NEGATIVE_DIR / f"{stamp}-claps.wav"
    write_wav(wav_path, audio, settings.sample_rate)

    print(f"\n[OK] {added} yeni alkış/arka plan penceresi negatif hafızaya eklendi.")
    print("Mevcut şıklatma örnekleri korunuyor.")
    print("Çalışan uygulama modeli birkaç saniye içinde canlı yeniden yükler.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nİşlem iptal edildi.")
        raise SystemExit(1)
    except Exception as exc:
        print(f"\n[HATA] Alkış örnekleri eklenemedi: {exc}")
        raise SystemExit(1)
