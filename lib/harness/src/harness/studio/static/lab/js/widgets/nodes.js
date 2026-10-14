// nodes(ctx, ids, {snapshots, size, label, key, state, onState}) -> element
//
// Max's nodes object: up to six circles on a pad, each holding a snapshot of `ids`. Drag the cursor among them and
// the params blend the snapshots by how far inside each circle the cursor sits (the circles' overlaps are where the
// mixes live; outside every circle nothing moves). The drag is relative: the cursor never jumps to the finger.
// Tap a node: the cursor glides to its centre. Long press a node: it captures the params as they are now. Turn on
// MOVE to drag nodes around (and drag a node's rim to resize it). Spokes show each node's weight.
// Double tap: the params back to the set. Long press the pad away from the nodes: choose a param to inspect.
//
//   snapshots  [{name, values: {id: norm 0..1}}] (default: SET, the tried lows, the tried highs, and now)
//   size       the pad's width in px (default 300)
//   key        save nodes and cursor on this phone; or state + onState(state) to keep them elsewhere

import { drag, h, haptic, longPress, toast } from '../ui.js';
import { normOf } from './core.js';
import { setNorm } from '../params.js';
import { chooser, fitCanvas, HEX, keep, rgba, tick, touches } from './kit.js';

const COLS = [HEX.hazard, HEX.cold, HEX.acid, HEX.collage, HEX.play, HEX.lcd];

/** Default snapshots: the set, the tried range's low and high ends (or +-20 % around the set), and the knobs now. */
export function defaultSnapshots(ctx, ids) {
  const snap = (fn) => Object.fromEntries(ids.map((id) => [id, fn(ctx.params.get(id), id)]));
  const edge = (p, hi) => {
    if (p.tried) { const a = normOf(p, p.tried[0]), b = normOf(p, p.tried[1]); return hi ? Math.max(a, b) : Math.min(a, b); }
    return Math.max(0, Math.min(1, setNorm(p) + (hi ? 0.2 : -0.2)));
  };
  return [
    { name: 'SET', values: snap((p) => setNorm(p)) },
    { name: 'LOW', values: snap((p) => edge(p, false)) },
    { name: 'HIGH', values: snap((p) => edge(p, true)) },
    { name: 'NOW', values: snap((_p, id) => ctx.store.get(id)) },
  ];
}

export function nodes(ctx, ids, { snapshots, size = 300, label = 'nodes', key, state, onState } = {}) {
  const snaps = (snapshots ?? defaultSnapshots(ctx, ids)).slice(0, 6);
  const n = snaps.length;
  const def = {
    nodes: snaps.map((sn, i) => {
      const a = -Math.PI / 2 + (i / n) * Math.PI * 2;
      return { name: sn.name, values: sn.values, x: 0.5 + 0.27 * Math.cos(a), y: 0.5 + 0.27 * Math.sin(a), r: n <= 4 ? 0.34 : 0.28 };
    }),
    cursor: { x: 0.5, y: 0.5 },
  };
  const kept = keep({ key, state, onState }, def);
  const S = kept.state;
  const cv = h('canvas', { class: 'nd-cv' });
  const pad = h('div', { class: 'nd-pad' }, cv);
  const moveBtn = h('button', { type: 'button', class: 'nd-move', 'aria-pressed': 'false' }, h('i'), 'move');
  const read = h('span', { class: 'nd-read' });
  const el = h('div', { class: 'w-nodes', dataset: { param: ids.join(' ') }, style: { '--w': `${size}px` } },
    h('div', { class: 'nd-head' }, h('span', { class: 'w-label', text: label }), read, moveBtn), pad);

  let edit = false, dirty = true, weights = S.nodes.map(() => 0), inside = -1;
  moveBtn.addEventListener('click', () => { edit = !edit; moveBtn.setAttribute('aria-pressed', String(edit)); el.classList.toggle('is-edit', edit); haptic(); dirty = true; });

  const weigh = () => {
    weights = S.nodes.map((nd) => Math.max(0, 1 - Math.hypot(S.cursor.x - nd.x, S.cursor.y - nd.y) / nd.r));
    const top = weights.reduce((b, w, i) => (w > (weights[b] ?? 0) ? i : b), 0);
    const now = weights[top] > 0 ? top : -1;
    if (now !== inside) { inside = now; if (now >= 0) haptic(); }
    const sum = weights.reduce((a, b) => a + b, 0);
    read.textContent = sum > 0 ? S.nodes.map((nd, i) => (weights[i] > 0 ? `${nd.name} ${Math.round((weights[i] / sum) * 100)}` : '')).filter(Boolean).join(' · ') : 'outside: holds';
    return sum;
  };
  const blend = () => {
    const sum = weigh();
    dirty = true;
    if (sum <= 0) return;
    for (const id of ids) {
      const p = ctx.params.get(id);
      let v = 0, ws = 0, best = -1, bw = 0;
      S.nodes.forEach((nd, i) => {
        const x = nd.values?.[id];
        if (x == null || weights[i] <= 0) return;
        v += x * weights[i]; ws += weights[i];
        if (weights[i] > bw) { bw = weights[i]; best = i; }
      });
      if (!ws) continue;
      if (p.scale === 'enum' || p.scale === 'toggle') v = S.nodes[best].values[id]; else v /= ws;
      ctx.store.set(id, v, { source: 'nodes' });
    }
  };

  const px = () => { const r = pad.getBoundingClientRect(); return { r, w: r.width, h: r.height }; };
  const hit = (cx, cy) => {
    const { r, w, h: hh } = px();
    const x = (cx - r.left) / w, y = (cy - r.top) / hh;
    let best = null;
    S.nodes.forEach((nd, i) => {
      const dpx = Math.hypot((x - nd.x) * w, (y - nd.y) * hh);
      const rim = Math.abs(dpx - nd.r * w) < 16;
      if (dpx < 26 && (!best || dpx < best.d)) best = { i, d: dpx, part: 'handle' };
      else if (edit && rim && !best) best = { i, d: dpx, part: 'rim' };
    });
    return best;
  };

  let grab = null, glide = null;
  drag(pad, {
    onStart: (e) => {
      glide = null;
      grab = edit ? hit(e.clientX, e.clientY) : null;
      if (!grab) ctx.store.begin();
      el.classList.add('is-touched');
    },
    onMove: (dx, dy, { x, y }) => {
      const { r, w, h: hh } = px();
      if (grab) {
        const nd = S.nodes[grab.i];
        if (grab.part === 'rim') nd.r = Math.max(0.12, Math.min(0.7, Math.hypot((x - r.left) / w - nd.x, (y - r.top) / hh - nd.y)));
        else { nd.x = Math.max(0.04, Math.min(0.96, nd.x + dx / w)); nd.y = Math.max(0.04, Math.min(0.96, nd.y + dy / hh)); }
        blend();
        return;
      }
      S.cursor.x = Math.max(0, Math.min(1, S.cursor.x + dx / w));
      S.cursor.y = Math.max(0, Math.min(1, S.cursor.y + dy / hh));
      blend();
    },
    onEnd: () => { if (!grab) ctx.store.end(); grab = null; el.classList.remove('is-touched'); kept.save(); },
    onTap: (e) => {
      const g = hit(e.clientX, e.clientY);
      if (!g || g.part !== 'handle') return;
      const nd = S.nodes[g.i];
      glide = { x0: S.cursor.x, y0: S.cursor.y, x1: nd.x, y1: nd.y, t: 0 };
      ctx.store.begin();
    },
  });
  touches(pad, ctx, ids, { long: false, name: label });
  longPress(pad, (e) => {
    const g = hit(e.clientX, e.clientY);
    if (g && g.part === 'handle') {
      const nd = S.nodes[g.i];
      nd.values = Object.fromEntries(ids.map((id) => [id, ctx.store.get(id)]));
      kept.save();
      dirty = true;
      toast(`${nd.name}: holds the controls as they are now`);
      return;
    }
    if (!ctx.local) chooser(ctx, ids, label);
  });

  tick(ctx, (_t, dt) => {
    if (glide) {
      glide.t = Math.min(1, glide.t + dt / 0.35);
      const k = glide.t * glide.t * (3 - 2 * glide.t);
      S.cursor.x = glide.x0 + (glide.x1 - glide.x0) * k;
      S.cursor.y = glide.y0 + (glide.y1 - glide.y0) * k;
      blend();
      if (glide.t >= 1) { glide = null; ctx.store.end(); kept.save(); }
    }
    if (dirty) { dirty = false; draw(); }
  }, el);
  ctx.own(() => { if (glide) ctx.store.end(); });
  weigh();

  function draw() {
    const { g, W, H, d } = fitCanvas(cv);
    g.clearRect(0, 0, W, H);
    const X = (v) => v * W, Y = (v) => v * H;
    S.nodes.forEach((nd, i) => {
      const c = COLS[i % COLS.length], R = nd.r * W, w = weights[i];
      const grd = g.createRadialGradient(X(nd.x), Y(nd.y), 0, X(nd.x), Y(nd.y), R);
      grd.addColorStop(0, rgba(c, 0.22 + 0.3 * w)); grd.addColorStop(1, rgba(c, 0.04 + 0.08 * w));
      g.fillStyle = grd;
      g.beginPath(); g.arc(X(nd.x), Y(nd.y), R, 0, Math.PI * 2); g.fill();
      g.strokeStyle = rgba(c, 0.55 + 0.45 * w); g.lineWidth = (1 + 1.5 * w) * d;
      if (edit) g.setLineDash([5 * d, 4 * d]);
      g.stroke(); g.setLineDash([]);
    });
    // spokes
    const cx = X(S.cursor.x), cy = Y(S.cursor.y);
    S.nodes.forEach((nd, i) => {
      if (weights[i] <= 0) return;
      g.strokeStyle = rgba(COLS[i % COLS.length], 0.85); g.lineWidth = (1 + 4 * weights[i]) * d;
      g.beginPath(); g.moveTo(cx, cy); g.lineTo(X(nd.x), Y(nd.y)); g.stroke();
    });
    // handles and names
    g.textAlign = 'center'; g.textBaseline = 'middle';
    S.nodes.forEach((nd, i) => {
      const c = COLS[i % COLS.length];
      g.fillStyle = '#0b0c0e'; g.strokeStyle = c; g.lineWidth = 1.5 * d;
      g.beginPath(); g.arc(X(nd.x), Y(nd.y), 13 * d, 0, Math.PI * 2); g.fill(); g.stroke();
      g.fillStyle = c; g.font = `700 ${9 * d}px ui-monospace, Menlo, monospace`;
      g.fillText(nd.name.slice(0, 4), X(nd.x), Y(nd.y) + 0.5 * d);
    });
    // the cursor
    g.shadowColor = '#fff'; g.shadowBlur = 10 * d;
    g.strokeStyle = '#fff'; g.lineWidth = 2 * d;
    g.beginPath(); g.arc(cx, cy, 10 * d, 0, Math.PI * 2); g.stroke();
    g.shadowBlur = 0;
    g.lineWidth = 1.2 * d;
    g.beginPath();
    g.moveTo(cx - 17 * d, cy); g.lineTo(cx - 6 * d, cy); g.moveTo(cx + 6 * d, cy); g.lineTo(cx + 17 * d, cy);
    g.moveTo(cx, cy - 17 * d); g.lineTo(cx, cy - 6 * d); g.moveTo(cx, cy + 6 * d); g.lineTo(cx, cy + 17 * d);
    g.stroke();
  }
  return el;
}
