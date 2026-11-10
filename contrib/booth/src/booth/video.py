"""The reply's picture and video: a piano roll drawn from the score with a moving playhead, over the render's audio.

Bluesky has no audio posts, so the piece goes out as an MP4. Drawn with Pillow and encoded by ffmpeg in the booth;
no browser is involved (contrib/docs/sound.md).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .compile import Plan

BG = (14, 14, 18)
INK = (236, 232, 222)
DIM = (120, 116, 110)
HUES = [(239, 108, 78), (246, 190, 82), (120, 200, 120), (82, 172, 230), (178, 128, 236), (236, 112, 176),
        (96, 214, 200), (210, 210, 120)]
MARGIN = 72
TOP = 300
BOTTOM = 220


def _font(size: int):
    for path in ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def roll(plan: Plan, title: str, credit: str, size: tuple[int, int], out: Path) -> tuple[int, int, int]:
    """Draw the still; return the roll's (x0, width, y0) so the playhead can follow it."""
    w, h = size
    img = Image.new("RGB", size, BG)
    d = ImageDraw.Draw(img)
    d.text((MARGIN, 110), title[:60], fill=INK, font=_font(64))
    d.text((MARGIN, 200), credit[:80], fill=DIM, font=_font(34))
    x0, width = MARGIN, w - 2 * MARGIN
    lanes = max(1, len(plan.tracks))
    lane_h = (h - TOP - BOTTOM) / lanes
    for k, t in enumerate(plan.tracks):
        y = TOP + k * lane_h
        d.text((x0, y + 6), t.label, fill=DIM, font=_font(26))
        lo, hi = t.range
        span = max(1, hi - lo)
        hue = HUES[k % len(HUES)]
        for s, dur in (t.sample.clips if t.sample else []):      # a sample's clips: a band across the lane
            nx = x0 + s / plan.render_beats * width
            nw = max(3.0, dur / plan.render_beats * width)
            d.rectangle([nx, y + 44, nx + nw - 2, y + lane_h - 16], fill=tuple(int(c * 0.55) for c in hue))
        for p, s, dur, v in t.notes:
            nx = x0 + s / plan.render_beats * width
            nw = max(3.0, dur / plan.render_beats * width)
            ny = y + 44 + (1 - (p - lo) / span) * (lane_h - 60)
            shade = 0.45 + 0.55 * v / 127
            d.rectangle([nx, ny, nx + nw, ny + 6], fill=tuple(int(c * shade) for c in hue))
    for bar in range(0, int(plan.render_beats) + 1, 16):     # every 4 bars
        bx = x0 + bar / plan.render_beats * width
        d.line([bx, TOP - 20, bx, h - BOTTOM + 10], fill=(40, 40, 46), width=1)
    img.save(out, quality=90)
    return x0, width, TOP - 20


CLIP_BYTES = 1024 * 1024  # Room World's limit for an uploaded clip


def loop(wav: Path, seconds: float, m4a: Path, max_bytes: int = CLIP_BYTES) -> int:
    """The render as a seamless loop for a Room World room: the song's own length (`seconds`, whole bars), with the
    tail that rings out past its end (reverb, echo) mixed back onto its start, so the loop's seam sounds like the song
    going round. AAC at the highest bitrate that keeps the file under Room World's clip limit; ffmpeg's MP4 records the
    encoder delay, which browsers skip, so nothing is inserted at the seam. Returns the bitrate in kb/s."""
    kbps = int(min(192, max(48, max_bytes * 8 * 0.9 / seconds / 1000)))
    graph = (f"[0]asplit[a][b];[a]atrim=0:{seconds:.6f},asetpts=PTS-STARTPTS[body];"
             f"[b]atrim={seconds:.6f},asetpts=PTS-STARTPTS[tail];[body][tail]amix=inputs=2:duration=first:normalize=0[out]")
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(wav), "-filter_complex", graph, "-map", "[out]",
         "-c:a", "aac", "-b:a", f"{kbps}k", str(m4a)], check=True, capture_output=True, timeout=300)
    if m4a.stat().st_size > max_bytes:
        raise RuntimeError(f"loop is {m4a.stat().st_size} bytes, over the {max_bytes} clip limit")
    return kbps


def encode(wav: Path, still: Path, geom: tuple[int, int, int], size: tuple[int, int], seconds: float,
           m4a: Path, mp4: Path) -> None:
    x0, width, y0 = geom
    h = size[1] - BOTTOM + 30 - y0
    run = lambda argv: subprocess.run(argv, check=True, capture_output=True, timeout=300)
    run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "aac", "-b:a", "256k", str(m4a)])
    run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "30", "-i", str(still), "-i", str(wav),
         "-filter_complex", f"[0]drawbox=x='{x0}+t/{seconds:.3f}*{width}':y={y0}:w=4:h={h}:color=white@0.85:t=fill,format=yuv420p[v]",
         "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-r", "30",
         "-c:a", "aac", "-b:a", "192k", "-t", f"{seconds:.3f}", "-movflags", "+faststart", str(mp4)])
