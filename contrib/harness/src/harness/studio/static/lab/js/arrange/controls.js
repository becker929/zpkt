// The arrange surface's own controls: the length dial (with the 33-50 s target), segmented selectors for the enum
// params (a hardware rotary switch laid flat: one lit LED per position), and LED buttons for the surface's modes.

import { drag, h, haptic, s, standard } from '../ui.js';
import { follow, writer } from '../widgets/core.js';
import { toNorm } from '../params.js';
import { BAR_S, TARGET } from './model.js';

const A0 = -135, A1 = 135;
const rad = (deg) => (deg - 90) * Math.PI / 180;
const pt = (r, deg) => [60 + r * Math.cos(rad(deg)), 60 + r * Math.sin(rad(deg))];
function arc(r, a, b) {
  if (Math.abs(b - a) < 0.01) return '';
  const [x0, y0] = pt(r, Math.min(a, b)), [x1, y1] = pt(r, Math.max(a, b));
  return `M${x0.toFixed(2)} ${y0.toFixed(2)}A${r} ${r} 0 ${Math.abs(b - a) > 180 ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

/** The Short's length: a big detented dial, 16-40 bars on the 4-bar grid, the 33-50 s zone lit, seconds below. */
export function lengthDial(ctx, id = 'arr.length', { size = 150 } = {}) {
  const p = ctx.params.get(id);
  const w = writer(ctx, id, 'dial');
  const steps = Math.round((p.max - p.min) / (p.step ?? 4));
  const ang = (bars) => A0 + (A1 - A0) * (bars - p.min) / (p.max - p.min);
  const lo = TARGET.lo / BAR_S, hi = TARGET.hi / BAR_S;
  const ticks = [];
  for (let k = 0; k <= steps; k++) {
    const bars = p.min + k * (p.step ?? 4);
    const [x0, y0] = pt(54, ang(bars)), [x1, y1] = pt(48, ang(bars));
    ticks.push(s('line', { x1: x0, y1: y0, x2: x1, y2: y1, class: 'ld-tick' }));
    const [tx, ty] = pt(42 - 0, ang(bars));
    if (k % 2 === 0) ticks.push(s('text', { x: tx, y: ty + 3, class: 'ld-num', text: String(bars) }));
  }
  const value = s('path', { class: 'ld-value' });
  const [sx, sy] = pt(57, ang(p.set));
  const pointer = s('line', { class: 'ld-pointer', x1: 60, y1: 60, x2: 60, y2: 33 });
  const cap = s('g', { class: 'ld-cap' },
    s('circle', { cx: 60, cy: 60, r: 29, class: 'ld-body' }),
    s('circle', { cx: 60, cy: 60, r: 29, class: 'ld-knurl' }),
    s('circle', { cx: 60, cy: 60, r: 21, class: 'ld-face' }), pointer);
  const svg = s('svg', { viewBox: '0 0 120 120', class: 'ld-svg', 'aria-hidden': 'true' },
    s('path', { class: 'ld-track', d: arc(57, A0, A1) }),
    s('path', { class: 'ld-zone', d: arc(57, ang(lo), ang(Math.min(hi, p.max))) }),
    value, ...ticks, s('circle', { class: 'ld-set', cx: sx, cy: sy, r: 2.8 }), cap);
  const bars = h('b', { class: 'ld-bars' });
  const secs = h('span', { class: 'ld-secs' });
  const led = h('span', { class: 'ld-led' });
  const el = h('div', { class: 'arr-ld', role: 'slider', tabindex: '0', 'aria-label': p.label, dataset: { param: id }, style: { '--size': `${size}px` } },
    h('div', { class: 'ld-dial' }, svg),
    h('div', { class: 'ld-read' }, h('div', { class: 'ld-lcd' }, bars, h('i', { text: 'BARS' })), h('div', { class: 'ld-sub' }, led, secs)));
  let wasIn = null;
  follow(ctx, id, (v, real) => {
    value.setAttribute('d', arc(57, A0, ang(real)));
    cap.setAttribute('transform', `rotate(${ang(real)} 60 60)`);
    bars.textContent = String(real);
    const sec = real * BAR_S;
    const inT = sec >= TARGET.lo && sec <= TARGET.hi;
    secs.textContent = `${sec.toFixed(1)} s`;
    led.textContent = inT ? 'IN 33-50 s' : sec < TARGET.lo ? 'TOO SHORT' : 'TOO LONG';
    el.classList.toggle('is-in', inT);
    el.classList.toggle('is-set', ctx.store.isSet(id));
    if (wasIn !== null && wasIn !== inT) haptic(true);
    wasIn = inT;
  });
  const dial = el.querySelector('.ld-dial');
  let acc = 0, start = 0, last = 0;
  drag(dial, {
    onStart: () => { w.begin(); acc = 0; start = last = ctx.store.real(id); el.classList.add('is-touched'); },
    onMove: (dx, dy) => {
      acc += (dx - dy);
      const real = Math.max(p.min, Math.min(p.max, Math.round((start + acc / 34 * (p.step ?? 4)) / (p.step ?? 4)) * (p.step ?? 4)));
      if (real !== last) { last = real; w.set(toNorm(p, real)); haptic(); }
    },
    onEnd: () => { w.end(); el.classList.remove('is-touched'); },
  });
  standard(dial, ctx.store, id);
  el.addEventListener('keydown', (e) => {
    const d = { ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1 }[e.key];
    if (!d) return;
    w.begin(); w.set(toNorm(p, Math.max(p.min, Math.min(p.max, ctx.store.real(id) + d * (p.step ?? 4))))); w.end(); e.preventDefault();
  });
  return el;
}

/** A row of lit positions for an enum param (or a toggle): tap one to select it. */
export function segmented(ctx, id, { label, icons = [], names } = {}) {
  const p = ctx.params.get(id);
  const opts = names ?? (p.scale === 'toggle' ? [p.off ?? 'Off', p.on ?? 'On'] : p.options);
  const w = writer(ctx, id, 'seg');
  const btns = opts.map((name, k) => {
    const b = h('button', { type: 'button', class: 'seg-b', dataset: { k } },
      h('i', { class: 'seg-led' }),
      icons[k] ? s('svg', { viewBox: '0 0 24 24', class: 'seg-ic', 'aria-hidden': 'true' }) : null,
      h('span', { text: name }));
    if (icons[k]) b.querySelector('svg').innerHTML = icons[k];
    b.addEventListener('click', () => {
      const n = p.scale === 'toggle' ? k : toNorm(p, k);
      w.begin(); w.set(n); w.end(); haptic();
    });
    return b;
  });
  const el = h('div', { class: 'arr-seg', role: 'radiogroup', 'aria-label': p.label, dataset: { param: id } },
    h('div', { class: 'w-label', text: label ?? p.short ?? p.label }), h('div', { class: 'seg-row' }, ...btns));
  const setK = Math.round(p.scale === 'toggle' ? (p.set ? 1 : 0) : p.set ?? 0);
  btns[setK]?.classList.add('is-setpos');
  follow(ctx, id, (_v, real) => {
    const k = Math.round(real);
    btns.forEach((b, j) => { b.classList.toggle('is-on', j === k); b.setAttribute('aria-checked', String(j === k)); });
  });
  for (const b of btns) standard(b, ctx.store, id, { double: false });
  return el;
}

/** A latching LED button for the surface's own modes (not a param). */
export function ledButton(text, { on = false, onToggle, cls = '' } = {}) {
  const b = h('button', { type: 'button', class: `arr-led ${cls}`.trim(), 'aria-pressed': String(on) }, h('i', { class: 'led' }), h('span', { text }));
  b.addEventListener('click', () => {
    const next = b.getAttribute('aria-pressed') !== 'true';
    b.setAttribute('aria-pressed', String(next));
    haptic();
    onToggle?.(next);
  });
  b.set = (v) => b.setAttribute('aria-pressed', String(!!v));
  return b;
}

export const ICONS = {
  wuh: '<path d="M4 12c2-5 4-5 6 0s4 5 6 0 3-4 4-2"/>',
  silence: '<path d="M7 7h10v10H7z"/>',
  straight: '<path d="M4 12h12M12 7l5 5-5 5"/>',
};

