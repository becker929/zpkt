// Three alternatives, A/B/C, in Anthony's format: one track that switches between them every 2 bars on the grid,
// so the change is heard in place. Pick what varies (length, hat order, splash, break, pre-kick, SFX); the three are
// "at the two ends and the centre of a target range, never outside it". Tap a pad to hold one; Keep writes it.

import { h, haptic, toast } from '../ui.js';
import { toNorm } from '../params.js';
import { plan as makePlan, readValues } from './model.js';

export const AXES = [
  { key: 'length', label: 'Length', about: '24, 28 and 32 bars: 36, 42 and 48 s, the ends and the centre of 33-50 s.',
    v: [{ name: '24 bars', set: { length: 24 } }, { name: '28 bars', set: { length: 28 } }, { name: '32 bars', set: { length: 32 } }] },
  { key: 'hats', label: 'Hat B', about: 'Layer B is quiet alone (+1 dB of highs). Alone, with C, or not until the drop.',
    v: [{ name: 'B alone', set: {} }, { name: 'B with C', set: (v) => ({ hatB: v.hatC }) }, { name: 'B at the drop', set: { hatB: 25 } }] },
  { key: 'splash', label: 'Splash', about: '"Spread them out by a factor of 2 or 4": every 4, 8 or 16 bars.',
    v: [{ name: 'every 4', set: { splashEvery: 0 } }, { name: 'every 8', set: { splashEvery: 1 } }, { name: 'every 16', set: { splashEvery: 2 } }] },
  { key: 'break', label: 'Break', about: 'No break, 4 bars, or 8 bars (the references break for 8 or more).',
    v: [{ name: 'no break', set: { breakOn: 0 } }, { name: '4-bar break', set: { breakOn: 1, breakBars: 4 } }, { name: '8-bar break', set: { breakOn: 1, breakBars: 8 } }] },
  { key: 'prekick', label: 'Pre-kick', about: 'Before the kick: the song\'s "wuh", a silence, or straight in.',
    v: [{ name: 'wuh', set: { preKick: 0 } }, { name: 'silence', set: { preKick: 1 } }, { name: 'straight in', set: { preKick: 2 } }] },
  { key: 'sfx', label: 'SFX', about: 'The references withhold their SFX early, then build: with the kick, at the drop, or never.',
    v: [{ name: 'with the kick', set: { sfxBuild: 1 } }, { name: 'at the drop', set: { sfxBuild: 2 } }, { name: 'withheld', set: { sfxBuild: 3 } }] },
];

const KEYMAP = {
  length: 'arr.length', hatB: 'arr.hatB', hatC: 'arr.hatC', splashEvery: 'arr.splashEvery', breakOn: 'arr.breakOn',
  breakBars: 'arr.breakBars', preKick: 'arr.preKick', sfxBuild: 'arr.sfxBuild',
};

/** The three variants' snapshots (normalised arr.* values) for an axis, from the store now. */
export function variants(store, axis) {
  const ids = store.params.stage('arrange').map((p) => p.id);
  const base = store.snapshot(ids);
  const now = readValues(store);
  return axis.v.map((variant) => {
    const set = typeof variant.set === 'function' ? variant.set(now) : variant.set;
    const snap = { ...base };
    for (const [k, real] of Object.entries(set)) {
      const id = KEYMAP[k];
      if (!id || !store.params.has(id)) continue;
      snap[id] = toNorm(store.params.get(id), real);
    }
    return { name: variant.name, snap };
  });
}

export function abcRack(ctx, arranger, data) {
  const store = ctx.store;
  let axisKey = 'length';
  try { axisKey = localStorage.getItem('lab:arr:abc') || 'length'; } catch { /* private mode */ }
  let made = [];
  const chips = AXES.map((a) => h('button', { type: 'button', class: 'abc-chip', text: a.label, dataset: { k: a.key }, onclick: () => pick(a.key) }));
  const about = h('p', { class: 'abc-about' });
  const pads = [0, 1, 2].map((k) => {
    const spark = h('canvas', { class: 'abc-spark' });
    const name = h('span', { class: 'abc-name' });
    const secs = h('span', { class: 'abc-secs' });
    const b = h('button', { type: 'button', class: 'abc-pad', dataset: { k } },
      h('i', { class: 'abc-led' }), h('b', { class: 'abc-letter', text: 'ABC'[k] }), name, secs, spark);
    b.addEventListener('click', () => hold(k));
    b.parts = { spark, name, secs };
    return b;
  });
  const run = h('button', { type: 'button', class: 'arr-led abc-run', 'aria-pressed': 'false' }, h('i', { class: 'led' }), h('span', { text: 'Switch every 2 bars' }));
  const keep = h('button', { type: 'button', class: 'arr-btn abc-keep', text: 'Keep' });
  const el = h('div', { class: 'arr-abc' }, h('div', { class: 'abc-chips' }, ...chips), about, h('div', { class: 'abc-pads' }, ...pads), h('div', { class: 'abc-acts' }, run, keep));

  const axis = () => AXES.find((a) => a.key === axisKey) ?? AXES[0];
  const refresh = () => {
    made = variants(store, axis());
    chips.forEach((c) => c.classList.toggle('is-on', c.dataset.k === axisKey));
    about.textContent = axis().about;
    made.forEach((m, k) => {
      const pl = makePlan(readValues(store, m.snap));
      pads[k].parts.name.textContent = m.name;
      pads[k].parts.secs.textContent = m.name.includes('bars') ? `${pl.seconds.toFixed(0)} s` : `${pl.L} bars · ${pl.seconds.toFixed(0)} s`;
      m.curve = arranger.energy(pl).map((x) => x.lufs); m.L = pl.L;
    });
    const all = made.flatMap((m) => m.curve).filter((x) => x > -60);
    const hi = Math.ceil(Math.max(...all) + 0.5), lo = Math.min(Math.floor(Math.min(...all) - 0.5), hi - 6);
    made.forEach((m, k) => {
      sparkline(pads[k].parts.spark, m.curve, m.L, lo, hi);
    });
    if (arranger.abc) { arranger.abc.make = () => made.map((m) => makePlan(readValues(store, m.snap))); }
  };
  const pick = (k) => {
    axisKey = k;
    try { localStorage.setItem('lab:arr:abc', k); } catch { /* private mode */ }
    haptic();
    refresh();
    if (arranger.abc) arranger.invalidate();
  };
  const start = (on) => {
    run.setAttribute('aria-pressed', String(on));
    if (on) {
      arranger.abc = { hold: -1, make: () => made.map((m) => makePlan(readValues(store, m.snap))) };
      toast('A, B, C: two bars each, in turn');
    } else arranger.abc = null;
    pads.forEach((p) => p.classList.remove('is-hold'));
    arranger.invalidate();
  };
  run.addEventListener('click', () => { haptic(true); start(!arranger.abc); });
  const hold = (k) => {
    haptic();
    if (!arranger.abc) start(true);
    arranger.abc.hold = arranger.abc.hold === k ? -1 : k;
    pads.forEach((p, j) => p.classList.toggle('is-hold', j === arranger.abc.hold));
    toast(arranger.abc.hold >= 0 ? `${'ABC'[k]} only: ${made[k].name}` : 'A, B, C in turn');
    arranger.invalidate();
  };
  keep.addEventListener('click', () => {
    const w = arranger.where();
    const k = arranger.abc?.hold >= 0 ? arranger.abc.hold : w?.variant;
    if (k == null || k < 0) { toast('Hold A, B or C first (tap its pad)'); return; }
    store.apply(made[k].snap, { source: 'abc' });
    haptic(true);
    toast(`Kept ${'ABC'[k]}: ${made[k].name}`);
    start(false);
    refresh();
  });
  ctx.own(store.onAny((id) => { if (id.startsWith('arr.')) refresh(); }));
  ctx.own(() => { arranger.abc = null; });
  refresh();
  el.tick = (w) => {
    const v = w?.variant;
    pads.forEach((p, j) => p.classList.toggle('is-playing', v === j));
  };
  return el;
}

function sparkline(cv, vals, L, lo = -30, hi = -8) {
  const dpr = Math.min(3, devicePixelRatio || 1);
  const W = 120, H = 26;
  cv.width = W * dpr; cv.height = H * dpr;
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  const X = (i) => i / 40 * W, Y = (l) => H - 2 - Math.max(0, Math.min(1, (l - lo) / (hi - lo))) * (H - 4);
  g.fillStyle = 'rgba(198,255,61,0.12)'; g.fillRect(X(22), 0, X(33.3) - X(22), H);
  g.strokeStyle = '#ffb547'; g.lineWidth = 1.4; g.beginPath();
  vals.forEach((l, i) => { if (i) g.lineTo(X(i), Y(l)); else g.moveTo(0, Y(l)); g.lineTo(X(i + 1), Y(l)); });
  g.stroke();
  g.fillStyle = 'rgba(255,90,31,0.9)'; g.fillRect(X(L) - 1, 2, 2, H - 4);
}
