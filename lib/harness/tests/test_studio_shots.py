"""Screenshot pairs on synthetic screens: where the zoom goes (saliency) and how the pair is encoded."""

import io
from dataclasses import replace

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from harness.studio import shots

W, H = 1920, 1080
P = shots.SALIENCY
FONT = ImageFont.load_default(size=13)


def ui(seed: int = 0, clock: str = "7:07") -> Image.Image:
    """A dark, Live-like 1080p screen: a menu bar with a clock, labelled panels, coloured track headers."""
    rng = np.random.default_rng(seed)
    im = Image.new("RGB", (W, H), (38, 38, 38))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W - 1, 29], fill=(60, 60, 64))
    d.text((10, 8), "Live  File  Edit  Create  View  Options  Help", font=FONT, fill=(230, 230, 230))
    d.text((1790, 8), f"Sat Oct 10 {clock}", font=FONT, fill=(230, 230, 230))
    for y in range(60, 1000, 40):
        for x in range(20, 1460, 240):
            d.rectangle([x, y, x + 200, y + 28], fill=(52, 52, 52), outline=(70, 70, 70))
            d.text((x + 6, y + 7), f"Param {x // 10 + y} {int(rng.integers(0, 100))} %", font=FONT,
                   fill=(200, 200, 200))
    for i, y in enumerate(range(80, 600, 30)):
        d.rectangle([1700, y, 1900, y + 24], fill=tuple(int(v) for v in rng.integers(60, 230, 3)))
        d.text((1706, y + 5), f"{i + 1} Track {i + 1}", font=FONT, fill=(10, 10, 10))
    return im


BASE = ui()


def px(im: Image.Image) -> np.ndarray:
    return np.asarray(im)


def box(im: Image.Image, rect, fill=(225, 225, 225), text=True) -> Image.Image:
    """`im` with a box drawn on it: a dialog (with text) or a plain block."""
    out = im.copy()
    d = ImageDraw.Draw(out)
    x, y, w, h = rect
    d.rectangle([x, y, x + w - 1, y + h - 1], fill=fill, outline=(120, 120, 120))
    if text and h > 40:
        d.text((x + 12, y + 10), "Export Audio/Video", font=FONT, fill=(0, 0, 0))
        for i in range(max(0, (h - 50) // 26)):
            d.text((x + 12, y + 36 + 26 * i), f"Option {i}: value {i * 7}", font=FONT, fill=(20, 20, 20))
    return out


def salient(prev: Image.Image, cur: Image.Image, **kw) -> shots.Saliency:
    return shots.find_salient(px(prev), px(cur), **kw)


def changed_bbox(prev, cur):
    m = shots.changed_mask(px(prev), px(cur), P.pix_thresh)
    ys, xs = np.nonzero(m)
    return (int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)), int(m.sum())


def contains(outer, inner) -> bool:
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return ox <= ix and oy <= iy and ix + iw <= ox + ow and iy + ih <= oy + oh


def assert_valid(rect, screen=(W, H), p=P):
    x, y, w, h = rect
    assert x >= 0 and y >= 0 and x + w <= screen[0] and y + h <= screen[1], rect
    assert w * p.aspect[1] == h * p.aspect[0], rect              # exactly the aspect
    assert w % 2 == 0 and h % 2 == 0, rect                      # even sides
    widest = min(screen[0], screen[1] * p.aspect[0] // p.aspect[1])
    assert min(p.min_w, widest) <= w <= max(p.max_w, p.min_w) + 2 * p.aspect[0], rect


# --- where the zoom goes -------------------------------------------------------------------------------------------
def test_identical_screens_fall_back_to_the_centre():
    sal = salient(BASE, BASE.copy())
    assert sal.reason == "centre" and sal.clusters == []
    assert sal.rect == (720, 360, 480, 360)


def test_a_dialog_is_found_and_framed():
    dialog = (700, 300, 420, 220)
    sal = salient(BASE, box(BASE, dialog))
    assert sal.reason == "change" and contains(sal.rect, dialog)
    assert_valid(sal.rect)


def test_the_menu_bar_clock_is_ignored():
    cur = ui(clock="7:08")
    assert changed_bbox(BASE, cur)[1] > 0                        # the clock did change...
    assert salient(BASE, cur).reason == "centre"                  # ...but it doesn't count


def test_a_blinking_caret_is_ignored():
    cur = box(BASE, (500, 607, 2, 16), fill=(255, 255, 255), text=False)
    sal = salient(BASE, cur, hint=(900, 500))
    assert sal.reason == "hint" and contains(sal.rect, (900, 500, 0, 0))


def test_a_changed_value_is_found_at_the_smallest_zoom():
    cur = BASE.copy()
    d = ImageDraw.Draw(cur)
    d.rectangle([501, 381, 699, 407], fill=(52, 52, 52))
    d.text((506, 387), "Gain -6.5 dB", font=FONT, fill=(255, 190, 60))
    bbox, n = changed_bbox(BASE, cur)
    assert n >= P.min_px
    sal = salient(BASE, cur)
    assert sal.reason == "change" and contains(sal.rect, bbox) and sal.rect[2:] == (480, 360)


def test_a_dialog_beats_level_meters():
    prev, cur = BASE.copy(), BASE.copy()
    rng = np.random.default_rng(3)
    for im in (prev, cur):                                       # 16 thin meters at different levels
        d = ImageDraw.Draw(im)
        for i in range(16):
            top = int(rng.integers(650, 900))
            d.rectangle([1500 + 10 * i, 650, 1503 + 10 * i, 900], fill=(38, 38, 38))
            d.rectangle([1500 + 10 * i, top, 1503 + 10 * i, 900], fill=(80, 220, 80))
    dialog = (300, 250, 360, 200)
    assert contains(salient(prev, box(cur, dialog)).rect, dialog)


def test_a_compact_change_beats_a_sprawling_one():
    cur = BASE.copy()
    d = ImageDraw.Draw(cur)
    for y in range(100, 800, 16):                                # a sparse re-layout: 1 px lines over 1200 x 700
        d.line([(300, y), (1499, y)], fill=(200, 60, 60))
    dialog = (1560, 700, 260, 160)
    sal = salient(BASE, box(cur, dialog))
    assert contains(sal.rect, dialog)
    sprawl = [c for c in sal.clusters if not contains(sal.rect, c.bbox)]
    assert sprawl and sprawl[0].px > sal.cluster.px             # though the sprawl changed more pixels


def test_video_that_keeps_playing_is_learnt_and_ignored():
    rng = np.random.default_rng(1)

    def frame(banner: bool = False) -> Image.Image:
        a = np.array(BASE)
        a[600:940, 100:700] = rng.integers(0, 255, (340, 600, 3), dtype=np.uint8)   # a playing video
        im = Image.fromarray(a)
        return box(im, (1540, 40, 360, 72)) if banner else im

    tracker = shots.ChangeTracker()
    frames = [frame() for _ in range(8)]
    for f in frames:
        tracker.update(px(f))
    post = frame(banner=True)
    assert salient(frames[-1], post).cluster.bbox[0] < 700       # without history, the video wins
    sal = salient(frames[-1], post, noise=tracker.noise)
    assert contains(sal.rect, (1540, 40, 360, 72))               # with it, the notification does


def test_the_tracker_forgets_once_things_settle():
    tracker = shots.ChangeTracker()
    a, b = px(BASE), px(box(BASE, (100, 100, 400, 300)))
    for f in [a, b] * 5:                                         # a block that blinks every frame
        tracker.update(f)
    assert tracker.noise[20, 30]
    for _ in range(6):                                           # then a stream that hands over the same frame
        tracker.update(a)
    assert not tracker.noise.any()


def test_a_change_in_the_corner_stays_on_screen():
    corner = (1850, 1040, 70, 40)
    sal = salient(BASE, box(BASE, corner, fill=(250, 120, 0), text=False))
    assert sal.reason == "change" and contains(sal.rect, corner)
    assert sal.rect == (W - 480, H - 360, 480, 360)


def test_a_huge_change_gets_the_biggest_zoom_near_the_hint():
    cur = Image.fromarray(255 - px(BASE))                        # everything changed
    sal = salient(BASE, cur)
    assert sal.rect[2:] == (P.max_w, P.max_w * 3 // 4)
    assert_valid(sal.rect)
    assert contains(salient(BASE, cur, hint=(1800, 950)).rect, (1800, 950, 0, 0))


def test_a_small_change_near_the_hint_beats_a_bigger_one_far_away():
    near, far = (300, 300, 30, 12), (1300, 800, 60, 20)
    cur = box(box(BASE, near, (250, 250, 0), False), far, (0, 200, 250), False)
    assert contains(salient(BASE, cur).rect, far)                # without a hint, the bigger change wins
    sal = salient(BASE, cur, hint=(310, 305))
    assert sal.reason == "change" and contains(sal.rect, near)


def test_a_dialog_far_from_the_hint_still_wins():
    near, dialog = (300, 300, 30, 12), (1200, 500, 400, 240)
    cur = box(box(BASE, near, (250, 250, 0), False), dialog)
    assert contains(salient(BASE, cur, hint=(310, 305)).rect, dialog)


def test_a_small_change_far_from_the_hint_loses_to_the_hint():
    cur = box(BASE, (1500, 950, 40, 12), (0, 200, 250), False)  # e.g. the CPU meter's digits
    sal = salient(BASE, cur, hint=(400, 400))
    assert sal.reason == "hint" and contains(sal.rect, (400, 400, 0, 0))


def test_a_hint_by_the_edge_stays_on_screen():
    sal = salient(BASE, BASE, hint=(5, 1075))
    assert sal.reason == "hint" and sal.rect == (0, H - 360, 480, 360)


def test_the_front_window_comes_after_a_change_and_a_hint():
    window = (743, 225, 434, 186)
    sal = salient(BASE, BASE, window=window)
    assert sal.reason == "window" and contains(sal.rect, window)
    assert salient(BASE, box(BASE, (100, 500, 420, 220)), window=window).reason == "change"
    assert salient(BASE, BASE, hint=(10, 10), window=window).reason == "hint"


def test_a_big_window_gets_the_biggest_zoom_on_its_centre():
    assert salient(BASE, BASE, window=(0, 30, 1920, 960)).rect == (480, 150, 960, 720)


def test_without_a_comparable_capture_there_is_no_change():
    assert salient(BASE.resize((1280, 720)), BASE).reason == "centre"
    assert shots.find_salient(None, px(BASE)).reason == "centre"


@pytest.mark.parametrize("aspect", [(4, 3), (16, 9)])
def test_fit_rect_always_frames_on_screen(aspect):
    p = replace(P, aspect=aspect, min_w=480 if aspect == (4, 3) else 640, max_w=960 if aspect == (4, 3) else 1280)
    rng = np.random.default_rng(7)
    for _ in range(500):
        w, h = int(rng.integers(0, 1500)), int(rng.integers(0, 900))
        x, y = int(rng.integers(0, W - w)), int(rng.integers(0, H - h))
        r = shots.fit_rect((x, y, w, h), (W, H), p)
        assert_valid(r, p=p)
        if w + 2 * p.pad <= p.max_w and (h + 2 * p.pad) * aspect[0] / aspect[1] <= p.max_w:
            assert contains(r, (x, y, w, h)), ((x, y, w, h), r)


def test_fit_rect_on_a_small_screen():
    assert shots.fit_rect((10, 10, 50, 50), (400, 300)) == (0, 0, 400, 300)


def test_label_is_eight_connected():
    m = np.zeros((6, 8), bool)
    m[0, 0] = m[1, 1] = m[2, 2] = True                           # a diagonal chain: one group
    m[0, 5] = m[0, 6] = True                                     # a separate run
    m[4, 0:8] = True                                             # a full row...
    m[5, 3] = True                                               # ...and a cell touching it
    lab, n = shots.label(m)
    assert n == 3
    assert lab[0, 0] == lab[2, 2] and lab[4, 0] == lab[5, 3] and lab[0, 5] != lab[0, 0]


def test_dilate_by_a_square():
    m = np.zeros((7, 7), bool)
    m[3, 3] = True
    assert shots.dilate(m, 2).sum() == 25


def test_cell_counts_pad_the_edges():
    c = shots.cell_counts(np.ones((10, 13), bool), 8)
    assert c.shape == (2, 2) and c.sum() == 130 and c[1, 1] == 2 * 5


# --- encoding ------------------------------------------------------------------------------------------------------
def decode(data: bytes) -> Image.Image:
    im = Image.open(io.BytesIO(data))
    im.load()
    return im


def test_a_major_pair_is_native_webp_within_budget():
    cur = box(BASE, (700, 300, 420, 220))
    rect = salient(BASE, cur).rect
    pair = shots.encode_pair(px(cur), rect, shots.PRESETS["major"])
    assert len(pair.full) <= 120_000 and len(pair.zoom) <= 60_000
    full, zoom = decode(pair.full), decode(pair.zoom)
    assert full.format == zoom.format == "WEBP"
    assert full.size == pair.full_size == (W, H) and zoom.size == pair.zoom_size == rect[2:]
    assert pair.rect == rect and pair.screen == (W, H)
    x, y, w, h = rect                                            # the zoom keeps native pixels
    src = px(cur)[y:y + h, x:x + w].astype(int)
    assert np.abs(np.asarray(zoom.convert("RGB")).astype(int) - src).mean() < 4


def test_a_firehose_pair_is_720p_and_never_enlarged():
    pair = shots.encode_pair(px(BASE), (720, 360, 480, 360), shots.PRESETS["firehose"])
    assert decode(pair.full).size == pair.full_size == (1280, 720)
    assert len(pair.full) <= 80_000 and len(pair.zoom) <= 45_000
    small = shots.encode_pair(px(BASE.resize((640, 360))), (80, 0, 480, 360), shots.PRESETS["firehose"])
    assert small.full_size == (640, 360) and small.screen == (640, 360)


def test_over_budget_the_full_screen_gives_up_quality_then_size():
    rng = np.random.default_rng(5)
    noisy = np.clip(px(BASE).astype(int) + rng.normal(0, 25, (H, W, 3)), 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(noisy).save(buf, "WEBP", quality=75, method=shots.WEBP_METHOD)
    assert buf.tell() > 120_000                                  # too big as it is
    pair = shots.encode_pair(noisy, (0, 0, 480, 360))
    assert len(pair.full) < buf.tell()
    assert len(pair.full) <= 120_000 or pair.full_size[0] <= 640
    assert pair.zoom_size == (480, 360)                          # the zoom is never resized


def test_a_rect_off_the_screen_is_clamped():
    pair = shots.encode_pair(px(BASE), (1800, 1000, 480, 360))
    assert pair.rect == (1800, 1000, 120, 80) and decode(pair.zoom).size == (120, 80)


def test_make_pair_says_whether_the_zoom_shows_a_change():
    cur = box(BASE, (700, 300, 420, 220))
    pair = shots.make_pair(px(BASE), px(cur))
    assert pair.changed and contains(pair.rect, (700, 300, 420, 220))
    unchanged = shots.make_pair(px(BASE), px(BASE), window=(743, 225, 434, 186))
    assert not unchanged.changed and contains(unchanged.rect, (743, 225, 434, 186))
    assert shots.make_pair(px(BASE), px(BASE), require_change=True) is None
