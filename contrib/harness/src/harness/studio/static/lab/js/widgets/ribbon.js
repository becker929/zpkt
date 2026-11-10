// Long touch strips.
//
// crossfader(ctx, id, {length, labels, label}) -> element
//   A DJ crossfader: a fat cap in a long horizontal slot, the two ends labelled (A and B by default), a centre
//   detent you can feel (the cap sticks at the middle with a click). Relative drag: the length of the slot is the
//   whole range; two fingers or hold-then-drag is fine. The set's value is an acid notch. Double tap: the set.
//
// ribbon(ctx, id, {length, mode, label}) -> element
//   A ribbon controller: a long glowing strip you slide a thumb along.
//     mode 'move'    (default) moves the param, relative, like a fader with no cap.
//     mode 'spring'  throws it: the param follows the finger away from where it is, and springs back when you let
//                    go (a modulation, not saved, no undo): a moment of more drive, a space swell.
//   The set's value is an acid line, the tried range a pale band. Double tap: the set. Long press: the inspector.

import { drag, h, haptic } from '../ui.js';
import { follow, normOf, shortLabel, stageColor, writer } from './core.js';
import { setNorm } from '../params.js';
import { modSource, tick, touches } from './kit.js';

const pct = (v) => `${(v * 100).toFixed(2)}%`;
const triedBand = (p, cls) => (p.tried
  ? h('i', { class: cls, style: { '--lo': pct(Math.min(normOf(p, p.tried[0]), normOf(p, p.tried[1]))), '--hi': pct(Math.max(normOf(p, p.tried[0]), normOf(p, p.tried[1]))) } })
  : null);

export function crossfader(ctx, id, { length = 300, labels = ['A', 'B'], label } = {}) {
  const p = ctx.params.get(id);
  const w = writer(ctx, id, 'crossfader');
  const cap = h('i', { class: 'xf-cap' });
  const rail = h('div', { class: 'xf-rail' },
    h('i', { class: 'xf-groove' }), triedBand(p, 'xf-tried'), h('i', { class: 'xf-mid' }),
    h('i', { class: 'xf-set', style: { '--at': pct(setNorm(p)) } }), cap);
  const slot = h('div', { class: 'xf-slot' }, rail);
  const read = h('div', { class: 'lcd-s' });
  const el = h('div', { class: 'w-xf', dataset: { param: id }, style: { '--len': `${length}px`, '--c': stageColor(p) } },
    h('div', { class: 'xf-head' }, h('span', { class: 'w-label', text: label ?? shortLabel(p) }), read), slot,
    h('div', { class: 'xf-ends' }, h('b', { text: labels[0] }), h('b', { text: labels[1] })));
  follow(ctx, id, (v, _r, text) => {
    el.style.setProperty('--v', pct(v));
    read.textContent = text;
    el.classList.toggle('is-set', ctx.store.isSet(id));
  });
  let u = 0, width = length, stuck = false;
  drag(slot, {
    onStart: () => { u = ctx.store.get(id); width = rail.getBoundingClientRect().width || length; w.begin(); el.classList.add('is-touched'); },
    onMove: (dx) => {
      u = Math.max(0, Math.min(1, u + dx / width));
      const inDetent = Math.abs(u - 0.5) < 0.025;
      if (inDetent && !stuck) haptic(true);
      stuck = inDetent;
      w.set(inDetent ? 0.5 : u);
    },
    onEnd: () => { w.end(); el.classList.remove('is-touched'); },
  });
  touches(slot, ctx, id);
  return el;
}

export function ribbon(ctx, id, { length = 320, mode = 'move', label } = {}) {
  const p = ctx.params.get(id);
  const w = writer(ctx, id, 'ribbon');
  const spring = mode === 'spring';
  const mod = spring ? modSource(ctx, 'ribbon') : null;
  const touch = h('i', { class: 'rib-touch' });
  const strip = h('div', { class: 'rib-strip' },
    triedBand(p, 'rib-tried'), h('i', { class: 'rib-set', style: { '--at': pct(setNorm(p)) } }),
    h('i', { class: 'rib-glow' }), touch);
  const read = h('div', { class: 'lcd-s' });
  const el = h('div', {
    class: `w-rib${spring ? ' is-spring' : ''}`, dataset: { param: id }, style: { '--len': `${length}px`, '--c': stageColor(p) },
  }, h('div', { class: 'rib-head' }, h('span', { class: 'w-label', text: label ?? shortLabel(p) }),
    h('span', { class: 'rib-mode', text: spring ? 'spring' : 'ribbon' }), read), strip);
  follow(ctx, id, (v, _r, text) => {
    el.style.setProperty('--v', pct(v));
    read.textContent = text;
    el.classList.toggle('is-set', ctx.store.isSet(id));
  });

  let width = length, x0 = 0, off = 0, homing = false;
  const showTouch = (x) => { const r = strip.getBoundingClientRect(); touch.style.setProperty('--x', pct((x - r.left) / r.width)); };
  drag(strip, {
    slop: 2,
    onStart: (e) => {
      width = strip.getBoundingClientRect().width || length;
      x0 = e.clientX;
      showTouch(e.clientX);
      el.classList.add('is-touched');
      if (spring) { homing = false; off = mod.get(id); x0 -= off * width; } else w.begin();
    },
    onMove: (dx, _dy, { x }) => {
      showTouch(x);
      if (spring) { off = Math.max(-1, Math.min(1, (x - x0) / width)); mod.set(id, off); } else w.add(dx / width);
    },
    onEnd: () => {
      el.classList.remove('is-touched');
      if (!spring) { w.end(); return; }
      homing = true;
    },
  });
  if (spring) {
    tick(ctx, (_t, dt) => {                                   // spring home over ~0.3 s
      if (!homing) return;
      off *= Math.exp(-dt / 0.07);
      if (Math.abs(off) < 0.002) { off = 0; homing = false; }
      mod.set(id, off);
    });
  }
  touches(strip, ctx, id);
  return el;
}
