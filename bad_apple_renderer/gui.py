"""Desktop GUI: reveal any video inside a Bad Apple-style silhouette."""

from __future__ import annotations

import contextlib
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path
from tkinter import BooleanVar, StringVar, Text, Tk, filedialog, messagebox, ttk

from bad_apple_renderer.core.frame_sync import resolve_source
from bad_apple_renderer.core.renderer_base import RenderCancelled, RenderConfig, parse_resolution
from bad_apple_renderer.renderers import VideoRenderer


VIDEO_FILETYPES = [("Video files", "*.mp4 *.mkv *.mov *.avi *.webm"), ("All files", "*.*")]


class QueueStream:
    """File-like stream that forwards renderer prints into the GUI log."""

    def __init__(self, events: "queue.Queue[tuple[str, object]]") -> None:
        self.events = events

    def write(self, text: str) -> int:
        if text.strip():
            self.events.put(("log", text.rstrip()))
        return len(text)

    def flush(self) -> None:
        return None


class BadAppleGui:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("Bad Apple Anything")
        self.root.geometry("900x720")
        self.root.minsize(820, 640)

        self.events: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.started_at = 0.0
        self.last_output: Path | None = None

        self._build_vars()
        self._setup_style()
        self._build_layout()
        self.root.after(100, self._drain_events)

    def _build_vars(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        silhouette = project_root / "test_assets" / "bad_apple_source_h264.mp4"
        output = project_root / "outputs" / "bad_apple_anything.mp4"

        self.silhouette_var = StringVar(value=str(silhouette) if silhouette.exists() else "")
        self.video_var = StringVar(value="")
        self.output_var = StringVar(value=str(output))
        self.resolution_var = StringVar(value="1280x720")
        self.fps_var = StringVar(value="30")
        self.audio_var = BooleanVar(value=True)
        self.threshold_var = StringVar(value="127")
        self.auto_threshold_var = BooleanVar(value=False)
        self.invert_mask_var = BooleanVar(value=False)
        self.antialias_var = BooleanVar(value=True)
        self.max_frames_var = StringVar(value="")
        self.blend_var = StringVar(value="mask")
        self.background_var = StringVar(value="black")
        self.fit_var = StringVar(value="contain")
        self.fill_fit_var = StringVar(value="cover")
        self.fill_gamma_var = StringVar(value="")
        self.crf_var = StringVar(value="18")
        self.preset_var = StringVar(value="medium")
        self.status_var = StringVar(value="Готов к рендеру")
        self.progress_text_var = StringVar(value="0%")
        self.detail_var = StringVar(value="Выбери силуэт (Bad Apple) и любое видео, затем жми Render.")

    def _setup_style(self) -> None:
        self.colors = {
            "bg": "#101413",
            "panel": "#19201e",
            "panel2": "#222a27",
            "text": "#ecf2ed",
            "muted": "#9eaaa4",
            "accent": "#8fd14f",
            "danger": "#e35d4f",
            "field": "#0c100f",
        }
        self.root.configure(bg=self.colors["bg"])
        style = ttk.Style(self.root)
        style.theme_use("clam")
        font = ("Bahnschrift", 10)
        style.configure(".", background=self.colors["bg"], foreground=self.colors["text"], font=font)
        style.configure("Main.TFrame", background=self.colors["bg"])
        style.configure("Panel.TFrame", background=self.colors["panel"])
        style.configure("Header.TLabel", background=self.colors["bg"], foreground=self.colors["text"], font=("Bahnschrift", 17, "bold"))
        style.configure("Subtle.TLabel", background=self.colors["bg"], foreground=self.colors["muted"], font=font)
        style.configure("PanelTitle.TLabel", background=self.colors["panel"], foreground=self.colors["text"], font=("Bahnschrift", 11, "bold"))
        style.configure("Panel.TLabel", background=self.colors["panel"], foreground=self.colors["text"], font=font)
        style.configure("Muted.TLabel", background=self.colors["panel"], foreground=self.colors["muted"], font=font)
        style.configure("TEntry", fieldbackground=self.colors["field"], foreground=self.colors["text"], insertcolor=self.colors["text"])
        style.configure("TCombobox", fieldbackground=self.colors["field"], background=self.colors["field"], foreground=self.colors["text"])
        style.configure("TCheckbutton", background=self.colors["panel"], foreground=self.colors["text"])
        style.map("TCheckbutton", background=[("active", self.colors["panel"])])
        style.configure("Accent.TButton", background=self.colors["accent"], foreground="#101413", font=("Bahnschrift", 11, "bold"))
        style.map("Accent.TButton", background=[("active", "#a6ec64"), ("disabled", "#506044")])
        style.configure("Danger.TButton", background=self.colors["danger"], foreground="#fff7f4", font=("Bahnschrift", 10, "bold"))
        style.configure("Tool.TButton", background=self.colors["panel2"], foreground=self.colors["text"])
        style.configure("Studio.Horizontal.TProgressbar", troughcolor=self.colors["field"], background=self.colors["accent"], thickness=22)

    def _build_layout(self) -> None:
        root = ttk.Frame(self.root, style="Main.TFrame", padding=18)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        header = ttk.Frame(root, style="Main.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Bad Apple Anything", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="Любое видео внутри силуэта Bad Apple.", style="Subtle.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Button(header, text="README", style="Tool.TButton", command=self._open_readme).grid(row=0, column=1, sticky="e")

        files = self._panel(root, 1, "Файлы")
        self._path_row(files, 1, "Силуэт (Bad Apple)", self.silhouette_var, self._choose_silhouette)
        ttk.Label(files, text="ЧБ клип-трафарет. Можно вставить YouTube/http ссылку.", style="Muted.TLabel").grid(row=2, column=1, sticky="w", pady=(2, 8))
        self._path_row(files, 3, "Видео", self.video_var, self._choose_video)
        ttk.Label(files, text="Любое видео, которое будет видно внутри силуэта.", style="Muted.TLabel").grid(row=4, column=1, sticky="w", pady=(2, 8))
        self._path_row(files, 5, "Выход (.mp4)", self.output_var, self._choose_output)

        settings = self._panel(root, 2, "Настройки")
        self._combo_row(settings, 1, 0, "Разрешение", self.resolution_var, ["640x360", "854x480", "1280x720", "1920x1080", "3840x2160"])
        self._entry_row(settings, 1, 2, "FPS", self.fps_var)
        self._combo_row(settings, 2, 0, "Blend", self.blend_var, ["mask", "multiply"])
        self._entry_row(settings, 2, 2, "Фон", self.background_var)
        self._combo_row(settings, 3, 0, "Силуэт fit", self.fit_var, ["contain", "stretch"])
        self._combo_row(settings, 3, 2, "Видео fit", self.fill_fit_var, ["cover", "contain", "stretch"])
        self._entry_row(settings, 4, 0, "Яркость (gamma)", self.fill_gamma_var)
        self._entry_row(settings, 4, 2, "Threshold", self.threshold_var)
        self._entry_row(settings, 5, 0, "CRF", self.crf_var)
        self._combo_row(settings, 5, 2, "Preset", self.preset_var, ["veryfast", "faster", "fast", "medium", "slow"])
        self._entry_row(settings, 6, 0, "Max frames (тест)", self.max_frames_var)

        checks = ttk.Frame(settings, style="Panel.TFrame")
        checks.grid(row=7, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        for idx, (text, var) in enumerate(
            [
                ("Звук", self.audio_var),
                ("Auto threshold", self.auto_threshold_var),
                ("Инвертировать", self.invert_mask_var),
                ("Antialias", self.antialias_var),
            ]
        ):
            ttk.Checkbutton(checks, text=text, variable=var).grid(row=0, column=idx, sticky="w", padx=(0, 14))

        self._build_progress_panel(self._panel(root, 3, "Прогресс"))

    def _panel(self, parent: ttk.Frame, row: int, title: str) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=14)
        frame.grid(row=row, column=0, sticky="nsew", pady=(0, 14))
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)
        ttk.Label(frame, text=title, style="PanelTitle.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))
        return frame

    def _build_progress_panel(self, frame: ttk.Frame) -> None:
        frame.rowconfigure(4, weight=1)

        controls = ttk.Frame(frame, style="Panel.TFrame")
        controls.grid(row=1, column=0, columnspan=4, sticky="ew")
        controls.columnconfigure(3, weight=1)
        self.render_button = ttk.Button(controls, text="Render", style="Accent.TButton", command=self._start_render)
        self.render_button.grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.stop_button = ttk.Button(controls, text="Stop", style="Danger.TButton", command=self._stop_render, state="disabled")
        self.stop_button.grid(row=0, column=1, sticky="w", padx=(0, 10))
        ttk.Button(controls, text="Папка вывода", style="Tool.TButton", command=self._open_output_folder).grid(row=0, column=2, sticky="w")
        ttk.Label(controls, textvariable=self.status_var, style="Muted.TLabel").grid(row=0, column=3, sticky="e")

        bar = ttk.Frame(frame, style="Panel.TFrame")
        bar.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(12, 6))
        bar.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(bar, orient="horizontal", mode="determinate", maximum=100, style="Studio.Horizontal.TProgressbar")
        self.progress.grid(row=0, column=0, sticky="ew")
        ttk.Label(bar, textvariable=self.progress_text_var, style="Panel.TLabel", width=8, anchor="e").grid(row=0, column=1, sticky="e", padx=(10, 0))
        ttk.Label(frame, textvariable=self.detail_var, style="Muted.TLabel").grid(row=3, column=0, columnspan=4, sticky="w", pady=(2, 4))

        self.log = Text(frame, height=8, bg=self.colors["field"], fg=self.colors["text"], insertbackground=self.colors["text"], relief="flat", wrap="word", font=("Cascadia Mono", 9))
        self.log.grid(row=4, column=0, columnspan=4, sticky="nsew", pady=(8, 0))
        self._log("GUI готов. Заполни поля и запускай рендер.")

    def _path_row(self, frame: ttk.Frame, row: int, label: str, var: StringVar, command) -> None:
        ttk.Label(frame, text=label, style="Panel.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Entry(frame, textvariable=var).grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)
        ttk.Button(frame, text="Выбрать", style="Tool.TButton", command=command).grid(row=row, column=3, sticky="e", padx=(8, 0), pady=4)

    def _entry_row(self, frame: ttk.Frame, row: int, column: int, label: str, var: StringVar) -> None:
        ttk.Label(frame, text=label, style="Panel.TLabel").grid(row=row, column=column, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(frame, textvariable=var, width=14).grid(row=row, column=column + 1, sticky="ew", pady=4)

    def _combo_row(self, frame: ttk.Frame, row: int, column: int, label: str, var: StringVar, values: list[str]) -> None:
        ttk.Label(frame, text=label, style="Panel.TLabel").grid(row=row, column=column, sticky="w", padx=(0, 8), pady=4)
        ttk.Combobox(frame, textvariable=var, values=values, state="normal", width=12).grid(row=row, column=column + 1, sticky="ew", pady=4)

    def _choose_silhouette(self) -> None:
        path = filedialog.askopenfilename(title="Выбери силуэт-клип (Bad Apple)", filetypes=VIDEO_FILETYPES)
        if path:
            self.silhouette_var.set(path)

    def _choose_video(self) -> None:
        path = filedialog.askopenfilename(title="Выбери любое видео", filetypes=VIDEO_FILETYPES)
        if path:
            self.video_var.set(path)

    def _choose_output(self) -> None:
        path = filedialog.asksaveasfilename(title="Куда сохранить результат", defaultextension=".mp4", filetypes=[("MP4 video", "*.mp4"), ("All files", "*.*")])
        if path:
            self.output_var.set(path)

    def _start_render(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.stop_event.clear()
        self.progress.configure(value=0)
        self.progress_text_var.set("0%")
        self.status_var.set("Подготовка...")
        self.started_at = time.monotonic()
        self._set_running(True)
        self._log("Старт рендера.")
        self.worker = threading.Thread(target=self._render_worker, daemon=True)
        self.worker.start()

    def _render_worker(self) -> None:
        stream = QueueStream(self.events)
        try:
            with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                silhouette_text = self.silhouette_var.get().strip()
                video_text = self.video_var.get().strip()
                if not silhouette_text:
                    raise ValueError("Не выбран силуэт: укажи Bad Apple/ЧБ-клип или URL.")
                if not video_text:
                    raise ValueError("Не выбрано видео: укажи любой видеофайл или URL.")

                output_path = Path(self.output_var.get().strip() or "outputs/bad_apple_anything.mp4").expanduser().resolve()
                download_dir = output_path.parent / "downloads"
                self.events.put(("status", "Открываю источники..."))
                silhouette_path = resolve_source(silhouette_text, download_dir=download_dir)
                video_path = resolve_source(video_text, download_dir=download_dir)

                config = RenderConfig(
                    source_path=silhouette_path,
                    output_path=output_path,
                    target_path=video_path,
                    resolution=parse_resolution(self.resolution_var.get().strip()),
                    fps=float(self.fps_var.get()),
                    keep_audio=bool(self.audio_var.get()),
                    threshold=int(self.threshold_var.get()),
                    auto_threshold=bool(self.auto_threshold_var.get()),
                    invert_mask=bool(self.invert_mask_var.get()),
                    antialias=bool(self.antialias_var.get()),
                    max_frames=self._optional_int(self.max_frames_var.get()),
                    crf=int(self.crf_var.get()),
                    preset=self.preset_var.get().strip() or "medium",
                    renderer_options={
                        "blend": self.blend_var.get(),
                        "background_color": self.background_var.get(),
                        "fit": self.fit_var.get(),
                        "fill_fit": self.fill_fit_var.get(),
                        "fill_gamma": self._optional_float(self.fill_gamma_var.get()),
                        "loop_target": True,
                        "clean_radius": 1,
                    },
                    progress_callback=self._progress_callback,
                )
                renderer = VideoRenderer(config)
                renderer.validate()
                result = renderer.render()
                self.last_output = Path(result)
                self.events.put(("done", str(result)))
        except RenderCancelled:
            self.events.put(("cancelled", "Рендер остановлен. Частичный файл можно перезаписать следующим запуском."))
        except Exception:
            self.events.put(("error", traceback.format_exc()))

    def _progress_callback(self, current: int, total: int, stage: str) -> None:
        if self.stop_event.is_set():
            raise RenderCancelled("Render stopped by user")
        self.events.put(("progress", (current, total, stage)))

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._log(str(payload))
                elif kind == "status":
                    self.status_var.set(str(payload))
                elif kind == "progress":
                    current, total, stage = payload  # type: ignore[misc]
                    self._update_progress(int(current), int(total), str(stage))
                elif kind == "done":
                    self.progress.configure(value=100)
                    self.progress_text_var.set("100%")
                    self.status_var.set("Готово")
                    self._log(f"Готово: {payload}")
                    self._set_running(False)
                    messagebox.showinfo("Bad Apple Anything", f"Рендер готов:\n{payload}")
                elif kind == "cancelled":
                    self.status_var.set("Остановлено")
                    self._log(str(payload))
                    self._set_running(False)
                elif kind == "error":
                    self.status_var.set("Ошибка")
                    self._log(str(payload))
                    self._set_running(False)
                    messagebox.showerror("Ошибка рендера", self._short_error(str(payload)))
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _update_progress(self, current: int, total: int, stage: str) -> None:
        total = max(1, total)
        percent = min(100.0, max(0.0, current / total * 100.0))
        elapsed = max(0.01, time.monotonic() - self.started_at)
        fps = current / elapsed
        eta = max(0, total - current) / fps if fps > 0 else 0.0
        self.progress.configure(value=percent)
        self.progress_text_var.set(f"{percent:5.1f}%")
        self.status_var.set(f"{stage}: {current}/{total}")
        self.detail_var.set(f"Кадры: {current}/{total} | Скорость: {fps:.1f} fps | ETA: {self._format_seconds(eta)}")

    def _set_running(self, running: bool) -> None:
        self.render_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")

    def _stop_render(self) -> None:
        if self.worker and self.worker.is_alive():
            self.stop_event.set()
            self.status_var.set("Останавливаю...")
            self._log("Запрошена остановка. Дождись закрытия ffmpeg-потока.")

    def _open_output_folder(self) -> None:
        raw = self.output_var.get().strip()
        path = self.last_output or (Path(raw).expanduser().resolve() if raw else Path.cwd())
        folder = path if path.is_dir() else path.parent
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    def _open_readme(self) -> None:
        readme = Path(__file__).resolve().parents[1] / "README.md"
        if readme.exists():
            webbrowser.open(str(readme))

    def _log(self, message: str) -> None:
        self.log.insert("end", message + "\n")
        self.log.see("end")

    @staticmethod
    def _optional_int(value: str) -> int | None:
        text = value.strip()
        return int(text) if text else None

    @staticmethod
    def _optional_float(value: str) -> float | None:
        text = value.strip()
        return float(text) if text else None

    @staticmethod
    def _format_seconds(seconds: float) -> str:
        seconds = int(max(0, seconds))
        minutes, sec = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:d}:{minutes:02d}:{sec:02d}"
        return f"{minutes:d}:{sec:02d}"

    @staticmethod
    def _short_error(text: str) -> str:
        lines = [line for line in text.strip().splitlines() if line.strip()]
        return lines[-1] if lines else text

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    BadAppleGui().run()


if __name__ == "__main__":
    main()
