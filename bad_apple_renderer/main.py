"""Command line interface: reveal any video inside a Bad Apple-style silhouette."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from .core.frame_sync import resolve_source
from .core.renderer_base import RenderConfig, parse_resolution
from .renderers import VideoRenderer


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("Value must be positive")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bad-apple-renderer",
        description="Reveal any video inside the white silhouette of a Bad Apple-style clip.",
    )
    parser.add_argument(
        "--silhouette",
        required=True,
        help="Black/white silhouette clip used as the stencil (Bad Apple). Local path or URL.",
    )
    parser.add_argument(
        "--video",
        required=True,
        help="Any video to reveal inside the silhouette. Local path or URL.",
    )
    parser.add_argument("--output", required=True, help="Output MP4 path.")

    parser.add_argument("--resolution", default="1280x720", help="Output resolution, e.g. 1920x1080.")
    parser.add_argument("--fps", type=float, default=30.0, help="Output frame rate.")
    parser.add_argument(
        "--audio",
        choices=["keep", "mute"],
        default="keep",
        help="Keep the silhouette clip's audio (e.g. the Bad Apple song) or mute.",
    )

    # Mask extraction.
    parser.add_argument("--threshold", type=int, default=127, help="Brightness threshold for the silhouette mask.")
    parser.add_argument("--auto-threshold", action="store_true", help="Use Otsu thresholding per frame.")
    parser.add_argument("--invert-mask", action="store_true", help="Swap which side of the silhouette shows the video.")
    parser.add_argument("--no-antialias", action="store_true", help="Disable the feathered mask edge.")
    parser.add_argument("--clean-radius", type=int, default=1, help="Morphological cleanup radius for the mask.")

    # Compositing / look.
    parser.add_argument(
        "--blend",
        default="mask",
        choices=["mask", "multiply"],
        help="mask = clean cutout on the background; multiply = ghostly fade outside the silhouette.",
    )
    parser.add_argument("--background-color", default="black", help="Color shown outside the silhouette.")
    parser.add_argument(
        "--fit",
        default="contain",
        choices=["contain", "stretch"],
        help="Silhouette aspect: contain keeps proportions (pads), stretch fills the frame.",
    )
    parser.add_argument(
        "--fill-fit",
        default="cover",
        choices=["cover", "contain", "stretch"],
        help="Video aspect: cover crops to fill, contain pads, stretch distorts.",
    )
    parser.add_argument(
        "--fill-gamma",
        type=float,
        default=None,
        help="Brightness curve for the video (lower = brighter; 0.85 helps dark footage). Default: no change.",
    )
    parser.add_argument("--no-loop-video", action="store_true", help="Do not loop the video when it is shorter than the song.")

    # Encoding.
    parser.add_argument("--crf", type=int, default=18, help="libx264 CRF quality. Lower is better/larger.")
    parser.add_argument("--preset", default="medium", help="libx264 preset, e.g. veryfast, fast, medium, slow.")
    parser.add_argument("--max-frames", type=positive_int, help="Limit rendered frames for quick tests/previews.")
    parser.add_argument("--download-dir", help="Directory used when an input is a URL.")
    return parser


def renderer_options_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "blend": args.blend,
        "background_color": args.background_color,
        "fit": args.fit,
        "fill_fit": args.fill_fit,
        "fill_gamma": args.fill_gamma,
        "loop_target": not args.no_loop_video,
        "clean_radius": args.clean_radius,
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        download_dir = Path(args.download_dir).expanduser().resolve() if args.download_dir else None
        silhouette_path = resolve_source(args.silhouette, download_dir=download_dir)
        video_path = resolve_source(args.video, download_dir=download_dir)

        config = RenderConfig(
            source_path=silhouette_path,
            output_path=Path(args.output).expanduser().resolve(),
            target_path=video_path,
            resolution=parse_resolution(args.resolution),
            fps=args.fps,
            keep_audio=args.audio == "keep",
            threshold=args.threshold,
            auto_threshold=args.auto_threshold,
            invert_mask=args.invert_mask,
            antialias=not args.no_antialias,
            max_frames=args.max_frames,
            crf=args.crf,
            preset=args.preset,
            renderer_options=renderer_options_from_args(args),
        )
        renderer = VideoRenderer(config)
        renderer.validate()
        output = renderer.render()
        print(f"Done: {output}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
