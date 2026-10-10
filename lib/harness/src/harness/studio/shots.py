"""What a screenshot pair shows, and how it is encoded: plain functions on pixels. grab.py captures, screens.py
decides when.

The zoom goes where the screen changed. Pixels that differ between two captures are counted in 8 px cells, nearby
active cells are grouped, and the group a zoom can show most of wins, weighted by how much of the zoom it fills: a
compact dialog beats a sprawling re-layout, and a thin caret, meter or playhead counts for little. Near a hint
(where Claude acted) a group counts four times as much, and far from it only a big change (a dialog) can win. With
no change the zoom falls back to the hint, then the front window, then the centre. It is framed at 4:3, from 480x360
to 960x720 screen pixels.

The full screen is WebP at up to 1080p, the zoom WebP at native pixels so its text stays legible. The numbers were
measured on real 1080p captures of Live.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

Rect = tuple[int, int, int, int]       # x, y, w, h in screen pixels
Point = tuple[int, int]


@dataclass
class Frame:
    """One capture of the screen. Its pixels are never modified, so frames are shared rather than copied."""

    pixels: np.ndarray                 # H x W x 3, uint8, RGB (sRGB)
    t: float                           # time.monotonic() when taken
    window: Rect | None = None         # the front window then, when the capture knows it


# --- saliency ------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class SaliencyParams:
    cell: int = 8              # px per cell (1920x1080 is 240 x 135 cells)
    pix_thresh: int = 24       # a pixel has changed when a channel moved by more than this
    cell_min_px: int = 2       # changed pixels for a cell to count
    merge_px: int = 16         # changes up to about twice this far apart are one group
    min_px: int = 80           # changed pixels for a group to count (a caret is ~32, a clock digit ~64, a knob's
                               # ring ~156, a dialog 10,000 or more)
    thin_px: int = 6           # groups thinner than this (carets, meters, the playhead) ...
    thin_weight: float = 0.3   # ... count this much
    menubar_px: int = 30       # groups inside the menu bar (its clock, status items) are ignored
    hint_radius: int = 160     # groups this close to the hint ...
    hint_boost: float = 4.0    # ... count this many times as much
    override_px: int = 1500    # with a hint, a group far from it needs this many pixels in the zoom to win (a dialog
                               # or a notification does; a CPU meter or a spinner doesn't)
    pad: int = 24              # margin around the change in the zoom
    aspect: tuple[int, int] = (4, 3)
    min_w: int = 480           # the zoom is never narrower (480 x 360) ...
    max_w: int = 960           # ... nor wider (960 x 720)


SALIENCY = SaliencyParams()


@dataclass
class Cluster:
    """A group of changed cells."""

    bbox: Rect                           # the changed pixels' bounds
    px: int                              # changed pixels
    score: float                         # pixels the zoom shows x sqrt(fill), x thin weight, x hint boost
    centroid: tuple[float, float]        # where the change is, weighted by it
    captured: int                        # changed pixels a zoom can show (px, when the group fits in one)
    focus: tuple[float, float] | None    # for a group too big for one zoom: the centre of its best zoom
    thin: bool
    near_hint: bool


@dataclass
class Saliency:
    rect: Rect                           # the zoom
    reason: str                          # change | hint | window | centre
    cluster: Cluster | None = None       # the group the zoom shows, when the reason is a change
    clusters: list[Cluster] = field(default_factory=list)   # every group that counted, best first


def changed_mask(prev: np.ndarray, cur: np.ndarray, thresh: int) -> np.ndarray:
    """Per pixel: did any channel move by more than `thresh`? (uint8 arithmetic that can't wrap)"""
    d = np.maximum(prev, cur)
    d -= np.minimum(prev, cur)
    return d.max(axis=2) > thresh


def cell_counts(mask: np.ndarray, cell: int) -> np.ndarray:
    """True pixels per cell x cell block (the edges padded with False)."""
    h, w = mask.shape
    hc, wc = -(-h // cell), -(-w // cell)
    if (hc * cell, wc * cell) != (h, w):
        padded = np.zeros((hc * cell, wc * cell), bool)
        padded[:h, :w] = mask
        mask = padded
    return mask.reshape(hc, cell, wc, cell).sum(axis=(1, 3), dtype=np.int32)


def dilate(mask: np.ndarray, r: int) -> np.ndarray:
    """Binary dilation by a (2r+1) x (2r+1) square, as shifts along each axis."""
    out = mask.copy()
    for k in range(1, r + 1):
        out[:, k:] |= mask[:, :-k]
        out[:, :-k] |= mask[:, k:]
    rows = out.copy()
    for k in range(1, r + 1):
        out[k:] |= rows[:-k]
        out[:-k] |= rows[k:]
    return out


def label(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """8-connected components of a small boolean grid, by runs per row and union-find: (labels 1..n, 0 for none; n)."""
    h, w = mask.shape
    labels = np.zeros((h, w), np.int32)
    parent = [0]

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    above: list[tuple[int, int, int]] = []
    for y in range(h):
        row = mask[y]
        if not row.any():
            above = []
            continue
        edges = np.diff(np.concatenate(([0], row.view(np.int8), [0])))
        runs = []
        for s, e in zip(np.flatnonzero(edges == 1).tolist(), np.flatnonzero(edges == -1).tolist(), strict=True):
            lab = 0
            for ps, pe, pl in above:          # 8-connected: a run above touching [s - 1, e]
                if ps <= e and pe >= s:
                    root = find(pl)
                    if lab == 0:
                        lab = root
                    elif root != lab:
                        lo, hi = min(root, lab), max(root, lab)
                        parent[hi] = lo
                        lab = lo
            if lab == 0:
                lab = len(parent)
                parent.append(lab)
            labels[y, s:e] = lab
            runs.append((s, e, lab))
        above = runs
    roots = np.array([find(i) for i in range(len(parent))], np.int32)
    uniq, compact = np.unique(roots, return_inverse=True)
    return compact.astype(np.int32)[labels], len(uniq) - 1


def fit_rect(box: Rect, screen: tuple[int, int], p: SaliencyParams = SALIENCY,
             focus: tuple[float, float] | None = None) -> Rect:
    """The smallest rect at p.aspect around `box` plus p.pad, from p.min_w to p.max_w wide and never bigger than the
    screen, moved (not shrunk) to lie on it, with even sides. A box too big for p.max_w is framed around `focus`."""
    sw, sh = screen
    ax, ay = p.aspect
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    zw = max(w + 2 * p.pad, (h + 2 * p.pad) * ax / ay, p.min_w)
    if zw > p.max_w:
        zw = p.max_w
        if focus is not None:
            cx, cy = focus
    zw = min(zw, sw, sh * ax / ay)
    unit = int(-(-zw // ax))                   # sides are whole, even multiples of the aspect
    unit += unit % 2
    while unit * ax > sw or unit * ay > sh:
        unit -= 2
    zw, zh = unit * ax, unit * ay
    zx = round(min(max(cx - zw / 2, 0), sw - zw))
    zy = round(min(max(cy - zh / 2, 0), sh - zh))
    return zx, zy, zw, zh


def _distance(a: Rect, b: Rect) -> float:
    dx = max(b[0] - (a[0] + a[2]), a[0] - (b[0] + b[2]), 0)
    dy = max(b[1] - (a[1] + a[3]), a[1] - (b[1] + b[3]), 0)
    return float(np.hypot(dx, dy))


def _best_window(grid: np.ndarray, size: tuple[int, int], target: tuple[float, float], slack: float
                 ) -> tuple[int, tuple[float, float]]:
    """Slide a window of `size` (cells, w x h) over a grid of counts. Of the windows that hold at least `slack` of
    the most any holds, take the one centred nearest `target`. Returns (its count, its centre in cells)."""
    hc, wc = min(size[1], grid.shape[0]), min(size[0], grid.shape[1])
    s = np.zeros((grid.shape[0] + 1, grid.shape[1] + 1), np.int64)
    s[1:, 1:] = grid.cumsum(0).cumsum(1)
    sums = s[hc:, wc:] - s[:-hc, wc:] - s[hc:, :-wc] + s[:-hc, :-wc]
    iy, ix = np.nonzero(sums >= slack * sums.max())
    k = int(np.argmin((ix + wc / 2 - target[0]) ** 2 + (iy + hc / 2 - target[1]) ** 2))
    return int(sums[iy[k], ix[k]]), (ix[k] + wc / 2, iy[k] + hc / 2)


def _clusters(active: np.ndarray, counts: np.ndarray, changed: np.ndarray, p: SaliencyParams,
              hint: Rect | None, screen: tuple[int, int]) -> list[Cluster]:
    """The groups of active cells that count, best first."""
    labels, n = label(dilate(active, round(p.merge_px / p.cell)))
    if n == 0:
        return []
    ax, ay = p.aspect
    c = p.cell
    ys, xs = np.nonzero(active)
    ls = labels[ys, xs]
    weights = counts[ys, xs].astype(np.float64)
    px = np.bincount(ls, weights=weights, minlength=n + 1)
    sx = np.bincount(ls, weights=weights * (xs + 0.5), minlength=n + 1)
    sy = np.bincount(ls, weights=weights * (ys + 0.5), minlength=n + 1)
    x0, y0 = np.full(n + 1, 1 << 30), np.full(n + 1, 1 << 30)
    x1, y1 = np.full(n + 1, -1), np.full(n + 1, -1)
    np.minimum.at(x0, ls, xs)
    np.minimum.at(y0, ls, ys)
    np.maximum.at(x1, ls, xs)
    np.maximum.at(y1, ls, ys)

    h, w = changed.shape
    out = []
    for k in range(1, n + 1):
        if px[k] < p.min_px:
            continue
        # The cells' bounds, narrowed to the changed pixels in them.
        cx0, cy0 = int(x0[k]) * c, int(y0[k]) * c
        cx1, cy1 = min((int(x1[k]) + 1) * c, w), min((int(y1[k]) + 1) * c, h)
        sub = changed[cy0:cy1, cx0:cx1]
        rows, cols = np.flatnonzero(sub.any(axis=1)), np.flatnonzero(sub.any(axis=0))
        if rows.size == 0:
            continue
        bbox = (cx0 + int(cols[0]), cy0 + int(rows[0]), int(cols[-1] - cols[0]) + 1, int(rows[-1] - rows[0]) + 1)
        if bbox[1] + bbox[3] <= p.menubar_px:
            continue
        centroid = (float(sx[k] / px[k]) * c, float(sy[k] / px[k]) * c)
        thin = min(bbox[2], bbox[3]) < p.thin_px
        near = hint is not None and _distance(bbox, hint) <= p.hint_radius
        captured, focus = int(px[k]), None
        if bbox[2] + 2 * p.pad > p.max_w or bbox[3] + 2 * p.pad > p.max_w * ay / ax:
            # Too big for one zoom: it counts for what the best zoom-sized window shows, and the zoom goes there
            # (near the hint when it is close, else near the change's centre).
            grid = np.where((labels == k) & active, counts, 0)
            target = (hint[0] + hint[2] / 2, hint[1] + hint[3] / 2) if near else centroid
            captured, centre = _best_window(grid, (p.max_w // c, p.max_w * ay // ax // c),
                                            (target[0] / c, target[1] / c), 0.7 if near else 0.95)
            focus = (centre[0] * c, centre[1] * c)
        # Compact changes (dialogs, pop-ups, notifications) beat sprawling ones: the pixels shown count by the
        # square root of how much of the zoom they fill.
        _, _, zw, zh = fit_rect(bbox, screen, p, focus=focus or centroid)
        score = captured * (captured / (zw * zh)) ** 0.5
        score *= (p.thin_weight if thin else 1.0) * (p.hint_boost if near else 1.0)
        out.append(Cluster(bbox=bbox, px=int(px[k]), score=score, centroid=centroid, captured=captured, focus=focus,
                           thin=thin, near_hint=near))
    out.sort(key=lambda cl: cl.score, reverse=True)
    return out


def find_salient(prev: np.ndarray | None, cur: np.ndarray, hint: Point | None = None, window: Rect | None = None,
                 noise: np.ndarray | None = None, p: SaliencyParams = SALIENCY) -> Saliency:
    """Where the zoom goes: the most significant change from `prev` to `cur`, else the hint (where Claude acted),
    else the front window, else the centre. `noise` marks cells that keep changing on their own
    (ChangeTracker.noise); they are ignored. Takes ~25 ms at 1080p."""
    sh, sw = cur.shape[:2]
    hint_box = (int(hint[0]), int(hint[1]), 0, 0) if hint is not None else None
    clusters: list[Cluster] = []
    if prev is not None and prev is not cur and prev.shape == cur.shape:
        changed = changed_mask(prev, cur, p.pix_thresh)
        counts = cell_counts(changed, p.cell)
        active = counts >= p.cell_min_px
        if noise is not None and noise.shape == active.shape:
            active &= ~noise
        clusters = _clusters(active, counts, changed, p, hint_box, (sw, sh))
    # With a hint, a small change far from it is incidental (a meter, a spinner): it loses to the hint.
    candidates = [cl for cl in clusters if hint_box is None or cl.near_hint or cl.captured >= p.override_px]
    if candidates:
        best = candidates[0]
        return Saliency(fit_rect(best.bbox, (sw, sh), p, focus=best.focus or best.centroid), "change", best, clusters)
    if hint_box is not None:
        reason, box = "hint", hint_box
    elif window is not None:
        reason, box = "window", window
    else:
        reason, box = "centre", (sw // 2, sh // 2, 0, 0)
    return Saliency(fit_rect(box, (sw, sh), p), reason, None, clusters)


class ChangeTracker:
    """What keeps changing on its own: per cell, a running average of "changed since the last frame".

    Fed a frame each second while tools run, cells that keep changing (video, level meters, the playhead, a spinner)
    reach `chronic` after about five frames and show up in `noise`, which find_salient then ignores. A one-off change
    (a dialog, a value) never gets there, and the map fades once things settle.
    """

    def __init__(self, p: SaliencyParams = SALIENCY, alpha: float = 0.2, chronic: float = 0.6):
        self.p, self.alpha, self.chronic = p, alpha, chronic
        self.prev: np.ndarray | None = None
        self.heat: np.ndarray | None = None

    def update(self, frame: np.ndarray) -> None:
        if self.prev is None or self.prev.shape != frame.shape:
            self.prev, self.heat = frame, None
            return
        if frame is self.prev:                 # the same frame again (a stream with nothing new): all is still
            if self.heat is not None:
                self.heat = self.heat * (1 - self.alpha)
            return
        counts = cell_counts(changed_mask(self.prev, frame, self.p.pix_thresh), self.p.cell)
        hit = (counts >= self.p.cell_min_px).astype(np.float32)
        self.heat = hit * self.alpha if self.heat is None else self.heat * (1 - self.alpha) + hit * self.alpha
        self.prev = frame

    @property
    def noise(self) -> np.ndarray | None:
        """Cells that keep changing (grown by one cell), once there have been two frames."""
        return None if self.heat is None else dilate(self.heat >= self.chronic, 1)


# --- encoding ------------------------------------------------------------------------------------------------------
MIN_QUALITY = 50
WEBP_METHOD = 4                 # effort, 0-6: 6 is 60% slower for 3% fewer bytes


@dataclass(frozen=True)
class Preset:
    """How a pair is encoded. The full screen is shrunk to fit `full_box` (never enlarged); the zoom keeps native
    pixels. An image over its budget steps its quality down by 10 to MIN_QUALITY; then the full screen (never the
    zoom: its point is legible text) shrinks by 0.8x."""

    full_box: tuple[int, int]
    full_q: int
    zoom_q: int
    full_budget: int
    zoom_budget: int


# major and minor: a 1080p screen at native size is 73-111 KB at q75 and its zooms 9-46 KB at q90.
SHARP = Preset(full_box=(1920, 1080), full_q=75, zoom_q=90, full_budget=120_000, zoom_budget=60_000)
# firehose, about one a second: 720p is ~52 KB, and the zoom stays sharp.
LIGHT = Preset(full_box=(1280, 720), full_q=70, zoom_q=85, full_budget=80_000, zoom_budget=45_000)
PRESETS = {"major": SHARP, "minor": SHARP, "firehose": LIGHT}


@dataclass
class Pair:
    full: bytes                    # WebP
    full_size: tuple[int, int]
    zoom: bytes                    # WebP, native pixels
    zoom_size: tuple[int, int]
    rect: Rect                     # the zoom on the screen: the page outlines it on the full image, scaled by
    screen: tuple[int, int]        # full_size[0] / screen[0]
    changed: bool = False          # the zoom shows a change (not the hint, the window or the centre)


def _webp(im: Image.Image, q: int, budget: int, shrink: bool) -> tuple[bytes, Image.Image]:
    """`im` as WebP, within `budget` bytes if it can be: quality down by 10 to MIN_QUALITY, then (with `shrink`) the
    image down by 0.8x while it is wider than 640 px."""
    while True:
        buf = io.BytesIO()
        im.save(buf, "WEBP", quality=q, method=WEBP_METHOD)
        if buf.tell() <= budget:
            return buf.getvalue(), im
        if q - 10 >= MIN_QUALITY:
            q -= 10
        elif shrink and im.width > 640:
            im = im.resize((round(im.width * 0.8), round(im.height * 0.8)), Image.Resampling.LANCZOS)
        else:
            return buf.getvalue(), im


def encode_pair(pixels: np.ndarray, rect: Rect, preset: Preset = SHARP) -> Pair:
    """The full screen and the zoom on `rect` (clamped to the screen), as WebP: ~100 ms for a 1080p screen."""
    im = Image.fromarray(pixels)
    sw, sh = im.size
    x, y = max(0, min(int(rect[0]), sw - 1)), max(0, min(int(rect[1]), sh - 1))
    w, h = max(1, min(int(rect[2]), sw - x)), max(1, min(int(rect[3]), sh - y))
    scale = min(1.0, preset.full_box[0] / sw, preset.full_box[1] / sh)
    full = im if scale == 1 else im.resize((round(sw * scale), round(sh * scale)), Image.Resampling.LANCZOS)
    full_bytes, full = _webp(full, preset.full_q, preset.full_budget, shrink=True)
    zoom_bytes, zoom = _webp(im.crop((x, y, x + w, y + h)), preset.zoom_q, preset.zoom_budget, shrink=False)
    return Pair(full=full_bytes, full_size=full.size, zoom=zoom_bytes, zoom_size=zoom.size, rect=(x, y, w, h),
                screen=(sw, sh))


def make_pair(before: np.ndarray | None, cur: np.ndarray, *, hint: Point | None = None, window: Rect | None = None,
              noise: np.ndarray | None = None, preset: Preset = SHARP, require_change: bool = False) -> Pair | None:
    """The pair for `cur`, zoomed on what changed since `before`; None if nothing did and a change is required.
    ~130 ms at 1080p: call it in a worker thread."""
    sal = find_salient(before, cur, hint, window, noise)
    if require_change and sal.reason != "change":
        return None
    pair = encode_pair(cur, sal.rect, preset)
    pair.changed = sal.reason == "change"
    return pair
