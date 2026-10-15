// The check's contact sounds: interface sounds, not music (docs/sound.md allows these), made on the spot like
// studio's ready cue. Anthony wanted a bassy snap or clunk, not a ping, so there is a choice of them. Each is a low
// body that drops in pitch, with harmonics, so it still reads as low on an iPhone's speaker (which gives almost
// nothing under ~100 Hz), plus a short filtered-noise transient for the snap. All under 0.35 s (0.6 s when the
// commit finishes a step), quiet, with ramped starts and ends so nothing clicks. Nothing pitched or melodic.
// The context is made on the first touch (iOS only starts one inside a gesture) and the sound can be turned off.
import { onTap } from '../concepts/model.js';

export const SOUNDS = [
  { id: 'clunk', label: 'Clunk', about: 'Heavy and round: a weight set down on wood' },
  { id: 'snap', label: 'Snap', about: 'Tight: a hard snap over a short low body' },
  { id: 'latch', label: 'Latch', about: 'Metal: a tick, then the latch catches' },
  { id: 'stamp', label: 'Stamp', about: 'Rubbery: a stamp pressed onto the page' },
  { id: 'vault', label: 'Vault door', about: 'Deep and metallic, with a short ring' },
  { id: 'gavel', label: 'Gavel', about: 'Woody: a hard knock on a block' },
  { id: 'seal', label: 'Seal', about: 'Soft and low: a seal pressed into wax' },
  { id: 'bolt', label: 'Bolt', about: 'A bolt thrown home, a short rattle after' },
  { id: 'ledger', label: 'Ledger', about: 'A heavy book shut: air, paper, a low thump' },
  { id: 'crate', label: 'Crate', about: 'A crate put down: a dull, boxy thud' },
];

const KEY = 'map:sound';
const ON_KEY = 'map:sound-on';
const LAND = 0.3;                    // the box settling back into its row: the same sound, at about a third

export const soundId = () => {
  let id = null;
  try { id = localStorage.getItem(KEY); } catch { /* the default */ }
  return SOUNDS.some((s) => s.id === id) ? id : SOUNDS[0].id;
};
export function setSoundId(id) { try { localStorage.setItem(KEY, id); } catch { /* this visit only */ } }
export const soundOn = () => { try { return localStorage.getItem(ON_KEY) !== 'off'; } catch { return true; } };
export function setSound(on) { try { localStorage.setItem(ON_KEY, on ? 'on' : 'off'); } catch { /* this visit only */ } }

let ctx = null;

/** Make (or resume) the context; call from inside a touch. */
export function wake() {
  if (!soundOn()) return;
  try {
    ctx ??= new AudioContext();
    if (ctx.state === 'suspended') ctx.resume();
  } catch { ctx = null; }
}

/** Play `id` now, through a gain of `level`. A context still resuming plays when it's ready. */
function sound(id, level, strong) {
  if (!soundOn() || !ctx) return;
  const go = () => {
    const out = ctx.createGain();
    out.gain.value = level;
    out.connect(ctx.destination);
    const end = build(ctx, out, id, ctx.currentTime + 0.005, { strong });
    setTimeout(() => out.disconnect(), (end - ctx.currentTime + 0.1) * 1000);
  };
  if (ctx.state === 'running') go();
  else ctx.resume().then(go, () => {});
}

/** The contact. `strong`: the commit finished a step (heavier, with a longer low tail). */
export function play(id = soundId(), { strong = false } = {}) { sound(id, 1, strong); }
/** The box settling back into its row: the chosen sound, quiet. */
export function land() { sound(soundId(), LAND, false); }

// --- the graph ---
const noises = new WeakMap();
function noiseBuffer(c) {
  let buf = noises.get(c);
  if (buf) return buf;
  const len = Math.round(c.sampleRate * 0.5);
  buf = c.createBuffer(1, len, c.sampleRate);
  const d = buf.getChannelData(0);
  let s = 0x2545f491;
  for (let i = 0; i < len; i++) { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; d[i] = ((s >>> 0) / 4294967296) * 2 - 1; }
  noises.set(c, buf);
  return buf;
}

/** A gain that rises over `attack` and falls exponentially to nothing at t + len. */
function env(c, t, gain, len, attack = 0.002) {
  const g = c.createGain();
  g.gain.setValueAtTime(0, t);
  g.gain.linearRampToValueAtTime(gain, t + attack);
  g.gain.exponentialRampToValueAtTime(0.0001, t + len);
  g.gain.setValueAtTime(0, t + len + 0.005);
  return g;
}

/** A body: an oscillator falling from f0 to f1 over `drop` (optionally through a lowpass at `lp`). */
function tone(c, dest, t, { f0, f1 = f0, drop = 0.08, len, gain, type = 'sine', lp = 0, attack }) {
  const o = c.createOscillator();
  o.type = type;
  o.frequency.setValueAtTime(f0, t);
  if (f1 !== f0) o.frequency.exponentialRampToValueAtTime(f1, t + drop);
  const g = env(c, t, gain, len, attack);
  let node = o;
  if (lp) { const f = c.createBiquadFilter(); f.type = 'lowpass'; f.frequency.value = lp; node = node.connect(f); }
  node.connect(g).connect(dest);
  o.start(t); o.stop(t + len + 0.02);
  return t + len + 0.02;
}

/** A transient or an air thump: noise through a filter (frequency gliding to `to`, if given). */
function hiss(c, dest, t, { type = 'lowpass', freq, to = 0, q = 1, len, gain, attack = 0.001 }) {
  const src = c.createBufferSource();
  src.buffer = noiseBuffer(c);
  const f = c.createBiquadFilter();
  f.type = type; f.Q.value = q;
  f.frequency.setValueAtTime(freq, t);
  if (to) f.frequency.exponentialRampToValueAtTime(to, t + len);
  const g = env(c, t, gain, len, attack);
  src.connect(f).connect(g).connect(dest);
  src.start(t); src.stop(t + len + 0.02);
  return t + len + 0.02;
}

// Each recipe takes the length factor `k` (1, or longer when strong) and returns its layers. Gains are kept so a
// recipe sums to ~0.35 at most, before the strong tail.
const RECIPES = {
  clunk: (k) => [
    ['tone', { f0: 180, f1: 82, drop: 0.12, len: 0.22 * k, gain: 0.2 }],
    ['tone', { f0: 360, f1: 165, drop: 0.08, len: 0.08 * k, gain: 0.06, type: 'triangle' }],
    ['hiss', { freq: 900, len: 0.025, gain: 0.08 }],
  ],
  snap: (k) => [
    ['hiss', { type: 'bandpass', freq: 1500, q: 2.5, len: 0.018, gain: 0.12 }],
    ['tone', { f0: 160, f1: 70, drop: 0.07, len: 0.14 * k, gain: 0.2 }],
    ['tone', { f0: 320, f1: 140, drop: 0.04, len: 0.05, gain: 0.04, type: 'triangle' }],
  ],
  latch: (k) => [
    ['hiss', { type: 'bandpass', freq: 2600, q: 4, len: 0.012, gain: 0.05 }],
    ['tone', { at: 0.035, f0: 120, f1: 110, len: 0.09 * k, gain: 0.08, type: 'square', lp: 650 }],
    ['tone', { at: 0.035, f0: 145, f1: 88, drop: 0.08, len: 0.16 * k, gain: 0.18 }],
    ['hiss', { at: 0.035, type: 'bandpass', freq: 1100, q: 6, len: 0.03, gain: 0.04 }],
  ],
  stamp: (k) => [
    ['tone', { f0: 125, f1: 60, drop: 0.1, len: 0.2 * k, gain: 0.21, attack: 0.004 }],
    ['hiss', { freq: 420, len: 0.06, gain: 0.12, attack: 0.003 }],
  ],
  vault: (k) => [
    ['tone', { f0: 98, f1: 55, drop: 0.2, len: 0.32 * k, gain: 0.2 }],
    ['tone', { f0: 196, f1: 110, drop: 0.12, len: 0.14 * k, gain: 0.07, type: 'triangle' }],
    ['hiss', { type: 'bandpass', freq: 620, q: 14, len: 0.18, gain: 0.06 }],
    ['hiss', { freq: 700, len: 0.02, gain: 0.04 }],
  ],
  gavel: (k) => [
    ['hiss', { type: 'bandpass', freq: 430, q: 6, len: 0.07, gain: 0.14 }],
    ['tone', { f0: 210, f1: 160, drop: 0.05, len: 0.09 * k, gain: 0.1 }],
    ['tone', { f0: 108, f1: 80, drop: 0.08, len: 0.15 * k, gain: 0.14 }],
  ],
  seal: (k) => [
    ['tone', { f0: 95, f1: 68, drop: 0.15, len: 0.26 * k, gain: 0.2, attack: 0.006 }],
    ['hiss', { freq: 260, len: 0.12, gain: 0.09, attack: 0.005 }],
    ['hiss', { type: 'bandpass', freq: 3000, q: 3, len: 0.008, gain: 0.012 }],
  ],
  bolt: (k) => [
    ['tone', { f0: 165, f1: 74, drop: 0.09, len: 0.18 * k, gain: 0.2 }],
    ['tone', { f0: 80, len: 0.1 * k, gain: 0.06, type: 'square', lp: 500 }],
    ['hiss', { freq: 1000, len: 0.02, gain: 0.05 }],
    ['hiss', { at: 0.07, type: 'bandpass', freq: 1400, q: 5, len: 0.012, gain: 0.025 }],
    ['hiss', { at: 0.1, type: 'bandpass', freq: 1250, q: 5, len: 0.01, gain: 0.015 }],
  ],
  ledger: (k) => [
    ['hiss', { freq: 320, to: 120, len: 0.14 * k, gain: 0.16, attack: 0.003 }],
    ['tone', { f0: 112, f1: 55, drop: 0.14, len: 0.24 * k, gain: 0.18 }],
    ['hiss', { type: 'bandpass', freq: 1200, q: 1.5, len: 0.015, gain: 0.04 }],
  ],
  crate: (k) => [
    ['tone', { f0: 142, f1: 96, drop: 0.06, len: 0.2 * k, gain: 0.16, type: 'triangle', lp: 420 }],
    ['tone', { f0: 96, f1: 70, drop: 0.1, len: 0.18 * k, gain: 0.12 }],
    ['hiss', { freq: 700, len: 0.05, gain: 0.08 }],
  ],
};

/** Build sound `id` into `dest`, landing at time `t`; returns when its last node stops. */
export function build(c, dest, id, t, { strong = false } = {}) {
  const recipe = RECIPES[id] ?? RECIPES[SOUNDS[0].id];
  const out = c.createGain();
  out.gain.value = strong ? 0.85 : 1;            // room for the tail under it
  out.connect(dest);
  let end = t;
  for (const [kind, { at = 0, ...o }] of recipe(strong ? 1.6 : 1)) {
    end = Math.max(end, (kind === 'tone' ? tone : hiss)(c, out, t + at, o));
  }
  if (strong) end = Math.max(end, tone(c, out, t, { f0: 70, f1: 44, drop: 0.3, len: 0.5, gain: 0.12, attack: 0.008 }));
  return end;
}

// --- the picker ---
const SVG = 'http://www.w3.org/2000/svg';
function speaker() {
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
  for (const [d, cls] of [['M4 9h4l5-4v14l-5-4H4z', ''], ['M16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12', 'w'], ['M16 9l6 6M22 9l-6 6', 'x']]) {
    const p = document.createElementNS(SVG, 'path');
    p.setAttribute('d', d); if (cls) p.setAttribute('class', cls);
    svg.append(p);
  }
  return svg;
}

/** The sounds as a list to pick from (each tap previews), with an on/off switch at the top. */
export function picker(host, { onPick } = {}) {
  const root = document.createElement('div');
  root.className = 'sp';
  const sw = document.createElement('button');
  sw.type = 'button'; sw.className = 'sp-on'; sw.setAttribute('role', 'switch');
  const swText = document.createElement('span');
  sw.append(speaker(), swText);
  const list = document.createElement('div');
  list.className = 'sp-list'; list.setAttribute('role', 'radiogroup'); list.setAttribute('aria-label', 'Check sound');
  const rows = SOUNDS.map((s) => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'sp-row'; b.setAttribute('role', 'radio'); b.dataset.id = s.id;
    const mark = document.createElement('i');
    const label = document.createElement('b'); label.textContent = s.label;
    const about = document.createElement('span'); about.textContent = s.about;
    b.append(mark, label, about);
    onTap(b, () => {
      setSoundId(s.id); paint();
      wake(); play(s.id);
      onPick?.(s.id);
    });
    return b;
  });
  list.append(...rows);
  onTap(sw, () => { const on = !soundOn(); setSound(on); paint(); if (on) { wake(); play(); } });
  function paint() {
    const on = soundOn(), id = soundId();
    sw.setAttribute('aria-checked', String(on));
    swText.textContent = on ? 'Sound on' : 'Sound off';
    root.classList.toggle('off', !on);
    for (const b of rows) b.setAttribute('aria-checked', String(b.dataset.id === id));
  }
  paint();
  root.append(sw, list);
  host.append(root);
  return { destroy: () => root.remove() };
}
