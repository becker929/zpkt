// The Rummage, laid out (docs/rummage.md): a junk market on layered paper. The Gramophone stands at the heart, in
// the north, its three plinth dishes facing you; the three machines stand round a crossroads to the west, the east
// and the south-west, with a signpost; the tear back to The Wasteland is at the south entrance. Torn-paper paths
// join them, bric-a-brac lines the paths like stalls, stands about in the open and piles up round the edge, and
// scraps, buttons and stamps lie on the ground. Everything comes from one seed, so it is the same place every visit.
// A world unit is a CSS px at zoom 1.
//
//   region(assets)          the layout: { W, H, edge, gram, machines, portal, sign, hub, start, things, solids, places,
//                           paths, pieces, patches, mats, decals, resolve, blocked }
//   resolve(x, y, r)        a point pushed out of every solid and back inside the ground: [x, y]
//   tear(pts, r, step, amp) a closed polygon with torn edges
import { rng } from '../concepts/model.js';

export const W = 1600, H = 2400;
export const EDGE = 60;                 // the ground's torn edge, this far in from the region's bounds
export const HERO_R = 17;               // the wanderer's feet
export const SEED = 0x5c0001;
export const PARTS = ['bed', 'drums', 'bass'];
export const MACHINES = {
  bed: { name: 'The Wireless', what: 'the bed' },
  drums: { name: 'The Clatter', what: 'the drums' },
  bass: { name: 'The Bellows', what: 'the low end' },
};

/** A smooth wobble in about [-1, 1], from a few sines with seeded phases. */
function wobble(r) {
  const k = [0, 1, 2].map((i) => [r() * 6.283, (0.7 + r()) * (i + 1)]);
  return (t) => k.reduce((a, [p, f], i) => a + Math.sin(t * f * 3.1 + p) / (i + 1), 0) / 1.83;
}

/** A closed polygon with torn edges: each side cut into short steps that wander in and out by up to `amp`. */
export function tear(pts, r, step = 9, amp = 3) {
  const out = [];
  for (let i = 0; i < pts.length; i++) {
    const [x0, y0] = pts[i], [x1, y1] = pts[(i + 1) % pts.length];
    const len = Math.hypot(x1 - x0, y1 - y0) || 1, n = Math.max(1, Math.round(len / step));
    const nx = (y1 - y0) / len, ny = -(x1 - x0) / len;
    for (let k = 0; k < n; k++) {
      const t = k / n, j = (r() - 0.5) * 2 * amp * (k === 0 ? 0.4 : 1);
      out.push([x0 + (x1 - x0) * t + nx * j, y0 + (y1 - y0) * t + ny * j]);
    }
  }
  return out;
}
/** The corners of a w x h rectangle centred on (cx, cy), turned by a. */
export function rect(cx, cy, w, h, a = 0) {
  const c = Math.cos(a), s = Math.sin(a);
  return [[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]].map(([x, y]) => [cx + x * c - y * s, cy + x * s + y * c]);
}
/** A lumpy closed shape round (cx, cy): n points at radii rx, ry, each pulled in or out by up to `lump`. */
export function blob(cx, cy, rx, ry, n, r, lump = 0.22, a0 = 0) {
  return Array.from({ length: n }, (_, i) => {
    const a = a0 + (i / n) * Math.PI * 2, k = 1 + (r() - 0.5) * 2 * lump;
    return [cx + Math.cos(a) * rx * k, cy + Math.sin(a) * ry * k];
  });
}
/** Every point pushed out from the shape's middle by d. */
export function grow(pts, d) {
  const cx = pts.reduce((a, p) => a + p[0], 0) / pts.length, cy = pts.reduce((a, p) => a + p[1], 0) / pts.length;
  return pts.map(([x, y]) => { const l = Math.hypot(x - cx, y - cy) || 1; return [x + ((x - cx) / l) * d, y + ((y - cy) / l) * d]; });
}
const bbox = (pts) => {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const [x, y] of pts) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
  return [x0, y0, x1, y1];
};
/** A piece of paper: its torn shape and a slightly larger white edge round it (the cut). */
function sheet(pts, r, step, amp, edge = 3) {
  const inner = tear(pts, r, step, amp), outer = tear(grow(pts, edge), r, step * 0.8, amp * 0.8);
  return { inner, outer, box: bbox(outer) };
}

let built = null;
export function region(assets) {
  if (built && built.assets === assets) return built;
  const r = rng(SEED);
  const things = [], solids = [], places = [];

  // --- the landmarks, nudged a little by the seed ---
  const jit = (v, a) => Math.round(v + (r() - 0.5) * 2 * a);
  const hub = { x: jit(800, 20), y: jit(1460, 20) };
  const g = assets.gramophone, gFoot = g.foot * g.w;
  const gram = { kind: 'gram', id: 'gram', asset: g, x: jit(800, 10), y: jit(570, 10), rot: 0, flip: false, r: gFoot };
  const spots = { bed: [jit(300, 20), jit(1180, 30)], drums: [jit(1300, 20), jit(1330, 30)], bass: [jit(520, 20), jit(1950, 20)] };
  const machines = {};
  for (const part of PARTS) {
    const a = assets.machines[part];
    machines[part] = { kind: 'machine', id: part, part, asset: a, x: spots[part][0], y: spots[part][1], rot: (r() - 0.5) * 0.03, flip: false, r: a.foot * a.w };
  }
  const pt = assets.portal;
  const portal = { kind: 'portal', id: 'portal', asset: pt, x: jit(800, 16), y: H - EDGE - 96, rot: 0, flip: false, r: Math.min(60, pt.foot * pt.w) };
  const sign = { kind: 'sign', id: 'sign', asset: assets.sign, x: hub.x + 100, y: hub.y - 62, rot: -0.02, flip: false, r: Math.max(12, assets.sign.foot * assets.sign.w) };
  const start = { x: portal.x, y: portal.y - pt.h * pt.anchor[1] - 90 };

  // --- the paths: torn paper laid end to end, from the tear to the crossroads and out to each machine ---
  const paths = [];
  const route = (ax, ay, bx, by, wig = 46) => {
    const pts = [], n = Math.ceil(Math.hypot(bx - ax, by - ay) / 12);
    const len = Math.hypot(bx - ax, by - ay), nx = -(by - ay) / len, ny = (bx - ax) / len, w = wobble(r);
    for (let k = 0; k <= n; k++) {
      const t = k / n, off = w(t * 1.3) * wig * Math.sin(Math.PI * t);
      pts.push([ax + (bx - ax) * t + nx * off, ay + (by - ay) * t + ny * off]);
    }
    paths.push(pts);
    return pts;
  };
  const front = (m, d = 26) => [m.x, m.y + d];        // just in front of its base
  route(portal.x, portal.y - pt.h * 0.4, hub.x, hub.y + 30, 44);
  for (const part of PARTS) route(hub.x, hub.y, ...front(machines[part], 44), 34);
  route(hub.x, hub.y - 30, ...front(gram, 60), 36);
  const pieces = [];
  const aspect = assets.pathAspect ?? 0.5;
  for (const pts of paths) {
    let acc = 0;
    for (let k = 1; k < pts.length; k++) {
      acc += Math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1]);
      if (acc < 70 + r() * 14 && k < pts.length - 1) continue;
      acc = 0;
      const [x, y] = pts[k], [px, py] = pts[Math.max(0, k - 2)], [qx, qy] = pts[Math.min(pts.length - 1, k + 2)];
      const a = Math.atan2(qy - py, qx - px) + (r() - 0.5) * 0.18;
      const len = 118 + r() * 24, wid = Math.max(48, Math.min(62, len * aspect * 1.15));
      pieces.push({ ...sheet(rect(x, y, len, wid, a), r, 8, 3.4, 2.6), mat: r() < 0.72 ? 'cream' : r() < 0.6 ? 'newsprint' : 'map', a, x, y, len, wid, flip: r() < 0.5, n: Math.floor(r() * 1e6) });
    }
  }
  const pathPts = paths.flat();
  const toPath = (x, y) => {
    let best = Infinity;
    for (const [px, py] of pathPts) { const d = (px - x) ** 2 + (py - y) ** 2; if (d < best) best = d; }
    return Math.sqrt(best);
  };

  // --- the ground: the region's sheet, patches of other stuff, mats under the landmarks, and small things ---
  const floor = assets.floor ?? { big: ['cork', 'newsprint', 'fabric', 'tin', 'card', 'wood', 'map'], small: ['map'] };
  const edge = sheet(rect(W / 2, H / 2, W - EDGE * 2, H - EDGE * 2), r, 15, 7, 5);
  const patches = [];
  for (let i = 0; i < 18; i++) {
    const small = i % 3 === 2, rx = small ? 60 + r() * 60 : 150 + r() * 160, ry = rx * (0.55 + r() * 0.5);
    const x = EDGE + rx * 0.4 + r() * (W - 2 * EDGE - rx * 0.8), y = EDGE + ry * 0.4 + r() * (H - 2 * EDGE - ry * 0.8);
    const mats = small ? floor.small : floor.big;
    patches.push({ ...sheet(blob(x, y, rx, ry, 6 + Math.floor(r() * 3), r, 0.2, r() * 6), r, 11, 4.5), mat: mats[i % mats.length], a: r() * 6.28, n: Math.floor(r() * 1e6) });
  }
  const mats = [
    { ...sheet(blob(gram.x, gram.y + 40, gFoot + 230, gFoot + 150, 40, r, 0.015), r, 10, 1.6, 6), mat: 'doily', cx: gram.x, cy: gram.y + 40, rx: gFoot + 230, ry: gFoot + 150 },
    ...PARTS.map((part, i) => {
      const m = machines[part];
      return { ...sheet(blob(m.x, m.y + 30, m.r + 110, m.r + 70, 7, r, 0.12, r()), r, 10, 4), mat: floor.big[i % floor.big.length], a: r() * 6.28, n: i };
    }),
  ];
  const decals = [];
  const KINDS = ['scrap', 'button', 'stamp', 'ticket', 'screw', 'string', 'tack', 'button', 'leaf', 'stamp'];
  for (let i = 0; i < 170; i++) {
    decals.push({ x: EDGE + 20 + r() * (W - 2 * EDGE - 40), y: EDGE + 20 + r() * (H - 2 * EDGE - 40), kind: KINDS[Math.floor(r() * KINDS.length)], a: r() * 6.28, s: 0.7 + r() * 0.6, c: Math.floor(r() * 8), n: Math.floor(r() * 1e6) });
  }

  // --- what stands: the landmarks, then bric-a-brac along the paths, in the open, and piled round the edge ---
  const keep = [
    [gram.x, gram.y + 60, gFoot + 170], [hub.x, hub.y, 80], [portal.x, portal.y - 60, 170], [start.x, start.y, 70],
    ...PARTS.map((part) => { const m = machines[part]; return [m.x, m.y + 50, m.r + 130]; }),
  ];
  // Seen from the front and a little above, a thing's anchor is the front of its base: what it stands on is a disc
  // behind that point, so the wanderer can come up to its face and pass close behind it.
  const stand = (t) => {
    things.push(t);
    if (t.r > 0) solids.push({ x: t.x, y: t.y - t.r * 0.55, r: t.r * 0.75, of: t.id });
  };
  [gram, ...PARTS.map((q) => machines[q]), portal, sign].forEach(stand);
  const props = assets.props;
  const fits = (x, y, rad, gap = 28, fromPath = 52) => {
    if (x < EDGE + rad + 16 || x > W - EDGE - rad - 16 || y < EDGE + rad + 30 || y > H - EDGE - rad - 16) return false;
    for (const [kx, ky, kr] of keep) if (Math.hypot(x - kx, y - ky) < kr + rad) return false;
    for (const s of solids) if (Math.hypot(x - s.x, y - s.y) < s.r + rad + gap) return false;
    return toPath(x, y) > fromPath + rad;
  };
  // each prop in turn, so all of them are out somewhere before any comes round again
  let deck = [];
  const pick = () => {
    if (!deck.length) { deck = props.slice(); for (let i = deck.length - 1; i > 0; i--) { const j = Math.floor(r() * (i + 1)); [deck[i], deck[j]] = [deck[j], deck[i]]; } }
    return deck.pop();
  };
  const prop = (x, y, a) => {
    const t = { kind: 'prop', id: a.id, asset: a, x: Math.round(x), y: Math.round(y), rot: Math.round((r() - 0.5) * 6) * 0.0105, flip: r() < 0.5, r: Math.max(10, a.foot * a.w) };
    stand(t);
    return t;
  };
  // stalls: along each path, now one side, now the other
  for (const pts of paths) {
    for (let k = 8; k < pts.length - 6; k += 9 + Math.floor(r() * 4)) {
      const [x, y] = pts[k], [px, py] = pts[k - 2], l = Math.hypot(x - px, y - py) || 1;
      const side = r() < 0.5 ? -1 : 1, a = pick(), rad = Math.max(10, a.foot * a.w), d = 66 + rad + r() * 40;
      const cx = x + (-(y - py) / l) * d * side, cy = y + ((x - px) / l) * d * side;
      if (r() < 0.8 && fits(cx, cy, rad, 18, 52)) prop(cx, cy, a); else deck.push(a);
    }
  }
  // the open ground
  for (let i = 0; i < 1200 && things.length < 140; i++) {
    const a = pick(), rad = Math.max(10, a.foot * a.w);
    const x = EDGE + r() * (W - 2 * EDGE), y = EDGE + r() * (H - 2 * EDGE);
    if (fits(x, y, rad, 66, 90)) prop(x, y, a); else deck.unshift(a);
  }
  // piles round the edge
  const ring = [];
  for (let x = EDGE + 70; x < W - EDGE - 40; x += 112) ring.push([x, EDGE + 66], [x + 40, H - EDGE - 36]);
  for (let y = EDGE + 150; y < H - EDGE - 60; y += 112) ring.push([EDGE + 52, y], [W - EDGE - 52, y + 50]);
  for (const [x, y] of ring) {
    const a = pick(), rad = Math.max(10, a.foot * a.w);
    const nx = x + (r() - 0.5) * 40, ny = y + (r() - 0.5) * 30;
    if (fits(nx, ny, rad, 4, 70)) prop(nx, ny, a);
  }
  things.sort((a, b) => a.y - b.y);

  // --- the names of places, and where each one can be worked from ---
  const top = (t) => t.y - t.asset.h * t.asset.anchor[1];
  places.push({ id: 'gram', name: 'The Gramophone', sub: 'SH001 · the track’s machine', x: gram.x, y: top(gram) - 6, at: [gram.x, gram.y], zone: gFoot + 120, see: gFoot + 380 });
  for (const part of PARTS) {
    const m = machines[part];
    places.push({ id: part, name: MACHINES[part].name, sub: MACHINES[part].what, x: m.x, y: top(m) - 6, at: [m.x, m.y], zone: m.r + 70, see: m.r + 320 });
  }
  places.push({ id: 'portal', name: 'The tear', sub: 'back to The Wasteland', x: portal.x, y: top(portal) - 6, at: [portal.x, portal.y], zone: portal.r + 80, see: 320 });
  // the signpost points the way to each
  const arm = (text, t) => {
    const dx = t.x - hub.x, dy = t.y - hub.y;
    return { text, dir: dx < 0 ? -1 : 1, up: Math.abs(dx) < Math.abs(dy) * 0.5 ? (dy < 0 ? 1 : -1) : 0 };
  };
  assets.sign.arms = [
    arm('THE GRAMOPHONE', gram), arm('THE WIRELESS', machines.bed), arm('THE CLATTER', machines.drums), arm('THE BELLOWS', machines.bass),
  ];

  // --- walking: solids are circles, the ground's edge a wall ---
  const CELL = 160, GW = Math.ceil(W / CELL), GH = Math.ceil(H / CELL);
  const grid = Array.from({ length: GW * GH }, () => []);
  for (const s of solids) {
    for (let j = Math.max(0, Math.floor((s.y - s.r - 40) / CELL)); j <= Math.min(GH - 1, Math.floor((s.y + s.r + 40) / CELL)); j++) {
      for (let i = Math.max(0, Math.floor((s.x - s.r - 40) / CELL)); i <= Math.min(GW - 1, Math.floor((s.x + s.r + 40) / CELL)); i++) grid[j * GW + i].push(s);
    }
  }
  const near = (x, y) => grid[Math.min(GH - 1, Math.max(0, Math.floor(y / CELL))) * GW + Math.min(GW - 1, Math.max(0, Math.floor(x / CELL)))];
  const LIM = { x0: EDGE + 26, y0: EDGE + 40, x1: W - EDGE - 26, y1: H - EDGE - 22 };
  function resolve(x, y, rad = HERO_R) {
    for (let pass = 0; pass < 3; pass++) {
      let moved = false;
      for (const s of near(x, y)) {
        const dx = x - s.x, dy = y - s.y, d = Math.hypot(dx, dy), min = s.r + rad;
        if (d >= min) continue;
        const k = d > 1e-3 ? min / d : 0;
        if (k) { x = s.x + dx * k; y = s.y + dy * k; } else y = s.y + min;
        moved = true;
      }
      x = Math.min(LIM.x1, Math.max(LIM.x0, x)); y = Math.min(LIM.y1, Math.max(LIM.y0, y));
      if (!moved) break;
    }
    return [x, y];
  }
  const blocked = (x, y, rad = HERO_R) => x < LIM.x0 || x > LIM.x1 || y < LIM.y0 || y > LIM.y1 || near(x, y).some((s) => Math.hypot(x - s.x, y - s.y) < s.r + rad - 0.5);

  built = { assets, W, H, edge, gram, machines, portal, sign, hub, start, things, solids, places, paths, pieces, patches, mats, decals, resolve, blocked, near, LIM };
  return built;
}
