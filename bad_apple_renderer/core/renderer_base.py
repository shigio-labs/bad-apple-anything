"""Common renderer interfaces and CLI parsing helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, ClassVar


Resolution = tuple[int, int]
Color = tuple[int, int, int]
ProgressCallback = Callable[[int, int, str], None]


class RenderCancelled(RuntimeError):
    """Raised when an interactive frontend asks a renderer to stop."""


def parse_resolution(value: str | Resolution) -> Resolution:
    """Parse WIDTHxHEIGHT strings into a validated resolution tuple."""

    if isinstance(value, tuple):
        width, height = value
    else:
        normalized = value.lower().replace("*", "x").replace(",", "x")
        parts = [p.strip() for p in normalized.split("x")]
        if len(parts) != 2:
            raise ValueError(f"Resolution must look like 1920x1080, got {value!r}")
        width, height = int(parts[0]), int(parts[1])

    if width <= 0 or height <= 0:
        raise ValueError("Resolution width and height must be positive")
    if width % 2 or height % 2:
        raise ValueError("Resolution must be even for H.264/yuv420p output")
    return width, height


def parse_color(value: str | Color) -> Color:
    """Parse #RRGGBB, R,G,B, or a small set of named colors into BGR."""

    if isinstance(value, tuple):
        if len(value) != 3:
            raise ValueError("Color tuple must contain exactly 3 channels")
        return value

    named = {
        "black": (0, 0, 0),
        "white": (255, 255, 255),
        "red": (0, 0, 255),
        "green": (0, 255, 0),
        "blue": (255, 0, 0),
        "magenta": (255, 0, 255),
        "cyan": (255, 255, 0),
        "yellow": (0, 255, 255),
    }
    text = value.strip().lower()
    if text in named:
        return named[text]

    if text.startswith("#"):
        text = text[1:]
        if len(text) == 3:
            text = "".join(ch * 2 for ch in text)
        if len(text) != 6:
            raise ValueError(f"Hex colors must be #RGB or #RRGGBB, got {value!r}")
        red = int(text[0:2], 16)
        green = int(text[2:4], 16)
        blue = int(text[4:6], 16)
        return blue, green, red

    pieces = [p.strip() for p in text.split(",")]
    if len(pieces) == 3:
        red, green, blue = (int(p) for p in pieces)
        for channel in (red, green, blue):
            if not 0 <= channel <= 255:
                raise ValueError("RGB color channels must be in the 0..255 range")
        return blue, green, red

    raise ValueError(f"Unsupported color value {value!r}")


@dataclass(slots=True)
class RenderConfig:
    """Shared configuration passed into renderer implementations."""

    source_path: Path
    output_path: Path
    target_path: Path | None
    resolution: Resolution = (1280, 720)
    fps: float = 30.0
    keep_audio: bool = True
    threshold: int = 127
    auto_threshold: bool = False
    invert_mask: bool = False
    antialias: bool = True
    max_frames: int | None = None
    temp_dir: Path | None = None
    crf: int = 18
    preset: str = "medium"
    renderer_options: dict[str, Any] = field(default_factory=dict)
    progress_callback: ProgressCallback | None = field(default=None, repr=False)

    @property
    def width(self) -> int:
        return self.resolution[0]

    @property
    def height(self) -> int:
        return self.resolution[1]

    def option(self, name: str, default: Any = None) -> Any:
        return self.renderer_options.get(name, default)

    def report_progress(self, current: int, total: int, stage: str = "render") -> None:
        if self.progress_callback is not None:
            self.progress_callback(current, total, stage)


class Renderer(ABC):
    """Base class for all rendering backends."""

    name: ClassVar[str]

    def __init__(self, config: RenderConfig) -> None:
        self.config = config

    @classmethod
    def add_cli_args(cls, parser: Any) -> None:
        """Attach renderer-specific argparse flags."""

    def validate(self) -> None:
        """Validate renderer-specific inputs before the expensive render starts."""

    @abstractmethod
    def render(self) -> Path:
        """Render the configured output and return the produced path."""
