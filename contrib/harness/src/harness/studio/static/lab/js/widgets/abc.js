// abcTapper(ctx, ids, {bars, labels, snaps, label, key, state, onState}) -> element
//
// Anthony's A/B format on the phone: three alternatives of the same controls, switched on the bar grid. By
// default A, B and C are the low end, the centre and the high end of each param's tried range ("three
// alternatives, at the two ends and the centre of a target range; never outside it"); without a tried range,
// 20 % either side of the set.
//   RUN       cycles A -> B -> C, switching every `bars` bars exactly on the downbeat (1, 2 or 4: tap the number).
//   tap A/B/C while running: that one is next; while stopped: hear it now (on the next bar if the transport runs),
//             and tap the lit one again to go back.
//   long press A/B/C: it captures the controls as they are now.
//   KEEP      keeps the one playing; stopping without KEEP puts the controls back where they were.
// The playing letter is lit; while it runs, the one that comes next blinks blue.
//
//   e.g. abcTapper(ctx, ['kick.drive', 'rumble.drive'], {bars: 1})

import { h, haptic, longPress, toast } from '../ui.js';
import { normOf, shortLabel, stageColor } from './core.js';
import { format, setNorm, toReal } from '../params.js';
import { keep, later } from './kit.js';

export function abcSnaps(ctx, ids) {
  const at = (k) => Object.fromEntries(ids.map((id) => {
    const p = ctx.params.get(id);
    if (p.tried) {
      const a = normOf(p, p.tried[0]), b = normOf(p, p.tried[1]);
      return [id, Math.min(a, b) + (Math.max(a, b) - Math.min(a, b)) * k];
    }
    return [id, Math.max(0, Math.min(1, setNorm(p) - 0.2 + 0.4 * k))];
  }));
  return [at(0), at(0.5), at(1)];
}

export function abcTapper(ctx, ids, { bars = 1, labels = ['A', 'B', 'C'], snaps, label = 'A / B / C', key, state, onState } = {}) {
  ids = [].concat(ids);
  const ps = ids.map((id) => ctx.params.get(id));
  const kept = keep({ key, state, onState }, { snaps: snaps ?? abcSnaps(ctx, ids), bars });
  const S = kept.state;
  const at = later(ctx);
  const sum = (snap) => (ids.length === 1 ? format(ps[0], toReal(ps[0], snap[ids[0]] ?? 0)) : ids.length <= 2
    ? ids.map((id, i) => format(ps[i], toReal(ps[i], snap[id] ?? 0))).join(' · ') : `${ids.length} controls`);
  const subs = [0, 1, 2].map(() => h('small'));
  const pads = [0, 1, 2].map((i) => h('button', { type: 'button', class: 'abc-pad', dataset: { i } }, h('i', { class: 'abc-led' }), h('b', { text: labels[i] }), subs[i]));
  const run = h('button', { type: 'button', class: 'abc-run', 'aria-pressed': 'false' }, h('i'), 'run');
  const barsBtn = h('button', { type: 'button', class: 'abc-bars' });
  const keepBtn = h('button', { type: 'button', class: 'abc-keep', text: 'keep' });
  const el = h('div', { class: 'w-abc', dataset: { param: ids.join(' ') }, style: { '--c': stageColor(ps[0]) } },
    h('div', { class: 'abc-head' }, h('span', { class: 'w-label', text: label }), h('span', { class: 'abc-what', text: ids.map((id) => shortLabel(ctx.params.get(id))).join(' + ') })),
    h('div', { class: 'abc-pads' }, ...pads),
    h('div', { class: 'abc-row' }, run, barsBtn, keepBtn));

  const paintSubs = () => S.snaps.forEach((sn, i) => { subs[i].textContent = sum(sn); });
  const paintBars = () => { barsBtn.textContent = `every ${S.bars} bar${S.bars > 1 ? 's' : ''}`; };
  paintSubs(); paintBars();

  let running = false, cur = -1, next = 0, before = null;
  const light = () => pads.forEach((p, i) => { p.classList.toggle('is-on', i === cur); p.classList.toggle('is-next', running && i === next && i !== cur); });
  const applySnap = (i) => {
    cur = i;
    for (const id of ids) ctx.store.set(id, S.snaps[i][id] ?? ctx.store.get(id), { source: 'abc', record: false });
    light();
  };
  const remember = () => { if (!before) before = ctx.store.snapshot(ids); };
  const restore = () => { if (before) { for (const [id, v] of Object.entries(before)) ctx.store.set(id, v, { source: 'abc', record: false }); } before = null; cur = -1; light(); };

  const e = ctx.engine;
  if (e?.onBar) {
    ctx.own(e.onBar((bar, when) => {
      if (!running) return;
      if (bar % S.bars !== 0) return;
      const i = next;
      at(when, () => { if (!running) return; applySnap(i); haptic(); next = (i + 1) % 3; light(); });
    }));
  }
  const queue = (i) => {
    remember();
    if (e?.playing) {
      const pos = e.position();
      at(e.timeOf((pos.bar + 1) * 16), () => applySnap(i));
    } else applySnap(i);
  };

  pads.forEach((pad, i) => {
    pad.addEventListener('click', () => {
      haptic();
      if (running) { next = i; light(); return; }
      if (i === cur) { restore(); return; }                  // tap the lit one again: back to where it was
      queue(i);
    });
    longPress(pad, () => { S.snaps[i] = ctx.store.snapshot(ids); kept.save(); paintSubs(); toast(`${labels[i]}: holds the controls as they are now`); });
  });
  run.addEventListener('click', () => {
    running = !running;
    run.setAttribute('aria-pressed', String(running));
    el.classList.toggle('is-running', running);
    haptic(true);
    if (!running) { restore(); return; }
    remember();
    next = cur >= 0 ? (cur + 1) % 3 : 0;
    if (!e?.playing) { applySnap(next); next = (next + 1) % 3; }
    light();
  });
  barsBtn.addEventListener('click', () => { S.bars = S.bars === 1 ? 2 : S.bars === 2 ? 4 : 1; paintBars(); kept.save(); haptic(); });
  keepBtn.addEventListener('click', () => {
    if (cur < 0) return;
    const keepI = cur;
    running = false;
    run.setAttribute('aria-pressed', 'false');
    el.classList.remove('is-running');
    const was = before;
    before = null;
    if (was) {                                                  // one undo step from where it was to the kept one
      for (const [id, v] of Object.entries(was)) ctx.store.set(id, v, { source: 'abc', record: false });
      ctx.store.begin();
      for (const id of ids) ctx.store.set(id, S.snaps[keepI][id] ?? ctx.store.get(id), { source: 'abc' });
      ctx.store.end();
    }
    cur = -1; light();
    haptic(true);
    toast(`Kept ${labels[keepI]}`);
  });
  /** Stop a run (or an audition) and put the controls back: the bench's STOP and Play's Stop all call this. */
  el.stop = () => {
    if (!running && !before) return;
    running = false;
    run.setAttribute('aria-pressed', 'false');
    el.classList.remove('is-running');
    restore();
  };
  ctx.own(() => { running = false; restore(); });
  return el;
}
