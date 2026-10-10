"""Screen capture, the salient region, and compact image pairs. Plain functions; screens.py decides when.

The zoom is where the screen changed: blocks of the two captures are compared at 1/8 scale, changed blocks are
grouped, and the most changed group (grown to a fixed 16:9 frame) is the zoom. With no change, a hint point (or
the centre) is used. The full screen is downscaled; the zoom keeps native pixels so text stays legible.
"""

from __future__ import annotations

import asyncio
import io
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image

BLOCK = 8                  # saliency works on 8x8 blocks
CHANGE = 10.0              # a block whose mean differs by more than this (0-255) has changed
MIN_BLOCKS = 6             # fewer changed blocks than this is noise (a blinking cursor, a meter)
IGNORE_TOP = 32            # the menu bar: its clock always changes
ASPECT = 16 / 9
ZOOM_MIN_W = 480
FULL_W = 1280
FULL_QUALITY = 72
ZOOM_QUALITY = 82


class CaptureError(RuntimeError):
    pass


@dataclass
class Frame:
    pixels: np.ndarray       # H x W x 3, uint8, RGB
    t: float                 # time.monotonic() when taken


class Capture(Protocol):
    async def grab(self) -> Frame: ...


class ScreenCapture:
    """The main display, via `screencapture` (needs Screen Recording for the process that started the harness)."""

    def __init__(self, display: int = 1, timeout: float = 15):
        self.display, self.timeout = display, timeout

    async def grab(self) -> Frame:
        fd, path = tempfile.mkstemp(suffix=".png", prefix="studio-shot-")
        os.close(fd)
        try:
            proc = await asyncio.create_subprocess_exec(
                "screencapture", "-x", "-D", str(self.display), "-t", "png", path,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            try:
                _, err = await asyncio.wait_for(proc.communicate(), self.timeout)
            except asyncio.TimeoutError:
                proc.kill()
                raise CaptureError("screencapture hung") from None
            if proc.returncode != 0 or os.path.getsize(path) == 0:
                raise CaptureError(f"screencapture failed: {err.decode(errors='replace').strip()[:200]}")
            pixels = await asyncio.to_thread(_load, Path(path))
            return Frame(pixels, time.monotonic())
        finally:
            os.unlink(path)


def _load(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"))


def _blocks(px: np.ndarray) -> np.ndarray:
    h, w = px.shape[0] // BLOCK, px.shape[1] // BLOCK
    return px[: h * BLOCK, : w * BLOCK].reshape(h, BLOCK, w, BLOCK, 3).mean(axis=(1, 3), dtype=np.float32)


def changed_blocks(prev: np.ndarray, cur: np.ndarray) -> np.ndarray:
    """Per 8x8 block: how much it changed (0 = not at all), with the menu bar ignored."""
    diff = np.abs(_blocks(cur) - _blocks(prev)).max(axis=2)
    diff[: IGNORE_TOP // BLOCK] = 0
    diff[diff < CHANGE] = 0
    return diff


def _groups(mask: np.ndarray) -> list[tuple[int, int, int, int, float]]:
    """Connected groups of changed blocks (8-neighbour, after growing each by one block): (r0, c0, r1, c1, weight)."""
    grown = mask.copy()
    grown[1:] |= mask[:-1]
    grown[:-1] |= mask[1:]
    grown[:, 1:] |= grown[:, :-1].copy()
    grown[:, :-1] |= grown[:, 1:].copy()
    seen = np.zeros_like(grown)
    out = []
    rows, cols = grown.shape
    for r, c in zip(*np.nonzero(grown)):
        if seen[r, c]:
            continue
        stack, cells = [(r, c)], []
        seen[r, c] = True
        while stack:
            y, x = stack.pop()
            cells.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < rows and 0 <= nx < cols and grown[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        ys, xs = zip(*cells)
        weight = float(mask[list(ys), list(xs)].sum())
        out.append((min(ys), min(xs), max(ys) + 1, max(xs) + 1, weight))
    return out


def salient_rect(prev: np.ndarray | None, cur: np.ndarray, hint: tuple[int, int] | None = None
                 ) -> tuple[int, int, int, int] | None:
    """(x, y, w, h) of the most changed region, framed at 16:9; None when nothing changed (and no hint)."""
    H, W = cur.shape[:2]
    if prev is not None and prev.shape == cur.shape:
        diff = changed_blocks(prev, cur)
        mask = diff > 0
        if mask.sum() >= MIN_BLOCKS:
            groups = [g for g in _groups(mask) if g[4] > 0]
            if groups:
                r0, c0, r1, c1, _ = max(groups, key=lambda g: g[4])
                return frame_rect(c0 * BLOCK, r0 * BLOCK, (c1 - c0) * BLOCK, (r1 - r0) * BLOCK, W, H)
    if hint is not None:
        return frame_rect(hint[0] - ZOOM_MIN_W // 2, hint[1] - int(ZOOM_MIN_W / ASPECT) // 2, ZOOM_MIN_W,
                          int(ZOOM_MIN_W / ASPECT), W, H)
    return None


def frame_rect(x: int, y: int, w: int, h: int, W: int, H: int) -> tuple[int, int, int, int]:
    """Grow (x, y, w, h) around its centre to at least ZOOM_MIN_W wide and to 16:9, then fit it on the screen."""
    pad = 16
    x, y, w, h = x - pad, y - pad, w + 2 * pad, h + 2 * pad
    cx, cy = x + w / 2, y + h / 2
    w = max(w, ZOOM_MIN_W, h * ASPECT)
    h = w / ASPECT
    if w > W:
        w, h = W, W / ASPECT
    if h > H:
        h, w = H, H * ASPECT
    x = int(min(max(cx - w / 2, 0), W - w))
    y = int(min(max(cy - h / 2, 0), H - h))
    return x, y, int(w), int(h)


@dataclass
class Pair:
    full: bytes
    zoom: bytes
    ext: str
    full_size: tuple[int, int]
    zoom_size: tuple[int, int]
    rect: tuple[int, int, int, int]
    changed: bool = True


def make_pair(before: np.ndarray | None, cur: np.ndarray, hint: tuple[int, int] | None = None,
              require_change: bool = False) -> Pair | None:
    """The pair for `cur`, zoomed on what changed since `before`; None if nothing changed and a change is required.
    Slow enough (tens of ms) to belong in a worker thread."""
    rect = salient_rect(before, cur, hint)
    if rect is None and require_change:
        return None
    pair = encode_pair(cur, rect)
    pair.changed = rect is not None
    return pair


def encode_pair(pixels: np.ndarray, rect: tuple[int, int, int, int] | None) -> Pair:
    """WebP pair: the screen at FULL_W wide, and the zoom at native pixels (centre of the screen when no rect)."""
    H, W = pixels.shape[:2]
    if rect is None:
        rect = frame_rect(W // 2 - ZOOM_MIN_W // 2, H // 2, ZOOM_MIN_W, 1, W, H)
    im = Image.fromarray(pixels)
    full = im if W <= FULL_W else im.resize((FULL_W, round(H * FULL_W / W)), Image.Resampling.LANCZOS)
    x, y, w, h = rect
    zoom = im.crop((x, y, x + w, y + h))
    return Pair(full=_webp(full, FULL_QUALITY), zoom=_webp(zoom, ZOOM_QUALITY), ext="webp", full_size=full.size,
                zoom_size=zoom.size, rect=rect)


def _webp(im: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=quality, method=4)
    return buf.getvalue()
