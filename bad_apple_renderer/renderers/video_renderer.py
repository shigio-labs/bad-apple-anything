"""Universal video fill renderer."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from bad_apple_renderer.core.imaging import resize_frame
from bad_apple_renderer.core.mask_extractor import MaskExtractor
from bad_apple_renderer.core.renderer_base import Renderer, parse_color
from bad_apple_renderer.output.encoder import VideoFrameEncoder


class FillVideoReader:
    """Sample a fill video on the *output* timeline.

    The previous implementation read one source frame per output frame, which
    silently played the fill in slow motion whenever its frame rate differed
    from the output (e.g. 60fps DOOM into a 30fps render). This reader maps each
    output frame to the fill frame at the matching wall-clock time, so the fill
    always plays at real speed and loops seamlessly to cover the full duration.
    """

    def __init__(
        self,
        path: Path,
        *,
        resolution: tuple[int, int],
        out_fps: float,
        loop: bool = True,
        fit: str = "cover",
    ) -> None:
        import cv2

        self.cv2 = cv2
        self.path = Path(path)
        self.resolution = resolution
        self.out_fps = float(out_fps)
        self.loop = loop
        self.fit = fit
        self.cap = cv2.VideoCapture(str(self.path))
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open target video: {self.path}")

        src_fps = float(self.cap.get(cv2.CAP_PROP_FPS) or 0.0)
        self.src_fps = src_fps if src_fps > 0 else self.out_fps
        count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.frame_count = count if count > 0 else None
        self.duration = count / self.src_fps if count > 0 else 0.0
        self.cur_index = -1
        self.cached: np.ndarray | None = None

    def _seek(self, index: int) -> None:
        self.cap.set(self.cv2.CAP_PROP_POS_FRAMES, index)
        self.cur_index = index - 1

    def frame_for(self, output_index: int) -> np.ndarray:
        cv2 = self.cv2
        timestamp = output_index / self.out_fps
        if self.loop and self.duration > 0:
            timestamp %= self.duration

        desired = int(timestamp * self.src_fps)
        if self.frame_count is not None:
            desired = min(desired, self.frame_count - 1)

        if desired < self.cur_index:  # looped back or rewound
            self._seek(desired)

        while self.cur_index < desired:
            ok, frame = self.cap.read()
            self.cur_index += 1
            if ok:
                self.cached = frame
            else:  # ran past the end: hold the last good frame
                break

        if self.cached is None:
            ok, frame = self.cap.read()
            self.cur_index += 1
            if not ok:
                width, height = self.resolution
                return np.zeros((height, width, 3), dtype=np.uint8)
            self.cached = frame

        return resize_frame(
            self.cached,
            self.resolution,
            mode=self.fit,
            interpolation=cv2.INTER_AREA,
        )

    def close(self) -> None:
        self.cap.release()


def _gamma_lut(gamma: float) -> np.ndarray:
    """Build a uint8 LUT; gamma < 1 brightens, > 1 darkens."""

    ramp = (np.arange(256, dtype=np.float32) / 255.0) ** gamma
    return np.clip(ramp * 255.0, 0, 255).astype(np.uint8)


class VideoRenderer(Renderer):
    """Mask any target video with the silhouette clip."""

    name = "video"

    def validate(self) -> None:
        if self.config.target_path is None:
            raise ValueError("--video is required: pass any clip to reveal inside the silhouette")

    def render(self) -> Path:
        import cv2

        extractor = MaskExtractor(
            self.config.source_path,
            resolution=self.config.resolution,
            fps=self.config.fps,
            threshold=self.config.threshold,
            auto_threshold=self.config.auto_threshold,
            invert=self.config.invert_mask,
            antialias=self.config.antialias,
            clean_radius=int(self.config.option("clean_radius", 1)),
            fit=str(self.config.option("fit", "contain")),
            max_frames=self.config.max_frames,
        )
        target = FillVideoReader(
            self.config.target_path,
            resolution=self.config.resolution,
            out_fps=self.config.fps,
            loop=bool(self.config.option("loop_target", True)),
            fit=str(self.config.option("fill_fit", "cover")),
        )
        blend = str(self.config.option("blend", "mask"))
        background = np.array(parse_color(str(self.config.option("background_color", "black"))), dtype=np.float32)

        gamma_value = self.config.option("fill_gamma")
        gamma_lut = None
        if gamma_value is not None and float(gamma_value) != 1.0:
            gamma_lut = _gamma_lut(float(gamma_value))

        try:
            with VideoFrameEncoder(
                self.config.output_path,
                resolution=self.config.resolution,
                fps=self.config.fps,
                audio_source=self.config.source_path,
                keep_audio=self.config.keep_audio,
                crf=self.config.crf,
                preset=self.config.preset,
            ) as encoder:
                for mask_frame in extractor.iter_masks():
                    fill = target.frame_for(mask_frame.index)
                    if gamma_lut is not None:
                        fill = cv2.LUT(fill, gamma_lut)
                    alpha = mask_frame.alpha[:, :, None]
                    frame = self._blend(fill, alpha, blend, background)
                    encoder.write(frame)
                    self.config.report_progress(mask_frame.index + 1, extractor.plan.frame_count, "video")
                    if mask_frame.index and mask_frame.index % 300 == 0:
                        print(
                            f"[video] {mask_frame.index}/{extractor.plan.frame_count} frames",
                            file=sys.stderr,
                        )
        finally:
            target.close()

        return self.config.output_path

    @staticmethod
    def _blend(
        fill: np.ndarray,
        alpha: np.ndarray,
        blend: str,
        background: np.ndarray,
    ) -> np.ndarray:
        fill_f = fill.astype(np.float32)

        if blend == "mask":
            # Show the video where the silhouette is white, background elsewhere.
            out = fill_f * alpha + background.reshape(1, 1, 3) * (1.0 - alpha)
        elif blend == "multiply":
            # Keep the video visible in white zones and fade the rest into shadow.
            out = fill_f * (0.12 + 0.88 * alpha)
        else:
            raise ValueError(f"Unsupported blend mode: {blend}")

        return np.clip(out, 0, 255).astype(np.uint8)
