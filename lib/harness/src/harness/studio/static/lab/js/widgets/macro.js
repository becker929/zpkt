// macro(ctx, targets, {label, size, key, state, onState}) -> element
//
// One big knob that moves many params, each over its own range and along its own curve: at 0 every target sits at
// its `from`, at 1 at its `to`. Under the knob, a row per target: its name, its range as a lit stretch of a small
// track with a dot where it is now, its curve as a little graph, its value. Relative drag (260 px is the whole
// sweep; two fingers or hold-then-drag fine); a haptic tick at the ends and the middle. Double tap: the macro to 0
// (every target back to its `from`, which is the set's value unless you say otherwise). Long press: choose a target
// to inspect. Its position is kept (opts.key on this phone, or state/onState).
//
//   targets  ids or {id, from, to, curve}: from/to in the param's unit (from defaults to the set's value, to to the
//            far end of the tried range, else a quarter of the range up); curve 'lin' | 'exp' (slow start) |
//            'log' (fast start) | 's' | a power.
//   e.g. macro(ctx, ['kick.drive', 'rumble.drive', {id: 'kick.colour', to: 7.6, curve: 's'}], {label: 'pressure'})

import { doubleTap, drag, h, haptic, s, longPress } from '../ui.js';
import { follow, shortLabel, stageColor } from './core.js';
import { setNorm, toNorm, toReal } from '../params.js';
import { chooser, keep } from './kit.js';

const CURVES = { lin: (t) => t, exp: (t) => Math.pow(t, 2.5), log: (t) => 1 - Math.pow(1 - t, 2.5), s: (t) => t * t * (3 - 2 * t) };
export const curveOf = (c) => (typeof c === 'number' ? (t) => Math.pow(t, c) : CURVES[c] ?? CURVES.lin);

export function macroTargets(ctx, targets) {
  return targets.map((t) => (typeof t === 'string' ? { id: t } : t)).map((t) => {
    const p = ctx.params.get(t.id);
    const from = t.from ?? p.set ?? p.min;
    let to = t.to;
    if (to == null) {
      if (p.tried) to = Math.abs(p.tried[1] - from) >= Math.abs(p.tried[0] - from) ? p.tried[1] : p.tried[0];
      else to = toReal(p, Math.min(1, setNorm(p) + 0.25));
    }
    return { id: t.id, p, from, to, curve: t.curve ?? 'lin', n0: toNorm(p, from), n1: toNorm(p, to), fn: curveOf(t.curve ?? 'lin') };
  });
}

const A0 = -135, A1 = 135;
const pt = (r, deg) => { const a = (deg - 90) * Math.PI / 180; return [60 + r * Math.cos(a), 60 + r * Math.sin(a)]; };
const arc = (r, a, b) => {
  if (Math.abs(b - a) < 0.01) return '';
  const [x0, y0] = pt(r, a), [x1, y1] = pt(r, b);
  return `M${x0.toFixed(2)} ${y0.toFixed(2)}A${r} ${r} 0 ${b - a > 180 ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
};

export function macro(ctx, targets, { label = 'macro', size = 128, key, state, onState } = {}) {
  const T = macroTargets(ctx, targets);
  const kept = keep({ key, state, onState }, { m: 0 });
  const S = kept.state;
  const value = s('path', { class: 'mc-value' });
  const cap = s('g', { class: 'mc-cap' },
    s('circle', { cx: 60, cy: 60, r: 30, class: 'mc-body' }), s('circle', { cx: 60, cy: 60, r: 30, class: 'mc-knurl' }),
    s('circle', { cx: 60, cy: 60, r: 22, class: 'mc-face' }), s('line', { x1: 60, y1: 60, x2: 60, y2: 36, class: 'mc-pointer' }));
  const ticks = Array.from({ length: 21 }, (_, i) => {
    const a = A0 + (A1 - A0) * (i / 20);
    const [x0, y0] = pt(59, a), [x1, y1] = pt(i % 10 === 0 ? 54 : i % 5 === 0 ? 55.5 : 57, a);
    return s('line', { x1: x0, y1: y0, x2: x1, y2: y1, class: 'mc-tick' });
  });
  // each target's own little arc inside the ring, so the knob shows them all moving
  const inner = T.slice(0, 5).map((t, i) => s('path', { class: 'mc-t', style: { '--c': stageColor(t.p), opacity: 0.9 - i * 0.1 } }));
  const svg = s('svg', { viewBox: '0 0 120 120', class: 'mc-svg', 'aria-hidden': 'true' },
    ...ticks, s('path', { class: 'mc-track', d: arc(49, A0, A1) }), value, ...inner, cap);
  const dial = h('div', { class: 'mc-dial' }, svg);
  const read = h('div', { class: 'lcd-s mc-read' });
  const rows = T.map((t) => {
    const lo = Math.min(t.n0, t.n1), hi = Math.max(t.n0, t.n1);
    const dot = h('i', { class: 'mc-dot' });
    const val = h('span', { class: 'mc-val' });
    const pts = Array.from({ length: 13 }, (_, i) => `${(i / 12) * 22 + 1},${13 - t.fn(i / 12) * 12}`).join(' ');
    const row = h('div', { class: 'mc-row', style: { '--c': stageColor(t.p), '--lo': `${lo * 100}%`, '--hi': `${hi * 100}%` } },
      h('span', { class: 'mc-name', text: shortLabel(t.p) }),
      h('span', { class: 'mc-bar' }, h('i', { class: 'mc-range' }), dot),
      s('svg', { viewBox: '0 0 24 14', class: 'mc-curve', 'aria-hidden': 'true' }, s('polyline', { points: pts })),
      val);
    follow(ctx, t.id, (v, _r, text) => { dot.style.left = `${(v * 100).toFixed(2)}%`; val.textContent = text; row.classList.toggle('is-set', ctx.store.isSet(t.id)); });
    return row;
  });
  const el = h('div', { class: 'w-macro', role: 'slider', tabindex: '0', 'aria-label': label, dataset: { param: T.map((t) => t.id).join(' ') }, style: { '--size': `${size}px` } },
    h('div', { class: 'mc-head' }, h('span', { class: 'w-label', text: label }), read), dial, h('div', { class: 'mc-rows' }, ...rows));

  const show = () => {
    const a = A0 + (A1 - A0) * S.m;
    value.setAttribute('d', arc(49, A0, a));
    cap.setAttribute('transform', `rotate(${a} 60 60)`);
    inner.forEach((path, i) => path.setAttribute('d', arc(43 - i * 3, A0, A0 + (A1 - A0) * T[i].fn(S.m))));
    read.textContent = `${Math.round(S.m * 100)}`;
    el.setAttribute('aria-valuetext', `${Math.round(S.m * 100)} percent`);
    el.classList.toggle('is-set', S.m === 0);
  };
  const apply = () => {
    for (const t of T) ctx.store.set(t.id, t.n0 + (t.n1 - t.n0) * t.fn(S.m), { source: 'macro' });
  };
  const move = (m) => {
    const before = S.m;
    S.m = Math.max(0, Math.min(1, m));
    if ([0, 0.5, 1].some((x) => (before - x) * (S.m - x) < 0 || (S.m === x && before !== x))) haptic(S.m !== 0.5);
    apply(); show();
  };
  drag(dial, {
    onStart: () => { ctx.store.begin(); el.classList.add('is-touched'); },
    onMove: (dx, dy) => move(S.m + (dx - dy) / 260),
    onEnd: () => { ctx.store.end(); el.classList.remove('is-touched'); kept.save(); },
  });
  doubleTap(dial, () => { ctx.store.begin(); move(0); ctx.store.end(); kept.save(); });
  longPress(dial, () => { if (!ctx.local) chooser(ctx, T.map((t) => t.id), label); });
  el.addEventListener('keydown', (e) => {
    const d = { ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1 }[e.key];
    if (d) { e.preventDefault(); ctx.store.begin(); move(S.m + d * 0.02); ctx.store.end(); kept.save(); }
  });
  show();
  return el;
}
