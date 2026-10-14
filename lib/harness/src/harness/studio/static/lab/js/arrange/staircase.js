// The hat staircase: four risers, one per layer, that you drag along the Short to where that layer enters. The
// steps' heights are the measured highs of the hats with those layers (the canonical Short's own A, AB, ABC and
// ABCD bars, or a masked bar for other sets; data/arrange-bars.json), so a layer that adds little shows as a low step. Anthony's rule sits under it:
// "a new layer has to add energy on its own"; a layer that enters alone and adds less than 2 dB of highs is flagged.

import { clamp, h, haptic, inspect, s } from '../ui.js';
import { toNorm } from '../params.js';
import { writer } from '../widgets/core.js';
import { LAYERS } from './model.js';
import { hatLevel } from './arranger.js';

const WHAT = {
  A: 'open offbeat hats (perc 2)',
  B: 'accented 16th closed hat (perc 1)',
  C: 'loud 8th rides (perc 2)',
  D: 'bright 16th closed hats (perc 2)',
};
const RULE_DB = 2;                 // highs a layer must add on its own

export function staircase(ctx, arranger, data) {
  const level = (set) => hatLevel(data, set, arranger.useShape);
  const svg = s('svg', { class: 'st-svg', viewBox: '0 0 360 170', preserveAspectRatio: 'none' });
  const list = h('div', { class: 'st-list' });
  const rule = h('p', { class: 'st-rule' },
    h('b', { text: 'The hat rule. ' }),
    '"Layers that are individually quieter cannot be added as independent new layers to raise energy. A new layer has to add energy on its own."');
  const el = h('div', { class: 'arr-st' }, h('div', { class: 'st-stage' }, svg), list, rule);
  const VW = 360, VH = 170, top = 14, bottom = 150, left = 10, right = 350;

  let drag = null;
  const render = () => {
    const pl = arranger.pl;
    if (!pl) return;
    const L = pl.L, X = (bar) => left + (right - left) * bar / L;
    // per bar: the hats now and their highs
    const hiOf = (set) => (set ? level(set).hi : -60);
    const Y = (db) => bottom - (bottom - top) * clamp((db + 44) / 18);
    svg.replaceChildren();
    // grid
    for (let b = 0; b <= L; b += 4) svg.append(s('line', { x1: X(b), x2: X(b), y1: top - 4, y2: bottom + 2, class: b % 8 ? 'st-g4' : 'st-g8' }));
    for (const db of [-40, -35, -30]) svg.append(s('line', { x1: left, x2: right, y1: Y(db), y2: Y(db), class: 'st-gh' }));
    // the steps: an area per bar at the highs of its hat set
    let d = `M${X(0)} ${bottom}`;
    for (const b of pl.bars) { const y = Y(hiOf(b.hats)); d += `L${X(b.i)} ${y}L${X(b.i + 1)} ${y}`; }
    d += `L${X(L)} ${bottom}Z`;
    svg.append(s('path', { d, class: 'st-area' }));
    // layer bands at the bottom: who plays where
    LAYERS.forEach((Lr, k) => {
      const y = bottom + 3 + k * 4;
      for (const b of pl.bars) if (b.hats.includes(Lr)) svg.append(s('rect', { x: X(b.i), y: y - 1, width: Math.max(0.5, X(1) - X(0) - 0.6), height: 3, class: `st-band st-${Lr}` }));
    });
    // risers
    const v = pl.values;
    const stack = new Map();                       // risers on one bar stack their caps downwards
    for (const Lr of LAYERS) {
      const bar = Math.min(L, Math.round(v[`hat${Lr}`]) - 1);
      const k = stack.get(bar) ?? 0;
      stack.set(bar, k + 1);
      const x = X(bar), cy = top - 3 + k * 21;
      const g = s('g', { class: `st-riser st-${Lr}${drag?.L === Lr ? ' is-on' : ''}` });
      g.append(s('line', { x1: x, x2: x, y1: top, y2: bottom, class: 'st-line' }));
      g.append(s('rect', { x: x - 11, y: cy - 9, width: 22, height: 18, rx: 4, class: 'st-cap' }));
      g.append(s('text', { x, y: cy + 1, class: 'st-letter', text: Lr }));
      svg.append(g);
    }
    // the list: each layer's entry and what it adds there
    list.replaceChildren(...LAYERS.map((Lr) => {
      const bar = Math.round(v[`hat${Lr}`]);
      const at = pl.bars[Math.min(L - 1, bar - 1)];
      const before = pl.bars[bar - 2]?.hats ?? '';
      const after = at?.hats ?? '';
      const others = LAYERS.filter((o) => o !== Lr && Math.round(v[`hat${o}`]) === bar);
      const alone = after.includes(Lr) && !others.some((o) => after.includes(o) && !before.includes(o));
      const addHi = after.includes(Lr) && !before.includes(Lr) ? hiOf(after) - hiOf(before) : null;
      const quiet = alone && addHi != null && addHi < RULE_DB && before;
      const lu = after.includes(Lr) && !before.includes(Lr) ? level(after).lufs - (before ? level(before).lufs : -70) : null;
      const heard = pl.bars.find((b) => b.i >= bar - 1 && b.hats.includes(Lr));
      const where = bar > L ? 'not in the Short' : !heard ? 'not heard' : heard.i + 1 > bar ? `bar ${bar} · heard from ${heard.i + 1}` : `bar ${bar}`;
      const row = h('div', { class: `st-row st-${Lr}${quiet ? ' is-quiet' : ''}${bar > L ? ' is-out' : ''}` },
        h('i', { class: 'st-chip', text: Lr }),
        h('div', { class: 'st-what' }, h('b', { text: where }), h('span', { text: WHAT[Lr] })),
        h('div', { class: 'st-db lcd-s', text: addHi == null ? '—' : !before ? 'FIRST' : `${addHi >= 0 ? '+' : ''}${addHi.toFixed(1)} dB` }),
        quiet ? h('em', { class: 'st-flag', text: 'adds too little alone' }) : others.length ? h('em', { class: 'st-with', text: `with ${others.join('+')}` }) : null);
      row.title = lu != null ? `${lu.toFixed(1)} LU louder` : '';
      return row;
    }));
  };

  // dragging a riser: grab near it anywhere on the stage
  svg.style.touchAction = 'none';
  const toBars = (px) => px / svg.getBoundingClientRect().width * VW / ((right - left) / (arranger.pl?.L || 20));
  svg.addEventListener('pointerdown', (e) => {
    const pl = arranger.pl; if (!pl) return;
    const r = svg.getBoundingClientRect();
    const xv = (e.clientX - r.left) / r.width * VW;
    const X = (bar) => left + (right - left) * bar / pl.L;
    let best = null, bd = 26;
    for (const Lr of LAYERS) {
      const dd = Math.abs(X(Math.round(pl.values[`hat${Lr}`]) - 1) - xv);
      if (dd < bd || (dd === bd && best && e.clientX > 0)) { bd = dd; best = Lr; }
    }
    if (!best) return;
    try { svg.setPointerCapture(e.pointerId); } catch { /* synthetic */ }
    const id = `arr.hat${best}`;
    drag = { L: best, id, pid: e.pointerId, x0: e.clientX, lx: e.clientX, start: ctx.store.real(id), last: ctx.store.real(id), w: writer(ctx, id, 'stairs'), moved: false, t0: performance.now(), same: LAYERS.filter((o) => Math.round(pl.values[`hat${o}`]) === Math.round(pl.values[`hat${best}`])) };
    drag.timer = setTimeout(() => { if (drag && !drag.moved) { haptic(true); inspect(id); drag = null; } }, 480);
    render();
  });
  svg.addEventListener('pointermove', (e) => {
    if (!drag || e.pointerId !== drag.pid) return;
    if (!drag.moved) {
      if (Math.abs(e.clientX - drag.x0) < 5) return;
      drag.moved = true; clearTimeout(drag.timer);
      if (drag.same.length > 1) {                      // risers on one bar: right takes the latest, left the earliest
        drag.L = e.clientX > drag.x0 ? drag.same.at(-1) : drag.same[0];
        drag.id = `arr.hat${drag.L}`; drag.start = drag.last = ctx.store.real(drag.id); drag.w = writer(ctx, drag.id, 'stairs');
      }
      drag.w.begin();
    }
    const p = ctx.params.get(drag.id);
    const real = clamp(Math.round(drag.start + toBars(e.clientX - drag.x0)), p.min, p.max);
    if (real !== drag.last) { drag.last = real; drag.w.set(toNorm(p, real)); haptic(Math.abs(real - p.set) < 0.5); }
  });
  const up = (e) => {
    if (!drag || e.pointerId !== drag.pid) return;
    clearTimeout(drag.timer);
    if (drag.moved) drag.w.end();
    drag = null; render();
  };
  svg.addEventListener('pointerup', up);
  svg.addEventListener('pointercancel', up);
  ctx.own(arranger.onChange(render));
  render();
  return el;
}
