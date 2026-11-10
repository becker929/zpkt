// Arrange (III): the Short's shape, playable. "A 33-50 s cut with an arc, usually from a longer track."
//
// The arranger (arrange/arranger.js) turns the arr.* params into the engine's sequence: whole bars of the stems on
// the 160 BPM grid, plus lanes for the masked hat layers, the splash, the song's own break and "wuh", the chord
// loop. Everything here writes the params; the arr.* sketches recompute the sequence; the level params move this
// surface's buses by their change from the set. Leaving the tab gives the stems back as they were.
//
//   the Short     the timeline (every edge a handle), the energy curve, Play the Short (count-in, once or loop)
//   length        the length dial (33-50 s lit), the scooped opening, the kick's entry, the pre-kick
//   hats          the staircase: where A, B, C, D enter, and what each adds
//   splash, breaks, SFX and chord: their racks
//   A / B / C     three alternatives, switching every 2 bars
//   the whole song  the set's 177 bars, tap to play the song from any bar; the references' shape beside it
//   bar library   what each source bar holds; hold to hear one

import { clamp, h, haptic, toast } from '../ui.js';
import { rack, stageHead } from './racks.js';
import { knob } from '../widgets/knob.js';
import { fader } from '../widgets/fader.js';
import { Arranger, hatLevel } from '../arrange/arranger.js';
import { Lanes } from '../arrange/lanes.js';
import { Timeline } from '../arrange/timeline.js';
import { staircase } from '../arrange/staircase.js';
import { SongMap } from '../arrange/songmap.js';
import { abcRack } from '../arrange/abc.js';
import { library } from '../arrange/library.js';
import { playbar } from '../arrange/playbar.js';
import { ICONS, lengthDial, segmented } from '../arrange/controls.js';
import { TARGET } from '../arrange/model.js';

let DATA = null;
const loadData = () => (DATA ??= fetch(new URL('../../data/arrange-bars.json', import.meta.url), { cache: 'no-cache' })
  .then((r) => { if (!r.ok) throw new Error(`bar library: ${r.status}`); return r.json(); })
  .catch((err) => { DATA = null; throw err; }));

/** The references' shape for the ghost: two breaks at their measured depth, a third and two thirds in. */
function refsShape(data) {
  const med = (a) => { const s = [...a].sort((x, y) => x - y); return s.length ? s[Math.floor(s.length / 2)] : 0; };
  const depths = [];
  for (const r of data.refs) {
    if (r.name === 'HW002') continue;
    for (const [a, b] of r.breaks) {
      if (b - a < 7) continue;
      const inside = r.lufs.slice(a - 1, b), before = r.lufs.slice(Math.max(0, a - 17), a - 1);
      if (inside.length && before.length) depths.push(med(inside) - med(before));
    }
  }
  const d = clamp(med(depths), -12, -1);
  return (L) => {
    const out = new Array(L).fill(0);
    const n = clamp(Math.floor(L / 4), 4, 8);
    for (const c of [L / 3, (2 * L) / 3]) {
      const a = Math.round(c - n / 2);
      for (let i = Math.max(0, a); i < Math.min(L, a + n); i++) out[i] = d;
    }
    return out;
  };
}

/** A random Short inside Anthony's rules: 24-32 bars, the scooped opening, hats a step at a time (or B with C),
 *  splashes spread out, a break that leads into the drop, sometimes a second. One undo step. */
function roll(store) {
  const pick = (a) => a[Math.floor(Math.random() * a.length)];
  const P = (id) => store.params.get(id);
  const v = {};
  const L = pick([24, 28, 32]);
  const intro = pick([2, 4, 4]);
  const kickIn = intro + 1;
  const drop = L >= 28 ? 8 : pick([4, 8]);
  const dropAt = L - drop + 1;
  Object.assign(v, { length: L, intro, kickIn, dropBars: drop, hatA: 1 });
  if (pick(['steps', 'steps', 'bc']) === 'steps') Object.assign(v, { hatB: kickIn, hatC: kickIn + 4, hatD: kickIn + 8 });
  else Object.assign(v, { hatB: kickIn + 4, hatC: kickIn + 4, hatD: kickIn + 8 });
  const len = pick([4, 8]);
  const at = dropAt - len;
  if (Math.random() < 0.8 && at >= kickIn + 8) {
    Object.assign(v, { breakOn: 1, breakAt: at, breakBars: len, breakStyle: 0 });
    if (L >= 28 && Math.random() < 0.45 && kickIn + 8 + 4 <= at) Object.assign(v, { secondBreak: 1, break2At: kickIn + 8, break2Bars: 4 });
    else v.secondBreak = 0;
  } else Object.assign(v, { breakOn: 0, secondBreak: 0 });
  Object.assign(v, { splashEvery: pick([1, 2]), preKick: pick([0, 0, 1, 2]), preKickBeats: pick([2, 4]), sfxBuild: pick([1, 2, 3]) });
  store.begin();
  for (const [k, real] of Object.entries(v)) {
    const id = `arr.${k}`;
    if (!store.params.has(id)) continue;
    const p = P(id);
    const n = p.scale === 'toggle' ? real : p.scale === 'enum' ? real / (p.options.length - 1) : (real - p.min) / (p.max - p.min);
    store.set(id, n, { source: 'roll' });
  }
  store.end();
  return v;
}

/** Anthony's hat rule against this plan: a layer that enters alone and adds under 2 dB of highs. */
function hatRule(pl, data, shape) {
  const hi = (set) => (set ? hatLevel(data, set, shape).hi : -60), out = [];
  for (let i = 1; i < pl.bars.length; i++) {
    const a = pl.bars[i - 1].hats, b = pl.bars[i].hats;
    if (!a || pl.bars[i].brk || pl.bars[i - 1].brk) continue;
    const added = [...b].filter((x) => !a.includes(x));
    if (added.length !== 1) continue;
    const gain = hi(b) - hi(a);
    if (gain < 2) out.push(`Hat ${added[0]} enters alone at bar ${i + 1}: +${gain.toFixed(1)} dB of highs. "A new layer has to add energy on its own."`);
  }
  return out;
}

const identity = (e) => Array.from({ length: e.stems.bars || 24 }, (_, i) => Object.fromEntries(e.stems.names.map((n) => [n, i])));

function build(shell, ctx, data) {
  const e = ctx.engine, store = ctx.store;
  const lanes = new Lanes(e, data);
  const arr = new Arranger(ctx, data, lanes);
  arr.recompute();

  // --- the Short: readouts, the timeline, play -----------------------------------------------------------------
  const lcd = (label, extra = null) => { const b = h('b', { class: 'lcd' }); return { el: h('div', { class: 'arr-lcd' }, h('span', { class: 'arr-lcd-l' }, h('span', { text: label }), extra), b), b }; };
  const target = h('i', { class: 'arr-target' });
  const L1 = lcd('Bars'), L2 = lcd('Secs', target), L3 = lcd('Breaks'), L4 = lcd('Splash');
  const tl = new Timeline(ctx, arr, data, { refsShape: refsShape(data) });
  const pb = playbar(ctx, arr);
  const notes = h('div', { class: 'arr-notes', 'aria-live': 'polite' });
  const legend = h('div', { class: 'arr-legend' },
    h('span', {}, h('i', { class: 'lg lg-now' }), 'this Short'), h('span', {}, h('i', { class: 'lg lg-set' }), 'the set\'s'),
    h('span', {}, h('i', { class: 'lg lg-ghost' }), 'references: two breaks'));
  const dice = h('button', { type: 'button', class: 'arr-btn arr-roll', 'aria-label': 'Roll a Short' });
  dice.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="3"/><circle cx="9" cy="9" r="1.3"/><circle cx="15" cy="15" r="1.3"/><circle cx="15" cy="9" r="1.3"/><circle cx="9" cy="15" r="1.3"/></svg><span>Roll a Short</span>';
  dice.addEventListener('click', () => {
    const v = roll(store);
    haptic(true);
    toast(`${v.length} bars, ${v.breakOn ? `a ${v.breakBars}-bar break` : 'no break'}${v.secondBreak ? ' and another' : ''}`);
  });
  const home = h('button', { type: 'button', class: 'arr-btn arr-home', text: 'The set\'s Short' });
  home.addEventListener('click', () => {
    store.resetAll(ctx.params.stage('arrange').map((p) => p.id));
    haptic(true); toast('Batch 4.3 track 1: the canonical shape');
  });
  const hero = rack('The Short', { sub: 'drag any edge · tap the ruler to play from a bar', cls: 'arr-hero' },
    h('div', { class: 'arr-lcds' }, L1.el, L2.el, L3.el, L4.el), tl.el, pb, legend, notes,
    h('div', { class: 'arr-tools' }, dice, home));

  const playFrom = async (bar) => {
    if (arr.mode !== 'short' || !e.ctx) { toast('Start the engine first'); return; }
    haptic();
    if (e.playing) e.stop();
    arr.countIn = false; arr.rotated = false; arr.offset = 0; arr.apply();
    await e.start(bar);
  };
  tl.onSeek = playFrom;

  // --- length, opening, kick ------------------------------------------------------------------------------------
  const shape = rack('Length and opening', { sub: '22-33 bars on the 4-bar grid', note: '"Final arrangement starts with the scooped kick." Never open on a single bar.', cls: 'arr-shape' },
    lengthDial(ctx),
    h('div', { class: 'arr-col' },
      h('div', { class: 'arr-knobs' }, knob(ctx, 'arr.intro', { size: 64, label: 'Scoop bars' }), knob(ctx, 'arr.kickIn', { size: 64, label: 'Kick in' })),
      segmented(ctx, 'arr.preKick', { label: 'Before the kick', icons: [ICONS.wuh, ICONS.silence, ICONS.straight] }),
      h('div', { class: 'arr-knobs' }, knob(ctx, 'arr.preKickBeats', { size: 64, label: 'Pre beats' }), knob(ctx, 'arr.dropBars', { size: 64, label: 'Drop bars' }))));

  const hats = rack('Hat staircase', { sub: 'drag a riser to where its layer enters', cls: 'arr-hats' }, staircase(ctx, arr, data));

  const splash = rack('Splash', { sub: 'long on every kick entry, short every N bars', note: '"Too many splashes. Spread them out by a factor of 2 or 4."', cls: 'arr-splash' },
    segmented(ctx, 'arr.splashEvery', { label: 'Short splash every' }),
    h('div', { class: 'arr-knobs' }, knob(ctx, 'arr.splashLong', { size: 64, label: 'Long beats' }), knob(ctx, 'arr.splashShort', { size: 64, label: 'Short beats' })),
    fader(ctx, 'arr.splashLevel', { length: 220, horizontal: true, label: 'Splash level' }));

  const brk = rack('Breaks', { sub: 'every reference has two of 8+ bars; HW002 has one', note: 'The song\'s break plays its own last bars, so it leads into the kick. Tap the form lane to drop a break there.', cls: 'arr-breaks' },
    h('div', { class: 'arr-pair' },
      h('div', { class: 'arr-card' },
        segmented(ctx, 'arr.breakOn', { label: 'First break', names: ['Off', 'On'] }),
        h('div', { class: 'arr-knobs' }, knob(ctx, 'arr.breakAt', { size: 56, label: 'Starts' }), knob(ctx, 'arr.breakBars', { size: 56, label: 'Bars' }))),
      h('div', { class: 'arr-card' },
        segmented(ctx, 'arr.secondBreak', { label: 'Second break', names: ['Off', 'On'] }),
        h('div', { class: 'arr-knobs' }, knob(ctx, 'arr.break2At', { size: 56, label: 'Starts' }), knob(ctx, 'arr.break2Bars', { size: 56, label: 'Bars' })))),
    segmented(ctx, 'arr.breakStyle', { label: 'The break plays' }),
    fader(ctx, 'arr.breakLevel', { length: 220, horizontal: true, label: 'Break level' }));

  const sfx = rack('SFX and the chord', { sub: 'the references withhold their SFX early', note: 'The ARC RAIDERS hit lands where SFX enters and every 16 bars after. The chord loop sits about 21 LU under the mix.', cls: 'arr-sfx' },
    segmented(ctx, 'arr.sfxBuild', { label: 'SFX enters' }),
    h('div', { class: 'arr-col' },
      segmented(ctx, 'arr.chord', { label: 'Chord loop', names: ['Muted', 'In the Short'] }),
      h('div', { class: 'arr-knobs' }, knob(ctx, 'arr.chordLevel', { size: 64, label: 'Chord dB' }), knob(ctx, 'arr.chordWidth', { size: 64, label: 'Width' }))));

  const abc = abcRack(ctx, arr, data);
  const abcR = rack('A / B / C', { sub: 'three versions, two bars each, in turn', cls: 'arr-abcr' }, abc);

  const map = new SongMap(ctx, arr, lanes, data);
  const mapR = rack('The whole song', { sub: '177 bars · pinch to zoom · tap a bar to play from it', note: 'Blue: the bars the Short is cut from (121-140). Orange: the song\'s break (81-96). Below the tracks, the four references bar by bar, their breaks outlined.', cls: 'arr-mapr' }, map.el);

  const lib = library(ctx, arr, data);
  const libR = rack('Bar library', { sub: 'the 24 source bars (the song\'s 121-144) · hold one to hear it', cls: 'arr-libr' }, lib);

  shell.replaceChildren(hero, h('div', { class: 'arr-grid' }, shape, hats, splash, brk, sfx, abcR, mapR, libR));

  // --- readouts follow the plan ------------------------------------------------------------------------------------
  const render = () => {
    const pl = arr.pl;
    L1.b.textContent = String(pl.L);
    L2.b.textContent = pl.seconds.toFixed(1);
    const inT = pl.seconds >= TARGET.lo && pl.seconds <= TARGET.hi;
    target.className = `arr-target ${inT ? 'is-in' : 'is-out'}`;
    target.textContent = inT ? 'IN' : pl.seconds < TARGET.lo ? 'SHORT' : 'LONG';
    target.title = inT ? 'inside 33-50 s' : 'outside 33-50 s';
    L3.b.textContent = String(pl.breaks.length);
    L4.b.textContent = String(pl.bars.filter((b) => b.splash).length);
    notes.replaceChildren(...pl.notes.map((n) => h('span', { class: 'arr-note', text: n })),
      ...hatRule(pl, data, arr.useShape).map((n) => h('span', { class: 'arr-note is-rule', text: n })),
      ...arr.missing().map((n) => h('span', { class: 'arr-note is-missing', text: n })));
    lib.mark(arr.base ?? []);
    tl.dirty = true;
  };
  ctx.own(arr.onChange(render));
  render();

  // --- sound: the arr.* sketches ----------------------------------------------------------------------------------
  for (const key of ['arr.length', 'arr.intro', 'arr.kickIn', 'arr.preKick', 'arr.preKickBeats', 'arr.hats', 'arr.splash', 'arr.break', 'arr.chord', 'arr.sfx']) {
    ctx.own(e.sketch(key, () => arr.invalidate()));
  }
  ctx.own(e.sketch('arr.splashLevel', (d) => lanes.setSplashLevel(d)));
  ctx.own(e.sketch('arr.breakLevel', (d) => e.bus('arr-break').set('gain', d)));
  ctx.own(e.sketch('arr.chordLevel', (d) => e.bus('arr-chord').set('gain', d)));
  ctx.own(e.sketch('arr.chordWidth', (_v, i) => e.bus('arr-chord').set('width', clamp(i.real / Math.max(1, i.set), 0, 20))));
  ctx.own(store.onAny((id) => { if (id.startsWith('arr.')) arr.invalidate(); }));

  // --- the engine's clock --------------------------------------------------------------------------------------------
  ctx.own(e.onBar((bar, when) => { arr.bar(bar, when); map.onBar(bar); }));
  ctx.own(e.onStop(() => { lanes.stopAll(); map.onEngineStop(); arr.countIn = false; arr.stopped(); }));
  ctx.own(e.onReady(() => { lanes.init(); lanes.prepare(); arr.apply(); }));
  lanes.onFull = () => { map.dirty = true; };

  // --- frames: only what is on screen -------------------------------------------------------------------------------
  const seen = new Map([[tl.el, true], [map.el, true]]);
  const io = new IntersectionObserver((list) => { for (const x of list) seen.set(x.target, x.isIntersecting); });
  io.observe(tl.el); io.observe(map.el);
  ctx.own(() => io.disconnect());
  // the manifest arrives (loadManifest resets the stems and says so): this surface's Short goes back in, with the
  // canonical Short's bars if the manifest has them
  let hadManifest = !!e.manifest;
  ctx.own(e.stems.onChange(() => {
    if (!e.manifest || arr.mode !== 'short' || e.stems.sequence === arr.applied) return;
    if (!hadManifest) { hadManifest = true; map.rows(); arr.recompute(); lanes.prepare(); } else arr.apply();
  }));
  let raf = 0;
  const frame = () => {
    raf = requestAnimationFrame(frame);
    if (e.ctx && e.manifest && !lanes.masks.bands && !lanes.masks.failed && !lanes._preparing) lanes.prepare();
    const w = arr.where();
    if (seen.get(tl.el)) tl.draw(w);
    pb.tick(w);
    abc.tick(w);
    if (seen.get(map.el)) map.draw();
  };
  raf = requestAnimationFrame(frame);
  ctx.own(() => cancelAnimationFrame(raf));

  // --- leaving: the stems back as they were, nothing of ours left running ----------------------------------------------
  ctx.own(() => {
    map.dead = true;
    map.stopSong(false);
    clearTimeout(arr._end);
    arr.mode = 'gone';
    arr.abc = null;
    lanes.dispose();
    if (e.manifest) {
      e.stems.enabled = true;
      e.stems.loop = true;
      e.stems.setSequence(identity(e));
    }
  });
  window.lab.arrange = { arranger: arr, lanes, timeline: tl, map };
  ctx.own(() => { if (window.lab) delete window.lab.arrange; });
}

export default {
  id: 'arrange',
  title: 'Arrange',
  n: 'III',
  icon: '<path d="M3 6h7M12 6h9M3 12h11M16 12h5M3 18h4M9 18h12"/>',
  about: 'The Short\'s shape: a 33-50 s cut with an arc, on a 4/8-bar grid.',
  mount(root, ctx) {
    let dead = false;
    ctx.own(() => { dead = true; });
    const shell = h('div', { class: 'arr' }, h('p', { class: 'rack-note', text: 'Loading the bar library…' }));
    root.append(stageHead('Arrange', 'the Short\'s shape', 'A 33-50 s cut with an arc, on a 4/8-bar grid. It opens on the scooped kick.'), shell);
    const say = (text) => { if (!dead) shell.replaceChildren(h('p', { class: 'rack-note', text })); };
    loadData().then((data) => {
      if (dead) return;
      try { build(shell, ctx, data); } catch (err) { console.error(err); say(`This surface broke: ${err.message}`); }
    }, (err) => { console.warn('arrange: bar library', err); say(`The bar library did not load: ${err.message}`); });
  },
};
