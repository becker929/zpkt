// The checklist's state for the concept pages: the same track data and the same saved checks as the checklist page
// (localStorage `checklist:<track>`), so a check made in one view shows in all of them. Release is never locked:
// a gate item is a decision point, not a door, and nothing here refuses an action because something else is open.
export { onTap } from '../tweaks.js';

export const TRACK = new URLSearchParams(location.search).get('track') || 'hw002';
const KEY = `checklist:${TRACK}`;

let saved = {};
const listeners = new Set();
function load() { try { saved = JSON.parse(localStorage.getItem(KEY)) || {}; } catch { saved = {}; } }
function save() { try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch { /* private mode: this visit only */ } }
load();
addEventListener('storage', (e) => { if (e.key === KEY) { load(); for (const fn of listeners) fn(); } });

/** The track's steps and items (data/<track>.json). */
export async function loadTrack() {
  const r = await fetch(`../data/${encodeURIComponent(TRACK)}.json`, { cache: 'no-cache' });
  if (!r.ok) throw new Error(`no checklist for ${TRACK}`);
  return r.json();
}

/** Run `fn` after any change to the checks, here or in another tab. */
export const onChange = (fn) => listeners.add(fn);
const changed = () => { save(); for (const fn of listeners) fn(); };

export const keyOf = (step, it) => `${step.id}.${it.id}`;
export const stateOf = (step, it) => saved[keyOf(step, it)] ?? it.state;      // done | open | waiting | agent
export const isDone = (step, it) => stateOf(step, it) === 'done';
/** Clear an item, or open it again (back to the state the data gives it, or open). */
export function setDone(step, it, done) {
  saved[keyOf(step, it)] = done ? 'done' : (it.state === 'done' ? 'open' : it.state);
  changed();
}
/** A concept's own value kept with the checks (e.g. `kick.drive!crack`); other views ignore keys they don't know. */
export const extra = (key) => saved[key];
export function setExtra(key, value) {
  if (value === undefined) delete saved[key]; else saved[key] = value;
  changed();
}
export function resetAll() { saved = {}; changed(); }

export const cleared = (step) => step.items.filter((it) => isDone(step, it)).length;
export const isClear = (step) => cleared(step) === step.items.length;
/** The lowest step with something open: a suggestion of where to work, never a lock. */
export const current = (data) => data.steps.find((s) => !isClear(s)) ?? null;
export const totals = (data) => data.steps.reduce((a, s) => [a[0] + cleared(s), a[1] + s.items.length], [0, 0]);

/** Each item's place on its step's path, as on the checklist page: done; you (your first open item, and anything
 * waiting on your listening); clearing (the agent's item); ready (between you and the agent: cleared by the agent,
 * waiting on your move); ahead (past the agent). */
export function roles(step) {
  const st = step.items.map((it) => stateOf(step, it));
  const you = st.findIndex((x) => x !== 'done');
  const agent = st.lastIndexOf('agent');
  return st.map((x, i) => {
    if (x === 'done') return 'done';
    if (i === you || x === 'waiting') return 'you';
    if (x === 'agent') return 'clearing';
    return agent > you && i > you && i < agent ? 'ready' : 'ahead';
  });
}

export const studioHref = (step, it) => `/studio/?focus=${encodeURIComponent(`${TRACK}.${step.id}.${it.id}`)}`;

// --- determinism: the same input always draws the same thing ---
/** FNV-1a, 32 bits. */
export function hash(str) {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 0x01000193); }
  return h >>> 0;
}
/** A seeded generator (mulberry32): rng() in [0, 1). */
export function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// --- haptics: iPhone Safari has no vibrate(); toggling an <input switch> through its label ticks (iOS 18+). A page
// that wants them carries <label class="haptic" aria-hidden="true"><input type="checkbox" switch tabindex="-1"></label>.
let lastTick = 0;
export function haptic(strong = false) {
  const now = performance.now();
  if (now - lastTick < 35) return;
  lastTick = now;
  if (navigator.vibrate) { navigator.vibrate(strong ? 22 : 6); return; }
  document.querySelector('label.haptic')?.click();
}
