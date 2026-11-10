// The bar library: what each of the 24 source bars holds (the song's bars 121-144, as the lab's stems), measured
// offline: the kick's low end under 130 Hz (scooped or full), the perc's loudness and hat layers (and the one
// splash), the SFX (the chord loop's 8-bar cycle, the ARC RAIDERS hit). Hold a column to hear that bar on a loop.

import { h, haptic } from '../ui.js';

export function library(ctx, arranger, data) {
  const st = data.stems;
  const cols = st.kick.map((_, i) => i);
  const norm = (v, lo, hi) => Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
  const used = new Set();
  const grid = h('div', { class: 'lib-grid', role: 'grid' }, ...cols.map((i) => {
    const k = st.kick[i], p = st.perc[i], s = st.sfx[i];
    const cell = (cls, level, text, title) => h('i', { class: `lib-cell ${cls}`, style: { '--l': level.toFixed(3) }, title }, text ? h('em', { text }) : null);
    const col = h('div', { class: 'lib-col', dataset: { i } },
      h('span', { class: 'lib-n', text: String(data.stem_song_bars?.[i] ?? i + 1) }),
      cell(k.scooped ? 'is-scoop' : 'is-full', norm(k.low, -30, -18), k.scooped ? 'S' : '', `kick under 130 Hz ${k.low.toFixed(1)} dB`),
      cell(p.splash ? 'is-splash' : 'is-hats', norm(p.lufs, -24, -18), p.splash ? '*' : p.layers === 'ABCD' ? '' : p.layers, `perc ${p.lufs.toFixed(1)} LUFS, ${p.layers}`),
      cell(s.arc ? 'is-arc' : 'is-chord', norm(s.lufs, -44, -20), s.arc ? 'A' : '', s.arc ? `ARC RAIDERS ${s.lufs.toFixed(1)} LUFS` : `chord ${s.lufs.toFixed(1)} LUFS`));
    return col;
  }));
  const legend = h('div', { class: 'lib-legend' },
    h('span', {}, h('i', { class: 'lib-sw is-scoop' }), 'scooped kick'), h('span', {}, h('i', { class: 'lib-sw is-full' }), 'full kick'),
    h('span', {}, h('i', { class: 'lib-sw is-hats' }), 'hats ABCD'), h('span', {}, h('i', { class: 'lib-sw is-splash' }), 'splash'),
    h('span', {}, h('i', { class: 'lib-sw is-chord' }), 'chord'), h('span', {}, h('i', { class: 'lib-sw is-arc' }), 'ARC hit'));
  // the canonical Short's perc bars (batch 4.3 track 1): the real layer sets the staircase plays
  const sh = data.shape;
  const shapeRow = sh ? h('div', { class: 'lib-shape' },
    h('div', { class: 'lib-shape-head' }, h('b', { text: 'THE CANONICAL SHORT' }), h('span', { text: 'hat layers per bar (L, S: its splashes)' })),
    h('div', { class: 'lib-shape-grid' }, ...sh.perc.map((r, i) => h('i', {
      class: `lib-sc${r.splash ? ` is-${r.splash}` : ''}`, style: { '--n': String(r.layers.length) },
      title: `bar ${i + 1}: ${r.layers}${r.splash ? `, ${r.splash} splash` : ''}, ${r.lufs.toFixed(1)} LUFS`,
    }, h('em', { text: r.splash ? (r.splash === 'long' ? 'L' : 'S') : String(r.layers.length) }))))) : null;
  const el = h('div', { class: 'arr-lib' },
    h('div', { class: 'lib-rows' }, h('span', { text: 'BAR' }), h('span', { text: 'KICK' }), h('span', { text: 'PERC' }), h('span', { text: 'SFX' })),
    grid, legend, shapeRow);

  // hold to audition one source bar
  const e = ctx.engine;
  let held = null;
  grid.style.touchAction = 'pan-y';
  grid.addEventListener('pointerdown', (ev) => {
    const col = ev.target.closest('.lib-col');
    if (!col || !e.ctx || !e.manifest || arranger.mode === 'song') return;
    const i = Number(col.dataset.i);
    held = { col, i, was: e.playing, pid: ev.pointerId, x: ev.clientX, y: ev.clientY };
    held.timer = setTimeout(() => start(held), 140);
  });
  const start = async (hd) => {
    if (!hd || held !== hd) return;
    hd.on = true;
    haptic(true);
    hd.col.classList.add('is-held');
    arranger.mode = 'audition';
    e.stems.loop = true;
    e.stems.setSequence([{ kick: hd.i, perc: hd.i, sfx: hd.i }]);
    if (!e.playing) await e.start(0);
  };
  const end = () => {
    const hd = held; held = null;
    if (!hd) return;
    clearTimeout(hd.timer);
    if (!hd.on) return;
    hd.col.classList.remove('is-held');
    arranger.mode = 'short';
    if (!hd.was && e.playing) e.stop();
    arranger.apply();
  };
  grid.addEventListener('pointermove', (ev) => { if (held && !held.on && Math.hypot(ev.clientX - held.x, ev.clientY - held.y) > 8) { clearTimeout(held.timer); held = null; } });
  grid.addEventListener('pointerup', end);
  grid.addEventListener('pointercancel', end);
  grid.addEventListener('pointerleave', end);
  ctx.own(end);

  el.mark = (seq) => {
    used.clear();
    for (const x of seq) for (const k of ['kick', 'perc', 'sfx']) if (x[k] >= 0) used.add(`${k}${x[k]}`);
    for (const col of grid.children) {
      const i = Number(col.dataset.i);
      col.classList.toggle('is-used', ['kick', 'perc', 'sfx'].some((k) => used.has(`${k}${i}`)));
    }
  };
  return el;
}
