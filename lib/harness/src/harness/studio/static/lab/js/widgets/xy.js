// xyPad(ctx, [idX, idY], {size, height, label, trail}) -> element
//
// Two params on one square: X across, Y up. A glowing puck with a fading trail of where it has been (modulation
// draws the trail too), crosshair lines to both axes, the set's values as an acid cross, the ranges experiments
// tried as a pale box. Drag anywhere on the pad, relative (the puck never jumps to the finger): one finger across
// the pad is the whole range, two fingers or hold-then-drag is fine. Double tap: both back to the set. Long press:
// choose which of the two to inspect. Tap an axis label to inspect that one.
//
//   size     the pad's width in px (default 300; it shrinks to fit its box)
//   height   the pad's height (default: square)
//   trail    false for no trail

import { drag, h, inspect } from '../ui.js';
import { follow, normOf, shortLabel, stageColor } from './core.js';
import { setNorm } from '../params.js';
import { fitCanvas, hexOf, rgba, HEX, tick, touches, writers } from './kit.js';

export function xyPad(ctx, ids, { size = 300, height, label, trail = true } = {}) {
  const [ix, iy] = ids;
  const px = ctx.params.get(ix), py = ctx.params.get(iy);
  const gw = writers(ctx, [ix, iy], 'xy');
  const col = hexOf(px);
  const cv = h('canvas', { class: 'xy-cv' });
  const pad = h('div', { class: 'xy-pad' }, cv);
  const rx = h('span', { class: 'lcd-s' }), ry = h('span', { class: 'lcd-s' });
  const axis = (p, tag, read, id) => h('button', {
    type: 'button', class: 'xy-ax', onclick: () => { if (!ctx.local) inspect(id); },
  }, h('span', { class: 'xy-name' }, h('i', { text: tag }), h('span', { class: 'w-label', text: shortLabel(p) })), read);
  const el = h('div', {
    class: 'w-xy', dataset: { param: ids.join(' ') },
    style: { '--w': `${size}px`, '--ar': String(size / (height ?? size)), '--c': stageColor(px) },
  },
  label ? h('div', { class: 'w-label xy-title', text: label }) : null,
  h('div', { class: 'xy-head' }, axis(px, 'X', rx, ix), axis(py, 'Y', ry, iy)),
  pad);

  const st = { x: 0, y: 0, bx: 0, by: 0, dirty: true, touched: false };
  const pts = [];
  const sx = setNorm(px), sy = setNorm(py);
  const tried = (p) => (p.tried ? [normOf(p, p.tried[0]), normOf(p, p.tried[1])].sort((a, b) => a - b) : null);
  const tx = tried(px), ty = tried(py);

  follow(ctx, ix, (v, _r, text) => { st.x = v; st.bx = ctx.store.get(ix); rx.textContent = text; st.dirty = true; mark(); });
  follow(ctx, iy, (v, _r, text) => { st.y = v; st.by = ctx.store.get(iy); ry.textContent = text; st.dirty = true; mark(); });
  function mark() {
    el.classList.toggle('is-set', ctx.store.isSet(ix) && ctx.store.isSet(iy));
    rx.parentElement.classList.toggle('is-set', ctx.store.isSet(ix));
    ry.parentElement.classList.toggle('is-set', ctx.store.isSet(iy));
  }

  drag(pad, {
    onStart: () => { gw.begin(); st.touched = true; el.classList.add('is-touched'); },
    onMove: (dx, dy) => {
      const r = pad.getBoundingClientRect();
      gw.add(0, dx / Math.max(80, r.width - 24));
      gw.add(1, -dy / Math.max(80, r.height - 24));
    },
    onEnd: () => { gw.end(); st.touched = false; el.classList.remove('is-touched'); st.dirty = true; },
  });
  touches(pad, ctx, [ix, iy], { name: label ?? `${shortLabel(px)} x ${shortLabel(py)}` });

  tick(ctx, (t) => {
    const now = t / 1000;
    if (trail && st.dirty) {
      const lp = pts.at(-1);
      if (!lp || Math.abs(lp.x - st.x) + Math.abs(lp.y - st.y) > 0.002) pts.push({ x: st.x, y: st.y, t: now });
    }
    while (pts.length && (now - pts[0].t > 1.4 || pts.length > 120)) pts.shift();
    if (!st.dirty && !pts.length) return;
    st.dirty = false;
    draw(now);
  }, el);

  function draw(now) {
    const { g, W, H, d } = fitCanvas(cv);
    const m = 14 * d;
    const X = (v) => m + v * (W - 2 * m), Y = (v) => H - m - v * (H - 2 * m);
    g.clearRect(0, 0, W, H);
    // tried box (or band)
    g.fillStyle = 'rgba(198,255,61,0.10)';
    g.strokeStyle = 'rgba(198,255,61,0.35)';
    g.lineWidth = d;
    if (tx || ty) {
      const x0 = tx ? X(tx[0]) : m, x1 = tx ? X(tx[1]) : W - m;
      const y0 = ty ? Y(ty[1]) : m, y1 = ty ? Y(ty[0]) : H - m;
      g.fillRect(x0, y0, Math.max(d, x1 - x0), Math.max(d, y1 - y0));
      g.setLineDash([3 * d, 3 * d]);
      g.strokeRect(x0, y0, Math.max(d, x1 - x0), Math.max(d, y1 - y0));
      g.setLineDash([]);
    }
    // the set: an acid cross
    const cx = X(sx), cy = Y(sy);
    g.strokeStyle = HEX.acid; g.lineWidth = 1.6 * d;
    g.beginPath(); g.moveTo(cx - 7 * d, cy); g.lineTo(cx + 7 * d, cy); g.moveTo(cx, cy - 7 * d); g.lineTo(cx, cy + 7 * d); g.stroke();
    // trail
    if (pts.length > 1) {
      g.lineCap = 'round'; g.lineJoin = 'round';
      for (let i = 1; i < pts.length; i++) {
        const a = Math.max(0, 1 - (now - pts[i].t) / 1.4);
        g.strokeStyle = rgba(col, a * 0.85);
        g.lineWidth = (2 + 5 * a) * d;
        g.beginPath(); g.moveTo(X(pts[i - 1].x), Y(pts[i - 1].y)); g.lineTo(X(pts[i].x), Y(pts[i].y)); g.stroke();
      }
    }
    // crosshair lines to the axes
    const qx = X(st.x), qy = Y(st.y);
    g.strokeStyle = rgba(col, 0.35); g.lineWidth = d;
    g.beginPath(); g.moveTo(qx, H); g.lineTo(qx, qy); g.moveTo(0, qy); g.lineTo(qx, qy); g.stroke();
    // the knob's own value when modulation moves the puck away from it
    if (Math.abs(st.bx - st.x) + Math.abs(st.by - st.y) > 0.004) {
      g.strokeStyle = 'rgba(89,199,255,0.7)'; g.lineWidth = 1.4 * d;
      g.beginPath(); g.arc(X(st.bx), Y(st.by), 6 * d, 0, Math.PI * 2); g.stroke();
    }
    // the puck
    const r = (st.touched ? 13 : 11) * d;
    const grd = g.createRadialGradient(qx - r * 0.3, qy - r * 0.3, r * 0.1, qx, qy, r);
    grd.addColorStop(0, '#ffffff'); grd.addColorStop(0.35, col); grd.addColorStop(1, rgba(col, 0.25));
    g.shadowColor = col; g.shadowBlur = 16 * d;
    g.fillStyle = grd; g.beginPath(); g.arc(qx, qy, r, 0, Math.PI * 2); g.fill();
    g.shadowBlur = 0;
    g.strokeStyle = '#000'; g.lineWidth = 1.5 * d; g.stroke();
  }
  return el;
}
