// The Wasteland as a place to walk: the camp in the middle with the track's machine, the museum below it, and the
// seven sites of the spine on a ring around them, joined to the camp by worn paths. In the storm to the east, a tear:
// the way into The Rummage (docs/rummage.md). Between them, sand, dunes,
// cracked ground, rocks, dead trees, ruins, wrecks and a line of pylons; round the edge, the storm. Everything is
// drawn from a fixed seed, so it is the same place every visit (the map screen will draw from the same layout).
//
//   land()                         the layout: { W, H, camp, museum, sites, props, flats, wires, landmarks }
//   solidAt(x, y)                  whether a world px is blocked
//   edgeDist(x, y)                 how far a world px is inside the storm's edge
//   chunk(i, j)                    the ground under CHUNK px square (i, j), drawn on first ask
import { BLACK, DIM, INK, Pix, bayer, fbm, ifrac, noise } from './pix.js';
import { art } from './props.js';
import { rng } from '../concepts/model.js';

export const W = 1600, H = 1408, CX = 800, CY = 704;
export const CHUNK = 256;
export const EDGE = 44;             // the storm is a wall within this many px of the edge
export const HAZE = 136;            // and thickens from here
const G = 4;                        // the collision and path grids' cell, px

export const SITES = [
  { step: 'collage', n: 'I', name: 'The scrapyard', what: 'Audio collage' },
  { step: 'drums', n: 'II', name: 'The drum circle', what: 'Drums' },
  { step: 'arrange', n: 'III', name: 'The rail yard', what: 'Arrange' },
  { step: 'kick', n: 'IV', name: 'The drop hammer', what: 'Kick' },
  { step: 'mix', n: 'V', name: 'The tanks', what: 'Mix' },
  { step: 'master', n: 'VI', name: 'The mast', what: 'Master' },
  { step: 'release', n: 'VII', name: 'The gate', what: 'Release' },
];

const GW = W / G, GH = H / G;
const solid = new Uint8Array(GW * GH);
const path = new Uint8Array(GW * GH);
const clear = new Uint8Array(GW * GH);

export const edgeDist = (x, y) => Math.min(x, y, W - x, H - y) + (noise(x, y, 60, 9) - 0.5) * 36;
export const solidAt = (x, y) => {
  const i = Math.floor(x / G), j = Math.floor(y / G);
  return i < 0 || j < 0 || i >= GW || j >= GH || solid[j * GW + i] === 1;
};
const stamp = (grid, x, y, r) => {
  for (let j = Math.floor((y - r) / G); j <= Math.ceil((y + r) / G); j++) {
    for (let i = Math.floor((x - r) / G); i <= Math.ceil((x + r) / G); i++) {
      if (i < 0 || j < 0 || i >= GW || j >= GH) continue;
      if (Math.hypot((i + 0.5) * G - x, (j + 0.5) * G - y) <= r) grid[j * GW + i] = 1;
    }
  }
};
const block = (x, y, w, h) => {
  for (let j = Math.floor(y / G); j < Math.ceil((y + h) / G); j++) {
    for (let i = Math.floor(x / G); i < Math.ceil((x + w) / G); i++) if (i >= 0 && j >= 0 && i < GW && j < GH) solid[j * GW + i] = 1;
  }
};
const isClear = (x, y) => clear[Math.floor(y / G) * GW + Math.floor(x / G)] === 1;
const onPath = (x, y) => path[(y >> 2) * GW + (x >> 2)] === 1;

let built = null;
export function land() {
  if (built) return built;
  const r = rng(0x5eed);
  const props = [], flats = [], landmarks = [];
  const put = (type, x, y, variant = 0, extra = {}) => {
    const a = art(type, variant);
    const p = { type, variant, x: Math.round(x), y: Math.round(y), a, ...extra };
    for (const f of [a.foot, a.foot2]) if (f) block(p.x + f[0], p.y + f[1], f[2], f[3]);
    props.push(p);
    return p;
  };

  // --- the camp, the museum, the sites, and the paths between them ---
  const camp = { x: CX, y: CY, r: 84 };
  const museum = { x: CX, y: CY + 200 };
  const sites = SITES.map((s, i) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / SITES.length;
    return { ...s, i, x: Math.round(CX + Math.cos(a) * 570), y: Math.round(CY + Math.sin(a) * 480), a };
  });
  stamp(clear, camp.x, camp.y, camp.r);
  for (const s of sites) stamp(clear, s.x, s.y, 70);
  for (let x = museum.x - 70; x <= museum.x + 70; x += 8) for (let y = museum.y - 60; y <= museum.y + 30; y += 8) stamp(clear, x, y, 10);

  const paths = [];
  const route = (ax, ay, bx, by, salt, wiggle = 34) => {
    const pts = [], n = Math.ceil(Math.hypot(bx - ax, by - ay) / 10);
    const nx = -(by - ay), ny = bx - ax, nl = Math.hypot(nx, ny);
    for (let k = 0; k <= n; k++) {
      const t = k / n, off = (noise(t * 4, salt, 1, 21) - 0.5) * 2 * wiggle * Math.sin(Math.PI * t);
      pts.push([ax + (bx - ax) * t + (nx / nl) * off, ay + (by - ay) * t + (ny / nl) * off]);
    }
    for (let k = 0; k < pts.length - 1; k++) {
      const [x0, y0] = pts[k], [x1, y1] = pts[k + 1], m = Math.ceil(Math.hypot(x1 - x0, y1 - y0) / 2);
      for (let q = 0; q <= m; q++) {
        const x = x0 + ((x1 - x0) * q) / m, y = y0 + ((y1 - y0) * q) / m;
        stamp(path, x, y, 6 + noise(x, y, 30, 22) * 3);
        stamp(clear, x, y, 18);
      }
    }
    paths.push(pts);
  };
  sites.forEach((s, i) => route(CX + Math.cos(s.a) * 40, CY + Math.sin(s.a) * 34, s.x - Math.cos(s.a) * 24, s.y - Math.sin(s.a) * 20, i + 1));
  route(CX, CY + 40, museum.x, museum.y + 8, 40, 6);
  // a tear in the storm to the east, past the rail yard: the way into The Rummage (a region of its own, SH001)
  const tear = { x: 1448, y: 1010 };
  route(sites[2].x - 10, sites[2].y + 24, tear.x - 26, tear.y + 4, 77, 18);
  stamp(clear, tear.x, tear.y, 46);

  // --- the storm round the edge ---
  for (let j = 0; j < GH; j++) for (let i = 0; i < GW; i++) if (edgeDist((i + 0.5) * G, (j + 0.5) * G) < EDGE) solid[j * GW + i] = 1;

  // --- the camp ---
  const machine = put('machine', CX, CY - 6);
  put('stones', CX - 32, CY + 34);
  const fire = { x: CX - 32, y: CY + 31 };
  put('tent', CX + 40, CY + 38, 1);
  put('crate', CX + 62, CY + 6, 1); put('crate', CX + 70, CY + 14, 2); put('crate', CX + 58, CY + 16, 3);
  landmarks.push({ id: 'machine', name: 'HW002', sub: 'The track machine', x: machine.x, y: machine.y - 46, r: 70 });

  // --- the museum ---
  const hall = put('museum', museum.x, museum.y);
  landmarks.push({ id: 'museum', name: 'The museum', sub: 'Every plate, hung', x: hall.x, y: hall.y - 82, r: 100 });

  put('tear', tear.x, tear.y);
  landmarks.push({ id: 'rummage', name: 'The Rummage', sub: 'A tear in the storm · SH001', x: tear.x, y: tear.y - 64, r: 90 });

  // --- the sites ---
  const lights = [{ x: machine.x, y: machine.y - 42, kind: 'lamp' }];
  for (const s of sites) {
    let top = 46;
    const at = (dx, dy) => [s.x + dx, s.y + dy];
    if (s.step === 'collage') {
      put('heap', ...at(-28, 4), 1); put('heap', ...at(18, -12), 2); put('heap', ...at(-2, 26), 3); put('crane', ...at(34, 24));
      top = 64;
    } else if (s.step === 'drums') {
      for (let k = 0; k < 9; k++) { const a = (k / 9) * Math.PI * 2 + 0.3; put('drum', ...at(Math.cos(a) * 30, Math.sin(a) * 20 + 4), k); }
      lights.push({ x: s.x, y: s.y + 2, kind: 'fire' });
      put('stones', s.x, s.y + 6);
    } else if (s.step === 'arrange') {
      flats.push({ x: s.x - 120, y: s.y + 4, w: 240, h: 9, draw: rails });
      for (let x = s.x - 120; x <= s.x + 120; x += 8) stamp(clear, x, s.y + 8, 14);
      put('boxcar', ...at(-30, 12), 1); put('boxcar', ...at(30, 12), 2);
      top = 30;
    } else if (s.step === 'kick') {
      flats.push({ x: s.x - 46, y: s.y - 30, w: 92, h: 62, draw: crater });
      put('press', ...at(0, 8));
      lights.push({ x: s.x, y: s.y - 14, kind: 'spark' });
      top = 52;
    } else if (s.step === 'mix') {
      flats.push({ x: s.x - 40, y: s.y - 6, w: 80, h: 20, draw: pipes });
      put('tank', ...at(-26, 4), 1); put('tank', ...at(2, -8), 2); put('tank', ...at(28, 6), 3);
      top = 50;
    } else if (s.step === 'master') {
      put('mast', ...at(0, 14));
      lights.push({ x: s.x, y: s.y + 14 - 79, kind: 'beacon' });
      top = 84;
    } else if (s.step === 'release') {
      put('gate', ...at(0, 12));
      top = 52;
    }
    landmarks.push({ id: s.step, name: s.name, sub: `${s.n} · ${s.what}`, x: s.x, y: s.y - top, r: 92, site: s });
  }

  // --- ruins: tumbled foundations, wall blocks on a grid ---
  const ruins = [];
  for (let tries = 0; ruins.length < 16 && tries < 400; tries++) {
    const x = 120 + r() * (W - 240), y = 120 + r() * (H - 240);
    const w = 4 + Math.floor(r() * 6), h = 3 + Math.floor(r() * 4);
    const x0 = Math.round(x / 8) * 8, y0 = Math.round(y / 8) * 8;
    let ok = edgeDist(x0, y0) > HAZE && edgeDist(x0 + w * 8, y0 + h * 8) > HAZE;
    for (let j = -1; ok && j <= h + 1; j++) for (let i = -1; i <= w + 1; i++) if (isClear(x0 + i * 8, y0 + j * 8)) { ok = false; break; }
    if (!ok || ruins.some((q) => Math.abs(q.x - x0) < 140 && Math.abs(q.y - y0) < 120)) continue;
    ruins.push({ x: x0, y: y0 });
    const door = Math.floor(r() * w);
    for (let i = 0; i < w; i++) for (const j of [0, h]) {
      if ((j === h && i === door) || r() < 0.22) continue;
      put('wall', x0 + i * 8 + 4, y0 + j * 8, Math.floor(r() * 4) + (j === h ? 0 : 1));
    }
    for (let j = 1; j < h; j++) for (const i of [0, w - 1]) if (r() > 0.25) put('wall', x0 + i * 8 + 4, y0 + j * 8, Math.floor(r() * 4));
    stamp(clear, x0 + (w * 8) / 2, y0 + (h * 8) / 2, Math.max(w, h) * 4 + 8);
  }

  // --- the pylons, marching across ---
  const pylons = [];
  for (let k = 0; k < 12; k++) {
    const x = 70 + k * 136, y = 520 + k * 62 + (noise(k, 0, 1, 30) - 0.5) * 30;
    if (edgeDist(x, y) < HAZE - 30 || isClear(x, y) || isClear(x, y - 8)) { pylons.push(null); continue; }
    pylons.push(put('pylon', x, y));
  }
  const wires = [];
  for (let k = 0; k < pylons.length - 1; k++) {
    const a = pylons[k], b = pylons[k + 1];
    if (!a || !b) continue;
    for (const [dx, dy] of a.a.tops) wires.push({ x0: a.x + dx, y0: a.y + dy, x1: b.x + dx, y1: b.y + dy, sag: 12 });
  }

  // --- scattered: rocks, dead trees, wrecks ---
  const step = 22;
  for (let gy = 0; gy < H; gy += step) for (let gx = 0; gx < W; gx += step) {
    const x = gx + (ifrac(gx, gy, 31) - 0.5) * 18, y = gy + (ifrac(gx, gy, 32) - 0.5) * 18;
    if (edgeDist(x, y) < EDGE + 10 || isClear(x, y)) continue;
    const p = ifrac(gx, gy, 33), rock = fbm(x, y, 260, 1), tree = fbm(x, y, 220, 2);
    const shape = Math.floor(ifrac(gx, gy, 34) * 10) * 3;              // a rock's variant: its size is variant % 3
    if (rock > 0.56 && p < (rock - 0.5) * 2.4) put('rock', x, y, shape + (rock > 0.68 ? 2 : Math.floor(ifrac(gx, gy, 39) * 2)));
    else if (tree > 0.6 && p < 0.42) put('tree', x, y, Math.floor(ifrac(gx, gy, 35) * 12));
    else if (p < 0.04) put('rock', x, y, shape);
    else if (p < 0.055) put('tree', x, y, 20 + Math.floor(ifrac(gx, gy, 37) * 8));
    else if (p < 0.062) put('wreck', x, y, Math.floor(ifrac(gx, gy, 38) * 4));
  }

  // the props, bucketed for drawing
  const B = 128, bw = Math.ceil(W / B), bh = Math.ceil(H / B);
  const buckets = Array.from({ length: bw * bh }, () => []);
  for (const p of props) buckets[Math.min(bh - 1, Math.floor(p.y / B)) * bw + Math.min(bw - 1, Math.floor(p.x / B))].push(p);
  const near = (x0, y0, x1, y1) => {
    const out = [];
    for (let j = Math.max(0, Math.floor(y0 / B)); j <= Math.min(bh - 1, Math.floor(y1 / B)); j++) {
      for (let i = Math.max(0, Math.floor(x0 / B)); i <= Math.min(bw - 1, Math.floor(x1 / B)); i++) out.push(...buckets[j * bw + i]);
    }
    return out;
  };

  built = { W, H, camp, museum, sites, tear, props, flats, wires, landmarks, lights, fire, paths, near, start: { x: CX + 4, y: CY + 52 } };
  return built;
}

// --- flat things drawn into the ground ---
function rails(p, ox, oy, f) {
  for (let x = f.x; x < f.x + f.w; x++) {
    if (x % 5 === 0) for (let y = f.y; y < f.y + 9; y++) p.set(x - ox, y - oy, DIM);
    p.set(x - ox, f.y + 2 - oy, INK); p.set(x - ox, f.y + 6 - oy, INK);
  }
}
function crater(p, ox, oy, f) {
  const cx = f.x + f.w / 2, cy = f.y + f.h / 2;
  for (let y = f.y; y < f.y + f.h; y++) for (let x = f.x; x < f.x + f.w; x++) {
    const d = Math.hypot((x - cx) / (f.w / 2), (y - cy) / (f.h / 2));
    if (d > 1) continue;
    if (d > 0.9) { if (bayer(x, y) < 10) p.set(x - ox, y - oy, INK); }
    else if (d > 0.78) { if (bayer(x, y) < 3 && y > cy) p.set(x - ox, y - oy, INK); }
    else p.set(x - ox, y - oy, BLACK);
  }
}
function pipes(p, ox, oy, f) {
  for (let x = f.x; x < f.x + f.w; x++) {
    const y = f.y + 8 + Math.round(Math.sin((x - f.x) / 9) * 2);
    p.set(x - ox, y - oy, INK); p.set(x - ox, y + 3 - oy, INK);
    if (x % 12 === 0) for (let k = 0; k < 4; k++) p.set(x - ox, y + k - oy, INK);
  }
}

// --- the ground ---
const chunks = new Map();
/** The ground of chunk (i, j) as a canvas: storm, paths, sand, dunes, cracks, small litter, flat things. */
export function chunk(i, j) {
  const key = i * 1000 + j;
  let c = chunks.get(key);
  if (c) return c;
  const L = land();
  const ox = i * CHUNK, oy = j * CHUNK, p = new Pix(CHUNK, CHUNK);
  for (let by = 0; by < CHUNK; by += 4) for (let bx = 0; bx < CHUNK; bx += 4) {
    const X = ox + bx, Y = oy + by;
    if (X >= W || Y >= H) continue;
    const e = edgeDist(X + 2, Y + 2);
    const sand = 0.003 + 0.02 * fbm(X, Y, 180, 4) ** 2;
    const dune = fbm(X, Y, 230, 6), crack = fbm(X, Y, 210, 10);
    const pathHere = onPath(X, Y);
    for (let y = Y; y < Y + 4; y++) for (let x = X; x < X + 4; x++) {
      // the ground is quiet (grey, sparse) so what stands on it reads; the storm and the litter are white
      let c = 0;
      if (e < HAZE) {
        const tone = Math.min(15, Math.max(0, ((HAZE - e) / (HAZE - EDGE + 30)) * 15 + (noise(x, y, 14, 40) - 0.5) * 5));
        if (bayer(x, y) < tone) c = tone > 9 ? INK : DIM;
      }
      if (!c && pathHere) { if (bayer(x, y) === 0 || (bayer(x, y) === 8 && ifrac(x, y, 41) < 0.3)) c = DIM; }
      else if (!c) {
        const f = ifrac(x, y, 5);
        if (f < sand) c = f < sand * 0.18 ? INK : DIM;
        else if (dune > 0.64) {
          const v = y + 3.4 * Math.sin(x * 0.085 + noise(x, y, 90, 7) * 6);
          if (Math.floor(v) % 9 === 0 && ifrac(x >> 2, y, 8) < (dune - 0.64) * 3) c = DIM;
        } else if (crack > 0.68 && cracked(x, y) && ifrac(x >> 1, y >> 1, 42) < 0.7) c = DIM;
      }
      if (c) p.d[(y - oy) * CHUNK + (x - ox)] = c;
    }
  }
  // litter: tufts, bones, pebbles, one tile in a few
  for (let ty = oy; ty < oy + CHUNK; ty += 8) for (let tx = ox; tx < ox + CHUNK; tx += 8) {
    const f = ifrac(tx, ty, 11);
    if (f > 0.05 || onPath(tx, ty) || edgeDist(tx, ty) < HAZE - 20) continue;
    const x = tx - ox + Math.floor(ifrac(tx, ty, 12) * 5), y = ty - oy + Math.floor(ifrac(tx, ty, 13) * 5);
    if (f < 0.022) { p.set(x, y, INK); p.set(x + 1, y - 1, INK); p.set(x + 2, y, INK); p.set(x + 3, y - 2, INK); p.set(x + 4, y, INK); }
    else if (f < 0.028) { p.line(x, y, x + 4, y + 1, INK); p.set(x - 1, y - 1, INK); p.set(x - 1, y + 1, INK); p.set(x + 5, y, INK); p.set(x + 5, y + 2, INK); }
    else { p.set(x, y, INK); p.set(x + 1, y, INK); p.set(x, y - 1, DIM); }
  }
  for (const f of L.flats) if (f.x < ox + CHUNK && f.x + f.w > ox && f.y < oy + CHUNK && f.y + f.h > oy) f.draw(p, ox, oy, f);
  c = p.canvas();
  chunks.set(key, c);
  return c;
}

// cracked ground: the edges of a Voronoi tiling
function cracked(x, y) {
  const S = 22, ci = Math.floor(x / S), cj = Math.floor(y / S);
  let d1 = 1e9, d2 = 1e9;
  for (let j = cj - 1; j <= cj + 1; j++) for (let i = ci - 1; i <= ci + 1; i++) {
    const px = (i + 0.15 + ifrac(i, j, 50) * 0.7) * S, py = (j + 0.15 + ifrac(i, j, 51) * 0.7) * S;
    const d = Math.hypot(px - x, py - y);
    if (d < d1) { d2 = d1; d1 = d; } else if (d < d2) d2 = d;
  }
  return d2 - d1 < 1.1;
}

