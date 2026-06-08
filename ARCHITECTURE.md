# Architecture

How **Bad Apple Anything** turns a silhouette clip plus any video into a single MP4 where
the video is revealed inside the moving silhouette.

## Overview

The tool is a small, streaming pipeline. Nothing is held in memory frame-by-frame: each
output frame is built and immediately piped into `ffmpeg`, so a 4-minute 1080p render uses a
near-constant amount of RAM.

Two clips go in:

- **silhouette** — a black/white clip (e.g. Bad Apple). It is the stencil **and** the source
  of the soundtrack, and it defines the total length of the render.
- **video** — anything you want to show inside the white areas of the silhouette.

## Data flow (per output frame)

```
 silhouette clip ──► [mask: B/W → alpha]  ──┐
                                            ├─► [composite: video·α + bg·(1−α)] ──► ffmpeg ──► out.mp4
 your video ──────► [frame at timestamp] ──┘                                          ▲
 silhouette clip ───────────────────────────────── audio (AAC) ───────────────────────┘
```

## Pipeline stages

### 1. Inputs — `core/frame_sync.py`

- `resolve_source()` accepts a local path **or a URL** (downloaded with `yt-dlp`).
- `probe_video()` reads fps, frame count, and duration through OpenCV (with an `ffprobe`
  fallback for duration).
- `build_frame_plan()` computes how many output frames to produce:

  ```
  frame_count = ceil(silhouette_duration × output_fps)
  ```

  The **silhouette** therefore controls the total length and the audio; the video is fitted
  into that length (looping if needed).

### 2. Silhouette → mask — `core/mask_extractor.py`

`MaskExtractor.iter_masks()` walks the silhouette at the output cadence. For output frame
`i` it picks silhouette frame `int(i × source_fps / output_fps)` (this resamples a 30 fps
silhouette up to a 60 fps render by repeating frames), then `_frame_to_mask()` does:

1. **Resize** to the output resolution, aspect-preserving (`fit=contain` pads instead of
   stretching, so the figure keeps its proportions).
2. **Grayscale → threshold** (fixed `--threshold`, or per-frame Otsu with `--auto-threshold`)
   to a hard black/white image.
3. **Morphology** open + close (`--clean-radius`) to remove specks and fill pinholes.
4. Optional **invert** (`--invert-mask`) to swap which side shows the video.
5. **Anti-alias**: a Gaussian blur whose sigma scales with height (`max(0.8, height/900)`)
   turns the hard edge into a smooth `alpha` ramp in `[0, 1]`. This keeps a clean ~1–2px
   edge at any resolution instead of a jagged one.

Output: `alpha` per pixel — `1` = show the video, `0` = background, fractional at the edge.

### 3. Video frame at the right time — `FillVideoReader` in `renderers/video_renderer.py`

This is the heart of the "looks right" behaviour. The video frame is chosen by **wall-clock
time**, not one-source-frame-per-output-frame:

```
t       = output_index / output_fps
t       = t mod video_duration          # if looping
frame#  = int(t × video_fps)
```

So the video always plays at **real speed** and **loops seamlessly** when it is shorter than
the song. (The earlier naive reader advanced one frame per output frame, which silently
played 60 fps footage at half speed in a 30 fps render — that was a bug.) The chosen frame is
fitted with `fit=cover` (fills the frame, crops the overflow, no distortion).

### 4. Composite — `_blend()`

An optional **gamma LUT** runs first (`--fill-gamma 0.85` lifts dark footage so it reads
inside thin strokes). Then the blend:

| Mode | Formula | Look |
|------|---------|------|
| `mask` | `out = video·α + background·(1 − α)` | clean cutout on a solid background |
| `multiply` | `out = video·(0.12 + 0.88·α)` | ghostly: background dimmed, not solid |

Because `α` is fractional at the edge, the cutout is anti-aliased for free.

### 5. Encode + audio — `output/encoder.py`

`VideoFrameEncoder` launches `ffmpeg` reading raw `bgr24` frames from stdin and encodes
**H.264** (`libx264`, `--crf`/`--preset`, `yuv420p`, `+faststart`). With `--audio keep` the
audio track of the **silhouette** clip is muxed in (`aac 192k`) using `-shortest`. Frame
writes tolerate `ffmpeg` finishing a few frames early under `-shortest` (so the render ends
cleanly instead of crashing on a closed pipe).

## Two independent resamplings

The two timelines are sampled differently on purpose:

- the **mask** is sampled by *frame index* (`source_fps / output_fps`) — a 30 fps silhouette
  in a 60 fps render just repeats each frame, which is correct since the animation is 30 fps;
- the **video** is sampled by *time* — so it runs at its own real speed.

Both emit exactly `frame_count` frames, so e.g. 60 fps DOOM can be shown buttery-smooth while
the silhouette honestly ticks at 30 fps.

## Module map

| File | Responsibility |
|------|----------------|
| `core/frame_sync.py` | resolve local/URL inputs, probe fps/duration, build the frame plan |
| `core/mask_extractor.py` | stream the silhouette as a clean binary mask + feathered alpha |
| `core/imaging.py` | aspect-preserving resize: `fit_contain` (pad) / `fit_cover` (crop) |
| `core/renderer_base.py` | `RenderConfig`, `parse_resolution`, `parse_color`, `Renderer` base |
| `renderers/video_renderer.py` | `FillVideoReader` (timeline sampling) + `_blend` compositor |
| `output/encoder.py` | pipe raw frames to ffmpeg, mux audio, H.264/AAC MP4 |
| `main.py` | CLI (argument parsing → `RenderConfig` → render) |
| `gui.py` | desktop GUI over the same `RenderConfig` + `VideoRenderer` |

## Extension points

- **New blend mode**: add a branch in `VideoRenderer._blend()` and a `--blend` choice in
  `main.py`.
- **Pre/post processing** (upscaling, frame interpolation): wrap `MaskExtractor` /
  `FillVideoReader` outputs, or insert a step before `VideoFrameEncoder.write()`.
- **Different sink** (stream, virtual camera): replace `VideoFrameEncoder` with another
  object exposing the same `write()` / context-manager interface — renderers stay unchanged.

## Performance notes

- Single-threaded Python feeding `ffmpeg`; the encoder is usually the bottleneck.
- At a fixed `--crf`, the `--preset` mainly trades render time for file size, **not** visual
  quality — use a faster preset to speed up renders without hurting the look.
- Memory stays flat: one mask frame + one video frame + one composite frame at a time.
