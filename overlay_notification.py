from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path

import spotify_snap as core
from feedback import (
    FALSE_POSITIVE_DIR,
    FeedbackStore,
    NotificationService as WindowsNotificationService,
    load_feedback_settings,
)
from online_learning import learn_from_wav

APP_DIR = Path(__file__).resolve().parent
TOAST_SECONDS = 3.0
BACKGROUND_KEY = "#010203"
CARD = "#17181c"
CARD_EDGE = "#2a2d33"
TEXT = "#f5f7fa"
MUTED = "#a9afb9"
GREEN = "#1ed760"
BUTTON = "#2a2d33"
BUTTON_HOVER = "#373b43"


def _rounded_rectangle(
    canvas: tk.Canvas,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    radius: int,
    **kwargs: object,
) -> int:
    points = [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)


def _pythonw_executable() -> str:
    current = Path(sys.executable)
    candidate = current.with_name("pythonw.exe")
    return str(candidate if candidate.exists() else current)


class OverlayNotificationService:
    """Small top-screen actionable overlay; falls back to Windows toast."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.fallback = WindowsNotificationService(enabled)

    def show_detection(self, event_id: str, action: str, snap_count: int) -> None:
        if not self.enabled:
            return
        command = [
            _pythonw_executable(),
            str(Path(__file__).resolve()),
            "--event-id",
            event_id,
            "--action",
            action,
            "--snap-count",
            str(snap_count),
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            subprocess.Popen(
                command,
                cwd=str(APP_DIR),
                creationflags=creationflags,
                close_fds=True,
            )
        except OSError:
            logging.exception("Özel bildirim açılamadı; Windows bildirimi kullanılıyor.")
            self.fallback.show_detection(event_id, action, snap_count)

    @staticmethod
    def show_feedback_result(status: str) -> None:
        WindowsNotificationService.show_feedback_result(status)


def _save_and_learn(event_id: str) -> tuple[str, int]:
    settings = core.load_settings()
    feedback_settings = load_feedback_settings()
    store = FeedbackStore(
        sample_rate=settings.sample_rate,
        block_size=settings.block_size,
        retention_hours=feedback_settings.pending_retention_hours,
    )
    status = store.mark_false_positive(event_id)
    learned = 0
    if status == "saved":
        wav_path = FALSE_POSITIVE_DIR / f"{event_id}.wav"
        learned = learn_from_wav(
            wav_path,
            source=f"overlay_false_positive:{event_id}",
        )
    return status, learned


class DetectionOverlay:
    WIDTH = 470
    HEIGHT = 104

    def __init__(self, event_id: str, action: str, snap_count: int) -> None:
        self.event_id = event_id
        self.action = action
        self.snap_count = snap_count
        self.closed = False
        self.learning = False
        self.remaining_ms = int(TOAST_SECONDS * 1000)

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.configure(bg=BACKGROUND_KEY)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-transparentcolor", BACKGROUND_KEY)
            self.root.attributes("-toolwindow", True)
        except tk.TclError:
            pass

        screen_width = self.root.winfo_screenwidth()
        x = max(10, (screen_width - self.WIDTH) // 2)
        self.root.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+22")
        self.root.attributes("-alpha", 0.0)

        self.canvas = tk.Canvas(
            self.root,
            width=self.WIDTH,
            height=self.HEIGHT,
            bg=BACKGROUND_KEY,
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)
        _rounded_rectangle(
            self.canvas,
            2,
            2,
            self.WIDTH - 2,
            self.HEIGHT - 2,
            28,
            fill=CARD,
            outline=CARD_EDGE,
            width=1,
        )

        self.canvas.create_oval(22, 24, 36, 38, fill=GREEN, outline="")
        action_text = "Sonraki şarkı" if action == "next" else "Önceki şarkı"
        snap_text = "Tek şıklatma" if snap_count == 1 else "Çift şıklatma"
        self.title_id = self.canvas.create_text(
            48,
            22,
            anchor="nw",
            text=action_text,
            fill=TEXT,
            font=("Segoe UI Semibold", 12),
        )
        self.subtitle_id = self.canvas.create_text(
            48,
            51,
            anchor="nw",
            text=f"{snap_text} algılandı · yanlışsa bildir",
            fill=MUTED,
            font=("Segoe UI", 9),
        )

        self.button_shape = _rounded_rectangle(
            self.canvas,
            320,
            29,
            448,
            75,
            18,
            fill=BUTTON,
            outline="",
            tags=("false_button",),
        )
        self.button_text = self.canvas.create_text(
            384,
            52,
            text="Hatalı algılama",
            fill=TEXT,
            font=("Segoe UI Semibold", 9),
            tags=("false_button",),
        )
        self.canvas.tag_bind("false_button", "<Button-1>", self._on_false)
        self.canvas.tag_bind("false_button", "<Enter>", self._hover_in)
        self.canvas.tag_bind("false_button", "<Leave>", self._hover_out)

        self.canvas.create_rectangle(26, 88, 444, 91, fill="#25282e", outline="")
        self.progress = self.canvas.create_rectangle(
            26, 88, 444, 91, fill=GREEN, outline=""
        )
        self.root.bind("<Escape>", lambda _event: self._close())
        self.root.after(20, self._fade_in)
        self.root.after(50, self._tick)
        self.root.deiconify()

    def _hover_in(self, _event: tk.Event[tk.Misc]) -> None:
        if not self.learning:
            self.canvas.itemconfigure(self.button_shape, fill=BUTTON_HOVER)

    def _hover_out(self, _event: tk.Event[tk.Misc]) -> None:
        if not self.learning:
            self.canvas.itemconfigure(self.button_shape, fill=BUTTON)

    def _fade_in(self) -> None:
        alpha = float(self.root.attributes("-alpha"))
        alpha = min(0.97, alpha + 0.13)
        self.root.attributes("-alpha", alpha)
        if alpha < 0.97 and not self.closed:
            self.root.after(18, self._fade_in)

    def _tick(self) -> None:
        if self.closed or self.learning:
            return
        self.remaining_ms -= 50
        ratio = max(0.0, self.remaining_ms / (TOAST_SECONDS * 1000))
        self.canvas.coords(self.progress, 26, 88, 26 + 418 * ratio, 91)
        if self.remaining_ms <= 0:
            self._fade_out()
        else:
            self.root.after(50, self._tick)

    def _fade_out(self) -> None:
        if self.closed:
            return
        alpha = float(self.root.attributes("-alpha"))
        alpha -= 0.12
        if alpha <= 0.02:
            self._close()
            return
        self.root.attributes("-alpha", alpha)
        self.root.after(18, self._fade_out)

    def _on_false(self, _event: tk.Event[tk.Misc]) -> None:
        if self.learning:
            return
        self.learning = True
        self.canvas.itemconfigure(self.button_shape, fill=BUTTON)
        self.canvas.itemconfigure(self.button_text, text="Öğreniyor…", fill=MUTED)
        self.canvas.itemconfigure(
            self.subtitle_id,
            text="Ses yalnızca bu bilgisayarda işleniyor",
        )

        def worker() -> None:
            try:
                status, learned = _save_and_learn(self.event_id)
                self.root.after(0, lambda: self._show_result(status, learned))
            except Exception:
                logging.exception("Yanlış algılama öğrenilemedi.")
                self.root.after(0, lambda: self._show_result("error", 0))

        threading.Thread(target=worker, daemon=True).start()

    def _show_result(self, status: str, learned: int) -> None:
        if status == "saved":
            title = "Tamam, öğrendim"
            subtitle = f"{learned} negatif ses penceresi modele eklendi"
        elif status == "already_saved":
            title = "Zaten kaydedilmiş"
            subtitle = "Bu algılama daha önce işaretlendi"
        elif status == "expired":
            title = "Kayıt bulunamadı"
            subtitle = "Geçici ses örneğinin süresi dolmuş"
        else:
            title = "Kaydedilemedi"
            subtitle = "Model değişmedi"
        self.canvas.itemconfigure(self.title_id, text=title)
        self.canvas.itemconfigure(self.subtitle_id, text=subtitle)
        self.canvas.itemconfigure(self.button_text, text="✓", fill=GREEN)
        self.root.after(1050, self._fade_out)

    def _close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def run(self) -> None:
        self.root.mainloop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--action", choices=("next", "previous"), required=True)
    parser.add_argument("--snap-count", type=int, choices=(1, 2), required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    DetectionOverlay(args.event_id, args.action, args.snap_count).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
