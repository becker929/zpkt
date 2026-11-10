// link(ctx, [idA, idB], {label, size, ratio, linked}) -> element
//
// Two params that move together, on one dial with two rings: A outside (its stage colour), B inside (cold blue),
// each with its tried range and the set's value. Linked (the chain in the middle is closed), a drag anywhere on
// the rings moves both by the same amount (B times `ratio`), keeping the gap between them: COLDFIRE and the
// Decapitator pushed into the 37-50 % target as one. Tap the chain to unlink: then the outer ring moves A and the
// inner ring moves B. Relative drag (220 px is the whole range; two fingers or hold-then-drag fine).
// Double tap: both back to the set. Long press: choose one to inspect.
//
//   e.g. link(ctx, ['kick.drive', 'rumble.drive'], {label: 'distortion'})

import { drag, h, haptic, s } from '../ui.js';
import { follow, normOf, shortLabel, stageColor } from './core.js';
import { setNorm } from '../params.js';
import { touches, writers } from './kit.js';

const A0 = -135, A1 = 135;
const ang = (v) => A0 + (A1 - A0) * v;
const pt = (r, deg) => { const a = (deg - 90) * Math.PI / 180; return [70 + r * Math.cos(a), 70 + r * Math.sin(a)]; };
const arc = (r, a, b) => {
  if (Math.abs(b - a) < 0.01) return '';
  const [x0, y0] = pt(r, Math.min(a, b)), [x1, y1] = pt(r, Math.max(a, b));
  return `M${x0.toFixed(2)} ${y0.toFixed(2)}A${r} ${r} 0 ${Math.abs(b - a) > 180 ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
};
const RA = 58, RB = 44;

export function link(ctx, ids, { label = 'link', size = 150, ratio = 1, linked = true } = {}) {
  const [ia, ib] = ids;
  const pa = ctx.params.get(ia), pb = ctx.params.get(ib);
  const gw = writers(ctx, ids, 'link');
  const ring = (p, r, cls) => {
    const tried = p.tried ? s('path', { class: 'lk-tried', d: arc(r, ang(normOf(p, p.tried[0])), ang(normOf(p, p.tried[1]))) }) : null;
    const [x, y] = pt(r, ang(setNorm(p)));
    const val = s('path', { class: `lk-val ${cls}` });
    return { val, nodes: [s('path', { class: 'lk-track', d: arc(r, A0, A1) }), tried, val, s('circle', { cx: x, cy: y, r: 3, class: 'lk-set' })] };
  };
  const A = ring(pa, RA, 'is-a'), B = ring(pb, RB, 'is-b');
  const ticks = Array.from({ length: 11 }, (_, i) => {
    const [x0, y0] = pt(67, ang(i / 10)), [x1, y1] = pt(i % 5 ? 64 : 62, ang(i / 10));
    return s('line', { x1: x0, y1: y0, x2: x1, y2: y1, class: 'lk-tick' });
  });
  const svg = s('svg', { viewBox: '0 0 140 140', class: 'lk-svg', 'aria-hidden': 'true' }, ...ticks, ...A.nodes, ...B.nodes);
  const chain = h('button', { type: 'button', class: 'lk-chain', 'aria-pressed': String(linked), 'aria-label': 'Link the two' });
  chain.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path class="lk-c1" d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path class="lk-c2" d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/></svg>';
  const dial = h('div', { class: 'lk-dial' }, svg, chain);
  const ra = h('span', { class: 'lcd-s' }), rb = h('span', { class: 'lcd-s' });
  const el = h('div', {
    class: `w-link${linked ? ' is-linked' : ''}`, dataset: { param: ids.join(' ') },
    style: { '--size': `${size}px`, '--c': stageColor(pa) },
  }, h('div', { class: 'w-label', text: label }), dial,
  h('div', { class: 'lk-reads' },
    h('div', { class: 'lk-read is-a' }, h('i'), h('span', { class: 'w-label', text: shortLabel(pa) }), ra),
    h('div', { class: 'lk-read is-b' }, h('i'), h('span', { class: 'w-label', text: shortLabel(pb) }), rb)));

  follow(ctx, ia, (v, _r, text) => { A.val.setAttribute('d', arc(RA, A0, ang(v))); ra.textContent = text; ra.parentElement.classList.toggle('is-set', ctx.store.isSet(ia)); });
  follow(ctx, ib, (v, _r, text) => { B.val.setAttribute('d', arc(RB, A0, ang(v))); rb.textContent = text; rb.parentElement.classList.toggle('is-set', ctx.store.isSet(ib)); });

  let on = linked, which = 'both', skip = false;
  chain.addEventListener('click', () => {
    on = !on;
    chain.setAttribute('aria-pressed', String(on));
    el.classList.toggle('is-linked', on);
    haptic(true);
  });
  drag(dial, {
    onStart: (e) => {
      skip = chain.contains(e.target);
      if (skip) return;
      const r = dial.getBoundingClientRect();
      const d = (Math.hypot(e.clientX - (r.left + r.width / 2), e.clientY - (r.top + r.height / 2)) / r.width) * 140;
      which = on ? 'both' : d >= (RA + RB) / 2 ? 'a' : 'b';
      gw.begin();
      el.classList.add('is-touched');
      el.dataset.which = which;
    },
    onMove: (dx, dy) => {
      if (skip) return;
      const d = (dx - dy) / 220;
      if (which !== 'b') gw.add(0, d);
      if (which !== 'a') gw.add(1, which === 'both' ? d * ratio : d);
    },
    onEnd: () => { if (skip) return; gw.end(); el.classList.remove('is-touched'); delete el.dataset.which; },
  });
  touches(svg, ctx, ids, { name: label });
  return el;
}
