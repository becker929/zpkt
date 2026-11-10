// The Rummage's interface sounds: made in Ableton Live from paper, tin, wood, brass and found objects (in D where
// pitched) by hands/scripts/rummage/sounds.py, and played as rendered (docs/sound.md): decoded once, started, nothing
// else. No gain, no filters, nothing made here. sounds.json names each sound's files by content, a list where a
// sound has variants (step has three); the harness serves them from /studio/regions/rummage/audio/.
//
//   wake()        inside a touch: makes (or resumes) the audio context, as iOS requires, and loads the sounds
//   play(name)    step, pickup, place, open, lever, finish, tear, tick, stamp: one of its variants, at random
//   step()        a planted foot: every other one is heard
//   heard         what was started, for the tests: [name, file]
//
// The check's "Sound off" (map:sound-on) silences these too. A sound asked for while the context cannot run (no
// touch yet) is skipped, never played late.
const BASE = '/studio/regions/rummage/audio/';
let names = null;
const manifest = () => (names ??= fetch(new URL('sounds.json', import.meta.url), { cache: 'no-cache' })
  .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`sounds.json ${r.status}`))))
  .catch(() => { names = null; return {}; }));
const on = () => { try { return localStorage.getItem('map:sound-on') !== 'off'; } catch { return true; } };

let ctx = null, decoder = null, loading = null;
const buffers = new Map();                     // file -> Promise<AudioBuffer | null>
export const heard = [];

function decode(file) {
  if (!buffers.has(file)) {
    buffers.set(file, fetch(BASE + file)
      .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(`${r.status} ${file}`))))
      .then((data) => {
        decoder ??= ctx ?? new OfflineAudioContext(2, 1, 44100);       // any context decodes
        return decoder.decodeAudioData(data);
      })
      .catch(() => { buffers.delete(file); return null; }));
  }
  return buffers.get(file);
}

/** Fetch and decode every sound (once; a few seconds of audio in all). */
export function load() {
  loading ??= manifest().then((m) => Promise.all(Object.values(m).flat().map(decode)));
  return loading;
}

/** Make (or resume) the context; call from inside a touch. */
export function wake() {
  if (!on()) return;
  try {
    ctx ??= new AudioContext();
    if (ctx.state === 'suspended') ctx.resume();
  } catch { ctx = null; }
  load();
}

const last = new Map();
/** Start one of the sound's renders, as rendered. */
export async function play(name) {
  if (!on() || !ctx) return;
  const files = (await manifest())[name];
  if (!files?.length) return;
  let i = Math.floor(Math.random() * files.length);
  if (files.length > 1 && i === last.get(name)) i = (i + 1) % files.length;        // never the same step twice
  last.set(name, i);
  const buf = await decode(files[i]);
  if (!buf || !ctx) return;
  if (ctx.state !== 'running') {
    // resume() waits for a touch when there has been none: give it a moment, then let this one go
    await Promise.race([ctx.resume().catch(() => {}), new Promise((ok) => setTimeout(ok, 150))]);
    if (ctx.state !== 'running') return;
  }
  const src = ctx.createBufferSource();
  src.buffer = buf;
  src.connect(ctx.destination);
  src.onended = () => src.disconnect();
  src.start();
  heard.push([name, files[i]]);
  if (heard.length > 50) heard.shift();
}

let feet = 0, lastStep = 0;
/** A planted foot (hero.stepped): every other one plays a step, never closer than 180 ms. */
export function step() {
  feet += 1;
  const t = performance.now();
  if (feet % 2 || t - lastStep < 180) return;
  lastStep = t;
  play('step');
}
