// stepGrid(ctx, ids, {steps, depth, labels, label, key, state, onState}) -> element
//
// A 16-step grid on the bar clock: one lane per param. Each lit cell throws its param up by `depth` (times the
// cell's level) for that 16th, on the beat, sample-timed from the engine's step clock (a modulation, not saved).
// Tap a cell to light or clear it; slide sideways to paint a run of cells; drag a cell up or down to set its level.
// The playhead walks the lanes while the transport runs. Beats are marked every four cells.
// The depth number box (drag or tap to type) sets how far a full cell throws.
//
//   steps    cells per lane (default 16: one bar of 16ths)
//   depth    0..1 of each param's range for a full cell (default 0.4)
//   key      save the pattern on this phone under this name; or state + onState(state) to keep it elsewhere
//   gate     () => boolean: the lanes play only while it says true (the bench's RUN)

import { h, haptic, longPress } from '../ui.js';
import { shortLabel, stageColor } from './core.js';
import { chooser, keep, later, localCtx, modSource } from './kit.js';
import { numberBox } from './numbox.js';

const OFFBEATS = (n) => Array.from({ length: n }, (_, i) => (i % 4 === 2 ? 1 : 0));

export function stepGrid(ctx, ids, { steps = 16, depth = 0.4, labels, label = 'step grid', key, state, onState, gate } = {}) {
  ids = [].concat(ids);
  const ps = ids.map((id) => ctx.params.get(id));
  const mod = modSource(ctx, 'steps');
  const at = later(ctx);
  const kept = keep({ key, state, onState }, { rows: ids.map(() => OFFBEATS(steps)), depth });
  const S = kept.state;
  while (S.rows.length < ids.length) S.rows.push(OFFBEATS(steps));

  const lctx = localCtx(ctx, [{ id: 'depth', label: 'Depth', short: 'Depth', unit: '%', min: 0, max: 100, set: depth * 100 }],
    { depth: S.depth }, (_id, v) => { S.depth = v; kept.save(); });
  const cells = [];
  const lanes = ids.map((id, r) => {
    const row = Array.from({ length: steps }, (_, c) => h('i', { class: `st-cell${c % 4 === 0 ? ' is-beat' : ''}`, dataset: { c } }, h('b')));
    cells.push(row);
    const lane = h('div', { class: 'st-cells', style: { '--steps': steps } }, ...row);
    wire(lane, r);
    const name = h('span', { class: 'st-name', text: labels?.[r] ?? shortLabel(ps[r]) });
    longPress(name, () => { if (!ctx.local) chooser(ctx, [id], shortLabel(ps[r])); });
    return h('div', { class: 'st-lane', style: { '--c': stageColor(ps[r]) } }, name, lane);
  });
  const el = h('div', { class: 'w-steps', dataset: { param: ids.join(' ') } },
    h('div', { class: 'st-head' }, h('span', { class: 'w-label', text: label }), numberBox(lctx, 'depth', { label: false, width: 78 })),
    ...lanes);

  const paint = (r) => cells[r].forEach((cell, c) => {
    const v = S.rows[r][c];
    cell.classList.toggle('is-on', v > 0);
    cell.style.setProperty('--lv', v.toFixed(2));
  });
  ids.forEach((_, r) => paint(r));

  function wire(lane, r) {
    lane.style.touchAction = 'none';
    let pid = null, c0 = -1, x0 = 0, y0 = 0, mode = null, paintTo = 0, lv0 = 0, rect = null;
    const col = (x) => Math.max(0, Math.min(steps - 1, Math.floor(((x - rect.left) / rect.width) * steps)));
    lane.addEventListener('pointerdown', (e) => {
      if (pid != null) return;
      pid = e.pointerId;
      try { lane.setPointerCapture(e.pointerId); } catch { /* synthetic pointer */ }
      rect = lane.getBoundingClientRect();
      c0 = col(e.clientX); x0 = e.clientX; y0 = e.clientY; mode = null;
      lv0 = S.rows[r][c0];
    });
    lane.addEventListener('pointermove', (e) => {
      if (e.pointerId !== pid) return;
      const dx = e.clientX - x0, dy = e.clientY - y0;
      if (!mode) {
        if (Math.hypot(dx, dy) < 6) return;
        mode = Math.abs(dx) > Math.abs(dy) ? 'paint' : 'level';
        paintTo = lv0 > 0 ? 0 : 1;
        if (mode === 'paint') { S.rows[r][c0] = paintTo; haptic(); }
      }
      if (mode === 'paint') {
        const c = col(e.clientX);
        if (S.rows[r][c] !== paintTo) { S.rows[r][c] = paintTo; haptic(); }
      } else {
        const v = Math.max(0, Math.min(1, (lv0 || 0.5) - dy / 80));
        S.rows[r][c0] = Math.round(v * 20) / 20;
      }
      paint(r);
    });
    const up = (e) => {
      if (e.pointerId !== pid) return;
      pid = null;
      if (!mode && e.type === 'pointerup') { S.rows[r][c0] = lv0 > 0 ? 0 : 1; haptic(); paint(r); }
      kept.save();
    };
    lane.addEventListener('pointerup', up);
    lane.addEventListener('pointercancel', up);
  }

  let now = -1;
  const show = (c) => {
    if (c === now) return;
    for (const row of cells) { if (now >= 0) row[now]?.classList.remove('is-now'); if (c >= 0) row[c]?.classList.add('is-now'); }
    now = c;
  };
  const e = ctx.engine;
  if (e?.onStep) {
    ctx.own(e.onStep((step, when) => {
      const c = step % steps;
      at(when, () => {
        if (!e.playing) return;
        if (gate && !gate()) { if (now >= 0) { show(-1); mod.clear(); } return; }
        show(c);
        const d = lctx.store.real('depth') / 100;
        ids.forEach((id, r) => mod.set(id, (S.rows[r][c] ?? 0) * d));
      });
    }));
  }
  if (e?.onStop) ctx.own(e.onStop(() => { show(-1); mod.clear(); }));
  return el;
}
