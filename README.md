# Bad Apple Anything

Reveal **any video inside the white silhouette of a Bad Apple-style clip**. Drop in
DOOM gameplay, a music video, your webcam capture — anything — and it plays through the
moving silhouette while the original Bad Apple song stays as the soundtrack.

It is the "DOOM running on a \<random device\>" meme, except the device is Bad Apple.

Pure Python + ffmpeg. CPU only, no GPU or model downloads.

## How it works

The **silhouette** clip is the stencil (and the soundtrack); your **video** is the fill.
For every output frame:

```
 silhouette clip ──► [mask: B/W → alpha]  ──┐
                                            ├─► [composite: video·α + bg·(1−α)] ──► ffmpeg ──► out.mp4
 your video ──────► [frame at timestamp] ──┘                                          ▲
 silhouette clip ───────────────────────────────── audio (AAC) ───────────────────────┘
```

1. **Mask** — each silhouette frame is resized (aspect-preserving), thresholded to clean
   black/white, denoised, and given a feathered edge → a per-pixel `alpha` in `[0, 1]`.
2. **Fill** — the video frame is picked by *wall-clock time* (`int(t × video_fps)`), so it
   plays at **real speed** and loops seamlessly when shorter than the song. No stretching.
3. **Composite** — `out = video·alpha + background·(1 − alpha)`: the video shows where the
   silhouette is white, the background color elsewhere, with an anti-aliased edge. The
   silhouette clip's audio is muxed in.

The silhouette sets the total length; the video is fitted into it. Want the full breakdown
(modules, the two resamplings, extension points)? See **[ARCHITECTURE.md](ARCHITECTURE.md)**.

## Install

Python 3.11+ recommended. Install [ffmpeg](https://ffmpeg.org/download.html) and make sure
both `ffmpeg` and `ffprobe` are on your `PATH`.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
```

## Get a silhouette clip

Any high-contrast black/white video works. The classic is Bad Apple:

```bash
yt-dlp -f "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best" \
  --merge-output-format mp4 \
  -o bad_apple.mp4 \
  "https://www.youtube.com/watch?v=FtutLA63Cp8"
```

You can also pass a URL straight to `--silhouette` / `--video` and it will be downloaded
with `yt-dlp` automatically.

## CLI

```bash
python main.py \
  --silhouette ./bad_apple.mp4 \
  --video ./doom_gameplay.mp4 \
  --output ./outputs/bad_apple_doom.mp4 \
  --resolution 1920x1080 \
  --fps 60 \
  --audio keep
```

Quick test (short, muted, fast):

```bash
python main.py --silhouette bad_apple.mp4 --video doom_gameplay.mp4 \
  --output outputs/test.mp4 --resolution 640x360 \
  --max-frames 120 --audio mute --preset veryfast
```

### Options

| Flag | Default | What it does |
|------|---------|--------------|
| `--silhouette` | required | Black/white stencil clip (Bad Apple). Path or URL. |
| `--video` | required | Any video to reveal inside the silhouette. Path or URL. |
| `--output` | required | Output MP4. |
| `--resolution` | `1280x720` | Output size (must be even). |
| `--fps` | `30` | Output frame rate. Match your video's fps for the smoothest result. |
| `--audio` | `keep` | Keep the silhouette clip's audio (the song) or `mute`. |
| `--blend` | `mask` | `mask` = clean cutout; `multiply` = ghostly fade outside the silhouette. |
| `--background-color` | `black` | Color shown outside the silhouette. |
| `--fit` | `contain` | Silhouette aspect: `contain` keeps proportions, `stretch` fills the frame. |
| `--fill-fit` | `cover` | Video aspect: `cover` crops to fill, `contain` pads, `stretch` distorts. |
| `--fill-gamma` | off | Brightness curve for the video; `0.85` lifts dark footage so it reads. |
| `--invert-mask` | off | Swap which side of the silhouette shows the video. |
| `--threshold` / `--auto-threshold` | `127` | Mask brightness cutoff (or Otsu per frame). |
| `--no-antialias` | off | Hard mask edge instead of a feathered one. |
| `--crf` / `--preset` | `18` / `medium` | libx264 quality / speed. |
| `--max-frames` | off | Render only the first N frames (for tests). |

### Recipes

```bash
# DOOM inside Bad Apple, smooth 1080p60 with the song
python main.py --silhouette bad_apple.mp4 --video doom.mp4 \
  --output outputs/doom.mp4 --resolution 1920x1080 --fps 60

# Dark footage? Lift it so it reads inside thin strokes
python main.py --silhouette bad_apple.mp4 --video gameplay.mp4 \
  --output outputs/lit.mp4 --fill-gamma 0.85

# Invert: show the video in the BLACK areas instead
python main.py --silhouette bad_apple.mp4 --video clip.mp4 \
  --output outputs/inverted.mp4 --invert-mask

# Ghostly look: video stays faintly visible outside the silhouette
python main.py --silhouette bad_apple.mp4 --video clip.mp4 \
  --output outputs/ghost.mp4 --blend multiply

# Pull either input straight from a URL (downloaded with yt-dlp)
python main.py --silhouette "https://youtu.be/FtutLA63Cp8" \
  --video your_clip.mp4 --output outputs/fromurl.mp4
```

## Desktop GUI

```bash
python gui.py
```

On Windows you can also double-click `run_gui.bat`. The window has file pickers for the
silhouette, the video, and the output, plus every option above, with live progress, speed,
ETA, and logs. It runs the render on a background thread.

## Project layout

```text
bad_apple_renderer/
  core/
    frame_sync.py      # input resolution (local/URL), probing, fps plan
    mask_extractor.py  # streams clean binary + anti-aliased silhouette masks
    imaging.py         # aspect-preserving resize (contain / cover)
    renderer_base.py   # RenderConfig + helpers
  renderers/
    video_renderer.py  # the compositor: video timeline reader + mask blend
  output/
    encoder.py         # raw frames piped to ffmpeg H.264/AAC MP4
  main.py              # CLI
  gui.py               # desktop GUI
main.py                # root entry point
gui.py                 # root GUI entry point
```

## License

MIT — see [LICENSE](LICENSE). You are responsible for the rights to any clips you feed in;
Bad Apple, DOOM, and similar are the property of their respective owners.
