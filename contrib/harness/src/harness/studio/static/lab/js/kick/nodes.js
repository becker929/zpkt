// A canvas with draggable nodes, each bound to one or two params: the envelope drawers, the EQ curve, the
// compressor's transfer curve, the transient shaper's picture use it.
//
//   nodeCanvas(ctx, {cls, nodes, draw, height}) -> {el, cv, redraw, selected()}
//   node: {key, ids: [...], pos(W, H) -> [x, y] in CSS px, move(dx, dy, {fine, W, H}) (writes through the
//          writers given to it), label}
//
// A finger takes the nearest node (anywhere on the canvas: no need to hit it exactly) and moves it by its travel
// (relative, never a jump). Two fingers or hold-then-drag: fine. Double tap: that node's params back to the set.
// Long press: the inspector of its first param. Each drag is one undo step.

import { drag, h, haptic, inspect, toast } from '../ui.js';
import { writer } from '../widgets/core.js';
import { canvas } from './util.js';

export function nodeCanvas(ctx, { cls = '', nodes, draw, label, sticky = false }) {
  const cv = canvas('kx-nc-cv');
  const el = h('div', { class: `kx-nc ${cls}`.trim(), role: 'group', 'aria-label': label ?? 'Curve' }, cv);
  const writers = new Map();
  const W = (id) => { if (!writers.has(id)) writers.set(id, writer(ctx, id, 'nodes')); return writers.get(id); };
  const state = { active: null, selected: nodes[0]?.key ?? null, hover: null };
  let redraw = () => {};

  const pick = (x, y) => {
    const r = cv.getBoundingClientRect();
    const px = x - r.left, py = y - r.top;
    let best = null, bd = Infinity;
    for (const n of nodes) {
      if (n.hidden?.()) continue;
      const [nx, ny] = n.pos(r.width, r.height);
      const d = Math.hypot(nx - px, (ny - py) * (n.yWeight ?? 1));
      if (d < bd) { bd = d; best = n; }
    }
    if (sticky && bd > 48) return nodes.find((n) => n.key === state.selected) ?? best;
    return best;
  };

  let downAt = null;
  el.addEventListener('pointerdown', (e) => { downAt = { x: e.clientX, y: e.clientY }; }, true);
  drag(el, {
    onStart: (e) => {
      const n = pick(e.clientX, e.clientY);
      state.active = n;
      if (!n) return;
      state.selected = n.key;
      ctx.store.begin();
      for (const id of n.ids) W(id).begin?.();
      el.classList.add('is-touched');
      redraw();
    },
    onMove: (dx, dy, { fine }) => {
      const n = state.active;
      if (!n) return;
      const r = cv.getBoundingClientRect();
      n.move(dx, dy, { fine, W: r.width, H: r.height, w: W });
      redraw();
    },
    onEnd: () => {
      if (state.active) ctx.store.end();
      state.active = null;
      el.classList.remove('is-touched');
      redraw();
    },
    onTap: (e) => {
      const n = pick(e.clientX, e.clientY);
      if (n) { state.selected = n.key; redraw(); n.tap?.(); }
    },
  });
  // double tap: the node back to the set (only for a tap that did not move)
  let last = -Infinity, lastKey = null;
  el.addEventListener('pointerup', (e) => {
    if (!downAt || Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y) > 10) { last = -Infinity; return; }
    const n = pick(e.clientX, e.clientY);
    const now = performance.now();
    if (n && now - last < 300 && lastKey === n.key) {
      last = -Infinity;
      ctx.store.resetAll(n.ids);
      haptic(true);
      toast(`${n.label ?? ctx.params.get(n.ids[0]).label}: the set's value`);
    } else { last = now; lastKey = n?.key ?? null; }
  });
  let lp = 0, lx = 0, ly = 0;
  el.addEventListener('pointerdown', (e) => {
    lx = e.clientX; ly = e.clientY;
    clearTimeout(lp);
    lp = setTimeout(() => { const n = pick(lx, ly); if (n) { haptic(true); inspect(n.ids[0]); } }, 520);
  });
  el.addEventListener('pointermove', (e) => { if (Math.hypot(e.clientX - lx, e.clientY - ly) > 8) clearTimeout(lp); });
  el.addEventListener('pointerup', () => clearTimeout(lp));
  el.addEventListener('pointercancel', () => clearTimeout(lp));
  el.addEventListener('contextmenu', (e) => e.preventDefault());
  ctx.own(() => clearTimeout(lp));

  const api = {
    el, cv, state, nodes,
    setRedraw(fn) { redraw = fn; },
    selected: () => nodes.find((n) => n.key === state.selected),
    select(key) { state.selected = key; redraw(); },
    draw: () => draw?.(api),
  };
  return api;
}

/** Move a param by a fraction of its normalised range (relative). */
export function nudgeNorm(ctx, w, id, d) {
  w(id).set(ctx.store.get(id) + d);
}
