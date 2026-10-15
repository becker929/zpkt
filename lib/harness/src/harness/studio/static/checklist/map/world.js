// The map with The Wasteland around it. The track is a walled base in the middle: each step a region of rooms, one
// room per item, as in the flow's map (../flow/juice/map.js). Outside the wall, beside each region on its outer side,
// lies that step's zone of The Wasteland. Each item has ONE find out there (finds.js), relevant to the item: when the
// item is checked, a trail runs from its room out through the wall to the find, the fog lifts around it and the find
// can be opened and used. When a step clears, its whole zone opens and its cache (a bigger unlock) rises. Unfound
// finds show as faint signals through the fog: something is out there. Nothing is locked: the finds entice, and
// release never waits on them. Drawn from the done set alone: the same set always draws the same map.
//
//   world(data)                                  the layout, in world px (U px to a cell)
//   render(data, done, {id, view, fresh, taken}) the drawing's markup
//   roomRect(data, key)                          a room's rect in world px (the shell flies the checkbox into it)
//   mini(host, data, done, {fresh})              the header glyph
//   play(stage, {...})                           one commit, with a camera; resolves {unlocked}
//   explore(host, data, done, {...})             the full-screen map to look around and open finds
import { hash, rng } from '../concepts/model.js';
import { asSet, bump, ease, el, f, fadeIn, keyFor, lerp, tween, wait } from '../flow/juice/fx.js';
import { CACHES, FINDS, KINDS } from './finds.js';

export const label = 'Map';

const U = 20;                       // one cell, in world px
const SLOT_W = 5, SLOT_H = 2, GAP = 2, GAP_Y = 3;
const BX = 6.5, BY = 2;             // the base's inner corner, in cells
const BASE_W = 2 * SLOT_W + GAP, BASE_H = 4 * SLOT_H + 3 * GAP_Y;
const ZW = 5, ZH = 5;               // a zone of The Wasteland
const COLS = 25, ROWS = 21;         // near square, for the splash's square stage
const W = COLS * U, H = ROWS * U;
const WALL = { x: BX * U - 4, y: BY * U - 4, w: BASE_W * U + 8, h: BASE_H * U + 8 };
const POI_R = 18;                   // the fog lifted around a find

const zoneAt = (row, col) => ({ x: (col === 0 ? 0.5 : BX + BASE_W + 1) * U, y: (BY + row * (SLOT_H + GAP_Y) - 1.5) * U, w: ZW * U, h: ZH * U, left: col === 0 });

/** The whole layout, in world px: regions and rooms (cells, as in the flow's map), zones, finds, caches. */
export function world(data) {
  const regions = data.steps.map((step, s) => {
    const row = Math.floor(s / 2), col = row % 2 ? 1 - (s % 2) : s % 2;
    const n = step.items.length, cols = Math.ceil(n / 2);
    const sx = BX + col * (SLOT_W + GAP), sy = BY + row * (SLOT_H + GAP_Y);
    const ox = sx + (SLOT_W - cols) / 2;
    const rooms = step.items.map((it, k) => {
      const top = k < cols;
      const c = top ? k : 2 * cols - 1 - k;
      return { it, k, key: `${step.id}.${it.id}`, cx: ox + c, cy: sy + (top ? 0 : 1) };
    });
    return { step, s, row, col, sx, sy, x0: ox, x1: ox + cols, rooms, zone: zoneAt(row, col) };
  });
  const finds = [], caches = [];
  for (const g of regions) {
    const z = g.zone, r = rng(hash(`${data.track}|zone|${g.step.id}`));
    const cand = [];
    for (let j = 0; j < 5; j++) for (let i = 0; i < 4; i++) cand.push({ i, j, x: z.x + (0.62 + i * 1.25) * U, y: z.y + (0.6 + j * 0.95) * U });
    // the cache sits inside the zone, away from its edges; the finds keep clear of it and, where they can, of each other
    const mid = cand.filter((c) => c.i >= 1 && c.i <= 2 && c.j >= 1 && c.j <= 3);
    const cache = mid[Math.floor(r() * mid.length)];
    const near = (a, b, d) => Math.hypot(a.x - b.x, a.y - b.y) < d * U;
    const free = cand.filter((c) => !near(c, cache, 1.3));
    for (let i = free.length - 1; i > 0; i--) { const j = Math.floor(r() * (i + 1)); [free[i], free[j]] = [free[j], free[i]]; }
    const pick = [];
    for (const c of free) if (pick.length < g.rooms.length && !pick.some((p) => near(p, c, 1.3))) pick.push(c);
    for (const c of free) if (pick.length < g.rooms.length && !pick.includes(c)) pick.push(c);
    pick.sort((a, b) => a.y - b.y || (z.left ? a.x - b.x : b.x - a.x));
    const rooms = [...g.rooms].sort((a, b) => a.cy - b.cy || (z.left ? a.cx - b.cx : b.cx - a.cx));
    rooms.forEach((rm, n) => {
      const p = pick[n];
      finds.push({ key: rm.key, step: g.step.id, x: p.x + (r() - 0.5) * 3, y: p.y + (r() - 0.5) * 3, room: rm, g });
    });
    caches.push({ step: g.step.id, x: cache.x, y: cache.y, g });
  }
  return { regions, finds, caches, W, H, U, beyond: zoneAt(3, 1) };
}

const roomBox = (r) => ({ x: r.cx * U + 2, y: r.cy * U + 2, w: U - 4, h: U - 4 });
const holeBox = (r) => ({ x: r.cx * U, y: r.cy * U, w: U, h: U });
const rect = (b, cls, extra = '') => `<rect class="${cls}" x="${f(b.x)}" y="${f(b.y)}" width="${f(b.w)}" height="${f(b.h)}"${extra}/>`;
const area = (g) => ({ x: g.x0 * U - 6, y: g.sy * U - 6, w: (g.x1 - g.x0) * U + 12, h: SLOT_H * U + 12 });
export function roomRect(data, key) {
  const r = world(data).regions.flatMap((g) => g.rooms).find((x) => x.key === key);
  return r ? roomBox(r) : null;
}

function door(a, b) {
  if (a.cy === b.cy) return { x: Math.max(a.cx, b.cx) * U - 3, y: a.cy * U + U / 2 - 2, w: 6, h: 4 };
  return { x: a.cx * U + U / 2 - 2, y: Math.max(a.cy, b.cy) * U - 3, w: 4, h: 6 };
}
function corridor(g, next) {
  if (!next) return null;
  if (g.row === next.row) {
    const [l, r] = g.col < next.col ? [g, next] : [next, g];
    return { x: l.x1 * U + 6, y: (g.sy + 1) * U - 3, w: r.x0 * U - 6 - (l.x1 * U + 6), h: 6 };
  }
  return { x: (g.sx + SLOT_W / 2) * U - 3, y: (g.sy + SLOT_H) * U + 6, w: 6, h: (next.sy - g.sy - SLOT_H) * U - 12 };
}
/** The trail from a room out through the wall to its find: the part outside the region, and where it crosses the wall. */
function trail(fd) {
  const a = area(fd.g), left = fd.g.zone.left, dir = left ? -1 : 1;
  const ry = fd.room.cy * U + U / 2;
  const ex = left ? a.x : a.x + a.w;
  const wx = left ? WALL.x : WALL.x + WALL.w;
  const d = `M${f(ex)} ${f(ry)}H${f(wx)}C${f(wx + dir * 16)} ${f(ry)} ${f(fd.x - dir * 14)} ${f(fd.y)} ${f(fd.x)} ${f(fd.y)}`;
  return { d, wx, ry, inner: `M${f(fd.room.cx * U + U / 2)} ${f(ry)}H${f(ex)}` };
}

// the finds' glyphs, in a box about 10 across, centred on 0
const GLYPH = {
  raw: '<path class="wl-g-line" d="M-5 0h1.6l1.1-3.4 1.8 6.8 1.8-6.8 1.1 3.4H5"/>',
  collaged: '<path class="wl-g-line" d="M-4.6-4.6h5.4v5.4h-5.4zM-.8-.8h5.4v5.4H-.8z"/>',
  processed: '<path class="wl-g-line" d="M-4.6-3.2h6.4M-4.6 0h4.2M-4.6 3.2h6.4M2.2-1.6 4.6 0 2.2 1.6"/>',
  whole: '<path class="wl-g-fill" d="M0-4.8 4.8 0 0 4.8-4.8 0Z"/>',
  learned: '<path class="wl-g-line" d="M-5 0Q0-5 5 0Q0 5-5 0Z"/><circle class="wl-g-fill" r="1.5"/>',
};

function poi(fd, find, { fresh, taken }) {
  const cls = `wl-poi${fresh ? ' fresh' : ''}${taken ? ' taken' : ''}`;
  return `<g class="${cls}" data-key="${fd.key}" data-kind="${find.kind}" transform="translate(${f(fd.x)} ${f(fd.y)})">`
    + '<circle class="wl-hit" r="11"/><circle class="wl-poi-bg" r="7.5"/>'
    + `${taken ? '<circle class="wl-taken" r="10"/>' : ''}${GLYPH[find.kind]}</g>`;
}
function tag(fd, find) {
  const text = `UNLOCKED · ${KINDS[find.kind].label.toUpperCase()}`;
  const w = text.length * 4.1 + 10;
  // above the find, kept over its zone
  const z = fd.g.zone;
  const x = Math.min(Math.max(fd.x - w / 2, z.x - 6), z.x + z.w + 6 - w);
  const y = fd.y - 24;
  return `<g class="wl-tag" data-key="${fd.key}"><rect x="${f(x)}" y="${f(y)}" width="${f(w)}" height="12" rx="2"/>`
    + `<text x="${f(x + w / 2)}" y="${f(y + 8.4)}">${text}</text></g>`;
}
function signal(fd, delay) {
  return `<g class="wl-signal" data-key="${fd.key}" transform="translate(${f(fd.x)} ${f(fd.y)})">`
    + `<circle class="wl-hit" r="10"/><circle class="wl-sig-ring" r="5" style="animation-delay:${delay}s"/><circle class="wl-sig-dot" r="1.6"/></g>`;
}
function cacheMark(c, open) {
  const pts = Array.from({ length: 6 }, (_, i) => { const a = Math.PI / 6 + (i * Math.PI) / 3; return `${f(Math.cos(a) * 12)},${f(Math.sin(a) * 12)}`; }).join(' ');
  if (!open) return `<g class="wl-cache sealed" data-step="${c.step}" transform="translate(${f(c.x)} ${f(c.y)})"><polygon points="${pts}"/></g>`;
  return `<g class="wl-cache" data-step="${c.step}" transform="translate(${f(c.x)} ${f(c.y)})">`
    + `<circle class="wl-hit" r="15"/><circle class="wl-cache-glow" r="17"/><polygon class="wl-cache-hex" points="${pts}"/>`
    + `<path class="wl-cache-core" d="M0-6 6 0 0 6-6 0Z"/></g>`;
}

/** The terrain of the whole Wasteland: dotted contours, rocks and ruins, the same for the track every time. */
function terrain(data, L) {
  const r = rng(hash(`${data.track}|terrain`));
  const zones = [...L.regions.map((g) => g.zone), L.beyond];
  const out = [];
  for (const z of zones) {
    for (let c = 0; c < 2; c++) {
      const cx = z.x + z.w * (0.2 + r() * 0.6), cy = z.y + z.h * (0.2 + r() * 0.6);
      const ph = r() * 6.28, k = 2 + Math.floor(r() * 2);
      for (let ring = 1; ring <= 3; ring++) {
        const rad = 7 + ring * 7 + r() * 3;
        const pts = Array.from({ length: 18 }, (_, i) => {
          const a = (i / 18) * Math.PI * 2;
          const rr = rad * (1 + 0.18 * Math.sin(a * k + ph) + 0.08 * Math.sin(a * 5 + ph * 2));
          return `${f(cx + Math.cos(a) * rr * 1.25)} ${f(cy + Math.sin(a) * rr * 0.8)}`;
        });
        out.push(`<path class="wl-contour" d="M${pts.join('L')}Z"/>`);
      }
    }
    for (let k = 0; k < 6; k++) {
      const x = z.x + 6 + r() * (z.w - 12), y = z.y + 6 + r() * (z.h - 12), s = 1.6 + r() * 2.6;
      const pts = Array.from({ length: 5 }, (_, i) => { const a = (i / 5) * 6.28 + r(); const q = s * (0.7 + r() * 0.5); return `${f(x + Math.cos(a) * q)},${f(y + Math.sin(a) * q)}`; });
      out.push(`<polygon class="wl-rock" points="${pts.join(' ')}"/>`);
    }
    const rx = z.x + 10 + r() * (z.w - 34), ry = z.y + 10 + r() * (z.h - 30), rw = 12 + r() * 10, rh = 9 + r() * 7;
    out.push(`<path class="wl-ruin" d="M${f(rx)} ${f(ry + rh * 0.4)}V${f(ry)}H${f(rx + rw * 0.6)}M${f(rx + rw)} ${f(ry + rh * 0.3)}V${f(ry + rh)}H${f(rx + rw * 0.35)}"/>`);
  }
  return out.join('');
}

/** The drawing for a done set. `fresh`: finds to tag as just unlocked; `taken`: finds in the crate; `view`: a viewBox. */
export function render(data, done, { id = 'wl', view = null, fresh = new Set(), taken = new Set() } = {}) {
  done = asSet(done); fresh = asSet(fresh); taken = asSet(taken);
  const L = world(data);
  const isOn = (key) => done.has(key);
  const cleared = (g) => g.rooms.every((r) => isOn(r.key));

  const holes = [], floors = [], walls = [], doors = [], seen = [], labels = [], ways = [];
  const trails = [], breaches = [], pois = [], signals = [], tags = [], caches = [];
  L.regions.forEach((g, i) => {
    const next = L.regions[i + 1], prevClear = i === 0 || cleared(L.regions[i - 1]);
    if (cleared(g)) {
      const a = area(g);
      holes.push(rect(a, '', ' rx="6"'));
      floors.push(rect(a, 'mp-region', ' rx="6"'));
      labels.push(`<text class="mp-label" x="${f(a.x + a.w / 2)}" y="${f(a.y - 5)}">${g.step.n} ${g.step.name.toUpperCase()}</text>`);
      const c = corridor(g, next);
      if (c) { holes.push(rect(c, '')); ways.push(rect(c, 'mp-way')); }
      holes.push(rect({ x: g.zone.x - 4, y: g.zone.y - 2, w: g.zone.w + 8, h: g.zone.h + 4 }, '', ' rx="12"'));
    }
    g.rooms.forEach((r, k) => {
      const on = isOn(r.key);
      if (on) {
        holes.push(rect(holeBox(r), ''));
        walls.push(`<g class="mp-room" data-key="${r.key}">${rect(roomBox(r), 'mp-floor')}${r.it.gate ? `<path class="mp-dp" d="M${f(r.cx * U + 10)} ${f(r.cy * U + 6)} l4 4 -4 4 -4 -4 Z"/>` : ''}</g>`);
      }
      const nb = [g.rooms[k - 1], g.rooms[k + 1]].filter(Boolean);
      for (const o of nb) {
        if (o.k < r.k) continue;
        const a = on, b = isOn(o.key);
        if (a || b) doors.push(rect(door(r, o), `mp-door${a && b ? '' : ' frontier'}`, ` data-a="${r.key}" data-b="${o.key}"`));
      }
      const near = nb.some((o) => isOn(o.key)) || (k === 0 && prevClear);
      if (!on && near) seen.push(rect(roomBox(r), 'mp-seen', ` data-key="${r.key}"`));
    });
  });
  const sig = rng(hash(`${data.track}|signals`));
  for (const fd of L.finds) {
    const find = FINDS[fd.key];
    const delay = -(sig() * 2.4).toFixed(2);
    if (!isOn(fd.key)) { signals.push(signal(fd, delay)); continue; }
    const t = trail(fd);
    holes.push(`<path class="wl-hole-trail" d="${t.d}" fill="none" stroke="#000" stroke-width="10" stroke-linecap="round"/><circle cx="${f(fd.x)}" cy="${f(fd.y)}" r="${POI_R}"/>`);
    trails.push(`<path class="wl-trail" data-key="${fd.key}" d="${t.d}"/>`);
    breaches.push(`<rect class="wl-breach" x="${f(t.wx - 2)}" y="${f(t.ry - 3.5)}" width="4" height="7"/>`);
    pois.push(poi(fd, find, { fresh: fresh.has(fd.key), taken: taken.has(fd.key) }));
    if (fresh.has(fd.key)) tags.push(tag(fd, find));
  }
  for (const c of L.caches) {
    const open = cleared(c.g);
    caches.push(cacheMark(c, open));
    if (open && fresh.has(c.step)) tags.push(cacheTag(c));
  }

  const r = rng(hash(`${data.track}|fog`));
  const dots = Array.from({ length: 7 }, () => `<circle cx="${f(r() * 14)}" cy="${f(r() * 14)}" r="${f(0.35 + r() * 0.45)}"/>`).join('');
  const defs = `<pattern id="${id}-dots" width="14" height="14" patternUnits="userSpaceOnUse"><g class="mp-dots">${dots}</g></pattern>`
    + `<mask id="${id}-fog" maskUnits="userSpaceOnUse" x="0" y="0" width="${W}" height="${H}"><rect x="0" y="0" width="${W}" height="${H}" fill="#fff"/>`
    + `<g class="wl-holes" fill="#000">${holes.join('')}</g></mask>`;
  const n = L.finds.filter((fd) => isOn(fd.key)).length;
  const vb = view ? `${f(view.x)} ${f(view.y)} ${f(view.w)} ${f(view.h)}` : `0 0 ${W} ${H}`;
  const b = L.beyond;
  return `<div class="jz jz-map wl"><svg viewBox="${vb}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="The map and The Wasteland: ${n} of ${L.finds.length} finds">`
    + `<defs>${defs}</defs>`
    + `<rect class="mp-ground" x="0" y="0" width="${W}" height="${H}" rx="10"/>`
    + `<g class="wl-terrain">${terrain(data, L)}</g>`
    + `<g class="mp-under">${trails.join('')}${floors.join('')}${ways.join('')}${walls.join('')}</g>`
    + `<g class="mp-fog" mask="url(#${id}-fog)"><rect class="mp-fog-ground" x="0" y="0" width="${W}" height="${H}" rx="10"/>`
    + `<rect class="mp-fog-dots" x="0" y="0" width="${W}" height="${H}" rx="10" fill="url(#${id}-dots)"/></g>`
    + `${rect(WALL, 'mp-wall', ' rx="4"')}<g class="wl-breaches">${breaches.join('')}</g>`
    + `<g class="mp-over">${seen.join('')}${doors.join('')}${labels.join('')}</g>`
    + `<text class="wl-beyond" x="${f(b.x + b.w / 2)}" y="${f(b.y + b.h / 2 + 3)}">BEYOND</text>`
    + `<text class="mp-waste-label" x="${W / 2}" y="${H - 14}">THE WASTELAND</text>`
    + `<g class="wl-signals">${signals.join('')}</g><g class="wl-caches">${caches.join('')}</g><g class="wl-pois">${pois.join('')}</g>`
    + `<g class="wl-tags">${tags.join('')}</g></svg></div>`;
}
function cacheTag(c) {
  const text = 'CACHE OPENED';
  const w = text.length * 4.1 + 10;
  const x = c.x - w / 2, y = c.y + 19;
  return `<g class="wl-tag cache" data-step="${c.step}"><rect x="${f(x)}" y="${f(y)}" width="${f(w)}" height="12" rx="2"/><text x="${f(c.x)}" y="${f(y + 8.4)}">${text}</text></g>`;
}

/** The header glyph: the rooms and the finds, the revealed ones solid; a gold dot while something is new. */
export function mini(host, data, done, { fresh = new Set() } = {}) {
  done = asSet(done); fresh = asSet(fresh);
  const L = world(data);
  const rooms = L.regions.flatMap((g) => g.rooms.map((r) => `<rect class="mp-mcell${done.has(r.key) ? ' on' : ''}" x="${f(r.cx * U + 2)}" y="${f(r.cy * U + 2)}" width="${U - 4}" height="${U - 4}" rx="2"/>`));
  const finds = L.finds.filter((fd) => done.has(fd.key)).map((fd) => `<circle class="wl-mfind" cx="${f(fd.x)}" cy="${f(fd.y)}" r="7"/>`);
  const news = fresh.size ? `<circle class="wl-mnew" cx="${W - 26}" cy="26" r="22"/>` : '';
  host.innerHTML = `<div class="jz jz-mini jz-map wl"><svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="The map">`
    + `<rect class="wl-mwall" x="${WALL.x}" y="${WALL.y}" width="${WALL.w}" height="${WALL.h}" rx="6"/>${rooms.join('')}${finds.join('')}${news}</svg></div>`;
}

// --- the camera ---
const setView = (svg, v) => svg.setAttribute('viewBox', `${f(v.x)} ${f(v.y)} ${f(v.w)} ${f(v.h)}`);
/** A view of aspect `asp` (h / w) holding the box b with margin m. */
function frame(b, asp, m = 0) {
  let w = b.w + 2 * m, h = b.h + 2 * m;
  if (h / w > asp) w = h / asp; else h = w * asp;
  return { x: b.x + b.w / 2 - w / 2, y: b.y + b.h / 2 - h / 2, w, h };
}
/** Between two views: the centre straight, the size by ratio (so a zoom feels even). */
function between(a, b, e) {
  const w = Math.exp(lerp(Math.log(a.w), Math.log(b.w), e)), h = w * (a.h / a.w);
  const cx = lerp(a.x + a.w / 2, b.x + b.w / 2, e), cy = lerp(a.y + a.h / 2, b.y + b.h / 2, e);
  return { x: cx - w / 2, y: cy - h / 2, w, h };
}
const unionBox = (...bs) => {
  const x = Math.min(...bs.map((b) => b.x)), y = Math.min(...bs.map((b) => b.y));
  return { x, y, w: Math.max(...bs.map((b) => b.x + b.w)) - x, h: Math.max(...bs.map((b) => b.y + b.h)) - y };
};

/** One commit: the room revealed close up (filling the big checkbox's place), the camera out along the trail to the
 * find, and, if the step cleared, out to the whole map as the zone opens. Settles on render(data, after, {fresh}). */
export async function play(stage, { data, before, after, step, item, reduced, from = null, taken = new Set() }) {
  const [sid, , key] = keyFor(step, item);
  before = asSet(before); after = asSet(after);
  const L = world(data);
  const g = L.regions.find((x) => x.step.id === sid);
  const rm = g?.rooms.find((x) => x.key === key);
  const fd = L.finds.find((x) => x.key === key);
  const stepClears = !!g && g.rooms.every((x) => after.has(x.key)) && !g.rooms.every((x) => before.has(x.key));
  const newly = !before.has(key) && after.has(key);
  const unlocked = [...(newly && FINDS[key] ? [FINDS[key]] : []), ...(stepClears ? [CACHES[sid]] : [])];
  const fresh = new Set(unlocked.map((u) => (u.cache ? u.step : u.key)));
  const final = () => render(data, after, { fresh, taken });
  if (reduced || !rm || !newly) { await fadeIn(stage, final()); return { unlocked }; }

  stage.innerHTML = render(data, before, { taken });
  const svg = stage.querySelector('svg');
  const S = svg.getBoundingClientRect();
  const asp = S.width > 0 ? S.height / S.width : 1;
  const whole = frame({ x: 0, y: 0, w: W, h: H }, asp);
  const rb = roomBox(rm);
  let start;
  if (from && S.width > 0 && from.width > 0) {
    const k = from.width / rb.w;                       // screen px per world px
    start = { x: rb.x - (from.left - S.left) / k, y: rb.y - (from.top - S.top) / k, w: S.width / k, h: S.height / k };
  } else start = frame(rb, asp, rb.w * 1.5);
  setView(svg, start);

  const mask = svg.querySelector('.wl-holes');
  const over = svg.querySelector('.mp-over'), under = svg.querySelector('.mp-under');
  const fx = el('g', { class: 'jz-fx' }, svg);
  const motion = [];
  const at = (ms, dur, fn, easing) => motion.push(tween(dur, fn, { delay: ms, easing }));

  // 1. close up: the fog peels back from the room, its walls draw in, its doors light (slow, weighty)
  const hb = holeBox(rm), cx = hb.x + U / 2, cy = hb.y + U / 2;
  const peel = el('rect', { x: cx, y: cy, width: 0, height: 0 }, mask);
  const scan = el('rect', { class: 'mp-scan', x: cx, y: cy, width: 0, height: 0 }, fx);
  const dotted = svg.querySelector(`.mp-seen[data-key="${key}"]`);
  const fl = el('rect', { class: 'mp-floor', ...rb, opacity: 0 }, under);
  const wall = el('rect', { class: 'mp-draw', x: rb.x, y: rb.y, width: rb.w, height: rb.h }, fx);
  const per = 2 * (rb.w + rb.h);
  wall.style.strokeDasharray = `${per}`; wall.style.strokeDashoffset = `${per}`;
  const sizeTo = (node, b, e, pad = 0) => {
    const w = lerp(0, b.w + pad * 2, e), h = lerp(0, b.h + pad * 2, e);
    node.setAttribute('x', f(cx - w / 2)); node.setAttribute('y', f(cy - h / 2));
    node.setAttribute('width', f(w)); node.setAttribute('height', f(h));
  };
  at(0, 640, (e) => { sizeTo(peel, hb, e, 0.5); sizeTo(scan, hb, e, 0.5); scan.style.opacity = String(1 - e * 0.5); });
  if (dotted) at(0, 360, (_, t) => { dotted.style.opacity = String(1 - t); });
  at(300, 520, (e) => fl.setAttribute('opacity', e.toFixed(3)));
  at(340, 640, (e) => { wall.style.strokeDashoffset = `${per * (1 - e)}`; }, ease.inOut);
  at(760, 300, (_, t) => { scan.style.opacity = String(0.5 * (1 - t)); });
  const nb = [g.rooms[rm.k - 1], g.rooms[rm.k + 1]].filter(Boolean);
  nb.forEach((o, i) => {
    const [a, b] = o.k < rm.k ? [o, rm] : [rm, o];
    svg.querySelector(`.mp-door[data-a="${a.key}"][data-b="${b.key}"]`)?.remove();
    const lit = after.has(o.key);
    const d = el('rect', { class: `mp-door ${lit ? 'jz-lit' : 'frontier'}`, ...door(rm, o), opacity: 0 }, fx);
    at(820 + i * 120, 520, (_, t) => {
      d.setAttribute('opacity', Math.min(1, t * 2.5).toFixed(3));
      d.style.transformBox = 'fill-box'; d.style.transformOrigin = 'center';
      d.style.transform = `scale(${(1 + 1.2 * bump(t)).toFixed(3)})`;
      if (lit) d.classList.toggle('hot', t < 0.8);
    }, ease.linear);
  });

  // 2. the camera pulls back and travels out along the trail, through the wall, to the find
  const T0 = 1000;
  const poiBox = { x: fd.x - 26, y: fd.y - 22, w: 52, h: 44 };
  const tagBox = { x: fd.g.zone.x - 6, y: fd.y - 26, w: fd.g.zone.w + 12, h: 16 };
  const out = frame(unionBox(rb, poiBox, tagBox), asp, 18);
  at(T0, 1150, (e) => setView(svg, between(start, out, e)), ease.inOut);
  const t = trail(fd);
  const inner = el('path', { class: 'wl-trail live', d: t.inner }, fx);
  const path = el('path', { class: 'wl-trail live', d: t.d }, fx);
  const hole = el('path', { class: 'wl-hole-trail', d: t.d, fill: 'none', stroke: '#000', 'stroke-width': 10, 'stroke-linecap': 'round' }, mask);
  const ilen = Math.abs(fd.room.cx * U + U / 2 - (fd.g.zone.left ? area(fd.g).x : area(fd.g).x + area(fd.g).w));
  let len = 400; try { len = path.getTotalLength() || 400; } catch { /* not laid out */ }
  for (const [p, l] of [[inner, ilen], [path, len], [hole, len]]) { p.style.strokeDasharray = `${l} ${l}`; p.style.strokeDashoffset = `${l}`; }
  at(T0 + 250, 300, (e) => { inner.style.strokeDashoffset = `${ilen * (1 - e)}`; }, ease.linear);
  at(T0 + 450, 900, (e) => { path.style.strokeDashoffset = `${len * (1 - e)}`; hole.style.strokeDashoffset = `${len * (1 - e)}`; }, ease.inOut);
  const breach = el('rect', { class: 'wl-breach', x: t.wx - 2, y: t.ry - 3.5, width: 4, height: 7, opacity: 0 }, fx);
  at(T0 + 640, 260, (e) => breach.setAttribute('opacity', e.toFixed(3)));

  // 3. the fog lifts around the find, which rises with a gold ping, and its tag comes up
  const T1 = T0 + 1350;
  const sigEl = svg.querySelector(`.wl-signal[data-key="${key}"]`);
  const lift = el('circle', { cx: fd.x, cy: fd.y, r: 0 }, mask);
  at(T1, 620, (e) => lift.setAttribute('r', f(POI_R * e)));
  if (sigEl) at(T1, 300, (_, tt) => { sigEl.style.opacity = String(1 - tt); });
  const holder = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  holder.innerHTML = poi(fd, FINDS[key], { fresh: true, taken: taken.has(key) });
  const p = holder.firstElementChild;
  p.setAttribute('opacity', '0');
  fx.append(p);
  at(T1 + 200, 600, (e, tt) => {
    p.setAttribute('opacity', Math.min(1, tt * 2).toFixed(3));
    p.setAttribute('transform', `translate(${f(fd.x)} ${f(fd.y + 8 * (1 - e))}) scale(${f(0.6 + 0.4 * e)})`);
  });
  const ping = el('circle', { class: 'mp-halo', cx: fd.x, cy: fd.y, r: 0 }, fx);
  at(T1 + 520, 700, (_, tt) => { ping.setAttribute('r', f(lerp(6, 34, tt))); ping.style.opacity = String(1 - tt); }, ease.out);
  const tg = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  tg.innerHTML = tag(fd, FINDS[key]);
  const tagEl = tg.firstElementChild;
  tagEl.setAttribute('opacity', '0');
  fx.append(tagEl);
  at(T1 + 760, 360, (e) => tagEl.setAttribute('opacity', e.toFixed(3)));

  let T2 = T1 + 1150;
  if (stepClears) {
    // 4. out to the whole map: the region opens, the corridor clears, the zone's fog rolls back, the cache rises
    at(T2, 1100, (e) => setView(svg, between(out, whole, e)), ease.inOut);
    const a = area(g);
    const open = el('rect', { x: cx, y: cy, width: 0, height: 0, rx: 6 }, mask);
    const floor = el('rect', { class: 'mp-region', x: a.x, y: a.y, width: a.w, height: a.h, rx: 6, opacity: 0 }, under);
    const name = el('text', { class: 'mp-label', x: f(a.x + a.w / 2), y: f(a.y - 5), opacity: 0 }, fx);
    name.textContent = `${g.step.n} ${g.step.name.toUpperCase()}`;
    at(T2 + 200, 800, (e) => {
      open.setAttribute('x', f(lerp(cx, a.x, e))); open.setAttribute('y', f(lerp(cy, a.y, e)));
      open.setAttribute('width', f(lerp(0, a.w, e))); open.setAttribute('height', f(lerp(0, a.h, e)));
      floor.setAttribute('opacity', e.toFixed(3));
    }, ease.inOut);
    at(T2 + 700, 400, (e) => name.setAttribute('opacity', e.toFixed(3)));
    const c = corridor(g, L.regions[g.s + 1]);
    if (c) {
      const cw = el('rect', { x: c.x, y: c.y, width: 0, height: 0 }, mask);
      const cwv = el('rect', { class: 'mp-way', x: c.x, y: c.y, width: 0, height: 0 }, under);
      at(T2 + 800, 460, (e) => {
        const w = c.w > c.h ? c.w * e : c.w, h = c.w > c.h ? c.h : c.h * e;
        for (const n of [cw, cwv]) { n.setAttribute('width', f(w)); n.setAttribute('height', f(h)); }
      });
    }
    const z = g.zone, zx = z.left ? z.x + z.w : z.x;
    const roll = el('rect', { x: zx, y: z.y - 2, width: 0, height: z.h + 4, rx: 12 }, mask);
    at(T2 + 900, 900, (e) => {
      const w = (z.w + 8) * e;
      roll.setAttribute('x', f(z.left ? z.x + z.w + 4 - w : z.x - 4)); roll.setAttribute('width', f(w));
    }, ease.inOut);
    const cc = L.caches.find((x) => x.step === sid);
    svg.querySelector(`.wl-cache[data-step="${sid}"]`)?.remove();
    const ch = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    ch.innerHTML = cacheMark(cc, true) + cacheTag(cc);
    const [cm, ct] = [...ch.children];
    for (const n of [cm, ct]) { n.setAttribute('opacity', '0'); fx.append(n); }
    at(T2 + 1500, 700, (e, tt) => {
      cm.setAttribute('opacity', Math.min(1, tt * 2).toFixed(3));
      cm.setAttribute('transform', `translate(${f(cc.x)} ${f(cc.y + 10 * (1 - e))}) scale(${f(0.5 + 0.5 * e)})`);
    });
    const halo = el('circle', { class: 'mp-halo', cx: cc.x, cy: cc.y, r: 0 }, fx);
    at(T2 + 1900, 800, (_, tt) => { halo.setAttribute('r', f(lerp(10, 60, tt))); halo.style.opacity = String(1 - tt); }, ease.out);
    at(T2 + 2100, 400, (e) => ct.setAttribute('opacity', e.toFixed(3)));
    T2 += 2550;
  } else {
    at(T2, 900, (e) => setView(svg, between(out, whole, e)), ease.inOut);
    T2 += 900;
  }
  await Promise.all(motion);
  await wait(120);
  stage.innerHTML = final();
  return { unlocked };
}

// --- looking around ---
/** The full-screen map: drag to look around, two zoom levels, tap a find, a signal or a cache. */
export function explore(host, data, done, { fresh = new Set(), taken = new Set(), onFind = () => {}, onSignal = () => {}, onClose = () => {} } = {}) {
  let state = { done: asSet(done), fresh: asSet(fresh), taken: asSet(taken) };
  const back = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5l-7 7 7 7"/></svg>';
  const zin = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5M8 11h6M11 8v6"/></svg>';
  const zout = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5M8 11h6"/></svg>';
  host.innerHTML = `<div class="wl-explore" role="dialog" aria-label="The Wasteland">
    <header class="wl-x-top"><button type="button" class="wl-x-back" aria-label="Back to the checklist">${back}</button>
      <div class="wl-x-title"><h2>The Wasteland</h2><p class="wl-x-count"></p></div>
      <button type="button" class="wl-x-zoom" aria-label="Zoom in" aria-pressed="false">${zin}</button></header>
    <div class="wl-x-view"></div>
    <p class="wl-x-hint">Drag to look around · tap a find · mocked</p></div>`;
  const root = host.firstElementChild;
  const viewEl = root.querySelector('.wl-x-view'), zoomBtn = root.querySelector('.wl-x-zoom');
  let zoomed = false, view = null, svg = null;

  // close up, the camera goes to the frontier: the first step not yet clear, its rooms and its zone
  const focus = () => {
    const L = world(data);
    const g = L.regions.find((x) => !x.rooms.every((r) => state.done.has(r.key))) ?? L.regions[L.regions.length - 1];
    const a = area(g), z = g.zone;
    return { x: (z.x + z.w / 2 + a.x + a.w / 2) / 2, y: z.y + z.h / 2 };
  };
  const size = () => { const r = viewEl.getBoundingClientRect(); return { w: r.width || 1, h: r.height || 1 }; };
  const clamp = (v) => {
    const c = (x, vw, WW) => (vw >= WW ? (WW - vw) / 2 : Math.min(Math.max(x, -U), WW - vw + U));
    return { ...v, x: c(v.x, v.w, W), y: c(v.y, v.h, H) };
  };
  function fit(at = null) {
    const { w, h } = size();
    const vw = zoomed ? W / 2 : W + 2 * 8, vh = vw * (h / w);
    const p = at ?? (zoomed ? focus() : { x: W / 2, y: H / 2 });
    view = clamp({ x: p.x - vw / 2, y: p.y - vh / 2, w: vw, h: vh });
    if (svg) setView(svg, view);
    zoomBtn.setAttribute('aria-pressed', String(zoomed));
    zoomBtn.setAttribute('aria-label', zoomed ? 'Zoom out' : 'Zoom in');
    zoomBtn.innerHTML = zoomed ? zout : zin;
  }
  function draw() {
    const L = world(data);
    const n = L.finds.filter((fd) => state.done.has(fd.key)).length;
    root.querySelector('.wl-x-count').textContent = `${n} of ${L.finds.length} found · ${state.taken.size} taken`;
    viewEl.innerHTML = render(data, state.done, { id: 'wlx', fresh: state.fresh, taken: state.taken });
    svg = viewEl.querySelector('svg');
    if (!view) fit(); else setView(svg, view);
  }
  draw();

  // the camera's world point under a screen point
  const toWorld = (x, y) => { const r = viewEl.getBoundingClientRect(); return { x: view.x + ((x - r.left) / r.width) * view.w, y: view.y + ((y - r.top) / r.height) * view.h }; };
  let down = null, lastTap = null;
  const onDown = (e) => { down = { x: e.clientX, y: e.clientY, v: { ...view }, moved: false, id: e.pointerId }; };
  const onMove = (e) => {
    if (!down || e.pointerId !== down.id) return;
    const dx = e.clientX - down.x, dy = e.clientY - down.y;
    if (!down.moved && Math.hypot(dx, dy) < 8) return;
    down.moved = true;
    const r = viewEl.getBoundingClientRect(), k = view.w / r.width;
    view = clamp({ ...down.v, x: down.v.x - dx * k, y: down.v.y - dy * k });
    setView(svg, view);
  };
  const onUp = (e) => {
    if (!down || e.pointerId !== down.id) return;
    const was = down; down = null;
    if (was.moved) return;
    const hit = document.elementFromPoint(e.clientX, e.clientY)?.closest('.wl-poi, .wl-signal, .wl-cache:not(.sealed)');
    if (hit) {
      lastTap = null;
      if (hit.classList.contains('wl-cache')) onFind(CACHES[hit.dataset.step]);
      else if (hit.classList.contains('wl-signal')) onSignal(FINDS[hit.dataset.key]);
      else onFind(FINDS[hit.dataset.key]);
      return;
    }
    const now = performance.now();
    if (lastTap && now - lastTap.t < 320 && Math.hypot(e.clientX - lastTap.x, e.clientY - lastTap.y) < 24) {
      lastTap = null; zoomed = !zoomed; fit(zoomed ? toWorld(e.clientX, e.clientY) : null);
    } else lastTap = { t: now, x: e.clientX, y: e.clientY };
  };
  const onCancel = () => { down = null; };
  viewEl.addEventListener('pointerdown', onDown);
  viewEl.addEventListener('pointermove', onMove);
  viewEl.addEventListener('pointerup', onUp);
  viewEl.addEventListener('pointercancel', onCancel);
  const tapOn = (b, fn) => {
    let d = null;
    b.addEventListener('pointerdown', (e) => { d = [e.clientX, e.clientY]; });
    b.addEventListener('pointerup', (e) => { const ok = d && Math.hypot(e.clientX - d[0], e.clientY - d[1]) < 12; d = null; if (ok) fn(); });
    b.addEventListener('click', (e) => { if (e.detail === 0) fn(); });
  };
  tapOn(root.querySelector('.wl-x-back'), () => onClose());
  tapOn(zoomBtn, () => { zoomed = !zoomed; fit(); });
  const onResize = () => fit();
  addEventListener('resize', onResize);
  return {
    destroy() { removeEventListener('resize', onResize); host.innerHTML = ''; },
    refresh(nextDone, { fresh: fr = state.fresh, taken: tk = state.taken } = {}) {
      state = { done: asSet(nextDone), fresh: asSet(fr), taken: asSet(tk) };
      draw();
    },
    get view() { return { ...view }; },
    get zoomed() { return zoomed; },
  };
}
