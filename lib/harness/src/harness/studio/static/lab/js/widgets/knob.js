// A hardware knob: knurled rim, 270 degree sweep, a value arc in the stage's colour (from zero for a bipolar dB
// knob), the set's value as an acid dot, the range experiments tried as a pale band, an amber LCD readout.
// Drag up or right to raise (one finger: 220 px is the whole range; two fingers or hold-then-drag: fine).
// Double tap: back to the set. Long press: the inspector.

import { drag, h, s, standard } from '../ui.js';
import { follow, normOf, shortLabel, stageColor, writer } from './core.js';
import { setNorm } from '../params.js';

const A0 = -135, A1 = 135;
const rad = (deg) => (deg - 90) * Math.PI / 180;
const pt = (r, deg) => [50 + r * Math.cos(rad(deg)), 50 + r * Math.sin(rad(deg))];
const ang = (v) => A0 + (A1 - A0) * v;

function arc(r, a, b) {
  if (Math.abs(b - a) < 0.01) return '';
  const [x0, y0] = pt(r, Math.min(a, b)), [x1, y1] = pt(r, Math.max(a, b));
  const large = Math.abs(b - a) > 180 ? 1 : 0;
  return `M${x0.toFixed(2)} ${y0.toFixed(2)}A${r} ${r} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

export function knob(ctx, id, { size = 76, skin = 'steel', label } = {}) {
  const p = ctx.params.get(id);
  const w = writer(ctx, id, 'knob');
  const bipolar = p.min < 0 && p.max > 0 && p.scale !== 'log';
  const zero = bipolar ? normOf(p, 0) : 0;
  const ticks = Array.from({ length: 11 }, (_, i) => {
    const [x0, y0] = pt(47, ang(i / 10)), [x1, y1] = pt(i % 5 === 0 ? 42 : 44, ang(i / 10));
    return s('line', { x1: x0, y1: y0, x2: x1, y2: y1, class: 'k-tick' });
  });
  const tried = p.tried ? s('path', { class: 'k-tried', d: arc(39, ang(normOf(p, p.tried[0])), ang(normOf(p, p.tried[1]))) }) : null;
  const value = s('path', { class: 'k-value' });
  const setDot = s('circle', { class: 'k-set', r: 2.6 });
  const [sx, sy] = pt(39, ang(setNorm(p)));
  setDot.setAttribute('cx', sx); setDot.setAttribute('cy', sy);
  const pointer = s('line', { class: 'k-pointer', x1: 50, y1: 50, x2: 50, y2: 24 });
  const cap = s('g', { class: 'k-cap' },
    s('circle', { cx: 50, cy: 50, r: 30, class: 'k-body' }),
    s('circle', { cx: 50, cy: 50, r: 30, class: 'k-knurl' }),
    s('circle', { cx: 50, cy: 50, r: 22, class: 'k-face' }),
    pointer);
  const svg = s('svg', { viewBox: '0 0 100 100', class: 'k-svg', 'aria-hidden': 'true' },
    ...ticks, s('path', { class: 'k-track', d: arc(39, A0, A1) }), tried, value, setDot, cap);
  const readout = h('div', { class: 'k-read lcd-s' });
  const el = h('div', {
    class: `w-knob skin-${skin}`, role: 'slider', tabindex: '0', 'aria-label': p.label,
    dataset: { param: id }, style: { '--size': `${size}px`, '--c': stageColor(p) },
  }, h('div', { class: 'w-label', text: label ?? shortLabel(p) }), h('div', { class: 'k-dial' }, svg), readout);

  follow(ctx, id, (v, _real, text) => {
    value.setAttribute('d', arc(39, ang(Math.min(v, zero)), ang(Math.max(v, zero))));
    cap.setAttribute('transform', `rotate(${ang(v)} 50 50)`);
    readout.textContent = text;
    el.setAttribute('aria-valuetext', text);
    el.classList.toggle('is-set', ctx.store.isSet(id));
  });

  const dial = el.querySelector('.k-dial');
  drag(dial, {
    onStart: () => { w.begin(); el.classList.add('is-touched'); },
    onMove: (dx, dy) => w.add((dx - dy) / 220),
    onEnd: () => { w.end(); el.classList.remove('is-touched'); },
  });
  standard(dial, ctx.store, id);
  el.addEventListener('keydown', (e) => {
    const step = e.shiftKey ? 0.1 : 0.01;
    if (e.key === 'ArrowUp' || e.key === 'ArrowRight') { w.begin(); w.add(step); w.end(); e.preventDefault(); }
    if (e.key === 'ArrowDown' || e.key === 'ArrowLeft') { w.begin(); w.add(-step); w.end(); e.preventDefault(); }
  });
  return el;
}
