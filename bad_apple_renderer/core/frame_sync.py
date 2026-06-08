"""Source resolution, video probing, and timeline planning."""

from __future__ import annotations

import math
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


URL_RE = re.compile(r"^https?://", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class VideoProbe:
    path: Path
    width: int
    height: int
    fps: float
    frame_count: int
    duration: float


@dataclass(frozen=True, slots=True)
class FrameSyncPlan:
    fps: float
    source_fps: float
    frame_count: int
    duration: float


def is_url(value: str) -> bool:
    return bool(URL_RE.match(value))


def require_executable(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(
            f"{name} was not found on PATH. Install it and retry. "
            "For ffmpeg: https://ffmpeg.org/download.html"
        )
    return path


def run_checked(args: Sequence[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args),
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        joined = " ".join(str(a) for a in args)
        raise RuntimeError(f"Command failed ({joined}):\n{result.stderr.strip()}")
    return result


def resolve_source(source: str, download_dir: Path | None = None) -> Path:
    """Resolve a local file or download a YouTube/http source with yt-dlp."""

    if not is_url(source):
        path = Path(source).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Source video does not exist: {path}")
        return path

    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("URL inputs require yt-dlp. Install requirements.txt first.") from exc

    out_dir = (download_dir or Path.cwd() / "downloads").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(out_dir / "%(title).200B-%(id)s.%(ext)s")
    options = {
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best",
        "merge_output_format": "mp4",
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": False,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(source, download=True)
        prepared = Path(ydl.prepare_filename(info)).resolve()

    if prepared.exists():
        return prepared
    mp4_candidate = prepared.with_suffix(".mp4")
    if mp4_candidate.exists():
        return mp4_candidate

    candidates = sorted(out_dir.glob(f"*{info.get('id', '')}*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0].resolve()
    raise RuntimeError(f"yt-dlp finished but no downloaded file was found in {out_dir}")


def ffprobe_duration(path: Path) -> float:
    ffprobe = require_executable("ffprobe")
    result = run_checked(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            str(path),
        ]
    )
    try:
        return max(0.0, float(result.stdout.strip()))
    except ValueError:
        return 0.0


def probe_video(path: Path) -> VideoProbe:
    """Probe video through OpenCV, with ffprobe used for duration fallback."""

    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("OpenCV is required. Install opencv-python from requirements.txt.") from exc

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video source: {path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()

    duration = frame_count / fps if fps > 0 and frame_count > 0 else 0.0
    if duration <= 0:
        try:
            duration = ffprobe_duration(path)
        except RuntimeError:
            duration = 0.0

    if fps <= 0:
        fps = 30.0
    if frame_count <= 0 and duration > 0:
        frame_count = int(round(duration * fps))
    return VideoProbe(path=path, width=width, height=height, fps=fps, frame_count=frame_count, duration=duration)


def build_frame_plan(source_path: Path, fps: float, max_frames: int | None = None) -> FrameSyncPlan:
    if fps <= 0:
        raise ValueError("FPS must be positive")
    probe = probe_video(source_path)
    duration = probe.duration if probe.duration > 0 else probe.frame_count / max(probe.fps, 1.0)
    frame_count = int(math.ceil(duration * fps)) if duration > 0 else probe.frame_count
    if max_frames is not None:
        frame_count = min(frame_count, max(0, max_frames))
        duration = frame_count / fps
    return FrameSyncPlan(fps=fps, source_fps=probe.fps, frame_count=frame_count, duration=duration)


def temporary_directory(prefix: str, parent: Path | None = None) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(parent) if parent else None)).resolve()
