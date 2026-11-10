// The widget library's shared kit (beside core.js, which it builds on): the lab's touches for a control over many
// params, a writer for many params as one undo step, one shared frame loop that only draws what is on screen, a
// modulation mixer (several modulators can move one param: their offsets add), a local store for a widget's own
// settings (a modulator's rate, a step lane's depth) so the same widgets can drive them, timers on the audio clock,
// saved state, canvas sizing and analyser lookup for meters.

import { Params, format, setNorm, toReal } from '../params.js';
import { clamp, doubleTap, h, haptic, inspect, longPress, toast } from '../ui.js';
import { writer } from './core.js';

/** Hex colours for canvas drawing (the CSS tokens, which a canvas cannot read as var()). */
export const HEX = {
  acid: '#c6ff3d', lcd: '#ffb547', cold: '#59c7ff', hazard: '#ff5a1f', alarm: '#ff2e4d', text: '#e9e7e2',
  text2: '#a4a19a', text3: '#6d6a65', steel: '#2c3036', bg: '#0a0a0b',
  collage: '#e0b7ff', arrange: '#59c7ff', kick: '#ff5a1f', mix: '#c6ff3d', play: '#ff3df2',
};
export const hexOf = (p) => HEX[p?.stage] ?? HEX.play;

/** rgba() from a #rrggbb and an alpha. */
export function rgba(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

// --- touches -----------------------------------------------------------------------------------------------------
/**
 * The lab's standard touches for a control over one or many params: double tap puts them all back to the set's
 * values (one undo step), long press opens the inspector (one param) or a chooser of the params (many).
 */
export function touches(el, ctx, ids, { double = true, long = true, name } = {}) {
  ids = [].concat(ids).filter(Boolean);
  if (double) {
    doubleTap(el, () => {
      ctx.store.begin();
      for (const id of ids) ctx.store.reset(id, { source: 'doubletap' });
      ctx.store.end();
      haptic(true);
      if (!ctx.local) toast(ids.length === 1 ? `${ctx.params.get(ids[0]).label}: the set's value` : `${name ?? 'These controls'}: the set's values`);
    });
  }
  if (long) longPress(el, () => { if (!ctx.local) (ids.length === 1 ? inspect(ids[0]) : chooser(ctx, ids, name)); });
}

/** A bottom sheet listing `ids`: tap one to open its inspector. */
export function chooser(ctx, ids, title = 'Which control?') {
  const sheet = document.getElementById('inspector');
  if (!sheet) return;
  const close = () => { sheet.hidden = true; document.removeEventListener('pointerdown', outside, true); };
  const outside = (e) => { if (!sheet.contains(e.target)) close(); };
  sheet.replaceChildren(
    h('div', { class: 'sheet-grip' }),
    h('h2', { text: title }),
    h('div', { class: 'live', text: `${ids.length} controls. Tap one: its knob in Live, the set's value, what was tried.` }),
    h('div', { class: 'w-choose' }, ...ids.map((id) => {
      const p = ctx.params.get(id);
      return h('button', { type: 'button', class: 'w-choose-item', onclick: () => { close(); inspect(id); } },
        h('b', { text: p.label }), h('span', { text: format(p, ctx.store.real(id)) }));
    })),
    h('div', { class: 'acts' }, h('button', { type: 'button', text: 'Close', onclick: close })));
  sheet.hidden = false;
  setTimeout(() => document.addEventListener('pointerdown', outside, true), 0);
}

/** Writers for many params that open and close one gesture (one undo step) together. */
export function writers(ctx, ids, source) {
  const ws = ids.map((id) => writer(ctx, id, source));
  let open = false;
  return {
    ws,
    begin() { if (open) return; open = true; for (const w of ws) w.begin(); },
    set(i, v) { ws[i].set(v); },
    add(i, d) { ws[i].add(d); },
    end() { if (!open) return; open = false; ctx.store.end(); },
  };
}

// --- one frame loop ---------------------------------------------------------------------------------------------
const frameFns = new Set();
let raf = 0;
function frame(t) {
  raf = 0;
  for (const fn of [...frameFns]) {
    try { fn(t); } catch (err) { console.error(err); frameFns.delete(fn); }
  }
  if (frameFns.size) raf = requestAnimationFrame(frame);
}

/**
 * fn(t, dt) on every animation frame until the surface unmounts (or the returned remover is called). With `el`,
 * only while el is on screen. All widgets share one requestAnimationFrame; it stops when nothing listens.
 */
export function tick(ctx, fn, el = null) {
  let visible = true, io = null, last = 0;
  if (el && 'IntersectionObserver' in window) {
    io = new IntersectionObserver((es) => { visible = es.some((x) => x.isIntersecting); });
    io.observe(el);
  }
  const f = (t) => {
    const dt = last ? Math.min(0.1, (t - last) / 1000) : 1 / 60;
    last = t;
    if (visible) fn(t, dt);
  };
  frameFns.add(f);
  if (!raf) raf = requestAnimationFrame(frame);
  const off = () => { frameFns.delete(f); io?.disconnect(); };
  ctx.own(off);
  return off;
}

/** How many frame functions are running (tests check this drops back after an unmount). */
export const frameCount = () => frameFns.size;

// --- modulation sources -----------------------------------------------------------------------------------------
// A modulation source (a bench LFO, a spring ribbon, a pad stab) for any number of params. The store sums the
// offsets of every source on a param; each source has its own name there, so several can move one param together.
// A source clears its own offsets when its surface unmounts.
let sources = 0;

export function modSource(ctx, name = 'mod') {
  const store = ctx.store;
  const key = `${name}#${++sources}`;
  const mine = new Map();                        // id -> this source's offset
  const src = {
    set(id, offset) {
      if (!Number.isFinite(offset)) offset = 0;
      offset = clamp(offset, -1, 1);
      if (Math.abs((mine.get(id) ?? 0) - offset) < 1e-6) return;
      if (Math.abs(offset) < 1e-5) mine.delete(id); else mine.set(id, offset);
      store.modulate(id, mine.get(id) ?? 0, key);
    },
    get(id) { return mine.get(id) ?? 0; },
    ids() { return [...mine.keys()]; },
    clear(id) {
      if (id != null) { src.set(id, 0); return; }
      for (const i of [...mine.keys()]) src.set(i, 0);
    },
  };
  ctx.own(() => src.clear());
  return src;
}

// --- a local store: a widget's own settings, driven by the same widgets ----------------------------------------
/** The Store's reading/writing/listening API over a handful of local params (no undo, no inspector). */
export class LocalStore {
  constructor(defs, values = {}, onChange = null) {
    this.params = new Params(defs);
    this.values = new Map(this.params.list.map((p) => [p.id, values[p.id] ?? setNorm(p)]));
    this.subs = new Map();
    this.onChange = onChange;
  }

  get(id) { return this.values.get(id) ?? 0; }
  live(id) { return this.get(id); }
  real(id) { return toReal(this.params.get(id), this.get(id)); }
  isSet(id) { return Math.abs(this.get(id) - setNorm(this.params.get(id))) < 1e-4; }
  set(id, value, { source = null } = {}) {
    if (!this.values.has(id)) return;
    const v = clamp(value);
    if (Math.abs(v - this.get(id)) < 1e-6) return;
    this.values.set(id, v);
    for (const fn of this.subs.get(id) ?? []) fn(v, id, source);
    this.onChange?.(id, v, this.real(id));
  }
  setReal(id, real, opts) { this.set(id, toNormLocal(this.params.get(id), real), opts); }
  nudge(id, d, opts) { this.set(id, this.get(id) + d, opts); }
  reset(id, opts) { this.set(id, setNorm(this.params.get(id)), opts); }
  begin() {}
  end() {}
  modulate() {}
  on(id, fn, { now = true } = {}) {
    if (!this.subs.has(id)) this.subs.set(id, new Set());
    this.subs.get(id).add(fn);
    if (now && this.values.has(id)) fn(this.get(id), id, 'init');
    return () => this.subs.get(id)?.delete(fn);
  }
  onAny() { return () => {}; }
  toJSON() { return Object.fromEntries(this.values); }
}

function toNormLocal(p, v) {
  if (p.scale === 'enum') return p.options.length > 1 ? clamp(v / (p.options.length - 1)) : 0;
  if (p.scale === 'toggle') return v ? 1 : 0;
  if (p.scale === 'log') return clamp(Math.log(v / p.min) / Math.log(p.max / p.min));
  return clamp((v - p.min) / (p.max - p.min));
}

/** A ctx whose store and params are local: pass it to any widget to drive a widget's own setting. */
export function localCtx(ctx, defs, values, onChange) {
  const store = new LocalStore(defs, values, onChange);
  return { ...ctx, store, params: store.params, local: true };
}

// --- time -------------------------------------------------------------------------------------------------------
/** A scheduler: at(when, fn) runs fn when the audio clock reaches `when` (an engine onStep/onBar time). */
export function later(ctx) {
  const timers = new Set();
  ctx.own(() => { for (const t of timers) clearTimeout(t); timers.clear(); });
  return (when, fn) => {
    const ac = ctx.engine?.ctx;
    const ms = ac ? Math.max(0, (when - ac.currentTime) * 1000) : 0;
    const t = setTimeout(() => { timers.delete(t); fn(); }, ms);
    timers.add(t);
  };
}

/** Bars since the start, smooth: the engine's clock while it plays, a free-running one at the tempo when not. */
export function barClock(engine) {
  let t = 0, lastNow = 0;
  return () => {
    const now = performance.now() / 1000;
    const dt = lastNow ? Math.min(0.1, now - lastNow) : 0;
    lastNow = now;
    const pos = engine?.position?.();
    if (pos?.playing && Number.isFinite(pos.t)) t = pos.t;
    else t += dt / (engine?.barSeconds || 1.5);
    return t;
  };
}

// --- saved state ------------------------------------------------------------------------------------------------
/**
 * A widget's own state (a pattern, node positions, a macro's position): from opts.state (the bench keeps it in its
 * patch, and hears changes through opts.onState), else localStorage under opts.key, else this visit only.
 */
export function keep(opts, def) {
  const key = opts.key ? `hw002-lab:w:${opts.key}` : null;
  let saved = opts.state ?? null;
  if (!saved && key) { try { saved = JSON.parse(localStorage.getItem(key) || 'null'); } catch { saved = null; } }
  const state = { ...structuredClone(def), ...(saved ?? {}) };
  let timer = 0;
  return {
    state,
    save() {
      clearTimeout(timer);
      timer = setTimeout(() => {
        if (opts.onState) opts.onState(state);
        else if (key) { try { localStorage.setItem(key, JSON.stringify(state)); } catch { /* private mode */ } }
      }, 150);
    },
  };
}

// --- drawing ----------------------------------------------------------------------------------------------------
/** Size a canvas's backing store to its layout box (times the pixel ratio). Returns {g, W, H, d}. */
export function fitCanvas(cv) {
  const d = Math.min(3, devicePixelRatio || 1);
  const W = Math.max(1, Math.round(cv.clientWidth * d)), H = Math.max(1, Math.round(cv.clientHeight * d));
  if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
  return { g: cv.getContext('2d'), W, H, d };
}

/** An AnalyserNode for a meter's source: 'master', a bus name, a Channel, an AnalyserNode. Null until audio is up. */
export function analyserOf(ctx, source = 'master') {
  const e = ctx.engine;
  if (source && typeof source.getFloatTimeDomainData === 'function') return source;
  if (source && source.meter) return source.meter;
  if (!e?.ctx) return null;
  if (!source || source === 'master') return e.master?.analyser ?? null;
  if (typeof source === 'string') return e.buses.get(source)?.meter ?? null;
  return null;
}

/** Stop a press on el from scrolling the page or starting a pan behind it. */
export function own(el) {
  el.style.touchAction = 'none';
  return el;
}
