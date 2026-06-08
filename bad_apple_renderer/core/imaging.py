"""Aspect-preserving resize helpers shared by the mask and fill pipelines.

Both functions keep the source aspect ratio so silhouettes and fill footage are
never stretched. ``fit_contain`` letterboxes (pads) and ``fit_cover`` fills the
canvas by center-cropping the overflow.
"""

from __future__ import annotations

import numpy as np


def fit_contain(
    frame: np.ndarray,
    size: tuple[int, int],
    *,
    interpolation: int,
    pad_value: int = 0,
) -> np.ndarray:
    """Resize ``frame`` to fit inside ``size`` (w, h), padding the rest."""

    import cv2

    target_w, target_h = size
    height, width = frame.shape[:2]
    if width == target_w and height == target_h:
        return frame

    scale = min(target_w / width, target_h / height)
    new_w = max(1, min(target_w, round(width * scale)))
    new_h = max(1, min(target_h, round(height * scale)))
    resized = cv2.resize(frame, (new_w, new_h), interpolation=interpolation)
    if new_w == target_w and new_h == target_h:
        return resized

    if frame.ndim == 3:
        canvas = np.full((target_h, target_w, frame.shape[2]), pad_value, dtype=frame.dtype)
    else:
        canvas = np.full((target_h, target_w), pad_value, dtype=frame.dtype)
    x = (target_w - new_w) // 2
    y = (target_h - new_h) // 2
    canvas[y : y + new_h, x : x + new_w] = resized
    return canvas


def fit_cover(
    frame: np.ndarray,
    size: tuple[int, int],
    *,
    interpolation: int,
) -> np.ndarray:
    """Resize ``frame`` to fill ``size`` (w, h), center-cropping the overflow."""

    import cv2

    target_w, target_h = size
    height, width = frame.shape[:2]
    if width == target_w and height == target_h:
        return frame

    scale = max(target_w / width, target_h / height)
    new_w = max(target_w, round(width * scale))
    new_h = max(target_h, round(height * scale))
    resized = cv2.resize(frame, (new_w, new_h), interpolation=interpolation)
    x = (new_w - target_w) // 2
    y = (new_h - target_h) // 2
    return resized[y : y + target_h, x : x + target_w]


def resize_frame(
    frame: np.ndarray,
    size: tuple[int, int],
    *,
    mode: str,
    interpolation: int,
    pad_value: int = 0,
) -> np.ndarray:
    """Dispatch to contain/cover/stretch resizing by ``mode``."""

    target_w, target_h = size
    height, width = frame.shape[:2]
    if width == target_w and height == target_h:
        return frame

    if mode == "contain":
        return fit_contain(frame, size, interpolation=interpolation, pad_value=pad_value)
    if mode == "cover":
        return fit_cover(frame, size, interpolation=interpolation)
    if mode == "stretch":
        import cv2

        return cv2.resize(frame, size, interpolation=interpolation)
    raise ValueError(f"Unsupported resize mode: {mode!r}")
