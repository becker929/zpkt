// The map (release 3): a screen of its own, opened from the header or with M. It charts The Wasteland from its
// layout in white line on black: the storm's edge, the worn paths, the ground's features as small marks, and the
// points of interest (the camp with the track's machine, the museum, the seven sites), named. Where you haven't
// walked is under fog, and the points of interest show through it faintly, so there is always somewhere to go. Tap
// one, on the chart or in the list under it, to set a waypoint: back in the world, a gold arrow on the screen's edge
// points to it and a pillar of light stands over it.
//
//   new Seen(W, H)                       where you've walked and the places you've reached, kept in this browser
//   openChart(host, { L, hero, seen, waypoint, onPick, onClose }) -> { close() }
import { haptic, onTap } from '../concepts/model.js';
import { EDGE, HAZE, edgeDist } from './land.js';

const CELL = 32;                    // the fog's cell, world px
const KEY = 'wasteland:seen';

export class Seen {
  constructor(W, H, reach = 120) {
    this.cw = Math.ceil(W / CELL); this.ch = Math.ceil(H / CELL); this.reach = reach;
    this.bits = new Uint8Array(this.cw * this.ch);
    this.places = new Set();
    try {
      const s = JSON.parse(localStorage.getItem(KEY));
      if (s?.w === this.cw && typeof s.bits === 'string') {
        const raw = atob(s.bits);
        for (let i = 0; i < raw.length && i < this.bits.length; i++) this.bits[i] = raw.charCodeAt(i);
      }
      for (const p of s?.places ?? []) this.places.add(p);
    } catch { /* a fresh chart */ }
    this.dirty = false;
  }
  /** Lifts the fog round (x, y). */
  walk(x, y) {
    const r = this.reach, i0 = Math.max(0, Math.floor((x - r) / CELL)), i1 = Math.min(this.cw - 1, Math.floor((x + r) / CELL));
    const j0 = Math.max(0, Math.floor((y - r) / CELL)), j1 = Math.min(this.ch - 1, Math.floor((y + r) / CELL));
    for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
      if (this.bits[j * this.cw + i]) continue;
      if (Math.hypot((i + 0.5) * CELL - x, (j + 0.5) * CELL - y) <= r) { this.bits[j * this.cw + i] = 1; this.dirty = true; }
    }
  }
  /** Marks a place as reached; true the first time. */
  reached(id) { if (this.places.has(id)) return false; this.places.add(id); this.dirty = true; return true; }
  has(i, j) { return this.bits[j * this.cw + i] === 1; }
  get fraction() { return this.bits.reduce((a, b) => a + b, 0) / this.bits.length; }
  save() {
    if (!this.dirty) return;
    this.dirty = false;
    try {
      localStorage.setItem(KEY, JSON.stringify({ w: this.cw, bits: btoa(String.fromCharCode(...this.bits)), places: [...this.places] }));
    } catch { /* this visit only */ }
  }
}

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') el.className = v; else if (k === 'text') el.textContent = v; else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
}
const svg = (d) => {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('aria-hidden', 'true');
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path'); p.setAttribute('d', d);
  s.append(p);
  return s;
};
const CLOSE = 'M6 6l12 12M18 6L6 18';

/** The points of interest, in the order the list shows them. */
export function pois(L) {
  return [
    { id: 'machine', name: 'HW002', sub: 'The camp · the track machine', x: L.camp.x, y: L.camp.y, mark: 'camp' },
    ...L.sites.map((s) => ({ id: s.step, name: s.name, sub: `${s.n} · ${s.what}`, x: s.x, y: s.y, mark: 'site', n: s.n })),
    { id: 'museum', name: 'The museum', sub: 'Every plate, hung', x: L.museum.x, y: L.museum.y - 30, mark: 'museum' },
  ];
}

// the chart's still layers, drawn once per size: the ground's marks, then the fog over them
function paintGround(c, L, k, dpr) {
  const { W, H } = L;
  c.fillStyle = '#000'; c.fillRect(0, 0, W * k, H * k);
  // the storm, as dots that crowd towards the edge
  for (let y = 4; y < H; y += 8) for (let x = 4; x < W; x += 8) {
    const e = edgeDist(x, y);
    if (e >= HAZE) continue;
    const tone = Math.min(1, Math.max(0, (HAZE - e) / (HAZE - EDGE + 30)));
    c.fillStyle = `rgb(255 255 255 / ${(0.15 + tone * 0.75).toFixed(2)})`;
    const s = Math.max(1, tone * 8 * k);
    c.fillRect(x * k - s / 2, y * k - s / 2, s, s);
  }
  // the worn paths
  c.strokeStyle = 'rgb(255 255 255 / 0.55)'; c.lineWidth = 1.4 * dpr; c.setLineDash([2.5 * dpr, 3 * dpr]);
  for (const p of L.paths) {
    c.beginPath();
    p.forEach(([x, y], i) => (i ? c.lineTo(x * k, y * k) : c.moveTo(x * k, y * k)));
    c.stroke();
  }
  c.setLineDash([]);
  // the wires
  c.strokeStyle = 'rgb(255 255 255 / 0.25)'; c.lineWidth = 0.8 * dpr;
  for (const w of L.wires) { c.beginPath(); c.moveTo(w.x0 * k, (w.y0 + 30) * k); c.lineTo(w.x1 * k, (w.y1 + 30) * k); c.stroke(); }
  // the things standing, as small marks
  const big = new Set(['machine', 'museum', 'heap', 'crane', 'drum', 'boxcar', 'press', 'tank', 'mast', 'gate', 'tent', 'crate', 'stones']);
  c.lineWidth = 1 * dpr;
  for (const p of L.props) {
    if (big.has(p.type)) continue;
    const x = p.x * k, y = p.y * k;
    c.strokeStyle = c.fillStyle = 'rgb(255 255 255 / 0.7)';
    if (p.type === 'rock') { c.beginPath(); c.arc(x, y - 2 * k, Math.max(1.2 * dpr, (p.a.img.width / 2.6) * k), 0, Math.PI * 2); c.stroke(); }
    else if (p.type === 'tree') { c.beginPath(); c.moveTo(x, y); c.lineTo(x, y - 9 * k); c.moveTo(x - 4 * k, y - 12 * k); c.lineTo(x, y - 8 * k); c.lineTo(x + 4 * k, y - 12 * k); c.stroke(); }
    else if (p.type === 'wall') { c.fillStyle = 'rgb(255 255 255 / 0.7)'; c.fillRect(x - 4 * k, y - 6 * k, 8 * k + 0.5, 6 * k + 0.5); }
    else if (p.type === 'wreck') c.strokeRect(x - 12 * k, y - 8 * k, 24 * k, 8 * k);
    else if (p.type === 'pylon') { c.beginPath(); c.moveTo(x - 4 * k, y); c.lineTo(x + 4 * k, y - 8 * k); c.moveTo(x + 4 * k, y); c.lineTo(x - 4 * k, y - 8 * k); c.stroke(); }
  }
}
function paintFog(c, L, k, seen) {
  c.fillStyle = 'rgb(0 0 0 / 0.86)'; c.fillRect(0, 0, L.W * k, L.H * k);
  c.globalCompositeOperation = 'destination-out';
  const r = CELL * 1.1 * k;
  for (let j = 0; j < seen.ch; j++) for (let i = 0; i < seen.cw; i++) {
    if (!seen.has(i, j)) continue;
    const x = (i + 0.5) * CELL * k, y = (j + 0.5) * CELL * k;
    const g = c.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, 'rgb(0 0 0 / 1)'); g.addColorStop(0.55, 'rgb(0 0 0 / 0.9)'); g.addColorStop(1, 'rgb(0 0 0 / 0)');
    c.fillStyle = g; c.fillRect(x - r, y - r, 2 * r, 2 * r);
  }
  c.globalCompositeOperation = 'source-over';
}
function paintMarks(c, list, k, dpr, seen, waypoint) {
  const GOLD = '#f1b64a';
  c.textAlign = 'center'; c.textBaseline = 'middle';
  for (const p of list) {
    const x = p.x * k, y = p.y * k, been = seen.places.has(p.id);
    c.globalAlpha = been ? 1 : 0.55;
    c.lineWidth = 1.6 * dpr; c.strokeStyle = '#fff'; c.fillStyle = '#000';
    c.setLineDash(been ? [] : [2 * dpr, 2 * dpr]);
    const R = 9 * dpr;
    c.beginPath();
    if (p.mark === 'camp') { c.moveTo(x, y - R * 1.2); c.lineTo(x + R * 1.2, y); c.lineTo(x, y + R * 1.2); c.lineTo(x - R * 1.2, y); c.closePath(); }
    else if (p.mark === 'museum') { c.moveTo(x - R, y + R * 0.8); c.lineTo(x - R, y - R * 0.2); c.lineTo(x, y - R); c.lineTo(x + R, y - R * 0.2); c.lineTo(x + R, y + R * 0.8); c.closePath(); }
    else c.arc(x, y, R, 0, Math.PI * 2);
    c.fill(); c.stroke();
    c.setLineDash([]);
    c.fillStyle = p.mark === 'camp' ? GOLD : '#fff';
    if (p.mark === 'camp') {
      const d = 4 * dpr;
      c.beginPath(); c.moveTo(x, y - d); c.lineTo(x + d, y); c.lineTo(x, y + d); c.lineTo(x - d, y); c.closePath(); c.fill();
    } else {
      c.font = `700 ${(p.mark === 'site' ? (p.n.length > 2 ? 7 : 8.5) : 8) * dpr}px ui-monospace, Menlo, monospace`;
      c.fillText(p.mark === 'site' ? p.n : 'M', x, y + 0.5 * dpr);
    }
    c.font = `600 ${9 * dpr}px ui-monospace, Menlo, monospace`;
    const label = p.name.toUpperCase(), lw = c.measureText(label).width + 6 * dpr;
    c.fillStyle = '#000'; c.fillRect(x - lw / 2, y + R + 3 * dpr, lw, 12 * dpr);
    c.fillStyle = '#fff'; c.fillText(label, x, y + R + 9.5 * dpr);
    if (waypoint?.id === p.id) {
      c.globalAlpha = 1; c.strokeStyle = GOLD; c.lineWidth = 2.2 * dpr;
      c.beginPath(); c.arc(x, y, R + 5 * dpr, 0, Math.PI * 2); c.stroke();
    }
  }
  c.globalAlpha = 1;
}

export function openChart(host, { L, hero, seen, waypoint, onPick, onClose }) {
  const dpr = Math.min(3, devicePixelRatio || 1);
  const list = pois(L);
  const close = h('button', { type: 'button', class: 'ch-x', 'aria-label': 'Back to the world' }, svg(CLOSE));
  const cv = h('canvas', { class: 'ch-map', 'aria-label': 'The map of The Wasteland' });
  const ul = h('ul', { class: 'ch-list' });
  const pct = Math.round(seen.fraction * 100);
  host.replaceChildren(
    h('header', { class: 'ch-top' }, close, h('div', { class: 'ch-title' }, h('b', { text: 'The Wasteland' }), h('span', { text: `HW002 · ${pct}% walked` }))),
    h('div', { class: 'ch-frame' }, cv),
    h('p', { class: 'ch-help', text: 'Tap a place to set a waypoint. Fog lifts where you walk.' }),
    ul,
  );
  host.classList.add('show'); host.setAttribute('aria-hidden', 'false');

  let wp = waypoint, k = 1, still = null, raf = 0;
  const c = cv.getContext('2d');
  function layout() {
    const w = cv.clientWidth;
    cv.width = Math.round(w * dpr); cv.height = Math.round((w * L.H / L.W) * dpr);
    k = cv.width / L.W;
    still = document.createElement('canvas'); still.width = cv.width; still.height = cv.height;
    const s = still.getContext('2d');
    paintGround(s, L, k, dpr);
    const fog = document.createElement('canvas'); fog.width = cv.width; fog.height = cv.height;
    paintFog(fog.getContext('2d'), L, k, seen);
    s.drawImage(fog, 0, 0);
  }
  function frame(now) {
    c.drawImage(still, 0, 0);
    paintMarks(c, list, k, dpr, seen, wp);
    // you: a gold arrow the way you face, in a ring that breathes
    const x = hero.x * k, y = hero.y * k, a = { down: Math.PI / 2, up: -Math.PI / 2, side: hero.flip ? Math.PI : 0 }[hero.face];
    const pulse = (now / 900) % 1;
    c.strokeStyle = `rgb(241 182 74 / ${(1 - pulse).toFixed(2)})`; c.lineWidth = 1.5 * dpr;
    c.beginPath(); c.arc(x, y, (5 + pulse * 14) * dpr, 0, Math.PI * 2); c.stroke();
    c.fillStyle = '#f1b64a'; c.strokeStyle = '#000'; c.lineWidth = 1.2 * dpr;
    c.beginPath();
    for (const [r, t] of [[7, 0], [5, 2.5], [2, Math.PI], [5, -2.5]]) c.lineTo(x + Math.cos(a + t) * r * dpr, y + Math.sin(a + t) * r * dpr);
    c.closePath(); c.fill(); c.stroke();
    raf = requestAnimationFrame(frame);
  }
  function rows() {
    ul.replaceChildren(...list.map((p) => {
      const d = Math.round(Math.hypot(p.x - hero.x, p.y - hero.y) / 8);
      const li = h('li', { class: `ch-row${wp?.id === p.id ? ' way' : ''}${seen.places.has(p.id) ? ' been' : ''}`, 'data-id': p.id },
        h('i', { class: p.mark, text: p.mark === 'site' ? p.n : p.mark === 'camp' ? '' : 'M' }),
        h('div', {}, h('b', { text: p.name }), h('span', { text: p.sub })),
        h('em', { text: wp?.id === p.id ? 'waypoint' : `${d} m` }));
      onTap(li, () => pick(p));
      return li;
    }));
  }
  function pick(p) {
    wp = wp?.id === p.id ? null : { id: p.id, name: p.name, x: p.x, y: p.y };
    haptic(true);
    onPick?.(wp);
    rows();
  }
  cv.addEventListener('pointerup', (e) => {
    const r = cv.getBoundingClientRect();
    const x = ((e.clientX - r.left) * dpr) / k, y = ((e.clientY - r.top) * dpr) / k;
    let best = null;
    for (const p of list) { const d = Math.hypot(p.x - x, p.y - y); if (!best || d < best.d) best = { p, d }; }
    if (best && best.d * (k / dpr) < 30) pick(best.p);
  });
  function shut() {
    cancelAnimationFrame(raf);
    host.classList.remove('show'); host.setAttribute('aria-hidden', 'true');
    removeEventListener('resize', relayout);
    onClose?.();
  }
  const relayout = () => layout();
  addEventListener('resize', relayout);
  onTap(close, shut);
  layout(); rows();
  raf = requestAnimationFrame(frame);
  return { close: shut };
}
