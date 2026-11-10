// The collage surface's runtime: the shelf on top, five modes below (GRAIN, SLICE, TAPE, BED, RACK), one sound
// graph, one draw loop. Panels are built the first time their mode opens and kept; everything registers its
// cleanup with the surface, so leaving the tab leaves nothing running or sounding.

import { h, haptic, toast } from '../ui.js';
import { loadState, saveState, state } from './state.js';
import { buildPeaks, bufferNow, defaultCue, loadBuffer, soundFrom, sourceList } from './sources.js';
import { buildGraph, collageSketches } from './graph.js';
import { Players } from './players.js';
import { Grains } from './grains.js';
import { TAPE_BASE } from './fx.js';
import { bus, icon } from './bits.js';
import { buildShelf } from './shelf.js';
import { seqStep } from './slicer.js';
import { bedStep } from './bed.js';
import { found } from './found.js';
import { record, warmRecorder } from './recorder.js';
import grainPanel from './panel-grain.js';
import slicePanel from './panel-slice.js';
import tapePanel from './panel-tape.js';
import bedPanel from './panel-bed.js';
import rackPanel from './panel-rack.js';

const MODES = [
  { id: 'grain', label: 'Grain', icon: 'grain', make: grainPanel },
  { id: 'slice', label: 'Slice', icon: 'slice', make: slicePanel },
  { id: 'tape', label: 'Tape', icon: 'tape', make: tapePanel },
  { id: 'bed', label: 'Bed', icon: 'bed', make: bedPanel },
  { id: 'rack', label: 'Rack', icon: 'rack', make: rackPanel },
];

export function mountCollage(root, ctx) {
  loadState();
  const { engine, store } = ctx;
  let dead = false;
  const C = {
    ctx, engine, store, state, ev: bus(), own: ctx.own,
    G: null, players: null, grains: null, sources: [], ready: false, chase: false, dice: 0, rec: { phase: 'idle' },
  };

  // --- what the panels ask of the runtime -----------------------------------------------------------------------
  C.src = (id = state.sel) => C.sources.find((s) => s.id === id) ?? null;
  C.cue = (id = state.sel) => {
    if (state.cue[id] != null) return state.cue[id];
    const buf = bufferNow(engine, id);
    return buf ? soundFrom(buf, defaultCue(C.src(id))) : defaultCue(C.src(id));
  };
  C.setCue = (id, s) => { state.cue[id] = Math.max(0, s); saveState(); C.ev.emit('cue', id); };
  C.tapeRev = () => store.real('col.tape.rev') === 1;
  C.select = (id) => {
    if (!id) return;
    state.sel = id;
    saveState();
    C.ev.emit('select', id);
    C.setLoaded({ src: id, off: C.cue(id), len: C.src(id)?.kind === 'rs' ? Math.round(C.src(id).seconds / engine.stepSeconds) : 16, st: 0, rev: false });
  };
  /** What a tap on an empty bed lane drops: the last thing picked or played. */
  C.setLoaded = (item) => { state.loaded = item; saveState(); C.ev.emit('loaded'); };

  /** The audio-clock time of the next bar line (now, if the transport is stopped). */
  C.nextBar = () => {
    const now = engine.ctx.currentTime;
    const p = engine.position();
    if (!p.playing) return now + 0.03;
    const k = Math.ceil(p.t + 0.05 / engine.barSeconds);
    return engine.timeOf(k * 16);
  };

  /** Hear a tape from its cue for two bars, from the next bar. toggle: a second tap stops it. */
  C.audition = (id = state.sel, { toggle = true } = {}) => {
    if (!C.ready) return false;
    const t = engine.ctx.currentTime;
    const mine = [...C.players.live].some((v) => v.tag === 'aud' && v.id === id && v.end > t);
    C.players.stopTag('aud');
    if (mine && toggle) return false;
    if (!bufferNow(engine, id)) return 'loading';
    const src = C.src(id);
    const dur = src?.kind === 'rs' ? src.seconds : engine.barSeconds * 2;
    C.players.play(id, { when: C.nextBar() - TAPE_BASE, off: C.cue(id), dur, rev: C.tapeRev(), tag: 'aud', release: 0.06 });
    return true;
  };

  C.auditionItem = (item) => {
    if (!C.ready) return;
    C.players.stopTag('aud');
    C.players.play(item.src, { when: C.nextBar() - TAPE_BASE, off: item.off, dur: item.len * engine.stepSeconds, st: item.st, rev: item.rev || C.tapeRev(), tag: 'aud', release: 0.03 });
  };

  C.found = () => found(C);

  C.panic = () => {
    C.players?.stopAll();
    C.grains?.releaseAll();
    state.seq = false;
    C.ev.emit('seq');
    C.ev.emit('ghost', false);
    toast('Collage: all quiet');
  };

  // --- resampling ---------------------------------------------------------------------------------------------
  C.resample = async () => {
    if (!C.ready) { toast('Start the engine first'); return; }
    if (C.rec.phase !== 'idle') { C.recCancel?.cancel?.(); return; }
    const bars = [1, 2, 4, 8][store.real('col.rs.bars')] ?? 2;
    const everything = store.real('col.rs.input') === 1;
    const seconds = bars * engine.barSeconds;
    const when = C.nextBar();
    const from = everything ? engine.master.out : C.G.tape.out;
    C.rec = { phase: 'armed', when, end: when + seconds, bars };
    C.ev.emit('rec');
    const cancel = C.recCancel = {};
    try {
      const buf = await record(engine.ctx, from, { when, seconds, cancel });
      if (dead) return;
      let peak = 0;
      for (let c = 0; c < buf.numberOfChannels; c++) for (const x of buf.getChannelData(c)) { const a = Math.abs(x); if (a > peak) peak = a; }
      if (peak < 1e-4) { toast('The take was silent: play something, then REC'); return; }
      const n = ++state.rsN;
      const d = new Date();
      state.rs.push({ id: `rs-${n}`, name: `Resample ${n}`, buffer: buf, bars, made: `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}` });
      if (state.rs.length > 12) {
        const drop = state.rs.find((r) => !state.bed.some((c) => c.src === r.id));
        if (drop) state.rs = state.rs.filter((r) => r !== drop);
      }
      C.sources = sourceList(engine);
      await buildPeaks(buf);
      if (dead) return;
      C.ev.emit('sources');
      C.ev.emit('buffer', `rs-${n}`);
      C.select(`rs-${n}`);
      C.setLoaded({ src: `rs-${n}`, off: 0, len: bars * 16, st: 0, rev: false });
      haptic(true);
      toast(`Resample ${n}: ${bars} ${bars === 1 ? 'bar' : 'bars'} on the shelf (${everything ? 'everything' : 'the collage'})`, 2400);
    } catch (err) {
      if (err.message === 'cancelled') toast('Resample cancelled');
      else { console.error(err); toast(`Resample failed: ${err.message}`); }
    } finally {
      if (!dead) { C.rec = { phase: 'idle' }; C.ev.emit('rec'); }
    }
  };

  // --- layout -------------------------------------------------------------------------------------------------------
  const shelf = buildShelf(C);
  const modeBtns = MODES.map((m) => {
    const b = h('button', { type: 'button', class: 'cl-mode', dataset: { mode: m.id }, 'aria-label': m.label }, icon(m.icon), h('span', { text: m.label }));
    b.addEventListener('click', () => { haptic(); show(m.id); });
    return b;
  });
  const dice = h('button', { type: 'button', class: 'cl-mode cl-found', 'aria-label': 'Found sound: a random tape, place and pitch, laid on the bed' }, icon('dice'), h('span', { text: 'Found' }));
  dice.addEventListener('click', () => { haptic(true); dice.classList.remove('is-rolled'); void dice.offsetWidth; dice.classList.add('is-rolled'); C.found(); });
  const stop = h('button', { type: 'button', class: 'cl-mode cl-panic', 'aria-label': 'Stop every collage sound' }, icon('stop'), h('span', { text: 'Hush' }));
  stop.addEventListener('click', () => { haptic(true); C.panic(); });
  const modes = h('nav', { class: 'cl-modes', 'aria-label': 'Collage modes' }, ...modeBtns, h('i', { class: 'cl-modes-gap' }), dice, stop);
  const host = h('div', { class: 'cl-host' });
  const status = h('div', { class: 'cl-status', text: 'Start the engine (the play button) to load the tapes.' });
  const el = h('div', { class: 'cl' }, shelf.el, modes, host, status);
  root.append(el);
  // a short screen (a smaller iPhone, Safari's bars showing): the cassettes fold to their labels and windows
  const ro = new ResizeObserver(() => el.classList.toggle('is-compact', el.getBoundingClientRect().height < 590));
  ro.observe(el);
  ctx.own(() => ro.disconnect());

  const panels = new Map();
  let current = null;
  const show = (mode) => {
    if (!MODES.some((m) => m.id === mode)) mode = 'grain';
    state.mode = mode;
    saveState();
    if (!panels.has(mode)) {
      const p = MODES.find((m) => m.id === mode).make(C);
      panels.set(mode, p);
      host.append(p.el);
    }
    for (const [id, p] of panels) p.el.hidden = id !== mode;
    current = panels.get(mode);
    current.show?.();
    for (const b of modeBtns) b.toggleAttribute('aria-current', b.dataset.mode === mode);
    C.ev.emit('mode', mode);
  };
  C.mode = show;
  show(state.mode);

  // --- sound ------------------------------------------------------------------------------------------------------
  const readGrains = () => {
    const r = (id) => store.real(id);
    return {
      size: r('col.grain.size') / 1000, density: r('col.grain.density'), spray: r('col.grain.spray') / 1000,
      pitch: r('col.grain.pitch'), rev: C.tapeRev() ? 1 : r('col.grain.rev') / 100, drift: r('col.grain.drift') / 100,
      pan: r('col.grain.pan') / 100, ymode: r('col.grain.y'), sync: r('col.grain.sync'),
    };
  };

  const loadAll = async () => {
    const order = [state.sel, ...C.sources.map((s) => s.id).filter((id) => id !== state.sel)];
    for (const id of order) {
      if (dead) return;
      try {
        const buf = await loadBuffer(engine, id);
        if (dead) return;
        if (buf) { await buildPeaks(buf); if (!dead) C.ev.emit('buffer', id); }
      } catch (err) { console.warn(`collage: ${id} did not load`, err); }
    }
  };

  ctx.own(engine.onReady(async () => {
    try {
      await engine.loadManifest();
      if (dead || C.G) return;
      C.sources = sourceList(engine);
      if (!C.src(state.sel)) state.sel = C.sources[0]?.id ?? null;
      C.G = buildGraph(engine, C.sources);
      C.unsketch = collageSketches(engine, C.G, C.sources.filter((s) => s.kind === 'clip').map((s) => s.id));
      C.players = new Players(C.G, engine);
      C.grains = new Grains(C.G, engine, readGrains);
      C.grains.start();
      C.G.onPitch = (id) => { C.players.repitch(id); C.ev.emit('slices'); };
      ctx.own(store.on('col.tape.speed', () => { C.G.speed = store.real('col.tape.speed') / 100; C.players.setSpeed(C.G.speed); }));
      ctx.own(store.on('col.tape.wow', (v) => C.G.tape.setWow(v)));
      ctx.own(store.on('col.tape.flutter', (v) => C.G.tape.setFlutter(v)));
      ctx.own(store.on('col.grain.freeze', (v) => { if (v < 0.5) C.grains.releaseFrozen(); }, { now: false }));
      warmRecorder(engine.ctx);
      C.ready = true;
      C.chase = engine.playing;
      status.hidden = true;
      if (!state.loaded && state.sel) C.select(state.sel);
      C.ev.emit('ready');
      C.ev.emit('sources');
      loadAll();
    } catch (err) {
      console.error(err);
      status.textContent = `The collage could not load its tapes: ${err.message || err}`;
      status.hidden = false;
    }
  }));

  ctx.own(engine.onStep((step, when) => {
    if (!C.ready || C.G.disposed) return;
    bedStep(C, step, when);
    seqStep(C, step, when);
  }));
  ctx.own(engine.onState((on) => {
    if (!C.ready) return;
    if (on) C.chase = true;
    else C.players.stopAll();
  }));
  const vis = () => { if (document.hidden && C.ready) { C.grains.releaseAll(); C.players.stopAll(); C.ev.emit('ghost', false); } };
  document.addEventListener('visibilitychange', vis);
  ctx.own(() => document.removeEventListener('visibilitychange', vis));

  // --- the draw loop: only the shelf and the open panel, only while visible --------------------------------------
  let raf = 0;
  const frame = (t) => {
    raf = requestAnimationFrame(frame);
    if (document.hidden) return;
    try { shelf.draw(t); current?.draw?.(t); } catch (err) { console.error(err); cancelAnimationFrame(raf); }
  };
  raf = requestAnimationFrame(frame);

  ctx.own(() => {
    dead = true;
    cancelAnimationFrame(raf);
    C.recCancel?.cancel?.();
    if (C.ready) {
      C.grains.stop();
      C.players.stopAll();
      C.unsketch?.();
      C.G.dispose();
    }
    store.unmodulate('collage-bend');                // the reels' bend and the tilt are not saved: none may stay
    store.unmodulate('collage-tilt');
    C.ev.emit('unmount');
    C.ready = false;
  });

  if (typeof window !== 'undefined') window.__collage = C;          // for the tests and the console
  return C;
}
