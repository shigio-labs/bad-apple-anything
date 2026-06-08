# test_assets

Drop your input clips here. Media files are git-ignored, so they will not be committed.

- A **silhouette** clip — a high-contrast black/white video (e.g. Bad Apple). See the
  README for a `yt-dlp` download command, or pass a URL directly to `--silhouette`.
- A **video** — anything you want to reveal inside the silhouette (DOOM gameplay, a music
  video, etc.).

Example:

```bash
python main.py --silhouette test_assets/bad_apple.mp4 \
  --video test_assets/your_video.mp4 \
  --output outputs/result.mp4 --resolution 1920x1080 --fps 60
```
