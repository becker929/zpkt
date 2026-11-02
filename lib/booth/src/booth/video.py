"""The reply's picture and video: a piano roll drawn from the score with a moving playhead, over the render's audio.

Bluesky has no audio posts, so the piece goes out as an MP4. Drawn with Pillow and encoded by ffmpeg in the booth;
no browser is involved (docs/sound.md).
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
        d.text((x0, y + 6), t.instrument.id, fill=DIM, font=_font(26))
        lo, hi = t.instrument.range
        span = max(1, hi - lo)
        hue = HUES[k % len(HUES)]
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
