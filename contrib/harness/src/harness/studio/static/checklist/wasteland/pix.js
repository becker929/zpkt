// A 1-bit drawing surface for The Wasteland's art: everything is drawn by code, in white ink on black, with gold
// for what is alive or lit. A Pix is drawn into with a few primitives and then becomes a canvas the game blits.
//
//   const p = new Pix(w, h); p.line(...); p.ellipse(...); p.canvas()
//   sprite(key, w, h, draw)         a canvas drawn once and kept
//   bayer(x, y)                     the ordered-dither threshold at a world pixel, 0..15

export const NONE = 0, INK = 1, BLACK = 2, GOLD = 3, DIM = 4;
// the only other colours in the 1-bit world: the collage showing through the tear to The Rummage
export const KRAFT = 5, RED = 6, TEAL = 7, CREAM = 8;
const RGBA = [[0, 0, 0, 0], [255, 255, 255, 255], [0, 0, 0, 255], [241, 182, 74, 255], [92, 92, 92, 255],
  [185, 138, 90, 255], [210, 85, 63, 255], [62, 143, 138, 255], [239, 227, 200, 255]];

const B4 = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];
/** The 4x4 Bayer threshold at (x, y): a pixel is lit at tone t (0..16) when bayer(x, y) < t. */
export const bayer = (x, y) => B4[(y & 3) * 4 + (x & 3)];

export class Pix {
  constructor(w, h) { this.w = w; this.h = h; this.d = new Uint8Array(w * h); }
  set(x, y, c) {
    x = Math.round(x); y = Math.round(y);
    if (x >= 0 && y >= 0 && x < this.w && y < this.h) this.d[y * this.w + x] = c;
  }
  get(x, y) { return x >= 0 && y >= 0 && x < this.w && y < this.h ? this.d[y * this.w + x] : NONE; }
  rect(x, y, w, h, c) { for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) this.set(x + i, y + j, c); }
  frame(x, y, w, h, c) {
    for (let i = 0; i < w; i++) { this.set(x + i, y, c); this.set(x + i, y + h - 1, c); }
    for (let j = 0; j < h; j++) { this.set(x, y + j, c); this.set(x + w - 1, y + j, c); }
  }
  line(x0, y0, x1, y1, c) {
    x0 = Math.round(x0); y0 = Math.round(y0); x1 = Math.round(x1); y1 = Math.round(y1);
    const dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    let e = dx + dy;
    for (;;) {
      this.set(x0, y0, c);
      if (x0 === x1 && y0 === y1) break;
      const e2 = 2 * e;
      if (e2 >= dy) { e += dy; x0 += sx; }
      if (e2 <= dx) { e += dx; y0 += sy; }
    }
  }
  /** A filled ellipse; `edge` (if given) rings it. `wob(a)` bends the radius at angle a (a rock's lumps). */
  blob(cx, cy, rx, ry, fill, edge = null, wob = null) {
    const inside = (x, y) => {
      const dx = (x - cx) / rx, dy = (y - cy) / ry;
      const k = wob ? wob(Math.atan2(dy, dx)) : 1;
      return dx * dx + dy * dy <= k * k;
    };
    const x0 = Math.floor(cx - rx * 1.4), x1 = Math.ceil(cx + rx * 1.4), y0 = Math.floor(cy - ry * 1.4), y1 = Math.ceil(cy + ry * 1.4);
    for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
      if (!inside(x + 0.5, y + 0.5)) continue;
      const rim = edge != null && (!inside(x + 1.5, y + 0.5) || !inside(x - 0.5, y + 0.5) || !inside(x + 0.5, y + 1.5) || !inside(x + 0.5, y - 0.5));
      this.set(x, y, rim ? edge : fill);
    }
    return inside;
  }
  /** Lights the pixels inside `test` at tone t (0..16) with the ordered dither, aligned to world pixel (ox, oy). */
  dither(x, y, w, h, c, t, test = null, ox = 0, oy = 0) {
    for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
      const X = x + i, Y = y + j;
      if (test && !test(X + 0.5, Y + 0.5)) continue;
      if (bayer(X + ox, Y + oy) < t) this.set(X, Y, c);
    }
  }
  /** Puts a black ring round everything drawn, so a white sprite reads against white ground detail. */
  outline() {
    const src = this.d.slice();
    for (let y = 0; y < this.h; y++) for (let x = 0; x < this.w; x++) {
      if (src[y * this.w + x] !== NONE) continue;
      const n = (i, j) => i >= 0 && j >= 0 && i < this.w && j < this.h && src[j * this.w + i] !== NONE && src[j * this.w + i] !== BLACK;
      if (n(x + 1, y) || n(x - 1, y) || n(x, y + 1) || n(x, y - 1)) this.d[y * this.w + x] = BLACK;
    }
    return this;
  }
  /** Copies `src` (a Pix or rows of characters: '.' none, 'w' ink, 'k' black, 'g' gold) at (x, y), mirrored if asked. */
  stamp(src, x, y, flip = false) {
    if (Array.isArray(src)) {
      const map = { w: INK, k: BLACK, g: GOLD, d: DIM };
      src.forEach((row, j) => [...row].forEach((ch, i) => { if (map[ch]) this.set(x + (flip ? row.length - 1 - i : i), y + j, map[ch]); }));
      return;
    }
    for (let j = 0; j < src.h; j++) for (let i = 0; i < src.w; i++) {
      const c = src.d[j * src.w + i];
      if (c) this.set(x + (flip ? src.w - 1 - i : i), y + j, c);
    }
  }
  canvas() {
    const cv = document.createElement('canvas');
    cv.width = this.w; cv.height = this.h;
    const ctx = cv.getContext('2d');
    const img = ctx.createImageData(this.w, this.h);
    for (let i = 0; i < this.d.length; i++) {
      const c = RGBA[this.d[i]];
      img.data[i * 4] = c[0]; img.data[i * 4 + 1] = c[1]; img.data[i * 4 + 2] = c[2]; img.data[i * 4 + 3] = c[3];
    }
    ctx.putImageData(img, 0, 0);
    return cv;
  }
}

const sprites = new Map();
/** A sprite drawn once by `draw(pix)` and kept as a canvas under `key`. */
export function sprite(key, w, h, draw) {
  let s = sprites.get(key);
  if (!s) {
    const p = new Pix(w, h);
    draw(p);
    s = p.canvas();
    sprites.set(key, s);
  }
  return s;
}

// --- determinism (the same world every visit) ---
/** A 32-bit hash of integer coordinates and a salt. */
export function ihash(x, y, salt = 0) {
  let h = Math.imul(x | 0, 374761393) ^ Math.imul(y | 0, 668265263) ^ Math.imul(salt | 0, 2147483647);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return (h ^ (h >>> 16)) >>> 0;
}
export const ifrac = (x, y, salt = 0) => ihash(x, y, salt) / 4294967296;
/** Smooth value noise in [0, 1) with features about `scale` px across. */
export function noise(x, y, scale, salt = 0) {
  const X = x / scale, Y = y / scale, i = Math.floor(X), j = Math.floor(Y), fx = X - i, fy = Y - j;
  const u = fx * fx * (3 - 2 * fx), v = fy * fy * (3 - 2 * fy);
  const a = ifrac(i, j, salt), b = ifrac(i + 1, j, salt), c = ifrac(i, j + 1, salt), d = ifrac(i + 1, j + 1, salt);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}
/** Two octaves of value noise. */
export const fbm = (x, y, scale, salt = 0) => 0.65 * noise(x, y, scale, salt) + 0.35 * noise(x, y, scale / 2.3, salt + 17);
