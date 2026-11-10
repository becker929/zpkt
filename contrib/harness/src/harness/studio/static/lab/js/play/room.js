// The Play surface's machine room: what every machine shares.
//
//   createRoom(ctx, scroller)   one animation loop for all machines; machines off screen do not draw, and of the
//                               WebGL machines only the most visible one draws (one context animating at a time).
//                               A machine that modulates keeps simulating while scrolled away (its sim), but only
//                               draws when seen (its draw).
//   room.clock()                the bar clock as heard: {t (bars), tRaw, bar, phase, beats, beat, beatPhase, playing}.
//                               The engine's clock while it plays (minus the output latency), a free one at 160 when
//                               not, so the machines still move in tempo without sound.
//   room.audio()                the master's bands now {low, mid, high} 0..1 and `pulse`: the kick, from the beat
//                               phase, as loud as the low band says.
//   room.out(name)              a machine's modulation output: its offsets go to the store under its own source
//                               ('play:<name>'; the store sums every source, the Bench's too); frame([[id, offset]...])
//                               per frame, clear() (store.unmodulate) on stop and unmount.
//   shell(), chips(), openPicker(), canvas2d(), pointers()   the chrome: a rack with a power switch, the param
//                               chips (tap: choose the param; long press: its inspector), the picker sheet.
//
// Machines are {key, el, view, gl?, sim?(dt), draw?(dt), running?(), destroy?()}.

import { h, haptic, inspect, longPress, toast } from '../ui.js';
import { format, toReal } from '../params.js';
import { knob } from '../widgets/knob.js';

export const C = {
  magenta: '#ff3df2', hazard: '#ff5a1f', acid: '#c6ff3d', lcd: '#ffb547', cold: '#59c7ff', alarm: '#ff2e4d',
  text: '#e9e7e2', text2: '#a4a19a', text3: '#6d6a65', steel0: '#111214', steel1: '#17191c', steel2: '#202328',
  steel3: '#2c3036', steel4: '#3b4048', collage: '#e0b7ff', arrange: '#59c7ff', kick: '#ff5a1f', mix: '#c6ff3d', play: '#ff3df2',
};
export const rgba = (hex, a) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
};
export const clamp = (x, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, x));
export const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';

// --- saved per machine (the param picks, a recorded loop) ------------------------------------------------------
const LS = 'hw002-lab:play:';
export function load(key, def) {
  try { const v = JSON.parse(localStorage.getItem(LS + key) || 'null'); return v ?? def; } catch { return def; }
}
export function save(key, v) {
  try { localStorage.setItem(LS + key, JSON.stringify(v)); } catch { /* private mode: this visit only */ }
}

// --- the room -------------------------------------------------------------------------------------------------------
export function createRoom(ctx, scroller) {
  const { store, engine } = ctx;
  const room = {
    ctx, store, engine, params: ctx.params, machines: [], frame: 0, sensors: { tilt: null },
    stats: { frames: 0, gl: {}, sims: 0, draws: 0, mounted: true }, activeGL: null,
  };
  const cleanups = [];
  room.own = (fn) => { cleanups.push(fn); return fn; };
  const changeFns = new Set();
  room.onChange = (fn) => { changeFns.add(fn); return () => changeFns.delete(fn); };
  room.changed = () => { for (const fn of changeFns) fn(); };

  // --- the clock -------------------------------------------------------------------------------------------------
  let freeT = 0, lastNow = performance.now(), clockCache = null, audioCache = null;
  room.clock = () => {
    if (clockCache) return clockCache;
    const p = engine.position();
    let t, tRaw;
    if (p.playing && Number.isFinite(p.t)) {
      const ac = engine.ctx;
      const lat = (ac?.outputLatency || 0) + (ac?.baseLatency || 0);
      tRaw = p.t;
      t = p.t - lat / (engine.barSeconds || 1.5);
      freeT = t;
    } else { t = freeT; tRaw = freeT; }
    const bar = Math.floor(t), phase = t - bar, beats = t * 4;
    // t: as heard now (for pictures); tRaw: the audio clock (a knob moved now is heard a latency later)
    return (clockCache = { t, tRaw, bar, phase, beats, beat: Math.floor(phase * 4), beatPhase: beats - Math.floor(beats), playing: !!p.playing });
  };

  // --- the master's bands ---------------------------------------------------------------------------------------
  let an = null, bins = null;
  const env = { low: 0, mid: 0, high: 0 };
  room.own(engine.onReady((e) => {
    if (an || !e.master) return;
    an = e.ctx.createAnalyser();
    an.fftSize = 1024; an.smoothingTimeConstant = 0.35; an.minDecibels = -85; an.maxDecibels = -12;
    e.master.out.connect(an);
    bins = new Uint8Array(an.frequencyBinCount);
  }));
  room.own(() => { if (an) { try { engine.master.out.disconnect(an); } catch { /* gone */ } an = null; } });
  room.audio = () => {
    if (audioCache) return audioCache;
    const c = room.clock();
    let low = 0, mid = 0, high = 0;
    if (an && engine.playing) {
      an.getByteFrequencyData(bins);
      const hz = engine.ctx.sampleRate / an.fftSize;
      const avg = (a, b) => {
        let s = 0, n = 0;
        for (let i = Math.max(1, Math.round(a / hz)); i <= Math.min(bins.length - 1, Math.round(b / hz)); i++) { s += bins[i]; n++; }
        return n ? s / n / 255 : 0;
      };
      low = avg(30, 140); mid = avg(300, 3000); high = avg(5000, 15000);
    }
    env.low += (low - env.low) * 0.45; env.mid += (mid - env.mid) * 0.3; env.high += (high - env.high) * 0.3;
    const pulse = c.playing ? Math.exp(-c.beatPhase * 7.5) * clamp(0.2 + env.low * 1.05, 0, 1) : 0;
    return (audioCache = { low: env.low, mid: env.mid, high: env.high, pulse });
  };

  // --- modulation outputs ---------------------------------------------------------------------------------------
  room.out = (name) => {
    const source = `play:${name}`;
    const live = new Map();                                   // id -> the offset last written
    const out = {
      source,
      /** Set this frame's offsets; any param this machine moved before and not now goes back to its knob. */
      frame(pairs) {
        const sums = new Map();                               // two slots on one param add up
        for (const [id, off] of pairs) {
          if (!id || !store.values.has(id) || !Number.isFinite(off)) continue;
          sums.set(id, (sums.get(id) ?? 0) + off);
        }
        const now = new Set();
        for (const [id, off] of sums) {
          const q = Math.round(clamp(off, -1, 1) * 1000) / 1000;
          if (q) now.add(id);
          if ((live.get(id) ?? 0) === q) continue;
          store.modulate(id, q, source);
          if (q) live.set(id, q); else live.delete(id);
        }
        for (const id of [...live.keys()]) if (!now.has(id)) { store.modulate(id, 0, source); live.delete(id); }
      },
      clear() {
        if (typeof store.unmodulate === 'function') store.unmodulate(source);
        else for (const id of live.keys()) store.modulate(id, 0, source);
        live.clear();
      },
      ids: () => [...live.keys()],
    };
    room.own(() => out.clear());
    return out;
  };

  // --- visibility and the loop -------------------------------------------------------------------------------------
  const ratios = new Map();
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) ratios.set(e.target, e.isIntersecting ? e.intersectionRatio : 0);
  }, { root: scroller, threshold: [0, 0.02, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1] });
  room.ratio = (m) => ratios.get(m.view) ?? 0;
  /** A phone-only param's value (data/extras-play.json), or `def` if that file did not load. */
  room.real = (id, def) => (room.params.has(id) ? store.real(id) : def);
  /** A knob for a phone-only param, or nothing if it did not load. */
  room.knob = (id, opts) => (room.params.has(id) ? knob(ctx, id, opts) : document.createComment(`no ${id}`));
  room.add = (m) => { room.machines.push(m); if (m.view) io.observe(m.view); return m; };

  const run = (m, what, dt) => {
    if (m.broken) return;
    try { m[what](dt); } catch (err) { m.broken = true; console.error(`play/${m.key}.${what}`, err); }
  };
  let raf = 0;
  const tick = (now) => {
    raf = requestAnimationFrame(tick);
    const dt = Math.min(0.06, Math.max(0.001, (now - lastNow) / 1000));
    lastNow = now;
    clockCache = null; audioCache = null;
    const t0 = performance.now();
    if (!engine.playing) freeT += dt / (engine.barSeconds || 1.5);
    room.frame++; room.stats.frames++;
    let gl = null, best = 0.0001;
    for (const m of room.machines) {
      const r = room.ratio(m);
      if (m.sim && (r > 0 || m.running?.())) { run(m, 'sim', dt); room.stats.sims++; }
      if (r <= 0 || !m.draw) continue;
      if (m.gl) { if (r > best + 0.001) { best = r; gl = m; } continue; }
      run(m, 'draw', dt); room.stats.draws++;
    }
    if (gl) { run(gl, 'draw', dt); room.stats.gl[gl.key] = (room.stats.gl[gl.key] ?? 0) + 1; }
    room.activeGL = gl?.key ?? null;
    for (const fn of frameFns) fn(dt);
    room.stats.ms = (room.stats.ms ?? 0) * 0.95 + (performance.now() - t0) * 0.05;     // JS per frame, smoothed
  };
  const frameFns = new Set();
  room.onFrame = (fn) => { frameFns.add(fn); return () => frameFns.delete(fn); };
  raf = requestAnimationFrame(tick);

  /** Run fn where a main-thread stall cannot starve the audio: just after the engine has queued a bar. */
  room.whenSafe = (fn) => {
    let done = false, timer = 0, off = () => {};
    const go = () => { if (done) return; done = true; off(); clearTimeout(timer); fn(); };
    if (!engine.playing) timer = setTimeout(go, 0);
    else {
      off = engine.onBar(() => { off(); clearTimeout(timer); timer = setTimeout(go, 15); });
      timer = setTimeout(go, 1700);                      // the transport stopped before the next bar line
    }
    room.own(() => { done = true; off(); clearTimeout(timer); });
  };

  room.destroy = () => {
    cancelAnimationFrame(raf);
    io.disconnect();
    for (const m of room.machines) { try { m.destroy?.(); } catch (err) { console.error(err); } }
    for (const fn of cleanups.splice(0).reverse()) { try { fn(); } catch (err) { console.error(err); } }
    closePicker();
    room.stats.mounted = false;
  };
  return room;
}

// --- a machine's rack ---------------------------------------------------------------------------------------------
/**
 * A machine: a rack with a title, a view (the canvas lives here), chips, tools and a note. With `power`, a switch in
 * the head: on means the machine moves knobs by itself (modulation, cold blue); off puts them back.
 */
export function shell(room, { key, title, sub, power = false, gl = false, note }) {
  const head = h('div', { class: 'rack-head pl-head' },
    h('span', { class: 'rack-title', text: title }), h('span', { class: 'rack-sub', text: sub ?? '' }));
  const m = {
    key, title, gl, on: false,
    view: h('div', { class: `pl-view pl-view-${key}` }),
    tools: h('div', { class: 'pl-tools' }),
    noteEl: note ? h('p', { class: 'rack-note pl-note', text: note }) : null,
  };
  if (power) {
    const label = h('span', { class: 'pl-power-t', text: 'Off' });
    m.powerBtn = h('button', { type: 'button', class: 'pl-power', 'aria-pressed': 'false', 'aria-label': `${title}: modulate` },
      h('i', { class: 'pl-led' }), label);
    m.powerBtn.addEventListener('click', () => m.setOn(!m.on, true));
    head.append(m.powerBtn);
    m.setOn = (on, user = false) => {
      on = !!on;
      if (m.on === on) return;
      m.on = on;
      m.powerBtn.setAttribute('aria-pressed', String(on));
      label.textContent = on ? 'Mod' : 'Off';
      m.el.classList.toggle('is-on', on);
      if (!on) m.output?.clear();
      m.onPower?.(on, user);
      if (user) haptic(on);
      room.changed();
    };
    m.running = () => m.on;
  }
  m.el = h('section', { class: `rack pl-machine pl-m-${key}`, id: `pl-${key}`, dataset: { machine: key } },
    head, m.view, m.tools, m.noteEl);
  return m;
}

/** A small hardware button for a machine's tools row. */
export function btn(text, onclick, { cls = '', label, pressed } = {}) {
  const b = h('button', { type: 'button', class: `pl-btn ${cls}`.trim(), 'aria-label': label ?? text }, text);
  if (pressed != null) b.setAttribute('aria-pressed', String(!!pressed));
  b.addEventListener('click', (e) => { haptic(); onclick(e, b); });
  return b;
}

/** A row of segment buttons; returns {el, set(i)}. */
export function segments(options, index, onpick, { cls = '' } = {}) {
  const el = h('div', { class: `pl-seg ${cls}`.trim(), role: 'group' });
  const bs = options.map((text, i) => {
    const b = h('button', { type: 'button', class: 'pl-seg-b', text, 'aria-pressed': String(i === index) });
    b.addEventListener('click', () => { haptic(); set(i); onpick(i); });
    return b;
  });
  const set = (i) => bs.forEach((b, j) => b.setAttribute('aria-pressed', String(i === j)));
  el.append(...bs);
  return { el, set };
}

// --- param chips --------------------------------------------------------------------------------------------------
export const pickable = (p) => p && p.stage !== 'play' && p.scale !== 'toggle' && p.scale !== 'enum';
export const shortOf = (p) => p.short ?? (p.label.length > 14 ? `${p.label.slice(0, 13)}…` : p.label);

/**
 * The params a machine drives, as chips under it: role (X, Y, pinch...), the param, its value as heard (cold blue
 * while modulated). Tap: choose another param. Long press: its inspector. Picks are saved per machine.
 * defs: [{role, hint, def}]. Returns {el, ids, onChange(fn)}.
 */
export function chips(room, m, defs) {
  const { store, params } = room;
  const saved = load(`${m.key}.picks`, []);
  const ids = defs.map((d, i) => (saved[i] && params.has(saved[i]) && pickable(params.get(saved[i])) ? saved[i] : d.def));
  const fns = new Set();
  const el = h('div', { class: 'pl-chips', dataset: { n: String(defs.length) } });
  defs.forEach((d, i) => {
    const name = h('span', { class: 'pl-chip-name' });
    const val = h('span', { class: 'pl-chip-val' });
    const b = h('button', { type: 'button', class: 'pl-chip', dataset: { slot: String(i) } },
      h('span', { class: 'pl-chip-role', text: d.role }), h('span', { class: 'pl-chip-txt' }, name, val));
    let unsub = null, longed = false;
    const bind = () => {
      unsub?.();
      const p = params.get(ids[i]);
      name.textContent = shortOf(p);
      b.style.setProperty('--sc', `var(--stage-${p.stage})`);
      b.setAttribute('aria-label', `${d.role} drives ${p.label}. Tap to choose another.`);
      unsub = store.on(ids[i], (v) => {
        const t = format(p, toReal(p, v));
        if (val.textContent !== t) val.textContent = t;
        const mod = store.mods.has(ids[i]);
        if (b.classList.contains('is-mod') !== mod) b.classList.toggle('is-mod', mod);
      });
    };
    bind();
    room.own(() => unsub?.());
    longPress(b, () => { longed = true; inspect(ids[i]); });
    b.addEventListener('click', () => {
      if (longed) { longed = false; return; }
      haptic();
      openPicker(room, {
        title: `${m.title ?? m.key} · ${d.role}`, hint: d.hint, current: ids[i],
        onPick: (id) => {
          const old = ids[i];
          if (id === old) return;
          ids[i] = id;
          save(`${m.key}.picks`, ids);
          bind();
          for (const fn of fns) fn(i, id, old);
        },
      });
    });
    el.append(b);
  });
  return { el, ids, onChange: (fn) => { fns.add(fn); return () => fns.delete(fn); } };
}

// --- the picker sheet ---------------------------------------------------------------------------------------------
const RECOMMENDED = [
  ['kick.drive', 'The kick needs more distortion: 37 to 50 % is the target.'],
  ['rumble.drive', 'The rumble\'s Decapitator: the same target.'],
  ['kick.colourFreq', 'Colour brings it forward: 484 Hz toward 2.2 kHz.'],
  ['kick.colour', 'How hard that colour bell pushes.'],
  ['mix.spaceMix', 'Colour and space is missing: Supermassive on the hats.'],
  ['kick.sub30', 'The deepest sub is missing: 25 to 40 Hz sits 7 to 9 dB under.'],
];
const STAGE_ORDER = ['kick', 'mix', 'collage', 'arrange'];
let openSheet = null;

export function closePicker() {
  if (!openSheet) return;
  const s = openSheet;
  openSheet = null;
  document.removeEventListener('pointerdown', s._outside, true);
  s.hidden = true;
  setTimeout(() => s.remove(), 260);
}

/** A bottom sheet of every param a machine can drive (the six that matter for HW002 first). */
export function openPicker(room, { title, hint, current, onPick }) {
  closePicker();
  const { params, store } = room;
  const row = (p, why) => h('button', {
    type: 'button', class: `pl-pick${p.id === current ? ' is-current' : ''}`, dataset: { id: p.id },
    style: { '--sc': `var(--stage-${p.stage})` },
    onclick: () => { haptic(); onPick(p.id); toast(`${p.label}`); closePicker(); },
  }, h('i', { class: 'pl-pick-dot' }),
  h('span', { class: 'pl-pick-l' }, h('b', { text: p.label }), h('small', { text: why ?? p.group })),
  h('span', { class: 'pl-pick-v', text: format(p, store.real(p.id)) }));
  const list = h('div', { class: 'pl-pick-list' });
  const sections = new Map();
  const sec = (key, label, color, rows) => {
    const el = h('section', { class: 'pl-pick-sec' }, h('div', { class: 'pl-pick-h', style: { '--sc': color }, text: label }), ...rows);
    sections.set(key, el);
    list.append(el);
  };
  sec('hw', 'For HW002 now', 'var(--stage-play)', RECOMMENDED.filter(([id]) => params.has(id)).map(([id, why]) => row(params.get(id), why)));
  for (const st of STAGE_ORDER) {
    const ps = params.list.filter((p) => p.stage === st && pickable(p));
    if (ps.length) sec(st, st, `var(--stage-${st})`, ps.map((p) => row(p)));
  }
  const jump = h('div', { class: 'pl-pick-jump' }, ...[['hw', 'HW002'], ...STAGE_ORDER.map((s) => [s, s])].filter(([k]) => sections.has(k)).map(([k, t]) =>
    h('button', { type: 'button', class: 'pl-btn is-small', text: t, onclick: () => { haptic(); list.scrollTo({ top: sections.get(k).offsetTop, behavior: 'smooth' }); } })));
  const sheet = h('div', { class: 'sheet pl-sheet', role: 'dialog', 'aria-label': title, hidden: true },
    h('div', { class: 'sheet-grip' }),
    h('h2', { text: title }),
    h('div', { class: 'live', text: hint ? `${hint} · choose what it drives` : 'Choose what it drives' }),
    jump, list,
    h('div', { class: 'acts' }, h('button', { type: 'button', text: 'Close', onclick: closePicker })));
  sheet._outside = (e) => { if (!sheet.contains(e.target)) closePicker(); };
  document.body.append(sheet);
  openSheet = sheet;
  requestAnimationFrame(() => { sheet.hidden = false; });
  setTimeout(() => document.addEventListener('pointerdown', sheet._outside, true), 0);
  const cur = [...list.querySelectorAll('.is-current')].at(-1);
  if (cur && !sections.get('hw')?.contains(cur)) setTimeout(() => { list.scrollTop = Math.max(0, cur.offsetTop - 90); }, 30);
  return sheet;
}

// --- canvases and touches -----------------------------------------------------------------------------------------
/** A 2D canvas in `parent`, sized to its box on demand (pixel ratio capped at 2: four times fewer pixels than 3x). */
export function canvas2d(room, parent, { dprMax = 2, cls = '' } = {}) {
  const cv = h('canvas', { class: `pl-cv ${cls}`.trim() });
  parent.append(cv);
  const S = { cv, g: cv.getContext('2d'), w: 1, h: 1, dpr: 1, dirty: true };
  const ro = new ResizeObserver(() => { S.dirty = true; });
  ro.observe(cv);
  room.own(() => ro.disconnect());
  /** Fit the backing store, reset the transform to CSS px. Call at the top of draw(). */
  S.fit = () => {
    if (S.dirty) {
      S.dirty = false;
      const dpr = Math.min(devicePixelRatio || 1, dprMax);
      S.w = Math.max(1, cv.clientWidth); S.h = Math.max(1, cv.clientHeight); S.dpr = dpr;
      const W = Math.round(S.w * dpr), H = Math.round(S.h * dpr);
      if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
    }
    S.g.setTransform(S.dpr, 0, 0, S.dpr, 0, 0);
    return S;
  };
  return S;
}

/**
 * Multi-touch on el, in CSS px relative to el: down(p, all), move(p, all), up(p, all) where p = {id, x, y, x0, y0,
 * vx, vy (px/s), t0, moved}. The map `all` holds every finger down. Pointer capture where the browser allows it.
 */
export function pointers(el, { down, move, up, slop = 5 } = {}) {
  el.style.touchAction = 'none';
  const all = new Map();
  const at = (e) => { const r = el.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  el.addEventListener('pointerdown', (e) => {
    try { el.setPointerCapture?.(e.pointerId); } catch { /* a synthetic pointer has nothing to capture */ }
    const [x, y] = at(e);
    const p = { id: e.pointerId, x, y, x0: x, y0: y, px: x, py: y, vx: 0, vy: 0, t0: performance.now(), t: performance.now(), moved: false, e };
    all.set(e.pointerId, p);
    down?.(p, all);
  });
  el.addEventListener('pointermove', (e) => {
    const p = all.get(e.pointerId);
    if (!p) return;
    const [x, y] = at(e);
    const now = performance.now();
    const dt = Math.max(1, now - p.t) / 1000;
    p.px = p.x; p.py = p.y; p.x = x; p.y = y; p.e = e;
    p.vx = p.vx * 0.5 + ((x - p.px) / dt) * 0.5; p.vy = p.vy * 0.5 + ((y - p.py) / dt) * 0.5;
    p.t = now;
    if (!p.moved && Math.hypot(x - p.x0, y - p.y0) >= slop) p.moved = true;
    move?.(p, all);
  });
  const end = (e) => {
    const p = all.get(e.pointerId);
    if (!p) return;
    if (performance.now() - p.t > 90) { p.vx = 0; p.vy = 0; }      // a finger that stopped before lifting: no fling
    p.cancel = e.type === 'pointercancel';
    all.delete(e.pointerId);
    up?.(p, all);
  };
  el.addEventListener('pointerup', end);
  el.addEventListener('pointercancel', end);
  el.addEventListener('contextmenu', (e) => e.preventDefault());
  return all;
}

/** The params' values as one line ("COLDFIRE 37 % · COLOUR HZ 1.20 kHz"), for a screen's readout. */
export function readout(room, ids) {
  return ids.map((id) => { const p = room.params.get(id); return `${shortOf(p).toUpperCase()} ${format(p, room.store.real(id))}`; }).join('  ·  ');
}

/** A label for a time: "012.3" (bar.beat, from 1). */
export const barText = (c) => `${String(Math.max(0, c.bar) + 1).padStart(3, '0')}.${c.beat + 1}`;
