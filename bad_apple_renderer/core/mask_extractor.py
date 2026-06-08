"""Binary and antialiased mask extraction from silhouette videos."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np

from .frame_sync import FrameSyncPlan, build_frame_plan
from .imaging import resize_frame


@dataclass(frozen=True, slots=True)
class MaskFrame:
    index: int
    timestamp: float
    mask: np.ndarray
    alpha: np.ndarray


class MaskExtractor:
    """Stream clean binary masks from a black/white clip without loading all frames."""

    def __init__(
        self,
        source_path: Path,
        *,
        resolution: tuple[int, int],
        fps: float = 30.0,
        threshold: int = 127,
        auto_threshold: bool = False,
        invert: bool = False,
        antialias: bool = True,
        clean_radius: int = 1,
        fit: str = "stretch",
        max_frames: int | None = None,
    ) -> None:
        self.source_path = Path(source_path)
        self.resolution = resolution
        self.fps = fps
        self.threshold = int(threshold)
        self.auto_threshold = auto_threshold
        self.invert = invert
        self.antialias = antialias
        self.clean_radius = max(0, int(clean_radius))
        self.fit = fit
        self.plan: FrameSyncPlan = build_frame_plan(self.source_path, fps=fps, max_frames=max_frames)

    def iter_masks(self) -> Iterator[MaskFrame]:
        import cv2

        cap = cv2.VideoCapture(str(self.source_path))
        if not cap.isOpened():
            raise RuntimeError(f"Could not open source video: {self.source_path}")

        source_fps = self.plan.source_fps or self.fps
        current_source_index = -1
        cached_frame: np.ndarray | None = None

        try:
            for output_index in range(self.plan.frame_count):
                desired_source_index = int(output_index * source_fps / self.fps)

                if desired_source_index < current_source_index:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, desired_source_index)
                    current_source_index = desired_source_index - 1

                while current_source_index < desired_source_index:
                    ok, frame = cap.read()
                    current_source_index += 1
                    if ok:
                        cached_frame = frame
                    elif cached_frame is None:
                        raise RuntimeError(
                            f"Source ended before the first requested frame at index {desired_source_index}"
                        )
                    else:
                        break

                if cached_frame is None:
                    ok, cached_frame = cap.read()
                    current_source_index += 1
                    if not ok:
                        raise RuntimeError("Could not read any frames from source")

                mask, alpha = self._frame_to_mask(cached_frame, cv2)
                yield MaskFrame(
                    index=output_index,
                    timestamp=output_index / self.fps,
                    mask=mask,
                    alpha=alpha,
                )
        finally:
            cap.release()

    def _frame_to_mask(self, frame: np.ndarray, cv2_module: object) -> tuple[np.ndarray, np.ndarray]:
        cv2 = cv2_module
        width, height = self.resolution
        if frame.shape[1] != width or frame.shape[0] != height:
            # Pad (contain) rather than stretch so the silhouette keeps its
            # proportions; padded borders are black and stay outside the mask.
            frame = resize_frame(
                frame,
                (width, height),
                mode=self.fit,
                interpolation=cv2.INTER_AREA,
                pad_value=0,
            )

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if self.auto_threshold:
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        else:
            _, binary = cv2.threshold(gray, self.threshold, 255, cv2.THRESH_BINARY)

        if self.clean_radius > 0:
            kernel = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (self.clean_radius * 2 + 1, self.clean_radius * 2 + 1),
            )
            binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
            binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

        if self.invert:
            binary = cv2.bitwise_not(binary)

        if self.antialias:
            # Feather scales with output height so the edge stays a clean ~1-2px
            # soft line at any resolution instead of a fixed (near-aliased) blur.
            sigma = max(0.8, height / 900.0)
            alpha = cv2.GaussianBlur(binary, (0, 0), sigmaX=sigma, sigmaY=sigma)
            alpha = alpha.astype(np.float32) / 255.0
        else:
            alpha = binary.astype(np.float32) / 255.0

        return binary, np.clip(alpha, 0.0, 1.0)
