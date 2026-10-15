// The Rummage, laid out (docs/rummage.md): a junk market on layered paper. The Gramophone stands at the heart, in
// the north, its three plinth dishes facing you; the three machines stand round a crossroads to the west, the east
// and the south-west, with a signpost; the tear back to The Wasteland is at the south entrance. Torn-paper paths
// join them, bric-a-brac lines the paths like stalls, stands about in the open and piles up round the edge, and
// scraps, buttons and stamps lie on the ground. Everything comes from one seed, so it is the same place every visit.
// A world unit is a CSS px at zoom 1.
//
//   region(assets)          the layout: { W, H, edge, gram, machines, portal, sign, easel, hub, start, out, things, solids, places,
//                           paths, pieces, patches, mats, rugs, decals, corners, resolve, blocked }
//   resolve(x, y, r)        a point pushed out of every solid and back inside the ground: [x, y]
//   tear(pts, r, step, amp) a closed polygon with torn edges
import { rng } from '../concepts/model.js';
import { crop } from './art.js';

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
  const spots = { bed: [jit(300, 12), jit(1185, 12)], drums: [jit(1300, 20), jit(1330, 30)], bass: [jit(400, 10), jit(1990, 10)] };
  const machines = {};
  for (const part of PARTS) {
    const a = assets.machines[part];
    machines[part] = { kind: 'machine', id: part, part, asset: a, x: spots[part][0], y: spots[part][1], rot: (r() - 0.5) * 0.03, flip: false, r: a.foot * a.w };
  }
  const pt = assets.portal;
  const portal = { kind: 'portal', id: 'portal', asset: pt, x: jit(800, 16), y: H - EDGE - 96, rot: 0, flip: false, r: Math.min(60, pt.foot * pt.w) };
  const sign = { kind: 'sign', id: 'sign', asset: assets.sign, x: hub.x - 112, y: hub.y - 52, rot: -0.02, flip: false, r: Math.max(12, assets.sign.foot * assets.sign.w) };   // (set by the paths)
  const start = { x: portal.x, y: portal.y - pt.h * pt.anchor[1] - 90 };
  const out = { x: portal.x + 80, y: portal.y + 36 };     // where he lands, stepping out of the tear from The Wasteland
  // the easel beside the Gramophone, for the latest sleeve
  const ea = assets.easel;
  const easel = { kind: 'easel', id: 'easel', asset: ea, x: Math.round(gram.x + g.w * 0.62 + 40), y: gram.y + 30, rot: 0.03, flip: false, r: Math.max(14, ea.foot * ea.w) };

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
  // the corners of the market, and the aisles off the main paths that lead to them
  const CORNERS = [
    { id: 'reading', name: 'The reading nook', sub: 'books, a globe, a typewriter', set: 'bookshelf', rug: 'rug-rag', fam: 'reading', x: 262, y: 520 },
    { id: 'parlour', name: 'The parlour corner', sub: 'clocks, a chair, a lamp', set: 'dresser', rug: 'rug-oriental', fam: 'parlour', x: 1335, y: 615 },
    { id: 'music', name: 'The record corner', sub: 'records, cassettes, a radio', set: 'pram', rug: 'rug-quilt', fam: 'music', x: 215, y: 1610 },
    { id: 'kitchen', name: 'The kitchen corner', sub: 'tins, teapots, a can pyramid', set: 'can-pyramid', rug: 'rug-doormat', fam: 'kitchen', x: 1262, y: 1965 },
  ];
  const [rd, pa, , ki] = CORNERS;
  route(gram.x - 10, gram.y + 330, rd.x + 160, rd.y + 80, 18);
  route(gram.x + 10, gram.y + 330, pa.x - 160, pa.y + 80, 18);
  route(portal.x + 12, ki.y + 40, ki.x - 160, ki.y + 20, 14);
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
  // the signpost stands at the crossroads, in the angle between the paths that leaves it most room
  let roomiest = -1;
  for (let k = 0; k < 16; k++) {
    const a = (k / 16) * Math.PI * 2, x = hub.x + Math.cos(a) * 118, y = hub.y + Math.sin(a) * 96, room = toPath(x, y);
    if (room > roomiest) { roomiest = room; Object.assign(sign, { x: Math.round(x), y: Math.round(y) }); }
  }

  // --- the ground: the region's sheet, patches of other stuff, mats under the landmarks, and small things ---
  const floor = assets.floor ?? { big: ['cork', 'newsprint', 'fabric', 'tin', 'card', 'wood', 'map'], small: ['map'] };
  // the ground runs out under the side walls, so their ragged ends show cork, not the table
  const edge = sheet(rect(W / 2, H / 2, W - (assets.edge?.length ? 16 : EDGE * 2), H - EDGE * 2), r, 15, 7, 5);
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
  const KINDS = ['scrap', 'button', 'stamp', 'screw', 'string', 'tack', 'button', 'leaf', 'stamp', 'string'];
  for (let i = 0; i < 170; i++) {
    decals.push({ x: EDGE + 20 + r() * (W - 2 * EDGE - 40), y: EDGE + 20 + r() * (H - 2 * EDGE - 40), kind: KINDS[Math.floor(r() * KINDS.length)], a: r() * 6.28, s: 0.7 + r() * 0.6, c: Math.floor(r() * 8), n: Math.floor(r() * 1e6) });
  }

  // --- what stands. A junk market with places: the machines stand alone, with room round them, so they read as
  // megaliths; the Gramophone's doily is the plaza; four corners each have a rug, a set piece and things of one kind;
  // a few tall set pieces are landmarks seen from afar; stalls and small clusters of one kind line the paths; the
  // same thing is never twice within a screen; and walls of junk close the border, the tear in a gap in the south.
  // what is kept clear, as ellipses [x, y, rx, ry]: the plaza is its doily; a machine keeps the ground round its
  // tall sprite and in front of its face
  const keep = [
    [gram.x, gram.y + 40, gFoot + 236, gFoot + 156],
    [hub.x, hub.y, 150, 130], [portal.x, portal.y - 60, 140, 140],                // the crossroads: just the signpost [start.x, start.y, 60, 60], [out.x, out.y, 60, 60], [easel.x, easel.y, 80, 80],
    ...PARTS.map((part) => { const m = machines[part]; return [m.x, m.y - 60, m.r + 80, m.r + 120]; }),
  ];
  // Seen from the front and a little above, a thing's anchor is the front of its base. What it stands on is a disc
  // behind that point (so the wanderer can come up to its face and pass close behind it), or, for the wide set
  // pieces and the walls, the art's `block`: a rectangle centred on the anchor, rising from it.
  const solidOf = (t) => {
    const whole = t.asset.whole ?? t.asset, b = whole.block;
    if (b) { const bw = b[0] * whole.w, bh = b[1] * whole.h; return { rect: true, x0: t.x - bw / 2, x1: t.x + bw / 2, y0: t.y - bh, y1: t.y, of: t.id }; }
    return t.r > 0 ? { x: t.x, y: t.y - t.r * 0.55, r: t.r * 0.75, of: t.id } : null;
  };
  const twins = new Map();                                                 // id -> where each one stands
  const stand = (t) => {
    things.push(t);
    const sol = solidOf(t);
    if (sol) solids.push(sol);
    if (!twins.has(t.id)) twins.set(t.id, []);
    twins.get(t.id).push([t.x, t.y]);
    return t;
  };
  [gram, ...PARTS.map((q) => machines[q]), portal, sign, easel].forEach(stand);
  const away = (x, y, sol) => (sol.rect ? Math.hypot(x - Math.min(sol.x1, Math.max(sol.x0, x)), y - Math.min(sol.y1, Math.max(sol.y0, y))) : Math.hypot(x - sol.x, y - sol.y) - sol.r);
  // never twice on one screen: a phone's screen shows about 520 x 1000 of the world
  const twinSeen = (id, x, y) => (twins.get(id) ?? []).some(([px, py]) => Math.abs(px - x) < 560 && Math.abs(py - y) < 1040);
  const why = { bounds: 0, keep: 0, solid: 0, twin: 0, path: 0, ok: 0, spots: [] };   // what stopped a placement (to tune by)
  const no = (x, y, reason) => { why[reason]++; why.spots.push([Math.round(x), Math.round(y), reason]); return false; };
  const fits = (id, x, y, rad, gap = 28, fromPath = 52) => {
    if (x < EDGE + rad + 40 || x > W - EDGE - rad - 40 || y < EDGE + rad + 90 || y > H - EDGE - rad - 70) return no(x, y, 'bounds');
    for (const [kx, ky, kx2, ky2] of keep) if (((x - kx) / (kx2 + rad)) ** 2 + ((y - ky) / (ky2 + rad)) ** 2 < 1) return no(x, y, 'keep');
    for (const sol of solids) if (away(x, y, sol) < rad + gap) return no(x, y, 'solid');
    if (twinSeen(id, x, y)) return no(x, y, 'twin');
    if (toPath(x, y) <= fromPath + rad) return no(x, y, 'path');
    why.ok++;
    return true;
  };
  const radOf = (a) => Math.max(10, a.foot * a.w);
  const put = (a, x, y, kind = 'prop', more = {}) => stand({
    kind, id: a.id, asset: a, x: Math.round(x), y: Math.round(y), rot: Math.round((r() - 0.5) * 6) * 0.0105, flip: r() < 0.5, r: radOf(a), ...more,
  });

  // the walls round the border: junk strips side by side, their ragged ends overlapping, stacked down the sides
  const walls = assets.edge ?? [];
  if (walls.length) {
    let i = Math.floor(r() * walls.length);
    // down the sides only a wall's inner end shows: those stand as that end alone (a canvas a third the size)
    const ends = new Map();
    const endOf = (a, side) => { const k = `${a.id}${side}`; if (!ends.has(k)) ends.set(k, side < 0 ? crop(a, 0.5, 1) : crop(a, 0, 0.5)); return ends.get(k); };
    const wall = (x, y, flip, side = 0) => {
      const w0 = walls[i++ % walls.length], a = side ? endOf(w0, flip ? -side : side) : w0;
      stand({ kind: 'wall', id: w0.id, asset: a, x: Math.round(x), y: Math.round(y), rot: 0, flip, still: true, r: 0 });
    };
    for (const x of [-150, 330, 800, 1270, 1750]) wall(x + jit(0, 20), EDGE + 70, r() < 0.5);
    // down the sides, each side runs through all four, set in or out a little so a different end shows each time;
    // each side keeps them one way round (four poses a side, not eight: each is a big canvas)
    let left = Math.floor(r() * walls.length), right = left + 2;
    for (let y = 330; y < H - 220; y += 184) {
      i = left++; wall(-150 + jit(0, 50), y + jit(0, 12), false, -1);
      i = right++; wall(W + 150 + jit(0, 50), y + 92 + jit(0, 12), true, 1);
    }
    i = left;
    const gap = 150;                                                       // the tear stands in a gap in the south wall
    for (const x of [-150, portal.x - gap - 260, portal.x + gap + 260, 1750]) wall(x, H - EDGE + 6, r() < 0.5);
  }
  const pileEdge = !walls.length;                                          // without the art's walls, junk piled instead

  // the families of things, so they gather by kind
  const FAMILIES = {
    parlour: ['chair', 'floor-lamp', 'mantel-clock', 'cuckoo-clock', 'rocking-horse', 'dolls-house', 'birdcage', 'clock', 'lamp'],
    music: ['record-stack', 'record-crate', 'cassettes', 'radio', 'television', 'trumpet', 'accordion', 'telephone'],
    kitchen: ['teapot', 'tin-cans', 'watering-can', 'buttons', 'sewing-basket', 'sewing-machine', 'kettle', 'oilcan'],
    reading: ['books', 'globe', 'typewriter', 'oil-lamp'],
    travel: ['suitcases', 'hatboxes', 'umbrella', 'bicycle-wheel', 'toy-robot', 'suitcase', 'wheel', 'crate', 'boot'],
    garden: ['fern', 'birdbath', 'watering-can', 'bicycle-wheel', 'birdcage'],
  };
  const byId = new Map(assets.props.map((a) => [a.id, a]));
  const family = Object.fromEntries(Object.entries(FAMILIES).map(([f, ids]) => [f, ids.filter((id) => byId.has(id))]));
  const known = new Set(Object.values(FAMILIES).flat());
  family.misc = assets.props.map((a) => a.id).filter((id) => !known.has(id));
  const shuffled = (ids) => { const d = ids.slice(); for (let i = d.length - 1; i > 0; i--) { const j = Math.floor(r() * (i + 1)); [d[i], d[j]] = [d[j], d[i]]; } return d; };
  /** One of a family that fits at (x, y), placed; null if none does. */
  const one = (fam, x, y, gap = 16, fromPath = 52) => {
    for (const id of shuffled(family[fam] ?? [])) {
      const a = byId.get(id);
      if (fits(id, x, y, radOf(a), gap, fromPath)) return put(a, x, y);
    }
    return null;
  };

  // the set pieces: landmarks seen from afar, and a stall on each of the two main aisles
  const sets = new Map((assets.sets ?? []).map((a) => [a.id, a]));
  const setAt = (id, x, y, flip = r() < 0.5) => (sets.has(id) ? put(sets.get(id), x, y, 'set', { flip, rot: (r() - 0.5) * 0.02 }) : null);
  setAt('case-tower', 545, 300);
  setAt('carousel-horse', 1080, 1075);
  setAt('phone-box', 1010, 1885, false);                                 // by the entrance: the first thing you see
  setAt('heap', 170, 2232);
  setAt('stall', 650, 2160, true);
  setAt('stall', 615, 1010, true);

  // the corners: a rug, a set piece behind it, and things of one kind round it (CORNERS, with the paths)
  const rugs = [], corners = [];
  const rugArt = new Map((assets.rugs ?? []).map((g) => [g.id, g]));
  for (const c of CORNERS) {
    const g = rugArt.get(c.rug);
    if (g) rugs.push({ id: g.id, art: g, x: c.x, y: c.y + 6, w: g.w, h: g.h, a: (r() - 0.5) * 0.16, box: [c.x - g.w * 0.6, c.y - g.h * 0.6, c.x + g.w * 0.6, c.y + g.h * 0.6] });
    const piece = setAt(c.set, c.x + jit(0, 14), c.y - 78, r() < 0.5);
    corners.push({ ...c, piece });
    // round the rug's edges: left, right, the front corners, and beside the set piece
    for (const [dx, dy] of [[-150, -8], [152, 4], [-112, 92], [118, 86], [150, -96], [-150, -100]]) one(c.fam, c.x + dx + jit(0, 8), c.y + dy + jit(0, 8), 12, 40);
  }

  // the aisles: along each path, now one side, now the other, a small cluster of one kind; near a corner, its kind
  const order = shuffled(['travel', 'garden', 'music', 'parlour', 'kitchen', 'reading', 'misc', 'travel']);
  let turn = 0;
  const kindNear = (x, y) => corners.find((c) => Math.hypot(c.x - x, c.y - y) < 520)?.fam;
  const cluster = (pts, k, side, row = 0) => {
    const [x, y] = pts[k], [px, py] = pts[k - 3], [qx, qy] = pts[k + 3], l = Math.hypot(qx - px, qy - py) || 1;
    const ux = (qx - px) / l, uy = (qy - py) / l;
    const d = 112 + row * 120 + r() * 24, cx = x - uy * d * side, cy = y + ux * d * side;
    const fam = kindNear(cx, cy) ?? order[turn++ % order.length], n = 2 + (r() < 0.5 ? 1 : 0);
    let o = -(n - 1) * 46;
    for (let j = 0; j < n; j++) {
      const back = (j % 2) * 22 * side, t = one(fam, cx + ux * o - uy * back, cy + uy * o + ux * back, 10, 44);
      o += (t ? t.r : 30) * 2 + 18;                                    // the next one beside it, by its size
    }
  };
  paths.forEach((pts, p) => {
    let side = r() < 0.5 ? -1 : 1;
    for (let k = 6; k < pts.length - 5; k += 8 + Math.floor(r() * 4)) {
      // the main street, from the tear, has stalls on both sides; the others mostly on one, now this side, now that
      const both = p === 0 || r() < 0.4;
      side = r() < 0.7 ? -side : side;
      cluster(pts, k, side);
      if (both) cluster(pts, k, -side);
      if (r() < 0.35) cluster(pts, k, side, 1);                            // and a second row behind, here and there
    }
  });
  if (pileEdge) {
    const ring = [];
    for (let x = EDGE + 110; x < W - EDGE - 80; x += 120) ring.push([x, EDGE + 120], [x + 40, H - EDGE - 80]);
    for (let y = EDGE + 220; y < H - EDGE - 120; y += 120) ring.push([EDGE + 90, y], [W - EDGE - 90, y + 50]);
    for (const [x, y] of ring) one(order[turn++ % order.length], x, y, 4, 60) ?? one('misc', x, y, 4, 60);
  }
  // a few more clusters in the open, only where there is room to spare: the market thins out between places
  for (let i = 0; i < 40; i++) {
    const x = EDGE + 160 + r() * (W - 2 * EDGE - 320), y = EDGE + 220 + r() * (H - 2 * EDGE - 400);
    const fam = kindNear(x, y) ?? order[turn++ % order.length];
    if (!one(fam, x, y, 100, 100)) continue;
    one(fam, x + (r() < 0.5 ? -80 : 80), y + (r() - 0.5) * 30, 14, 90);
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
  // the corners name themselves too, though there is nothing to do there but look
  for (const c of corners) places.push({ id: c.id, name: c.name, sub: c.sub, x: c.x, y: (c.piece ? top(c.piece) : c.y - 160) - 6, at: [c.x, c.y], zone: 0, see: 230 });
  // the signpost points the way to each
  const arm = (text, t) => {
    const dx = t.x - hub.x, dy = t.y - hub.y;
    return { text, dir: dx < 0 ? -1 : 1, up: Math.abs(dx) < Math.abs(dy) * 0.5 ? (dy < 0 ? 1 : -1) : 0 };
  };
  assets.sign.arms = [
    arm('THE GRAMOPHONE', gram), arm('THE WIRELESS', machines.bed), arm('THE CLATTER', machines.drums), arm('THE BELLOWS', machines.bass),
  ];

  // --- walking: solids are discs and rectangles; the ground's edge is a wall behind the walls ---
  const CELL = 160, GW = Math.ceil(W / CELL), GH = Math.ceil(H / CELL);
  const grid = Array.from({ length: GW * GH }, () => []);
  for (const sol of solids) {
    const [x0, y0, x1, y1] = sol.rect ? [sol.x0, sol.y0, sol.x1, sol.y1] : [sol.x - sol.r, sol.y - sol.r, sol.x + sol.r, sol.y + sol.r];
    for (let j = Math.max(0, Math.floor((y0 - 40) / CELL)); j <= Math.min(GH - 1, Math.floor((y1 + 40) / CELL)); j++) {
      for (let i = Math.max(0, Math.floor((x0 - 40) / CELL)); i <= Math.min(GW - 1, Math.floor((x1 + 40) / CELL)); i++) grid[j * GW + i].push(sol);
    }
  }
  const near = (x, y) => grid[Math.min(GH - 1, Math.max(0, Math.floor(y / CELL))) * GW + Math.min(GW - 1, Math.max(0, Math.floor(x / CELL)))];
  const LIM = { x0: EDGE + 26, y0: EDGE + 40, x1: W - EDGE - 26, y1: H - EDGE - 22 };
  function resolve(x, y, rad = HERO_R) {
    for (let pass = 0; pass < 3; pass++) {
      let moved = false;
      for (const sol of near(x, y)) {
        if (sol.rect) {
          const cx = Math.min(sol.x1, Math.max(sol.x0, x)), cy = Math.min(sol.y1, Math.max(sol.y0, y)), dx = x - cx, dy = y - cy, d = Math.hypot(dx, dy);
          if (d >= rad) continue;
          if (d > 1e-3) { x = cx + (dx / d) * rad; y = cy + (dy / d) * rad; } else {
            // inside it: out by the nearest side
            const m = Math.min(x - sol.x0, sol.x1 - x, y - sol.y0, sol.y1 - y);
            if (m === x - sol.x0) x = sol.x0 - rad; else if (m === sol.x1 - x) x = sol.x1 + rad; else if (m === y - sol.y0) y = sol.y0 - rad; else y = sol.y1 + rad;
          }
          moved = true;
          continue;
        }
        const dx = x - sol.x, dy = y - sol.y, d = Math.hypot(dx, dy), min = sol.r + rad;
        if (d >= min) continue;
        const k = d > 1e-3 ? min / d : 0;
        if (k) { x = sol.x + dx * k; y = sol.y + dy * k; } else y = sol.y + min;
        moved = true;
      }
      x = Math.min(LIM.x1, Math.max(LIM.x0, x)); y = Math.min(LIM.y1, Math.max(LIM.y0, y));
      if (!moved) break;
    }
    return [x, y];
  }
  const blocked = (x, y, rad = HERO_R) => x < LIM.x0 || x > LIM.x1 || y < LIM.y0 || y > LIM.y1 || near(x, y).some((sol) => away(x, y, sol) < rad - 0.5);

  built = { assets, W, H, edge, gram, machines, portal, sign, easel, hub, start, out, things, solids, places, paths, pieces, patches, mats, rugs, decals, corners, resolve, blocked, near, LIM, why, keep };
  return built;
}
