// The things standing in The Wasteland, drawn in 1-bit by code (pix.js): rocks, dead trees, ruined walls, wrecks,
// pylons, and the structures of the camp, the museum and the seven sites. Lit from the top left; shade is dithered.
//
// art(type, variant) -> { img, ax, ay, foot: [x, y, w, h], tops? }
//   img: the sprite's canvas; (ax, ay): the anchor (the middle of the base) inside it; foot: the solid part, relative
//   to the anchor, in px; tops: points relative to the anchor (a pylon's wire hooks, a lamp)
import { BLACK, DIM, GOLD, INK, NONE, Pix } from './pix.js';
import { rng } from '../concepts/model.js';

const cache = new Map();
export function art(type, variant = 0) {
  const key = `${type}:${variant}`;
  let a = cache.get(key);
  if (!a) {
    a = DRAW[type](rng(variant * 7919 + type.length * 104729 + type.charCodeAt(0)), variant);
    a.img = a.pix.canvas();
    delete a.pix;
    cache.set(key, a);
  }
  return a;
}

// shade a region's lower-right with dither: the light comes from the top left
function shade(p, test, cx, cy, t = 5, ox = 0) {
  for (let y = 0; y < p.h; y++) for (let x = 0; x < p.w; x++) {
    if (p.get(x, y) !== BLACK || !test(x + 0.5, y + 0.5)) continue;
    if ((x - cx) * 0.6 + (y - cy) > 1 && ((x + ox + y * 2) % 4 === 0 || (t > 6 && (x + y) % 2 === 0))) p.set(x, y, INK);
  }
}
const lattice = (p, x0, y0, x1, y1, w0, w1, steps) => {
  // a tapering lattice tower from (x0, y0) at the base to (x1, y1) at the top, w0 and w1 wide
  const L = (t) => [x0 - w0 / 2 + (x1 - w1 / 2 - (x0 - w0 / 2)) * t, y0 + (y1 - y0) * t];
  const R = (t) => [x0 + w0 / 2 + (x1 + w1 / 2 - (x0 + w0 / 2)) * t, y0 + (y1 - y0) * t];
  p.line(...L(0), ...L(1), INK); p.line(...R(0), ...R(1), INK);
  for (let i = 0; i < steps; i++) {
    const a = i / steps, b = (i + 1) / steps;
    p.line(...L(a), ...R(b), INK); p.line(...R(a), ...L(b), INK);
    p.line(...L(b), ...R(b), INK);
  }
};

const DRAW = {
  rock(r, v) {
    const s = 1 + (v % 3), rx = 3 + s * 3 + r() * 2, ry = rx * (0.62 + r() * 0.15);
    const w = Math.ceil(rx * 2 + 6), h = Math.ceil(ry * 2 + 8), cx = w / 2, cy = h - ry - 3;
    const p = new Pix(w, h);
    const k = [r(), r(), r(), r()];
    const wob = (a) => 1 + 0.12 * Math.sin(a * 2 + k[0] * 6) + 0.08 * Math.sin(a * 3 + k[1] * 6) - (Math.sin(a) > 0.4 ? 0.1 : 0);
    const inside = p.blob(cx, cy, rx, ry, BLACK, INK, wob);
    shade(p, inside, cx, cy, 5, v);
    // a crack and a glint
    const a0 = k[2] * Math.PI;
    p.line(cx - Math.cos(a0) * rx * 0.3, cy - ry * 0.3, cx + Math.cos(a0) * rx * 0.2, cy + ry * 0.2, INK);
    p.set(cx - rx * 0.45, cy - ry * 0.5, INK); p.set(cx - rx * 0.45 + 1, cy - ry * 0.5, INK);
    return { pix: p.outline(), ax: Math.round(cx), ay: Math.round(cy + ry * 0.7), foot: [-rx + 1, -ry * 0.8, rx * 2 - 2, ry * 1.1] };
  },
  tree(r, v) {
    const w = 30, h = 34, bx = 15, by = 32;
    const p = new Pix(w, h);
    const tall = 14 + r() * 8;
    const branch = (x, y, a, len, depth) => {
      const x1 = x + Math.cos(a) * len, y1 = y + Math.sin(a) * len;
      p.line(x, y, x1, y1, INK);
      if (depth >= 3 || len < 3) return;
      const n = depth === 0 ? 3 : 2;
      for (let i = 0; i < n; i++) branch(x1, y1, a + (r() - 0.5) * 1.6, len * (0.55 + r() * 0.2), depth + 1);
    };
    p.line(bx, by, bx, by - 3, INK); p.line(bx + 1, by, bx + 1, by - 5, INK);
    branch(bx, by - 2, -Math.PI / 2 + (r() - 0.5) * 0.4, tall * 0.55, 0);
    p.set(bx - 2, by, INK); p.set(bx + 3, by, INK);
    return { pix: p.outline(), ax: bx, ay: by, foot: [-2, -2, 5, 3] };
  },
  wall(r, v) {
    // one 8 px block of ruined wall: a top and a brick face; blocks side by side make a wall
    const hgt = 4 + (v % 4) * 2 + Math.floor(r() * 2);
    const w = 8, h = hgt + 6, p = new Pix(w, h);
    p.rect(0, 0, 8, 5, BLACK); p.dither(0, 0, 8, 5, INK, 6);
    p.line(0, 0, 7, 0, INK);
    p.rect(0, 5, 8, hgt, BLACK);
    p.line(0, 5, 7, 5, INK);
    for (let y = 8; y < 5 + hgt; y += 3) {
      p.line(0, y, 7, y, INK);
      const off = (y / 3) % 2 ? 1 : 5;
      p.set(off, y - 1, INK); p.set(off, y - 2, INK);
    }
    if (r() < 0.5) { p.set(Math.floor(r() * 8), 0, NONE); p.set(Math.floor(r() * 8), 1, NONE); }
    return { pix: p, ax: 4, ay: h - 1, foot: [-4, -6, 8, 6] };
  },
  wreck(r, v) {
    const w = 30, h = 20, p = new Pix(w, h);
    // the body, its cab and windows, three wheels showing; tipped a little
    p.rect(2, 7, 26, 9, BLACK); p.frame(2, 7, 26, 9, INK);
    p.rect(8, 2, 13, 6, BLACK); p.frame(8, 2, 13, 6, INK);
    p.rect(10, 4, 4, 3, BLACK); p.frame(10, 3, 4, 4, INK); p.frame(15, 3, 4, 4, INK);
    p.dither(3, 8, 24, 7, INK, 3);
    for (const x of [6, 22]) p.blob(x, 16, 3, 3, BLACK, INK);
    p.line(3, 11, 27, 11, INK);
    if (v % 2) { p.rect(24, 7, 4, 4, NONE); p.line(24, 7, 27, 10, INK); }
    return { pix: p.outline(), ax: 15, ay: 18, foot: [-13, -9, 26, 9] };
  },
  pylon() {
    const w = 26, h = 46, p = new Pix(w, h), bx = 13, by = 45;
    lattice(p, bx, by, bx, 6, 10, 3, 6);
    p.line(bx - 11, 10, bx + 11, 10, INK); p.line(bx - 8, 15, bx + 8, 15, INK);
    p.line(bx - 11, 10, bx - 2, 6, INK); p.line(bx + 11, 10, bx + 2, 6, INK);
    for (const x of [bx - 11, bx + 11, bx - 8, bx + 8]) p.set(x, x === bx - 11 || x === bx + 11 ? 11 : 16, INK);
    p.line(bx, 6, bx, 2, INK);
    return { pix: p.outline(), ax: bx, ay: by, foot: [-5, -3, 10, 4], tops: [[-11, -34], [11, -34], [-8, -29], [8, -29]] };
  },
  drum(r, v) {
    const w = 9, h = 13, p = new Pix(w, h);
    p.rect(0, 2, 9, 9, BLACK);
    p.line(0, 2, 0, 10, INK); p.line(8, 2, 8, 10, INK);
    p.blob(4, 2, 4, 1.6, BLACK, INK); p.blob(4, 10.5, 4, 1.6, BLACK, INK);
    p.rect(1, 3, 7, 7, BLACK); p.line(1, 5, 7, 5, INK); p.line(1, 8, 7, 8, INK);
    p.dither(5, 3, 3, 7, INK, 7);
    if (v % 3 === 1) p.set(3, 1, INK);
    return { pix: p.outline(), ax: 4, ay: 11, foot: [-4, -3, 9, 4] };
  },
  heap(r, v) {
    const w = 38, h = 22, p = new Pix(w, h), cx = 19, cy = 20;
    const inside = p.blob(cx, cy, 17, 14, BLACK, INK, (a) => (Math.sin(a) > 0 ? 0.01 : 1 + 0.1 * Math.sin(a * 5 + v)));
    shade(p, inside, cx, cy - 8, 5, v);
    for (let i = 0; i < 9; i++) {
      const x = 6 + r() * 26, y = 9 + r() * 9, a = r() * Math.PI, l = 3 + r() * 6;
      if (r() < 0.3) p.frame(Math.round(x), Math.round(y), 4, 3, INK);
      else if (r() < 0.2) p.blob(x, y, 2.2, 2.2, BLACK, INK);
      else p.line(x, y, x + Math.cos(a) * l, y - Math.sin(a) * l, INK);
    }
    p.line(cx + 3, 8, cx + 9, 1, INK); p.line(cx + 9, 1, cx + 11, 2, INK);       // a pipe sticking out
    return { pix: p.outline(), ax: cx, ay: cy, foot: [-15, -8, 30, 8] };
  },
  crane() {
    const w = 52, h = 60, p = new Pix(w, h), bx = 12, by = 58;
    p.rect(bx - 6, by - 7, 12, 7, BLACK); p.frame(bx - 6, by - 7, 12, 7, INK); p.dither(bx - 5, by - 6, 10, 5, INK, 4);
    lattice(p, bx, by - 7, bx, 14, 7, 5, 6);
    // the boom out to the right, and the hook hanging from it
    p.line(bx - 2, 14, 48, 4, INK); p.line(bx + 2, 18, 48, 6, INK);
    for (let i = 0; i < 6; i++) { const x = bx + 4 + i * 6; p.line(x, 16 - i * 1.6, x + 3, 13 - i * 1.8, INK); }
    p.line(46, 6, 46, 30, INK); p.frame(44, 30, 5, 3, INK); p.set(46, 33, INK);
    return { pix: p.outline(), ax: bx, ay: by, foot: [-6, -6, 12, 6] };
  },
  boxcar(r, v) {
    const w = 36, h = 20, p = new Pix(w, h);
    p.rect(1, 1, 34, 14, BLACK); p.frame(1, 1, 34, 14, INK); p.line(1, 3, 34, 3, INK);
    for (let x = 5; x < 34; x += 4) p.line(x, 4, x, 13, INK);
    p.rect(14, 5, 8, 9, BLACK); p.frame(14, 5, 8, 9, INK); p.line(14, 5, 21, 13, INK);
    p.dither(2, 4, 32, 10, INK, 2);
    for (const x of [6, 11, 25, 30]) p.blob(x, 16, 2.2, 2.2, BLACK, INK);
    return { pix: p.outline(), ax: 18, ay: 18, foot: [-17, -8, 34, 8] };
  },
  press() {
    // the kick pit's drop hammer: two pillars, a beam, the weight hanging over an anvil
    const w = 40, h = 46, p = new Pix(w, h), cx = 20, by = 44;
    for (const x of [5, 31]) { p.rect(x, 6, 5, by - 6, BLACK); p.frame(x, 6, 5, by - 6, INK); p.dither(x + 2, 7, 2, by - 8, INK, 6); }
    p.rect(2, 2, 36, 6, BLACK); p.frame(2, 2, 36, 6, INK); p.line(3, 5, 36, 5, INK);
    p.line(cx, 8, cx, 16, INK);
    p.rect(cx - 7, 16, 14, 10, BLACK); p.frame(cx - 7, 16, 14, 10, INK); p.dither(cx - 6, 17, 12, 8, INK, 5);
    p.rect(cx - 9, by - 8, 18, 8, BLACK); p.frame(cx - 9, by - 8, 18, 8, INK); p.line(cx - 12, by - 8, cx + 12, by - 8, INK);
    p.dither(cx - 8, by - 7, 16, 6, INK, 3);
    return { pix: p.outline(), ax: cx, ay: by, foot: [-17, -9, 34, 9], tops: [[0, -22]] };
  },
  tank(r, v) {
    const w = 24, h = 32, p = new Pix(w, h), cx = 12;
    p.rect(2, 8, 20, 20, BLACK);
    p.line(2, 8, 2, 27, INK); p.line(21, 8, 21, 27, INK);
    p.blob(cx, 8, 10, 6, BLACK, INK, (a) => (Math.sin(a) > 0.05 ? 0.01 : 1));
    p.blob(cx, 28, 10, 2.5, BLACK, INK);
    p.rect(3, 9, 18, 19, BLACK);
    for (const y of [13, 20]) for (let x = 4; x < 21; x += 3) p.set(x, y, INK);
    p.dither(14, 9, 7, 19, INK, 6);
    p.line(5, 8, 5, 27, INK); p.line(8, 8, 8, 27, INK);
    for (let y = 10; y < 27; y += 3) p.line(5, y, 8, y, INK);                    // the ladder
    return { pix: p.outline(), ax: cx, ay: 29, foot: [-10, -6, 20, 7] };
  },
  mast() {
    const w = 60, h = 82, p = new Pix(w, h), bx = 30, by = 80;
    lattice(p, bx, by, bx, 8, 8, 2, 12);
    p.line(bx, 8, bx, 2, INK);
    for (const [gx, ty] of [[2, 30], [58, 30], [8, 55], [52, 55]]) p.line(bx + (gx < bx ? -1 : 1), ty, gx, by - 2, DIM);
    p.rect(bx - 4, by - 3, 9, 3, INK);
    return { pix: p.outline(), ax: bx, ay: by, foot: [-5, -4, 10, 4], tops: [[0, -79]] };
  },
  gate() {
    const w = 64, h = 52, p = new Pix(w, h), by = 50;
    for (const x of [4, 50]) {
      p.rect(x, 10, 10, by - 10, BLACK); p.frame(x, 10, 10, by - 10, INK);
      for (let y = 14; y < by; y += 4) p.line(x, y, x + 9, y, INK);
      p.dither(x + 5, 11, 4, by - 12, INK, 6);
    }
    p.rect(0, 2, 64, 9, BLACK); p.frame(0, 2, 64, 9, INK); p.line(1, 4, 62, 4, INK);
    p.dither(1, 5, 62, 5, INK, 2);
    p.rect(22, 0, 20, 3, INK);
    return { pix: p.outline(), ax: 32, ay: by, foot: [-28, -6, 10, 6], foot2: [18, -6, 10, 6] };
  },
  machine() {
    // the track's machine at the camp: a cabinet with two speaker cones, a row of knobs, a screen, a lamp on top
    const w = 56, h = 44, p = new Pix(w, h), cx = 28, by = 42;
    p.rect(4, 8, 48, 34, BLACK); p.frame(4, 8, 48, 34, INK);
    p.rect(2, 6, 52, 4, BLACK); p.frame(2, 6, 52, 4, INK);
    p.dither(5, 11, 46, 30, INK, 1);
    for (const x of [15, 41]) { p.blob(x, 30, 8, 8, BLACK, INK); p.blob(x, 30, 4.5, 4.5, BLACK, INK); p.set(x, 30, INK); }
    p.rect(20, 12, 16, 9, BLACK); p.frame(20, 12, 16, 9, INK);
    // HW002 in a 3x5 face, on the screen
    const G = { H: ['w.w', 'w.w', 'www', 'w.w', 'w.w'], W: ['w.w', 'w.w', 'w.w', 'www', 'w.w'], 0: ['www', 'w.w', 'w.w', 'w.w', 'www'], 2: ['ww.', '..w', '.w.', 'w..', 'www'] };
    // the screen is 14 px inside: H W 0 0 2 at 3 px each with no gap won't fit; show "002" and a bar under it
    [...'002'].forEach((ch, i) => p.stamp(G[ch], 22 + i * 4, 14));
    p.line(34, 14, 34, 18, GOLD);
    for (let x = 8; x < 50; x += 5) if (x < 20 || x > 36) p.blob(x, 15, 1.5, 1.5, BLACK, INK);
    p.line(cx, 6, cx, 1, INK);
    p.rect(8, 41, 4, 2, INK); p.rect(44, 41, 4, 2, INK);
    return { pix: p.outline(), ax: cx, ay: by, foot: [-25, -14, 50, 14], tops: [[0, -42]] };
  },
  museum() {
    // a hall with columns and a pediment; its door is dark
    const w = 112, h = 78, p = new Pix(w, h), cx = 56, by = 76;
    // steps
    for (let i = 0; i < 3; i++) { p.rect(4 + i * 3, by - 3 - i * 3, 104 - i * 6, 3, BLACK); p.line(4 + i * 3, by - 3 - i * 3, 107 - i * 3, by - 3 - i * 3, INK); }
    p.dither(4, by - 9, 104, 9, INK, 2);
    // the wall behind the columns, and the door
    p.rect(14, 26, 84, 42, BLACK); p.dither(14, 26, 84, 42, INK, 1);
    p.rect(cx - 7, 40, 14, 28, BLACK); p.frame(cx - 8, 39, 16, 29, INK);
    // the columns
    for (let i = 0; i < 6; i++) {
      const x = 12 + i * 17 + (i >= 3 ? 4 : 0);
      if (Math.abs(x + 3 - cx) < 12) continue;
      p.rect(x, 26, 7, 42, BLACK); p.line(x, 26, x, 67, INK); p.line(x + 6, 26, x + 6, 67, INK);
      p.line(x + 2, 28, x + 2, 66, INK); p.dither(x + 4, 27, 2, 40, INK, 6);
      p.rect(x - 1, 24, 9, 2, INK); p.rect(x - 1, 67, 9, 1, INK);
    }
    // the frieze and the pediment
    p.rect(6, 16, 100, 8, BLACK); p.frame(6, 16, 100, 8, INK); p.dither(7, 18, 98, 5, INK, 3);
    for (let y = 0; y < 14; y++) {
      const half = (y / 14) * 50;
      p.set(cx - half, 2 + y, INK); p.set(cx + half, 2 + y, INK);
      for (let x = cx - half + 1; x < cx + half; x++) if (y === 13 || (x + y) % 5 === 0 && y > 4) p.set(x, 2 + y, y === 13 ? INK : DIM);
    }
    p.blob(cx, 10, 3, 3, BLACK, GOLD);
    return { pix: p.outline(), ax: cx, ay: by, foot: [-52, -22, 104, 22], tops: [[0, -66]] };
  },
  tent(r, v) {
    const w = 28, h = 20, p = new Pix(w, h);
    for (let y = 0; y < 16; y++) {
      const half = 1 + y * 0.8;
      p.set(14 - half, 2 + y, INK); p.set(14 + half, 2 + y, INK);
      for (let x = Math.ceil(14 - half) + 1; x < 14 + half; x++) p.set(x, 2 + y, (x > 14 && (x + y) % 3 === 0) ? INK : BLACK);
    }
    p.line(1, 17, 27, 17, INK);
    for (let y = 9; y < 17; y++) { const half = (y - 9) * 0.5; for (let x = Math.ceil(14 - half); x <= 14 + half; x++) p.set(x, y, BLACK); }
    p.line(14, 1, 14, 17, INK); p.line(14, 2, 10, 0, INK);
    return { pix: p.outline(), ax: 14, ay: 18, foot: [-12, -6, 24, 6] };
  },
  crate(r, v) {
    const p = new Pix(10, 11);
    p.rect(0, 3, 10, 8, BLACK); p.frame(0, 3, 10, 8, INK); p.line(0, 3, 9, 10, INK); p.line(9, 3, 0, 10, INK);
    p.rect(0, 0, 10, 4, BLACK); p.frame(0, 0, 10, 4, INK); p.dither(1, 1, 8, 2, INK, 8);
    return { pix: p.outline(), ax: 5, ay: 10, foot: [-5, -5, 10, 5] };
  },
  stones() {
    // the fire's ring, low enough to read as flat
    const p = new Pix(16, 9);
    for (let i = 0; i < 8; i++) { const a = (i / 8) * Math.PI * 2; p.blob(8 + Math.cos(a) * 6, 4.5 + Math.sin(a) * 3, 1.6, 1.2, BLACK, INK); }
    return { pix: p, ax: 8, ay: 6, foot: [-5, -4, 10, 4] };
  },
};
