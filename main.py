"""Compatibility entry point for `python main.py ...`."""

from __future__ import annotations

from bad_apple_renderer.main import main


if __name__ == "__main__":
    raise SystemExit(main())
