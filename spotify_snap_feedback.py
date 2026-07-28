from __future__ import annotations

import argparse
import asyncio
import ctypes
import logging
import math
import queue
import sys
import time
from collections import deque
from typing import Any

import numpy as np
import sounddevice as sd

import spotify_snap as core
from feedback import FeedbackStore, NotificationService, load_feedback_settings


def configure_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    handlers: list[logging.Handler] = []
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    try:
        handlers.append(logging.FileHandler(core.LOG_PATH, encoding="utf-8"))
    except OSError:
        pass
    if not handlers:
        handlers.append(logging.NullHandler())

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,
    )


def copy_audio_buffer(audio_buffer: deque[np.ndarray]) -> np.ndarray:
    if not audio_buffer:
        return np.empty(0, dtype=np.float32)
    return np.concatenate(tuple(audio_buffer)).astype(np.float32, copy=True)


async def run_controller(settings: core.Settings, debug: bool) -> None:
    feedback_settings = load_feedback_settings()
    audio_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=100)
    capture_blocks = max(
        1,
        math.ceil(
            feedback_settings.capture_seconds
            * settings.sample_rate
            / settings.block_size
        ),
    )
    rolling_audio: deque[np.ndarray] = deque(maxlen=capture_blocks)

    def audio_callback(
        indata: np.ndarray,
        frames: int,
        time_info: Any,
        status: Any,
    ) -> None:
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

    manager = await core.MediaManager.request_async()
    spotify = core.SpotifyController(manager)
    detector = core.SnapDetector(settings)
    feedback_store = FeedbackStore(
        sample_rate=settings.sample_rate,
        block_size=settings.block_size,
        retention_hours=feedback_settings.pending_retention_hours,
    )
    notifications = NotificationService(
        feedback_settings.notifications_enabled
    )

    first_snap_time: float | None = None
    first_snap_metrics: list[dict[str, float]] = []
    first_snap_audio: np.ndarray | None = None

    async def perform_action(
        action: str,
        snap_count: int,
        metrics: list[dict[str, float]],
        audio_samples: np.ndarray,
    ) -> None:
        success = await spotify.execute(action)
        if not success or not feedback_settings.notifications_enabled:
            return

        try:
            event_id = feedback_store.save_pending(
                audio_samples=audio_samples,
                action=action,
                snap_count=snap_count,
                metrics=metrics,
            )
            notifications.show_detection(
                event_id=event_id,
                action=action,
                snap_count=snap_count,
            )
        except Exception:
            logging.exception("Feedback bildirimi hazırlanamadı.")

    logging.info("Spotify Snap Control aktif.")
    logging.info("Tek şıklatma: sonraki | Çift şıklatma: önceki")
    logging.info("Yalnızca Spotify şarkı çalarken komut gönderilir.")
    if feedback_settings.notifications_enabled:
        logging.info(
            "Feedback bildirimleri aktif; yanlış algılamalar "
            "yerel eğitim verisine kaydedilebilir."
        )

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
            "Mikrofon açılamadı. Windows Ayarları > Gizlilik ve güvenlik > "
            "Mikrofon bölümünden masaüstü uygulamalarına mikrofon izni ver. "
            f"Ayrıntı: {exc}"
        ) from exc

    with stream:
        while True:
            try:
                while True:
                    samples = audio_queue.get_nowait()
                    rolling_audio.append(samples)
                    detected, metrics = detector.analyze(samples)

                    if debug:
                        logging.debug(
                            "rms=%.4f peak=%.4f crest=%.2f high=%.2f "
                            "noise=%.4f",
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
                        first_snap_metrics = [metrics]
                        first_snap_audio = copy_audio_buffer(rolling_audio)
                    elif (
                        snap_time - first_snap_time
                        <= settings.double_snap_window
                    ):
                        await perform_action(
                            action="previous",
                            snap_count=2,
                            metrics=first_snap_metrics + [metrics],
                            audio_samples=copy_audio_buffer(rolling_audio),
                        )
                        first_snap_time = None
                        first_snap_metrics = []
                        first_snap_audio = None
                    else:
                        await perform_action(
                            action="next",
                            snap_count=1,
                            metrics=first_snap_metrics,
                            audio_samples=(
                                first_snap_audio
                                if first_snap_audio is not None
                                else copy_audio_buffer(rolling_audio)
                            ),
                        )
                        first_snap_time = snap_time
                        first_snap_metrics = [metrics]
                        first_snap_audio = copy_audio_buffer(rolling_audio)

            except queue.Empty:
                pass

            now = time.monotonic()
            if (
                first_snap_time is not None
                and now - first_snap_time > settings.double_snap_window
            ):
                await perform_action(
                    action="next",
                    snap_count=1,
                    metrics=first_snap_metrics,
                    audio_samples=(
                        first_snap_audio
                        if first_snap_audio is not None
                        else copy_audio_buffer(rolling_audio)
                    ),
                )
                first_snap_time = None
                first_snap_metrics = []
                first_snap_audio = None

            await asyncio.sleep(0.01)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Parmak şıklatmasıyla Spotify kontrolü ve yanlış algılama feedback'i"
        )
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="ses ölçümlerini ayrıntılı yazdır",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mutex: Any | None = None
    try:
        settings = core.load_settings()
        if args.debug:
            settings.debug = True
        configure_logging(settings.debug)

        mutex = core.acquire_single_instance_mutex()
        asyncio.run(run_controller(settings=settings, debug=settings.debug))
        return 0
    except KeyboardInterrupt:
        logging.info("Program kapatıldı.")
        return 0
    except Exception as exc:
        logging.exception("Program başlatılamadı: %s", exc)
        return 1
    finally:
        if mutex is not None:
            ctypes.windll.kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    raise SystemExit(main())
