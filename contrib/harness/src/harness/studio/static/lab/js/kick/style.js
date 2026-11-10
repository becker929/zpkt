// Distortion: COLDFIRE on the kick bus and the Decapitator on the rumble. The Decapitator's style is a five-position
// chicken-head rotary (A E N T P), each position with a drawing of its curve; turn it (drag) or tap a position.

import { drag, h, haptic, s, standard } from '../ui.js';
import { toNorm } from '../params.js';
import { follow, writer } from '../widgets/core.js';
import { knob } from '../widgets/knob.js';
import { toggle } from '../widgets/fader.js';
import { SHAPES, STYLES } from './dsp.js';
import { panel } from './util.js';

const ANG = [-64, -32, 0, 32, 64];
const CX = 120, CY = 126;
const NAMES = ['Ampex: tape, round', 'EMI: console, lean', 'Neve: transformer, thick', 'Thermionic: hot, flat-topped', 'Pentode: hard, fizzing'];
const pt = (r, deg) => [CX + r * Math.sin((deg * Math.PI) / 180), CY - r * Math.cos((deg * Math.PI) / 180)];

function iconPath(name, x0, y0, size) {
  const f = SHAPES[name];
  let d = '';
  for (let i = 0; i <= 24; i++) {
    const x = (i / 24) * 2 - 1;
    const y = Math.max(-1.1, Math.min(1.1, f(x * 3)));
    d += `${i ? 'L' : 'M'}${(x0 + ((x + 1) / 2) * size).toFixed(1)} ${(y0 + ((1 - y) / 2) * size).toFixed(1)}`;
  }
  return d;
}

export function styleRotary(ctx) {
  const id = 'rumble.style';
  const p = ctx.params.get(id);
  const w = writer(ctx, id, 'rotary');
  const positions = STYLES.map((name, i) => {
    const [ix, iy] = pt(106, ANG[i]);
    const [lx, ly] = pt(78, ANG[i]);
    const [t0x, t0y] = pt(47, ANG[i]), [t1x, t1y] = pt(56, ANG[i]);
    return s('g', { class: 'kx-rot-pos', dataset: { i: String(i) } },
      s('line', { x1: t0x, y1: t0y, x2: t1x, y2: t1y, class: 'kx-rot-tick' }),
      s('rect', { x: ix - 14, y: iy - 14, width: 28, height: 28, rx: 5, class: 'kx-rot-box' }),
      s('path', { d: iconPath(name, ix - 10, iy - 10, 20), class: 'kx-rot-icon' }),
      s('text', { x: lx, y: ly + 4, class: 'kx-rot-letter', 'text-anchor': 'middle' }, name));
  });
  const head = s('g', { class: 'kx-rot-head' },
    s('path', { d: `M${CX} ${CY - 58} C ${CX + 9} ${CY - 43}, ${CX + 29} ${CY - 25}, ${CX + 29} ${CY} A 29 29 0 1 1 ${CX - 29} ${CY} C ${CX - 29} ${CY - 25}, ${CX - 9} ${CY - 43}, ${CX} ${CY - 58} Z`, class: 'kx-rot-body' }),
    s('line', { x1: CX, y1: CY - 52, x2: CX, y2: CY - 14, class: 'kx-rot-line' }),
    s('circle', { cx: CX, cy: CY, r: 9, class: 'kx-rot-cap' }));
  const svg = s('svg', { viewBox: '0 0 240 160', class: 'kx-rot-svg', 'aria-hidden': 'true' },
    s('circle', { cx: CX, cy: CY, r: 42, class: 'kx-rot-skirt' }), ...positions, head);
  const name = h('b', { class: 'kx-rot-name' });
  const el = h('div', { class: 'kx-rot', role: 'slider', tabindex: '0', 'aria-label': p.label, dataset: { kparam: id } }, svg, name);
  follow(ctx, id, (_v, real) => {
    const i = Math.round(real);
    head.setAttribute('transform', `rotate(${ANG[i]} ${CX} ${CY})`);
    positions.forEach((g, j) => g.classList.toggle('is-on', j === i));
    name.textContent = `${STYLES[i]} · ${NAMES[i]}`;
    el.classList.toggle('is-set', ctx.store.isSet(id));
    el.setAttribute('aria-valuetext', p.options[i]);
  });
  let acc = 0;
  const to = (i) => { w.set(toNorm(p, Math.max(0, Math.min(4, i)))); };
  drag(el, {
    onStart: () => { w.begin(); acc = 0; el.classList.add('is-touched'); },
    onMove: (dx, dy) => {
      acc += dx - dy;
      const cur = Math.round(ctx.store.real(id));
      if (Math.abs(acc) >= 34) { to(cur + Math.sign(acc)); acc = 0; }
    },
    onEnd: () => { w.end(); el.classList.remove('is-touched'); },
    onTap: (e) => {
      const r = svg.getBoundingClientRect();
      const x = ((e.clientX - r.left) / r.width) * 240, y = ((e.clientY - r.top) / r.height) * 160;
      if (Math.hypot(x - CX, y - CY) < 40) return;
      const deg = (Math.atan2(x - CX, CY - y) * 180) / Math.PI;
      let best = 0;
      ANG.forEach((a, i) => { if (Math.abs(a - deg) < Math.abs(ANG[best] - deg)) best = i; });
      w.begin(); to(best); w.end(); haptic();
    },
  });
  standard(el, ctx.store, id);
  el.addEventListener('keydown', (e) => {
    const d = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[e.key];
    if (d) { w.begin(); to(Math.round(ctx.store.real(id)) + d); w.end(); e.preventDefault(); }
  });
  return el;
}

export function distortion(ctx) {
  return panel('Distortion', { sub: 'COLDFIRE on the bus, Decapitator on the rumble', cls: 'kx-distrack' },
    h('div', { class: 'kx-dist' },
      styleRotary(ctx),
      h('div', { class: 'kx-dist-side' }, toggle(ctx, 'rumble.punish', { label: 'Punish' }), toggle(ctx, 'kick.roar', { label: 'Roar' }))),
    h('div', { class: 'rack-body kx-knobrow' },
      knob(ctx, 'kick.drive', { size: 72, label: 'COLDFIRE' }), knob(ctx, 'rumble.drive', { size: 72, label: 'Decap' }),
      knob(ctx, 'rumble.tone', { size: 64 }), knob(ctx, 'rumble.mix', { size: 64 })),
    h('p', { class: 'rack-note', text: '"The kick needs more distortion." Batch 8.1: 37-50% on both drives. Decapitator 7.1: 37% and 50% were best, 77% and 100% worse, about +0.7 LU per 10%. Punish: +20 dB into the saturator.' }));
}
