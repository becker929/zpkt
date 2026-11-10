// A long-throw fader (vertical, or horizontal with {horizontal: true}): a groove with dB-style scale marks, a
// steel cap with a hazard line, the set's value as an acid notch, the tried range as a pale band. Drag the cap or
// anywhere on the groove (relative: the cap does not jump to the finger). Double tap: the set. Long press: inspect.
//
// toggle(): a latching hardware button with an LED, for on/off params and enum steps (each tap goes to the next).

import { drag, h, haptic, standard } from '../ui.js';
import { follow, normOf, shortLabel, stageColor, writer } from './core.js';
import { setNorm } from '../params.js';

export function fader(ctx, id, { length = 180, horizontal = false, label, thin = false } = {}) {
  const p = ctx.params.get(id);
  const w = writer(ctx, id, 'fader');
  const pos = (v) => `${(v * 100).toFixed(2)}%`;
  const marks = Array.from({ length: 9 }, (_, i) => h('i', { class: 'f-mark', style: { '--at': pos(i / 8) } }));
  const tried = p.tried ? h('i', { class: 'f-tried', style: { '--lo': pos(normOf(p, p.tried[0])), '--hi': pos(normOf(p, p.tried[1])) } }) : null;
  const set = h('i', { class: 'f-set', style: { '--at': pos(setNorm(p)) } });
  const fill = h('i', { class: 'f-fill' });
  const cap = h('i', { class: 'f-cap' });
  const groove = h('div', { class: 'f-groove' }, ...marks, tried, fill, set, cap);
  const readout = h('div', { class: 'f-read lcd-s' });
  const el = h('div', {
    class: `w-fader${horizontal ? ' is-h' : ''}${thin ? ' is-thin' : ''}`, role: 'slider', tabindex: '0', 'aria-label': p.label,
    dataset: { param: id }, style: { '--len': `${length}px`, '--c': stageColor(p) },
  }, h('div', { class: 'w-label', text: label ?? shortLabel(p) }), groove, readout);

  follow(ctx, id, (v, _real, text) => {
    el.style.setProperty('--v', pos(v));
    readout.textContent = text;
    el.setAttribute('aria-valuetext', text);
    el.classList.toggle('is-set', ctx.store.isSet(id));
  });
  drag(groove, {
    onStart: () => { w.begin(); el.classList.add('is-touched'); },
    onMove: (dx, dy) => w.add((horizontal ? dx : -dy) / length),
    onEnd: () => { w.end(); el.classList.remove('is-touched'); },
  });
  standard(groove, ctx.store, id);
  el.addEventListener('keydown', (e) => {
    const d = { ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1 }[e.key];
    if (d) { w.begin(); w.add(d * (e.shiftKey ? 0.1 : 0.01)); w.end(); e.preventDefault(); }
  });
  return el;
}

export function toggle(ctx, id, { label, wide = false } = {}) {
  const p = ctx.params.get(id);
  const w = writer(ctx, id, 'toggle');
  const led = h('i', { class: 't-led' });
  const text = h('span', { class: 't-text' });
  const el = h('button', {
    type: 'button', class: `w-toggle${wide ? ' is-wide' : ''}`, dataset: { param: id }, style: { '--c': stageColor(p) },
  }, led, h('span', { class: 't-label', text: label ?? shortLabel(p) }), text);
  follow(ctx, id, (v, real, t) => {
    const on = p.scale === 'toggle' ? real === 1 : v > 0;
    el.classList.toggle('is-on', on);
    el.setAttribute('aria-pressed', String(on));
    text.textContent = p.scale === 'toggle' ? '' : t;
    el.classList.toggle('is-set', ctx.store.isSet(id));
  });
  el.addEventListener('click', () => {
    const steps = p.scale === 'enum' ? p.options.length - 1 : 1;
    const v = ctx.store.get(id);
    w.begin();
    w.set(p.scale === 'enum' ? (Math.round(v * steps) + 1) % (steps + 1) / steps : (v >= 0.5 ? 0 : 1));
    w.end();
    haptic();
  });
  standard(el, ctx.store, id, { double: false });
  return el;
}
