from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import logging
import queue
import sys
import time
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd
from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as MediaManager,
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
)

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
LOG_PATH = APP_DIR / "spotify_snap.log"
MUTEX_NAME = "Local\\SpotifySnapControl_lightlessy"


@dataclass(slots=True)
class Settings:
    sample_rate: int = 48_000
    block_size: int = 1024
    input_device: int | None = None
    double_snap_window: float = 0.48
    refractory_time: float = 0.17
    min_rms: float = 0.006
    min_peak: float = 0.045
    noise_multiplier: float = 2.8
    min_crest_factor: float = 3.5
    min_high_frequency_ratio: float = 0.30
    high_frequency_cutoff_hz: int = 2_500
    debug: bool = False


def load_settings(path: Path = CONFIG_PATH) -> Settings:
    settings = Settings()
    if not path.exists():
        path.write_text(
            json.dumps({field.name: getattr(settings, field.name) for field in fields(settings)}, indent=2),
            encoding="utf-8",
        )
        return settings

    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"config.json okunamadı: {exc}") from exc

    allowed = {field.name for field in fields(settings)}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        logging.warning("Bilinmeyen ayarlar yok sayıldı: %s", ", ".join(unknown))

    values = {field.name: raw.get(field.name, getattr(settings, field.name)) for field in fields(settings)}
    return Settings(**values)


def configure_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        handlers.append(logging.FileHandler(LOG_PATH, encoding="utf-8"))
    except OSError:
        pass

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,
    )


def acquire_single_instance_mutex() -> Any:
    if sys.platform != "win32":
        raise RuntimeError("Bu uygulama yalnızca Windows 10/11 için tasarlandı.")

    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not mutex:
        raise ctypes.WinError()
    if kernel32.GetLastError() == 183:
        kernel32.CloseHandle(mutex)
        raise RuntimeError("Spotify Snap Control zaten çalışıyor.")
    return mutex


class SnapDetector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.noise_floor = 0.003
        self.last_detection = 0.0
        self.window = np.hanning(settings.block_size).astype(np.float32)

    def analyze(self, samples: np.ndarray) -> tuple[bool, dict[str, float]]:
        samples = samples.astype(np.float32, copy=False)
        samples = samples - float(np.mean(samples))

        rms = float(np.sqrt(np.mean(samples * samples)) + 1e-9)
        peak = float(np.max(np.abs(samples)))
        crest_factor = peak / rms

        window = self.window
        if len(samples) != len(window):
            window = np.hanning(len(samples)).astype(np.float32)

        spectrum = np.abs(np.fft.rfft(samples * window)) ** 2
        frequencies = np.fft.rfftfreq(len(samples), 1 / self.settings.sample_rate)
        total_energy = float(np.sum(spectrum)) + 1e-9
        high_energy = float(
            np.sum(spectrum[frequencies >= self.settings.high_frequency_cutoff_hz])
        )
        high_ratio = high_energy / total_energy

        loud_enough = rms > max(
            self.settings.min_rms,
            self.noise_floor * self.settings.noise_multiplier,
        )
        sharp_enough = (
            peak > self.settings.min_peak
            and crest_factor > self.settings.min_crest_factor
            and high_ratio > self.settings.min_high_frequency_ratio
        )

        detected = loud_enough and sharp_enough
        now = time.monotonic()

        if not detected:
            self.noise_floor = self.noise_floor * 0.995 + min(rms, 0.05) * 0.005

        accepted = detected and now - self.last_detection > self.settings.refractory_time
        if accepted:
            self.last_detection = now

        metrics = {
            "rms": rms,
            "peak": peak,
            "crest": crest_factor,
            "high_ratio": high_ratio,
            "noise_floor": self.noise_floor,
        }
        return accepted, metrics


class SpotifyController:
    def __init__(self, manager: Any) -> None:
        self.manager = manager

    def find_session(self) -> Any | None:
        for session in self.manager.get_sessions():
            app_id = str(session.source_app_user_model_id).lower()
            if "spotify" in app_id:
                return session
        return None

    async def execute(self, action: str) -> bool:
        session = self.find_session()
        if session is None:
            logging.info("Spotify medya oturumu bulunamadı.")
            return False

        playback_info = session.get_playback_info()
        if playback_info.playback_status != PlaybackStatus.PLAYING:
            logging.info("Spotify çalmıyor; şıklatma yok sayıldı.")
            return False

        controls = playback_info.controls
        if action == "next":
            if not controls.is_next_enabled:
                logging.info("Spotify sonraki şarkı komutunu şu anda desteklemiyor.")
                return False
            success = bool(await session.try_skip_next_async())
            logging.info("→ Sonraki şarkı" if success else "Sonraki şarkı komutu reddedildi.")
            return success

        if action == "previous":
            if not controls.is_previous_enabled:
                logging.info("Spotify önceki şarkı komutunu şu anda desteklemiyor.")
                return False
            success = bool(await session.try_skip_previous_async())
            logging.info("← Önceki şarkı" if success else "Önceki şarkı komutu reddedildi.")
            return success

        raise ValueError(f"Bilinmeyen eylem: {action}")


async def run_controller(settings: Settings) -> None:
    audio_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=100)

    def audio_callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        if status:
            logging.debug("Mikrofon durumu: %s", status)
        mono = indata[:, 0].copy()
        try:
            audio_queue.put_nowait(mono)
        except queue.Full:
            try:
                audio_queue.get_nowait()
                audio_queue.put_nowait(mono)
            except queue.Empty:
                pass

    manager = await MediaManager.request_async()
    spotify = SpotifyController(manager)
    detector = SnapDetector(settings)
    first_snap_time: float | None = None

    logging.info("Spotify Snap Control aktif.")
    logging.info("Tek şıklatma: sonraki | Çift şıklatma: önceki")
    logging.info("Yalnızca Spotify şarkı çalarken komut gönderilir.")

    try:
        stream = sd.InputStream(
            device=settings.input_device,
            samplerate=settings.sample_rate,
            blocksize=settings.block_size,
            channels=1,
            dtype="float32",
            callback=audio_callback,
        )
    except Exception as exc:
        raise RuntimeError(
            "Mikrofon açılamadı. Windows Ayarları > Gizlilik ve güvenlik > Mikrofon "
            "bölümünden masaüstü uygulamalarına mikrofon izni ver. "
            f"Ayrıntı: {exc}"
        ) from exc

    with stream:
        while True:
            now = time.monotonic()

            try:
                while True:
                    samples = audio_queue.get_nowait()
                    detected, metrics = detector.analyze(samples)

                    if settings.debug:
                        logging.debug(
                            "rms=%.4f peak=%.4f crest=%.2f high=%.2f noise=%.4f",
                            metrics["rms"],
                            metrics["peak"],
                            metrics["crest"],
                            metrics["high_ratio"],
                            metrics["noise_floor"],
                        )

                    if not detected:
                        continue

                    snap_time = time.monotonic()
                    logging.info(
                        "Şıklatma algılandı (peak=%.3f, tiz=%.2f)",
                        metrics["peak"],
                        metrics["high_ratio"],
                    )

                    if first_snap_time is None:
                        first_snap_time = snap_time
                    elif snap_time - first_snap_time <= settings.double_snap_window:
                        await spotify.execute("previous")
                        first_snap_time = None
                    else:
                        await spotify.execute("next")
                        first_snap_time = snap_time

            except queue.Empty:
                pass

            if (
                first_snap_time is not None
                and now - first_snap_time > settings.double_snap_window
            ):
                await spotify.execute("next")
                first_snap_time = None

            await asyncio.sleep(0.01)


async def check_installation(settings: Settings) -> int:
    print("\nKurulum kontrolü")
    print("-----------------")
    print(f"Python: {sys.version.split()[0]}")
    print(f"NumPy: {np.__version__}")
    print(f"sounddevice: {getattr(sd, '__version__', 'kurulu')}")

    try:
        devices = sd.query_devices()
        print(f"Ses aygıtı sayısı: {len(devices)}")
        default_input = sd.default.device[0]
        print(f"Varsayılan mikrofon ID: {default_input}")
    except Exception as exc:
        print(f"[HATA] Mikrofonlar okunamadı: {exc}")
        return 1

    try:
        manager = await MediaManager.request_async()
        sessions = list(manager.get_sessions())
        spotify_found = any("spotify" in str(s.source_app_user_model_id).lower() for s in sessions)
        print(f"Spotify oturumu: {'bulundu' if spotify_found else 'şu anda bulunamadı'}")
    except Exception as exc:
        print(f"[HATA] Windows medya API'si açılamadı: {exc}")
        return 1

    print("[OK] Kurulum çalışmaya hazır.")
    return 0


def list_devices() -> int:
    print(sd.query_devices())
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parmak şıklatmasıyla Spotify kontrolü")
    parser.add_argument("--check", action="store_true", help="kurulumu ve aygıtları test et")
    parser.add_argument("--list-devices", action="store_true", help="mikrofonları listele")
    parser.add_argument("--debug", action="store_true", help="ses ölçümlerini ayrıntılı yazdır")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        settings = load_settings()
        if args.debug:
            settings.debug = True
        configure_logging(settings.debug)

        if args.list_devices:
            return list_devices()
        if args.check:
            return asyncio.run(check_installation(settings))

        mutex = acquire_single_instance_mutex()
        try:
            asyncio.run(run_controller(settings))
        finally:
            ctypes.windll.kernel32.CloseHandle(mutex)
        return 0
    except KeyboardInterrupt:
        logging.info("Program kapatıldı.")
        return 0
    except Exception as exc:
        logging.exception("Program başlatılamadı: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
