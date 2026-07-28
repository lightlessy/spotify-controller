from __future__ import annotations

import csv
import json
import logging
import re
import shutil
import uuid
import wave
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np
from winotify import Notification

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "feedback_config.json"
TRAINING_DATA_DIR = APP_DIR / "training_data"
PENDING_DIR = TRAINING_DATA_DIR / "pending"
FALSE_POSITIVE_DIR = TRAINING_DATA_DIR / "false_positives"
MANIFEST_PATH = FALSE_POSITIVE_DIR / "manifest.csv"
APP_ID = "Spotify Snap Control"
PROTOCOL_SCHEME = "spotify-snap"
EVENT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


@dataclass(slots=True)
class FeedbackSettings:
    notifications_enabled: bool = True
    capture_seconds: float = 1.5
    pending_retention_hours: int = 24


def load_feedback_settings(path: Path = CONFIG_PATH) -> FeedbackSettings:
    settings = FeedbackSettings()
    if not path.exists():
        path.write_text(
            json.dumps(
                {
                    field.name: getattr(settings, field.name)
                    for field in fields(settings)
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return settings

    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"feedback_config.json okunamadı: {exc}") from exc

    return FeedbackSettings(
        **{
            field.name: raw.get(field.name, getattr(settings, field.name))
            for field in fields(settings)
        }
    )


class FeedbackStore:
    def __init__(
        self,
        sample_rate: int,
        block_size: int,
        retention_hours: int,
    ) -> None:
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.retention_hours = max(1, retention_hours)
        PENDING_DIR.mkdir(parents=True, exist_ok=True)
        FALSE_POSITIVE_DIR.mkdir(parents=True, exist_ok=True)
        self.cleanup_pending()

    def cleanup_pending(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=self.retention_hours
        )
        for path in PENDING_DIR.glob("*"):
            if not path.is_file():
                continue
            try:
                modified = datetime.fromtimestamp(
                    path.stat().st_mtime,
                    tz=timezone.utc,
                )
                if modified < cutoff:
                    path.unlink(missing_ok=True)
            except OSError:
                logging.debug(
                    "Geçici feedback dosyası temizlenemedi: %s",
                    path,
                )

    def save_pending(
        self,
        audio_samples: np.ndarray,
        action: str,
        snap_count: int,
        metrics: list[dict[str, float]],
    ) -> str:
        event_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()
        wav_path = PENDING_DIR / f"{event_id}.wav"
        json_path = PENDING_DIR / f"{event_id}.json"

        samples = np.asarray(audio_samples, dtype=np.float32).reshape(-1)
        if samples.size == 0:
            samples = np.zeros(self.block_size, dtype=np.float32)
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")

        temp_wav = wav_path.with_suffix(".wav.tmp")
        with wave.open(str(temp_wav), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(pcm.tobytes())
        temp_wav.replace(wav_path)

        metadata = {
            "event_id": event_id,
            "created_at": created_at,
            "label": "pending",
            "action": action,
            "snap_count": snap_count,
            "sample_rate": self.sample_rate,
            "duration_seconds": round(samples.size / self.sample_rate, 4),
            "metrics": metrics,
            "wav_file": wav_path.name,
            "privacy": "local_only",
        }
        temp_json = json_path.with_suffix(".json.tmp")
        temp_json.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_json.replace(json_path)
        return event_id

    @staticmethod
    def event_id_from_uri(uri: str) -> str:
        parsed = urlparse(uri)
        if (
            parsed.scheme.lower() != PROTOCOL_SCHEME
            or parsed.netloc.lower() != "false-positive"
        ):
            raise ValueError("Geçersiz feedback bağlantısı.")

        event_id = parsed.path.strip("/").lower()
        if not EVENT_ID_PATTERN.fullmatch(event_id):
            raise ValueError("Geçersiz feedback kimliği.")
        return event_id

    def mark_false_positive_from_uri(self, uri: str) -> str:
        return self.mark_false_positive(self.event_id_from_uri(uri))

    def mark_false_positive(self, event_id: str) -> str:
        if not EVENT_ID_PATTERN.fullmatch(event_id):
            raise ValueError("Geçersiz feedback kimliği.")

        pending_wav = PENDING_DIR / f"{event_id}.wav"
        pending_json = PENDING_DIR / f"{event_id}.json"
        target_wav = FALSE_POSITIVE_DIR / f"{event_id}.wav"
        target_json = FALSE_POSITIVE_DIR / f"{event_id}.json"

        if target_wav.exists() and target_json.exists():
            return "already_saved"
        if not pending_wav.exists() or not pending_json.exists():
            return "expired"

        metadata = json.loads(pending_json.read_text(encoding="utf-8"))
        metadata["label"] = "false_positive"
        metadata["feedback_at"] = datetime.now(timezone.utc).isoformat()
        metadata["wav_file"] = target_wav.name

        temp_target_json = target_json.with_suffix(".json.tmp")
        temp_target_json.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        shutil.move(str(pending_wav), str(target_wav))
        temp_target_json.replace(target_json)
        pending_json.unlink(missing_ok=True)
        self._append_manifest(metadata)
        return "saved"

    @staticmethod
    def _append_manifest(metadata: dict[str, Any]) -> None:
        manifest_exists = MANIFEST_PATH.exists()
        fieldnames = [
            "event_id",
            "created_at",
            "feedback_at",
            "label",
            "action",
            "snap_count",
            "duration_seconds",
            "wav_file",
            "metrics_json",
        ]
        with MANIFEST_PATH.open(
            "a",
            encoding="utf-8",
            newline="",
        ) as manifest_file:
            writer = csv.DictWriter(
                manifest_file,
                fieldnames=fieldnames,
            )
            if not manifest_exists:
                writer.writeheader()
            writer.writerow(
                {
                    "event_id": metadata["event_id"],
                    "created_at": metadata["created_at"],
                    "feedback_at": metadata["feedback_at"],
                    "label": metadata["label"],
                    "action": metadata["action"],
                    "snap_count": metadata["snap_count"],
                    "duration_seconds": metadata["duration_seconds"],
                    "wav_file": metadata["wav_file"],
                    "metrics_json": json.dumps(
                        metadata["metrics"],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
            )


class NotificationService:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def show_detection(
        self,
        event_id: str,
        action: str,
        snap_count: int,
    ) -> None:
        if not self.enabled:
            return

        action_text = (
            "Sonraki şarkıya geçildi"
            if action == "next"
            else "Önceki şarkıya dönüldü"
        )
        detection_text = (
            "Tek şıklatma algılandı."
            if snap_count == 1
            else "Çift şıklatma algılandı."
        )
        toast = Notification(
            app_id=APP_ID,
            title=f"Spotify Snap · {action_text}",
            msg=(
                f"{detection_text} Yanlış algılamaysa bildir; "
                "ses örneği yalnızca bu bilgisayarda saklanır."
            ),
            duration="long",
        )
        toast.add_actions(
            label="Hatalı algılamaydı",
            launch=(
                f"{PROTOCOL_SCHEME}://false-positive/"
                f"{event_id}"
            ),
        )
        toast.show()

    @staticmethod
    def show_feedback_result(status: str) -> None:
        if status == "saved":
            title = "Feedback kaydedildi"
            message = (
                "Ses örneği yanlış-pozitif eğitim verisine eklendi. "
                "Teşekkürler."
            )
        elif status == "already_saved":
            title = "Feedback zaten kayıtlı"
            message = "Bu algılama daha önce yanlış olarak işaretlenmiş."
        else:
            title = "Feedback süresi dolmuş"
            message = "Geçici ses örneği artık bulunamadı."

        Notification(
            app_id=APP_ID,
            title=title,
            msg=message,
            duration="short",
        ).show()
