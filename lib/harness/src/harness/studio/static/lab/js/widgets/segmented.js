// Two ways to choose one of a few positions.
//
// segmented(ctx, id, {label, options, steps}) -> element
//   A segmented switch: a row of lit hardware segments with a sliding lamp. Tap a segment, or slide across them
//   (a haptic tick on each). For an enum or on/off param; a continuous param gets `steps` positions (default 5)
//   from min to max. The set's option carries an acid tick. "A (Ampex)" shows "A" big and "Ampex" small.
//   Long press: the inspector.
//
// pictslider(ctx, id, {label, steps, length}) -> element
//   Max's pictslider as a detented slider: a knurled thumb in a slot that clicks into `steps` notches (an enum's
//   options, or `steps` positions along a continuous param), each notch with its own pictogram (bars that grow
//   from one notch to the next, or the option's initial). Drag is relative and snaps; a haptic tick per notch.
//   The set's notch is acid, the tried range a pale band. Double tap: the set. Long press: the inspector.

import { drag, h, haptic } from '../ui.js';
import { follow, normOf, shortLabel, stageColor, writer } from './core.js';
import { format, setNorm, toReal } from '../params.js';
import { touches } from './kit.js';

function positions(p, steps) {
  if (p.scale === 'enum') return p.options.map((o, i) => ({ v: i / Math.max(1, p.options.length - 1), text: o }));
  if (p.scale === 'toggle') return [{ v: 0, text: p.off ?? 'Off' }, { v: 1, text: p.on ?? 'On' }];
  const n = Math.max(2, steps);
  return Array.from({ length: n }, (_, i) => ({ v: i / (n - 1), text: format(p, toReal(p, i / (n - 1))) }));
}

const nearest = (list, v) => list.reduce((b, x, i) => (Math.abs(x.v - v) < Math.abs(list[b].v - v) ? i : b), 0);

export function segmented(ctx, id, { label, options, steps = 5 } = {}) {
  const p = ctx.params.get(id);
  const w = writer(ctx, id, 'segmented');
  const pos = positions(p, steps).map((x, i) => ({ ...x, text: options?.[i] ?? x.text }));
  const setI = nearest(pos, setNorm(p));
  const segs = pos.map((x, i) => {
    const [main, rest] = String(x.text).split(/\s+(?=\()/);
    return h('div', { class: `seg-opt${i === setI ? ' is-setopt' : ''}` },
      h('i', { class: 'seg-led' }), h('b', { text: main }), rest ? h('small', { text: rest.replace(/[()]/g, '') }) : null);
  });
  const lamp = h('i', { class: 'seg-lamp' });
  const track = h('div', { class: 'seg-track', role: 'radiogroup', 'aria-label': p.label }, lamp, ...segs);
  const el = h('div', { class: 'w-seg', dataset: { param: id }, style: { '--n': pos.length, '--c': stageColor(p) } },
    h('div', { class: 'w-label', text: label ?? shortLabel(p) }), track);

  let cur = -1;
  follow(ctx, id, (v) => {
    const i = nearest(pos, v);
    if (i !== cur) {
      cur = i;
      lamp.style.setProperty('--i', i);
      segs.forEach((s, j) => { s.classList.toggle('is-on', j === i); s.setAttribute('aria-checked', String(j === i)); });
    }
    el.classList.toggle('is-set', ctx.store.isSet(id));
  });

  let rect = null;
  const pick = (x) => {
    const i = Math.max(0, Math.min(pos.length - 1, Math.floor(((x - rect.left) / rect.width) * pos.length)));
    if (i === nearest(pos, ctx.store.get(id))) return;
    w.set(pos[i].v);
    if (p.scale !== 'enum' && p.scale !== 'toggle') haptic();
  };
  drag(track, {
    onStart: (e) => { rect = track.getBoundingClientRect(); w.begin(); pick(e.clientX); el.classList.add('is-touched'); },
    onMove: (_dx, _dy, { x }) => pick(x),
    onEnd: () => { w.end(); el.classList.remove('is-touched'); },
  });
  touches(track, ctx, id, { double: false });
  return el;
}

const glyph = (i, n, text, isEnum) => {
  if (isEnum) { const t = String(text).trim(); return h('b', { class: 'ps-ini', text: t.length <= 3 ? t : t[0] }); }
  const bars = Array.from({ length: 4 }, (_, j) => h('i', { class: j / 3 <= i / Math.max(1, n - 1) + 0.01 ? 'on' : '' }));
  return h('span', { class: 'ps-bars' }, ...bars);
};

export function pictslider(ctx, id, { label, steps = 9, length = 260 } = {}) {
  const p = ctx.params.get(id);
  const w = writer(ctx, id, 'pictslider');
  const discrete = p.scale === 'enum' || p.scale === 'toggle';
  const pos = positions(p, steps);
  const pct = (v) => `${(v * 100).toFixed(2)}%`;
  const setI = nearest(pos, setNorm(p));
  const notches = pos.map((x, i) => h('div', { class: `ps-notch${i === setI ? ' is-setopt' : ''}`, style: { '--at': pct(x.v) } },
    glyph(i, pos.length, x.text, discrete), h('i', { class: 'ps-tick' })));
  const tried = p.tried ? h('i', { class: 'ps-tried', style: { '--lo': pct(Math.min(normOf(p, p.tried[0]), normOf(p, p.tried[1]))), '--hi': pct(Math.max(normOf(p, p.tried[0]), normOf(p, p.tried[1]))) } }) : null;
  const thumb = h('i', { class: 'ps-thumb' });
  const slot = h('div', { class: 'ps-slot' }, tried, h('i', { class: 'ps-groove' }), ...notches, thumb);
  const read = h('div', { class: 'lcd-s ps-read' });
  const el = h('div', { class: 'w-pict', dataset: { param: id }, style: { '--len': `${length}px`, '--c': stageColor(p) } },
    h('div', { class: 'ps-head' }, h('span', { class: 'w-label', text: label ?? shortLabel(p) }), read), slot);

  let cur = -1;
  follow(ctx, id, (v, _r, text) => {
    thumb.style.setProperty('--v', pct(v));
    const i = nearest(pos, v);
    if (i !== cur) { cur = i; notches.forEach((n, j) => n.classList.toggle('is-on', j === i)); }
    read.textContent = text;
    el.classList.toggle('is-set', ctx.store.isSet(id));
  });

  let u = 0, width = length;
  drag(slot, {
    onStart: () => { u = ctx.store.get(id); width = slot.getBoundingClientRect().width || length; w.begin(); el.classList.add('is-touched'); },
    onMove: (dx) => {
      u = Math.max(0, Math.min(1, u + dx / width));
      const i = nearest(pos, u);
      if (Math.abs(pos[i].v - ctx.store.get(id)) > 1e-6) { w.set(pos[i].v); if (!discrete) haptic(); }
    },
    onEnd: () => { w.end(); el.classList.remove('is-touched'); },
  });
  touches(slot, ctx, id);
  return el;
}
