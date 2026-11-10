// encoder(ctx, id, {size, detents, steps, label}) -> element
//
// An endless rotary encoder with detents, like the ones on a Push or a Digitakt: a knurled cap with a dimple that
// turns forever, and a ring of LEDs around it showing the value (from zero for a bipolar param). Turn it by circling
// a finger around the cap: every detent (`detents` per turn, 24 by default) is one step and one haptic click.
// `steps` steps cover the whole range (an enum: one option per click; 64 by default, so 2.7 turns end to end).
// Near the centre, an up/right drag turns it instead (8 px a click). The set's LED is ringed acid; the tried range's
// LEDs glow pale when unlit. Double tap: the set. Long press: the inspector.

import { h, haptic, s } from '../ui.js';
import { follow, normOf, shortLabel, stageColor, writer } from './core.js';
import { setNorm } from '../params.js';
import { touches } from './kit.js';

const LEDS = 25, A0 = -150, A1 = 150;
const rad = (deg) => (deg - 90) * Math.PI / 180;

export function encoder(ctx, id, { size = 84, detents = 24, steps, label } = {}) {
  const p = ctx.params.get(id);
  const w = writer(ctx, id, 'encoder');
  const n = steps ?? (p.scale === 'enum' ? p.options.length - 1 : p.scale === 'toggle' ? 1 : 64);
  const bipolar = p.min < 0 && p.max > 0 && p.scale !== 'log';
  const zero = bipolar ? normOf(p, 0) : 0;
  const lo = p.tried ? Math.min(normOf(p, p.tried[0]), normOf(p, p.tried[1])) : 2, hi = p.tried ? Math.max(normOf(p, p.tried[0]), normOf(p, p.tried[1])) : -1;
  const setLed = Math.round(setNorm(p) * (LEDS - 1));
  const leds = Array.from({ length: LEDS }, (_, i) => {
    const a = rad(A0 + (A1 - A0) * (i / (LEDS - 1)));
    const at = i / (LEDS - 1);
    return s('circle', {
      cx: 50 + 45 * Math.cos(a), cy: 50 + 45 * Math.sin(a), r: 2.6,
      class: `en-led${at >= lo - 0.02 && at <= hi + 0.02 ? ' is-tried' : ''}${i === setLed ? ' is-setled' : ''}`,
    });
  });
  const teeth = Array.from({ length: detents }, (_, i) => {
    const a = (i / detents) * Math.PI * 2;
    return s('line', { x1: 50 + 29 * Math.cos(a), y1: 50 + 29 * Math.sin(a), x2: 50 + 34 * Math.cos(a), y2: 50 + 34 * Math.sin(a), class: 'en-tooth' });
  });
  const cap = s('g', { class: 'en-cap' },
    s('circle', { cx: 50, cy: 50, r: 35, class: 'en-body' }), ...teeth,
    s('circle', { cx: 50, cy: 50, r: 26, class: 'en-face' }),
    s('circle', { cx: 50, cy: 31, r: 3.4, class: 'en-dimple' }));
  const svg = s('svg', { viewBox: '0 0 100 100', class: 'en-svg', 'aria-hidden': 'true' }, s('circle', { cx: 50, cy: 50, r: 45, class: 'en-ring' }), ...leds, cap);
  const dial = h('div', { class: 'en-dial' }, svg);
  const read = h('div', { class: 'lcd-s' });
  const el = h('div', {
    class: 'w-enc', role: 'slider', tabindex: '0', 'aria-label': p.label, dataset: { param: id },
    style: { '--size': `${size}px`, '--c': stageColor(p) },
  }, h('div', { class: 'w-label', text: label ?? shortLabel(p) }), dial, read);

  follow(ctx, id, (v, _r, text) => {
    const a = Math.min(v, zero), b = Math.max(v, zero);
    leds.forEach((l, i) => { const at = i / (LEDS - 1); l.classList.toggle('is-on', at >= a - 0.5 / LEDS && at <= b + 0.5 / LEDS); });
    read.textContent = text;
    el.setAttribute('aria-valuetext', text);
    el.classList.toggle('is-set', ctx.store.isSet(id));
  });

  let rot = 0, acc = 0, prev = 0, pid = null, cx = 0, cy = 0, lx = 0, ly = 0;
  const detent = 360 / detents;
  const click = (dir) => {
    w.set(Math.round(ctx.store.get(id) * n + dir) / n);
    haptic();
  };
  dial.style.touchAction = 'none';
  dial.addEventListener('pointerdown', (e) => {
    if (pid != null) return;
    pid = e.pointerId;
    try { dial.setPointerCapture(e.pointerId); } catch { /* synthetic pointer */ }
    const r = dial.getBoundingClientRect();
    cx = r.left + r.width / 2; cy = r.top + r.height / 2;
    prev = Math.atan2(e.clientY - cy, e.clientX - cx) * 180 / Math.PI;
    lx = e.clientX; ly = e.clientY; acc = 0;
    w.begin();
    el.classList.add('is-touched');
  });
  dial.addEventListener('pointermove', (e) => {
    if (e.pointerId !== pid) return;
    const r = dial.getBoundingClientRect();
    const dist = Math.hypot(e.clientX - cx, e.clientY - cy);
    const a = Math.atan2(e.clientY - cy, e.clientX - cx) * 180 / Math.PI;
    let da;
    if (dist < r.width * 0.22) da = ((e.clientX - lx) - (e.clientY - ly)) * (detent / 8);
    else { da = a - prev; if (da > 180) da -= 360; if (da < -180) da += 360; }
    prev = a; lx = e.clientX; ly = e.clientY;
    rot += da; acc += da;
    cap.setAttribute('transform', `rotate(${rot.toFixed(1)} 50 50)`);
    while (acc >= detent) { click(1); acc -= detent; }
    while (acc <= -detent) { click(-1); acc += detent; }
  });
  const up = (e) => {
    if (e.pointerId !== pid) return;
    pid = null;
    w.end();
    el.classList.remove('is-touched');
    rot = Math.round(rot / detent) * detent;              // settle into the detent
    cap.setAttribute('transform', `rotate(${rot} 50 50)`);
  };
  dial.addEventListener('pointerup', up);
  dial.addEventListener('pointercancel', up);
  touches(dial, ctx, id);
  el.addEventListener('keydown', (e) => {
    const d = { ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1 }[e.key];
    if (d) { e.preventDefault(); w.begin(); click(d); w.end(); rot += d * detent; cap.setAttribute('transform', `rotate(${rot} 50 50)`); }
  });
  return el;
}
