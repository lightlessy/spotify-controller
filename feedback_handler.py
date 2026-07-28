from __future__ import annotations

import argparse
import logging
import sys

import spotify_snap as core
from feedback import (
    FALSE_POSITIVE_DIR,
    FeedbackStore,
    NotificationService,
    load_feedback_settings,
)
from online_learning import learn_from_wav


def configure_logging() -> None:
    handlers: list[logging.Handler] = []
    try:
        handlers.append(logging.FileHandler(core.LOG_PATH, encoding="utf-8"))
    except OSError:
        pass
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    if not handlers:
        handlers.append(logging.NullHandler())

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=handlers,
        force=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "feedback_uri",
        nargs="?",
        help="spotify-snap:// ile başlayan feedback bağlantısı",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="feedback bileşenlerini test et",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_logging()

    settings = core.load_settings()
    feedback_settings = load_feedback_settings()
    store = FeedbackStore(
        sample_rate=settings.sample_rate,
        block_size=settings.block_size,
        retention_hours=feedback_settings.pending_retention_hours,
    )

    if args.check:
        print("[OK] Feedback sistemi çalışmaya hazır.")
        return 0

    if not args.feedback_uri:
        raise SystemExit("Feedback bağlantısı eksik.")

    try:
        event_id = store.event_id_from_uri(args.feedback_uri)
        status = store.mark_false_positive(event_id)
        if status == "saved":
            learned = learn_from_wav(
                FALSE_POSITIVE_DIR / f"{event_id}.wav",
                source=f"windows_toast_false_positive:{event_id}",
            )
            logging.info(
                "Yanlış algılama modele öğretildi (%d negatif pencere).",
                learned,
            )
    except Exception as exc:
        logging.exception("Feedback kaydedilemedi: %s", exc)
        status = "expired"

    NotificationService.show_feedback_result(status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
