"""Cut game sprites out of generated images and write a region's art manifest.

    cd lib/harness
    uv run python scripts/cutout.py scripts/rummage-art.json            # every asset in the plan
    uv run python scripts/cutout.py scripts/rummage-art.json --only props/teapot,hero
    uv run python scripts/cutout.py scripts/rummage-art.json --sheet ~/somewhere/sheet.png

The plan (JSON) names, for every asset, the id of the image it is cut from (an id in images.jsonl, made through
`harness images`, docs/images.md) and its size. Sprites are generated as one object on flat magenta (#FF00FF):
the magenta is keyed out (soft alpha only near the background, and magenta in shadow counts as background), the
pink fringe is unmixed and despilled, small specks are dropped, the sprite is trimmed to its alpha, resized
(premultiplied) and written as WebP with alpha. Ground textures are made to tile: the far band of each axis is laid
over the near one along a minimum-error cut, so the seam follows edges already in the texture. Panels are
cover-cropped. The manifest follows docs/rummage.md: w/h are the file's pixels, anchor is the base point as
fractions, foot the collision radius as a fraction of the width; a plan entry may also give `pick` ([index, count]:
one figure of a sheet, from the left), `slots_src` (points in the source's pixels, mapped into the sprite), `anchor`,
`foot`, `flip`, `crop` ([x0, y0, x1, y1] before keying), `scale`, `key` (keying settings), for a hero view `walk`
(frames, each a sprite spec), `block_h` (and `block_band`) for a rectangular base, `anchor_x` and, for grounds,
`mute` and `overlap`. `title` is a sprite; `sets`, `rugs` and `edge` are lists of sprites with ids (rugs are flat:
no anchor or foot; edge walls get an anchor and a block but no foot); `sleeves` are full-bleed squares,
cover-cropped to 720 px.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

MAX_BYTES = 300_000
DEFAULT_IMAGES = Path.home() / "_agent_scratch/studio/images/files"


# ---- loading -----------------------------------------------------------------------------------------------

def source(images: Path, image_id: str) -> Path:
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        p = images / f"{image_id}{ext}"
        if p.is_file():
            return p
    raise FileNotFoundError(f"no image file for {image_id} in {images}")


def load_rgb(p: Path) -> np.ndarray:
    return np.asarray(Image.open(p).convert("RGB"), dtype=np.float32) / 255.0


# ---- keying ------------------------------------------------------------------------------------------------

def _dilate(mask: np.ndarray, px: int) -> np.ndarray:
    im = Image.fromarray((mask * 255).astype(np.uint8))
    for _ in range(max(0, px)):
        im = im.filter(ImageFilter.MaxFilter(3))
    return np.asarray(im) > 127


def _components(alpha: np.ndarray) -> tuple[np.ndarray, list[int], int]:
    """Labels the opaque islands on a reduced grid: (labels, sizes with sizes[0] unused, the grid's factor)."""
    h, w = alpha.shape
    f = max(1, round(max(h, w) / 256))
    small = alpha[::f, ::f] > 0.5
    sh, sw = small.shape
    labels = np.zeros(small.shape, dtype=np.int32)
    sizes = [0]
    n = 0
    for y0 in range(sh):
        for x0 in range(sw):
            if small[y0, x0] and not labels[y0, x0]:
                n += 1
                stack = [(y0, x0)]
                labels[y0, x0] = n
                count = 0
                while stack:
                    y, x = stack.pop()
                    count += 1
                    for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                        if 0 <= yy < sh and 0 <= xx < sw and small[yy, xx] and not labels[yy, xx]:
                            labels[yy, xx] = n
                            stack.append((yy, xx))
                sizes.append(count)
    return labels, sizes, f


def _keep(alpha: np.ndarray, labels: np.ndarray, keep: np.ndarray) -> np.ndarray:
    h, w = alpha.shape
    kept = keep[labels]
    # back to full size, grown a little so the soft edges of kept islands stay
    kept_full = np.asarray(Image.fromarray(kept.astype(np.uint8) * 255).resize((w, h), Image.NEAREST)) > 127
    return np.where(_dilate(kept_full, 3), alpha, 0.0)


def _drop_specks(alpha: np.ndarray, min_frac: float) -> np.ndarray:
    """Drops opaque islands smaller than min_frac of the largest one."""
    labels, sizes, _ = _components(alpha)
    if len(sizes) <= 2:
        return alpha
    biggest = max(sizes)
    keep = np.array([s >= biggest * min_frac for s in sizes])
    keep[0] = False
    return _keep(alpha, labels, keep)


def pick(alpha: np.ndarray, index: int, count: int) -> np.ndarray:
    """From a sheet of `count` figures side by side, keeps the index-th from the left (its largest islands)."""
    labels, sizes, _ = _components(alpha)
    xs = {i: np.nonzero(labels == i)[1].mean() for i in range(1, len(sizes))}
    big = sorted(range(1, len(sizes)), key=lambda i: -sizes[i])[:count]
    order = sorted(big, key=lambda i: xs[i])
    chosen = order[index]
    keep = np.zeros(len(sizes), dtype=bool)
    for i in range(1, len(sizes)):              # every island goes with the nearest figure (boots, loose ends)
        if min(big, key=lambda b: abs(xs[b] - xs[i])) == chosen:
            keep[i] = True
    return _keep(alpha, labels, keep)


def key_magenta(rgb: np.ndarray, lo: float = 0.16, hi: float = 0.62, core: float = 0.5, zone: int = 4,
                specks: float = 0.004, erode: int = 0) -> np.ndarray:
    """RGB floats (h, w, 3) on flat magenta -> RGBA floats with the magenta keyed out and the fringe cleaned."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    m = np.minimum(r, b) - g                     # magenta-ness: 1 for #FF00FF, 0 for greys and white
    mx = np.maximum(np.maximum(r, b), 1e-3)
    purity = (np.minimum(r, b) - g) / mx         # the hue, whatever the brightness: magenta in shadow is still magenta
    balance = np.abs(r - b) / mx
    shaded = (purity > 0.6) & (balance < 0.35) & (mx > 0.12)
    bg = (m > core) | shaded
    if bg.any():
        M = np.median(rgb[bg], axis=0)
    else:
        M = np.array([1.0, 0.0, 1.0], dtype=np.float32)
    near = _dilate(bg, zone)
    t = np.clip((m - lo) / (hi - lo), 0.0, 1.0)  # how much background is mixed into the pixel
    t = np.where(near, t, 0.0)
    t = np.where(bg, 1.0, t)
    a = 1.0 - t
    # unmix the background out of the edge pixels: C = a*F + (1-a)*M
    safe = np.maximum(a, 1e-3)[..., None]
    F = np.clip((rgb - (1.0 - a)[..., None] * M) / safe, 0.0, 1.0)
    F = np.where((a > 0.999)[..., None], rgb, F)
    # despill what is left near the background: the paper edge is white, so lift green to the red/blue floor
    rr, gg, bb = F[..., 0], F[..., 1], F[..., 2]
    floor = np.minimum(rr, bb)
    tinted = near | ((purity > 0.3) & (balance < 0.4))
    gg = np.where(tinted, np.maximum(gg, floor), gg)
    F = np.stack([rr, gg, bb], axis=-1)
    a = np.where(a < 0.04, 0.0, a)
    if erode:
        im = Image.fromarray((a * 255).astype(np.uint8))
        for _ in range(erode):
            im = im.filter(ImageFilter.MinFilter(3))
        a = np.asarray(im, dtype=np.float32) / 255.0
    if specks:
        a = _drop_specks(a, specks)
    return np.concatenate([F, a[..., None]], axis=-1)


# ---- shaping -----------------------------------------------------------------------------------------------

def to_image(rgba: np.ndarray) -> Image.Image:
    return Image.fromarray(np.clip(rgba * 255 + 0.5, 0, 255).astype(np.uint8), "RGBA")


def trim_box(im: Image.Image, pad: int = 2) -> tuple[int, int, int, int]:
    a = np.asarray(im)[..., 3]
    ys, xs = np.nonzero(a > 8)
    if not len(xs):
        raise ValueError("nothing left after keying")
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    return max(0, x0 - pad), max(0, y0 - pad), min(im.width, x1 + pad), min(im.height, y1 + pad)


def trim(im: Image.Image, pad: int = 2) -> Image.Image:
    return im.crop(trim_box(im, pad))


def resize_rgba(im: Image.Image, w: int, h: int) -> Image.Image:
    return im.convert("RGBa").resize((w, h), Image.LANCZOS).convert("RGBA")


def fit(im: Image.Image, *, h: int | None = None, w: int | None = None, side: int | None = None,
        scale: float | None = None) -> Image.Image:
    if scale:
        s = scale
    elif side:
        s = side / max(im.width, im.height)
    elif h:
        s = h / im.height
    elif w:
        s = w / im.width
    else:
        return im
    return resize_rgba(im, max(1, round(im.width * s)), max(1, round(im.height * s)))


def base_of(im: Image.Image, lift: float) -> tuple[list[float], float]:
    """Anchor (x, y fractions): x at the centre of mass of the lower 40% (the body on the ground, not a scarf or a
    handle sticking out), y at the bottom of the alpha lifted a little into the footprint; and the foot radius as a
    fraction of the width, from the lower 40%'s extent."""
    a = np.asarray(im)[..., 3] > 127
    h, w = a.shape
    rows = np.nonzero(a.any(axis=1))[0]
    bottom = rows.max()
    band = a[max(0, bottom - int(0.4 * h)):bottom + 1]
    cx = float(np.nonzero(band)[1].mean()) + 0.5
    cols = np.nonzero(band.any(axis=0))[0]
    foot = float(np.clip(0.5 * (cols.max() - cols.min() + 1) / w * 0.8, 0.28, 0.42))
    ay = min(0.99, (bottom + 1) / h - lift)
    return [round(cx / w, 3), round(float(ay), 3)], round(foot, 3)


def block_of(im: Image.Image, depth: float, band_frac: float = 0.15) -> list[float]:
    """A rectangular base for a wide piece: [w_frac, h_frac], centred on the anchor and rising from it. Its width is
    the solid part of the bottom `band_frac` of the alpha (columns at least a quarter full), its depth is given."""
    a = np.asarray(im)[..., 3] > 127
    h, w = a.shape
    rows = np.nonzero(a.any(axis=1))[0]
    band = a[max(0, rows.max() - int(band_frac * h)):rows.max() + 1]
    cols = np.nonzero(band.mean(axis=0) > 0.25)[0]
    return [round(float((cols.max() - cols.min() + 1) / w * 0.92), 3), round(float(depth), 3)]


def plinth_slots(im: Image.Image, count: int = 3, top: float = 0.14) -> list[list[float]] | None:
    """The Gramophone's slots, found as the `count` islands after the machine itself (its plinths, cut out apart from
    it): the centre of each plinth's top face, as fractions of the sprite, left to right."""
    alpha = im.getchannel("A")
    for erode in range(0, 14, 2):                # paper edges that touch are pulled apart by eroding a little
        a = alpha
        for _ in range(erode):
            a = a.filter(ImageFilter.MinFilter(3))
        labels, sizes, f = _components(np.asarray(a, dtype=np.float32) / 255.0)
        order = sorted(range(1, len(sizes)), key=lambda i: -sizes[i])
        if len(order) >= count + 1 and sizes[order[count]] >= 0.02 * sizes[order[0]]:
            break
    else:
        return None
    slots = []
    for i in order[1:count + 1]:
        ys, xs = np.nonzero(labels == i)
        x0, x1, y0, y1 = xs.min() * f, (xs.max() + 1) * f, ys.min() * f, (ys.max() + 1) * f
        slots.append([round(float((x0 + x1) / 2 / im.width), 3), round(float((y0 + top * (y1 - y0)) / im.height), 3)])
    return sorted(slots)


def save_webp(im: Image.Image, path: Path, quality: int = 82) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    q = quality
    while True:
        im.save(path, "WEBP", quality=q, method=6, alpha_quality=90)
        n = path.stat().st_size
        if n <= MAX_BYTES or q <= 50:
            return n
        q -= 6


# ---- ground ------------------------------------------------------------------------------------------------

def _min_cut(err: np.ndarray) -> np.ndarray:
    """The column, per row, of the cheapest top-to-bottom path through err (rows, cols), moving at most one
    column per row (the minimum-error boundary cut of image quilting)."""
    rows, cols = err.shape
    cost = err.astype(np.float64).copy()
    back = np.zeros((rows, cols), dtype=np.int8)
    idx = np.arange(cols)
    for y in range(1, rows):
        prev = cost[y - 1]
        options = np.stack([np.r_[np.inf, prev[:-1]], prev, np.r_[prev[1:], np.inf]])
        k = options.argmin(axis=0)
        cost[y] += options[k, idx]
        back[y] = k - 1
    path = np.zeros(rows, dtype=np.int64)
    path[-1] = int(cost[-1].argmin())
    for y in range(rows - 1, 0, -1):
        path[y - 1] = path[y] + back[y, path[y]]
    return path


def _wrap_columns(a: np.ndarray, overlap: float, feather: int = 3) -> np.ndarray:
    """Makes the columns wrap: the last `overlap` of the width is laid over the first along a minimum-error cut
    (so the seam follows the torn edges already in the texture), and the image is shortened by that much."""
    n = a.shape[1]
    o = int(n * overlap)
    s = n - o
    far, near = a[:, s:], a[:, :o]                      # far continues column s-1 (the wrap); near continues column o
    diff = ((far - near) ** 2).sum(axis=2)
    diff = np.asarray(Image.fromarray(np.clip(diff / diff.max() * 255, 0, 255).astype(np.uint8))
                      .filter(ImageFilter.GaussianBlur(2)), dtype=np.float32)
    margin = feather + 2
    diff[:, :margin] = 1e6
    diff[:, -margin:] = 1e6
    path = _min_cut(diff)
    j = np.arange(o)[None, :]
    m = np.clip((j - path[:, None]) / (2 * feather) + 0.5, 0.0, 1.0)[..., None]   # 0 = far, 1 = near
    band = far * (1 - m) + near * m
    return np.concatenate([band, a[:, o:s]], axis=1)


def make_tileable(im: Image.Image, overlap: float = 0.2) -> Image.Image:
    """Wraps both axes along minimum-error cuts, so the texture tiles without a visible seam or ghosting."""
    a = np.asarray(im.convert("RGB"), dtype=np.float32)
    a = _wrap_columns(a, overlap)
    a = _wrap_columns(a.transpose(1, 0, 2), overlap).transpose(1, 0, 2)
    return Image.fromarray(np.clip(a + 0.5, 0, 255).astype(np.uint8), "RGB")


def mute(im: Image.Image, amount: float) -> Image.Image:
    if amount <= 0:
        return im
    a = np.asarray(im, dtype=np.float32)
    mean = a.reshape(-1, 3).mean(axis=0)
    a = a * (1 - amount) + mean * amount
    return Image.fromarray(np.clip(a + 0.5, 0, 255).astype(np.uint8), "RGB")


# ---- the plan ----------------------------------------------------------------------------------------------

LIFT = {"props": 0.035, "machines": 0.025, "gramophone": 0.03, "hero": 0.02, "portal": 0.03, "sets": 0.03,
        "edge": 0.03}
FOOT = {"props", "machines", "gramophone", "portal", "sets"}       # kinds that get a collision radius


def sprite(images: Path, spec: dict, kind: str, out: Path, rel: str) -> dict:
    rgb = load_rgb(source(images, spec["src"]))
    if spec.get("crop"):                         # [x0, y0, x1, y1] in the source's pixels, before keying
        x0, y0, x1, y1 = spec["crop"]
        rgb = rgb[y0:y1, x0:x1]
    rgba = key_magenta(rgb, **spec.get("key", {}))
    if spec.get("pick"):                         # [index, count]: one figure of a sheet, counted from the left
        rgba[..., 3] = pick(rgba[..., 3], *spec["pick"])
    im = to_image(rgba)
    box = trim_box(im)
    im = im.crop(box)
    if spec.get("flip"):
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    im = fit(im, h=spec.get("h"), w=spec.get("w"), side=spec.get("side"), scale=spec.get("scale"))
    n = save_webp(im, out / rel)
    rec = {"file": rel, "w": im.width, "h": im.height}
    if spec.get("slots_src"):                    # points given in the source image's pixels -> fractions of the sprite
        bw, bh = box[2] - box[0], box[3] - box[1]
        rec["slots"] = [[round(float((x - box[0]) / bw), 3), round(float((y - box[1]) / bh), 3)] for x, y in spec["slots_src"]]
    if kind in LIFT:
        anchor, foot = base_of(im, spec.get("lift", LIFT[kind]))
        if spec.get("anchor_x") is not None:     # e.g. 0.5 for a long wall, whose lowest point is off-centre
            anchor[0] = spec["anchor_x"]
        rec["anchor"] = spec.get("anchor", anchor)
        if kind in FOOT:
            rec["foot"] = spec.get("foot", foot)
        if spec.get("block_h"):                  # a rectangular base for a wide piece: [w_frac, h_frac]
            rec["block"] = spec.get("block") or block_of(im, spec["block_h"], spec.get("block_band", 0.15))
    rec["src"] = spec["src"]
    print(f"  {rel:28} {im.width:4}x{im.height:<4} {n / 1000:6.1f} KB")
    return rec


def ground(images: Path, spec: dict, out: Path) -> dict:
    im = Image.open(source(images, spec["src"])).convert("RGB")
    if spec.get("crop"):
        im = im.crop(tuple(spec["crop"]))
    im = make_tileable(im, spec.get("overlap", 0.2))
    im = mute(im, spec.get("mute", 0.0))
    size = spec.get("size", 1024)
    im = im.resize((size, size), Image.LANCZOS)
    rel = f"{spec['id']}.webp"
    n = save_webp(im, out / rel, spec.get("quality", 80))
    print(f"  {rel:28} {size:4}x{size:<4} {n / 1000:6.1f} KB")
    return {"id": spec["id"], "file": rel, "w": size, "h": size, "src": spec["src"]}


def panel(images: Path, src: str, out: Path, rel: str, w: int = 828, h: int = 1472) -> None:
    im = Image.open(source(images, src)).convert("RGB")
    s = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    x0, y0 = (im.width - w) // 2, (im.height - h) // 2
    im = im.crop((x0, y0, x0 + w, y0 + h))
    n = save_webp(im, out / rel)
    print(f"  {rel:28} {w:4}x{h:<4} {n / 1000:6.1f} KB")


def sleeve(images: Path, src: str, out: Path, rel: str, size: int = 720) -> dict:
    """A record sleeve: full-bleed and square, cover-cropped and resized."""
    im = Image.open(source(images, src)).convert("RGB")
    side = min(im.width, im.height)
    x0, y0 = (im.width - side) // 2, (im.height - side) // 2
    im = im.crop((x0, y0, x0 + side, y0 + side)).resize((size, size), Image.LANCZOS)
    n = save_webp(im, out / rel, 80)
    print(f"  {rel:28} {size:4}x{size:<4} {n / 1000:6.1f} KB")
    return {"file": rel, "w": size, "h": size, "src": src}


def build(plan: dict, out: Path, images: Path, only: set[str] | None) -> dict:
    mf_path = out / "manifest.json"
    mf = json.loads(mf_path.read_text()) if mf_path.is_file() and only else {}
    mf["version"] = 1

    def want(key: str) -> bool:
        return not only or any(key == o or key.startswith(o + "/") or o == key.split("/")[0] for o in only)

    if want("ground"):
        mf["ground"] = [ground(images, g, out) for g in plan["ground"]]
    if want("path") and plan.get("path"):
        mf["path"] = sprite(images, plan["path"], "path", out, "path.webp")
    if "props" in plan:
        props = {p["id"]: p for p in mf.get("props", [])}
        for p in plan["props"]:
            if want(f"props/{p['id']}"):
                rec = sprite(images, p, "props", out, f"props/{p['id']}.webp")
                props[p["id"]] = {"id": p["id"], **rec}
        mf["props"] = [props[p["id"]] for p in plan["props"] if p["id"] in props]
    for key, kind in (("sets", "sets"), ("rugs", "rugs"), ("edge", "edge")):   # lists of pieces with ids
        if key in plan:
            have = {p["id"]: p for p in mf.get(key, [])}
            for p in plan[key]:
                if want(f"{key}/{p['id']}"):
                    have[p["id"]] = {"id": p["id"], **sprite(images, p, kind, out, f"{key}/{p['id']}.webp")}
            mf[key] = [have[p["id"]] for p in plan[key] if p["id"] in have]
    if "machines" in plan:
        ms = mf.get("machines", {})
        for k, m in plan["machines"].items():
            if want(f"machines/{k}"):
                rec = sprite(images, m, "machines", out, f"machines/{k}.webp")
                if m.get("panel_src"):
                    panel(images, m["panel_src"], out, f"panels/{k}.webp")
                    rec["panel"] = f"panels/{k}.webp"
                    rec["panel_src"] = m["panel_src"]
                ms[k] = rec
        mf["machines"] = ms
    if want("gramophone") and plan.get("gramophone"):
        g = plan["gramophone"]
        rec = sprite(images, g, "gramophone", out, "gramophone.webp")
        slots = g.get("slots") or rec.pop("slots", None) or plinth_slots(Image.open(out / "gramophone.webp"))
        if not slots:
            raise SystemExit("gramophone: the plinths are not separate islands; give its slots in the plan")
        rec["slots"] = slots
        print(f"  gramophone slots {slots}")
        mf["gramophone"] = rec
    if "artifacts" in plan:
        arts = mf.get("artifacts", {})
        for k, a in plan["artifacts"].items():
            if want(f"artifacts/{k}"):
                arts[k] = sprite(images, a, "artifacts", out, f"artifacts/{k}.webp")
        mf["artifacts"] = {k: arts[k] for k in plan["artifacts"] if k in arts}
    if "hero" in plan:
        hero = mf.get("hero", {})
        for k, v in plan["hero"].items():
            if want(f"hero/{k}"):
                hero[k] = sprite(images, v, "hero", out, f"hero/{k}.webp")
                walk = [sprite(images, {"h": v.get("h"), **w}, "hero", out, f"hero/{k}-walk-{i + 1}.webp")
                        for i, w in enumerate(v.get("walk", []))]
                if walk:
                    hero[k]["walk"] = walk
        mf["hero"] = hero
    if want("portal") and plan.get("portal"):
        mf["portal"] = sprite(images, plan["portal"], "portal", out, "portal.webp")
    if want("title") and plan.get("title"):
        mf["title"] = sprite(images, plan["title"], "title", out, "title.webp")
    if "sleeves" in plan:
        sl = mf.get("sleeves", {})
        for k, v in plan["sleeves"].items():
            if want(f"sleeves/{k}"):
                sl[k] = sleeve(images, v["src"], out, f"sleeves/{k}.webp", v.get("size", 720))
        mf["sleeves"] = {k: sl[k] for k in plan["sleeves"] if k in sl}
    order = ["version", "ground", "path", "props", "sets", "rugs", "edge", "machines", "gramophone", "artifacts", "hero",
             "portal", "title", "sleeves"]
    mf = {k: mf[k] for k in order if k in mf}
    mf_path.write_text(json.dumps(mf, indent=1) + "\n")
    return mf


# ---- contact sheet ------------------------------------------------------------------------------------------

def sleeve_sheet(mf: dict, out: Path, dest: Path, cell: int = 300) -> None:
    """The sleeves in a 9 x 3 grid, in order of their combination, each labelled."""
    keys = sorted(mf.get("sleeves", {}))
    cols, gap, lab = 9, 14, 18
    rows = (len(keys) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * (cell + gap) + gap, rows * (cell + gap + lab) + gap), (128, 128, 128))
    d = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=14)
    for i, k in enumerate(keys):
        x, y = gap + (i % cols) * (cell + gap), gap + (i // cols) * (cell + gap + lab)
        im = Image.open(out / mf["sleeves"][k]["file"]).convert("RGB").resize((cell, cell), Image.LANCZOS)
        canvas.paste(im, (x, y))
        d.text((x, y + cell + 2), k, fill=(20, 20, 20), font=font)
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest)
    print(f"sleeve sheet: {dest} ({canvas.width}x{canvas.height})")


def sheet(mf: dict, out: Path, dest: Path, scale: float = 0.5) -> None:
    """Every asset at its on-screen size (half its file pixels) on mid-grey, with labels, and the ground tiled 2x2."""
    items: list[tuple[str, Image.Image]] = []

    def add(label: str, rel: str, s: float = scale) -> None:
        im = Image.open(out / rel).convert("RGBA")
        items.append((label, im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)))

    for k, m in mf.get("machines", {}).items():
        add(f"machine {k}", m["file"])
    if "gramophone" in mf:
        add("gramophone", mf["gramophone"]["file"])
    if "portal" in mf:
        add("portal", mf["portal"]["file"])
    for k, h in mf.get("hero", {}).items():
        add(f"hero {k}", h["file"])
        for i, w in enumerate(h.get("walk", [])):
            add(f"walk {i + 1}", w["file"])
    if "title" in mf:
        add("title", mf["title"]["file"])
    for key in ("sets", "edge", "rugs", "props"):
        for p in mf.get(key, []):
            add(p["id"], p["file"])
    for k, a in mf.get("artifacts", {}).items():
        add(k, a["file"])
    if "path" in mf:
        add("path", mf["path"]["file"])
    W, gap, lab = 1800, 18, 16
    font = ImageFont.load_default(size=14) if hasattr(ImageFont, "load_default") else None
    rows, row, x, rh = [], [], gap, 0
    for label, im in items:
        if x + im.width + gap > W and row:
            rows.append((row, rh))
            row, x, rh = [], gap, 0
        row.append((x, label, im))
        x += im.width + gap
        rh = max(rh, im.height + lab)
    if row:
        rows.append((row, rh))
    panels = [m for m in mf.get("machines", {}).values() if m.get("panel")]
    ph = 520
    tile = 280
    H = (gap + sum(rh + gap for _, rh in rows) + (ph + gap + lab if panels else 0)
         + (2 * tile + gap + lab if mf.get("ground") else 0))
    canvas = Image.new("RGB", (W, H), (128, 128, 128))
    d = ImageDraw.Draw(canvas)
    y = gap
    for row, rh in rows:
        for x, label, im in row:
            canvas.paste(im, (x, y + rh - lab - im.height), im)
            d.text((x, y + rh - lab + 1), label, fill=(20, 20, 20), font=font)
        y += rh + gap
    if panels:
        x = gap
        for k, m in mf["machines"].items():
            if m.get("panel"):
                im = Image.open(out / m["panel"]).convert("RGB")
                im = im.resize((round(im.width * ph / im.height), ph), Image.LANCZOS)
                canvas.paste(im, (x, y))
                d.text((x, y + ph + 1), f"panel {k}", fill=(20, 20, 20), font=font)
                x += im.width + gap
        y += ph + gap + lab
    x = gap
    for g in mf.get("ground", []):
        im = Image.open(out / g["file"]).convert("RGB").resize((tile, tile), Image.LANCZOS)
        for dx in (0, 1):
            for dy in (0, 1):
                canvas.paste(im, (x + dx * tile, y + dy * tile))
        d.text((x, y + 2 * tile + 1), f"{g['id']} (2x2, seams at the middle)", fill=(20, 20, 20), font=font)
        x += 2 * tile + gap
        if x + 2 * tile > W:
            break
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest)
    print(f"sheet: {dest} ({W}x{H})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan", type=Path)
    ap.add_argument("--images", type=Path, default=DEFAULT_IMAGES)
    ap.add_argument("--only", default="", help="comma list: ground, path, props, props/<id>, machines/<k>, hero, ...")
    ap.add_argument("--sheet", type=Path, help="also write a contact sheet PNG here")
    ap.add_argument("--sleeve-sheet", type=Path, help="also write a sheet of the sleeves here")
    ap.add_argument("--no-build", action="store_true", help="only the sheets, from the manifest as it is")
    a = ap.parse_args()
    plan = json.loads(a.plan.read_text())
    out = (a.plan.parent / plan["out"]).resolve()
    if a.no_build:
        mf = json.loads((out / "manifest.json").read_text())
    else:
        only = {s.strip() for s in a.only.split(",") if s.strip()} or None
        mf = build(plan, out, a.images.expanduser(), only)
    if a.sheet:
        sheet(mf, out, a.sheet.expanduser())
    if a.sleeve_sheet:
        sleeve_sheet(mf, out, a.sleeve_sheet.expanduser())


if __name__ == "__main__":
    sys.exit(main())
