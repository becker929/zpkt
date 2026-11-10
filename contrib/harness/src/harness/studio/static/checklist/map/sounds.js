// The check's sounds: interface sounds rendered in Ableton Live, played as rendered (docs/sound.md). Each is three
// layers in Live (a low body from Operator with a pitch drop, a click transient, a splashy mid-high of noise-FM
// through a filter), with an Echo on the splash, a ping-pong Delay return, and Drum Buss (distortion, transients,
// boom), Glue Compressor and a Limiter on Main. The recipe that makes them is hands/scripts/ui_sounds/ (one set,
// six variants, each rendered three times: the hit, a heavier one for a commit that finishes a step, and a soft knock
// for the box settling back into its row). Here they are only decoded and started: no gain, no filters, nothing made.
// The files are in R2, not git; sounds.json names them (by content) and the harness serves them from sounds/.
// Files are decoded ahead (any context decodes); the real context is made on the first touch, as iOS requires.
import { onTap } from '../concepts/model.js';

export const SOUNDS = [
  { id: 'anvil', label: 'Anvil', about: 'A hammer on steel: a tight low thump, a bright metal ring, a slap of echo' },
  { id: 'vault', label: 'Vault', about: 'Deep and heavy: a big low body, a hiss on top, a slow dotted echo' },
  { id: 'crack', label: 'Crack', about: 'Snappy: a sharp crack on top, a short punch under it, a quick ping-pong' },
  { id: 'slam', label: 'Slam', about: 'Squashed hard: compressed and saturated, a splash that blooms after the hit' },
  { id: 'block', label: 'Block', about: 'Woody: a knock on a heavy block, a boxy mid splash, a short tail' },
  { id: 'thunder', label: 'Thunder', about: 'Wide and rolling: a boomy body, a crashing splash, echoes that roll away' },
];
export const KINDS = ['hit', 'strong', 'land'];
let names = null;
const manifest = () => (names ??= fetch(new URL('sounds.json', import.meta.url), { cache: 'no-cache' })
  .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`sounds.json ${r.status}`))))
  .catch(() => { names = null; return {}; }));
/** The URL of one sound's file. */
export async function fileOf(id, kind) {
  const file = (await manifest())[id]?.[kind];
  return file ? new URL(`sounds/${file}`, import.meta.url).href : null;
}

const KEY = 'map:sound';
const ON_KEY = 'map:sound-on';

export const soundId = () => {
  let id = null;
  try { id = localStorage.getItem(KEY); } catch { /* the default */ }
  return SOUNDS.some((s) => s.id === id) ? id : SOUNDS[0].id;
};
export function setSoundId(id) { try { localStorage.setItem(KEY, id); } catch { /* this visit only */ } }
export const soundOn = () => { try { return localStorage.getItem(ON_KEY) !== 'off'; } catch { return true; } };
export function setSound(on) { try { localStorage.setItem(ON_KEY, on ? 'on' : 'off'); } catch { /* this visit only */ } }

let ctx = null;
let decoder = null;
const buffers = new Map();                 // `${id}-${kind}` -> Promise<AudioBuffer | null>

/** Fetch and decode one sound's three files (once). */
export function load(id = soundId()) {
  for (const kind of KINDS) {
    const k = `${id}-${kind}`;
    if (buffers.has(k)) continue;
    buffers.set(k, fileOf(id, kind)
      .then((url) => (url ? fetch(url) : Promise.reject(new Error(`no file for ${k}`))))
      .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(`${r.status} ${k}`))))
      .then((data) => {
        decoder ??= ctx ?? new OfflineAudioContext(2, 1, 44100);
        return decoder.decodeAudioData(data);
      })
      .catch(() => { buffers.delete(k); return null; }));
  }
}

/** Make (or resume) the context; call from inside a touch. */
export function wake() {
  if (!soundOn()) return;
  try {
    ctx ??= new AudioContext();
    if (ctx.state === 'suspended') ctx.resume();
  } catch { ctx = null; }
  load();
}

async function start(id, kind) {
  if (!soundOn() || !ctx) return;
  load(id);
  const buf = await buffers.get(`${id}-${kind}`);
  if (!buf || !ctx) return;
  if (ctx.state !== 'running') { try { await ctx.resume(); } catch { return; } }
  const src = ctx.createBufferSource();
  src.buffer = buf;
  src.connect(ctx.destination);
  src.onended = () => src.disconnect();
  src.start();
}

/** The contact: `strong` when the commit finishes a step. */
export function play(id = soundId(), { strong = false } = {}) { start(id, strong ? 'strong' : 'hit'); }
/** The box settling back into its row. */
export function land(id = soundId()) { start(id, 'land'); }

const SVG = 'http://www.w3.org/2000/svg';
function icon(paths) {
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
  for (const [d, cls] of paths) {
    const p = document.createElementNS(SVG, 'path');
    p.setAttribute('d', d); if (cls) p.setAttribute('class', cls);
    svg.append(p);
  }
  return svg;
}
const speaker = () => icon([['M4 9h4l5-4v14l-5-4H4z', ''], ['M16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12', 'w'], ['M16 9l6 6M22 9l-6 6', 'x']]);

/** The sounds as a list to pick from (a tap picks and plays the hit), each with buttons to hear its other two:
 * the heavier one for a finished step and the soft knock. An on/off switch at the top. */
export function picker(host, { onPick } = {}) {
  const root = document.createElement('div');
  root.className = 'sp';
  const sw = document.createElement('button');
  sw.type = 'button'; sw.className = 'sp-on'; sw.setAttribute('role', 'switch');
  const swText = document.createElement('span');
  sw.append(speaker(), swText);
  const note = document.createElement('p');
  note.className = 'sp-note';
  note.textContent = 'Rendered in Ableton Live: a low body, a click, a splash, with delay, distortion and compression.';
  const list = document.createElement('div');
  list.className = 'sp-list'; list.setAttribute('role', 'radiogroup'); list.setAttribute('aria-label', 'Check sound');
  const rows = SOUNDS.map((s) => {
    const item = document.createElement('div');
    item.className = 'sp-item';
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'sp-row'; b.setAttribute('role', 'radio'); b.dataset.id = s.id;
    const mark = document.createElement('i');
    const label = document.createElement('b'); label.textContent = s.label;
    const about = document.createElement('span'); about.textContent = s.about;
    b.append(mark, label, about);
    onTap(b, () => {
      setSoundId(s.id); paint();
      wake(); load(s.id); play(s.id);
      onPick?.(s.id);
    });
    const alts = document.createElement('div');
    alts.className = 'sp-alts';
    for (const [kind, text] of [['strong', 'Step done'], ['land', 'Settle']]) {
      const a = document.createElement('button');
      a.type = 'button'; a.className = 'sp-alt'; a.dataset.kind = kind; a.textContent = text;
      a.setAttribute('aria-label', `${s.label}: ${text.toLowerCase()}`);
      onTap(a, () => { wake(); load(s.id); start(s.id, kind); });
      alts.append(a);
    }
    item.append(b, alts);
    return item;
  });
  list.append(...rows);
  onTap(sw, () => { const on = !soundOn(); setSound(on); paint(); if (on) { wake(); play(); } });
  function paint() {
    const on = soundOn(), id = soundId();
    sw.setAttribute('aria-checked', String(on));
    swText.textContent = on ? 'Sound on' : 'Sound off';
    root.classList.toggle('off', !on);
    for (const item of rows) { const b = item.querySelector('.sp-row'); b.setAttribute('aria-checked', String(b.dataset.id === id)); }
  }
  paint();
  root.append(sw, note, list);
  host.append(root);
  return { destroy: () => root.remove() };
}
