"""Streaming ffmpeg encoder for H.264/AAC MP4 outputs."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from bad_apple_renderer.core.frame_sync import require_executable


class VideoFrameEncoder:
    """Pipe raw BGR frames into ffmpeg and optionally mux source audio."""

    def __init__(
        self,
        output_path: Path,
        *,
        resolution: tuple[int, int],
        fps: float,
        audio_source: Path | None = None,
        keep_audio: bool = True,
        crf: int = 18,
        preset: str = "medium",
    ) -> None:
        self.output_path = Path(output_path).resolve()
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.width, self.height = resolution
        self.fps = fps
        self.audio_source = audio_source
        self.keep_audio = keep_audio
        self.crf = crf
        self.preset = preset
        self.process: subprocess.Popen[bytes] | None = None
        self._stopped = False

    def __enter__(self) -> "VideoFrameEncoder":
        ffmpeg = require_executable("ffmpeg")
        args = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{self.width}x{self.height}",
            "-r",
            f"{self.fps:g}",
            "-i",
            "pipe:0",
        ]
        if self.keep_audio and self.audio_source is not None:
            args.extend(["-i", str(self.audio_source), "-map", "0:v:0", "-map", "1:a:0?", "-shortest"])
            args.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            args.extend(["-an"])

        args.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                self.preset,
                "-crf",
                str(self.crf),
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(self.output_path),
            ]
        )
        self.process = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        return self

    def write(self, frame: np.ndarray) -> None:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("Encoder is not open")
        if self._stopped:
            return
        if frame.shape != (self.height, self.width, 3):
            raise ValueError(f"Expected frame shape {(self.height, self.width, 3)}, got {frame.shape}")
        if frame.dtype != np.uint8:
            raise ValueError(f"Expected uint8 frame, got {frame.dtype}")
        try:
            self.process.stdin.write(np.ascontiguousarray(frame).tobytes())
        except (BrokenPipeError, OSError):
            # ffmpeg can finish early because of -shortest (e.g. the silhouette
            # clip's audio ends a few frames before the rendered video). When the
            # pipe is already closed, stop feeding frames instead of crashing.
            if self.process.poll() is not None:
                self._stopped = True
                return
            raise

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.process is None:
            return
        if self.process.stdin is not None:
            self.process.stdin.close()
        stderr = self.process.stderr.read().decode("utf-8", errors="replace") if self.process.stderr else ""
        return_code = self.process.wait()
        self.process = None
        if exc_type is None and return_code != 0:
            raise RuntimeError(f"ffmpeg failed with exit code {return_code}:\n{stderr.strip()}")
