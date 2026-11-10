// matrixctrl(ctx, grid, {rows, cols, label}) -> element
//
// Max's matrixctrl as a routing grid: sources down the side, destinations across the top, a pin at every crossing.
// `grid` is rows x cols of param ids (null leaves a hole), e.g. buses x (level, space, drive):
//
//   matrixctrl(ctx, [['mix.kick', 'kick.verb', 'kick.drive'],
//                    ['mix.perc', 'mix.spaceMix', 'mix.hatsDrive'],
//                    ['mix.sfx', 'mix.sfxVerb', null]], {rows: ['Kick', 'Perc', 'SFX'], cols: ['Level', 'Space', 'Drive']})
//
// Each pin is a little LED in a ring: the ring fills with the amount, the LED glows with it, the set's amount is an
// acid dot on the ring. Tap a pin to pull it out (to zero) and tap again to put it back where it was; drag a pin up
// or down to set the amount (120 px is the whole range). Double tap: the set. Long press: the inspector.

import { drag, h, haptic, s } from '../ui.js';
import { follow, stageColor, writer } from './core.js';
import { setNorm } from '../params.js';
import { touches } from './kit.js';

const RING = 2 * Math.PI * 15;

export function matrixctrl(ctx, grid, { rows = [], cols = [], label = 'matrixctrl' } = {}) {
  const nc = Math.max(...grid.map((r) => r.length));
  const memory = new Map();
  const cell = (id) => {
    if (!id) return h('i', { class: 'mx-hole' });
    const p = ctx.params.get(id);
    const w = writer(ctx, id, 'matrix');
    const arc = s('circle', { cx: 22, cy: 22, r: 15, class: 'mx-arc', transform: 'rotate(-90 22 22)', 'stroke-dasharray': `0 ${RING}` });
    const sa = setNorm(p) * Math.PI * 2 - Math.PI / 2;
    const led = s('circle', { cx: 22, cy: 22, r: 7.5, class: 'mx-led' });
    const svg = s('svg', { viewBox: '0 0 44 44', class: 'mx-svg', 'aria-hidden': 'true' },
      s('circle', { cx: 22, cy: 22, r: 15, class: 'mx-track' }), arc,
      s('circle', { cx: 22 + 15 * Math.cos(sa), cy: 22 + 15 * Math.sin(sa), r: 2.2, class: 'mx-setdot' }),
      s('circle', { cx: 22, cy: 22, r: 9.5, class: 'mx-well' }), led);
    const el = h('div', { class: 'mx-pin', role: 'slider', 'aria-label': p.label, dataset: { param: id }, style: { '--c': stageColor(p) } }, svg);
    follow(ctx, id, (v, _r, text) => {
      arc.setAttribute('stroke-dasharray', `${(v * RING).toFixed(2)} ${RING}`);
      led.style.opacity = (0.08 + 0.92 * v).toFixed(3);
      el.classList.toggle('is-out', v < 0.02);
      el.classList.toggle('is-set', ctx.store.isSet(id));
      el.setAttribute('aria-valuetext', text);
      el.title = `${p.label}: ${text}`;
    });
    drag(el, {
      onStart: () => { w.begin(); el.classList.add('is-touched'); },
      onMove: (dx, dy) => w.add((dx - dy) / 120),
      onEnd: () => { w.end(); el.classList.remove('is-touched'); },
      onTap: () => {
        const v = ctx.store.get(id);
        w.begin();
        if (v > 0.02) { memory.set(id, v); w.set(0); } else { const back = memory.get(id) ?? setNorm(p); w.set(back > 0.02 ? back : 0.75); }
        w.end();
        haptic(true);
      },
    });
    touches(el, ctx, id);
    return el;
  };
  const el = h('div', { class: 'w-matrix', style: { '--cols': nc } },
    h('div', { class: 'w-label mx-title', text: label }),
    h('div', { class: 'mx-grid' },
      h('i', { class: 'mx-corner' }),
      ...Array.from({ length: nc }, (_, c) => h('span', { class: 'mx-col', text: cols[c] ?? '' })),
      ...grid.flatMap((row, r) => [h('span', { class: 'mx-row', text: rows[r] ?? '' }),
        ...Array.from({ length: nc }, (_, c) => cell(row[c] ?? null))])));
  return el;
}
