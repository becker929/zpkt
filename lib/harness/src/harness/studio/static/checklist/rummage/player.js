// The short's renders through Web Audio: the player engine for a region (docs/rummage.md, docs/sound.md). Every
// combination of the three parts is its own render from Live (sh001-<bed>-<drums>-<bass>), all the same length and
// tempo. The renders in play are decoded and started together on one clock, each through its own gain, and only one
// is audible: a switch is a short equal-power crossfade between two of them at the identical playhead (they never
// restart), and each plays at its `gain_db`, so a switch is loudness-matched. Nothing is made or changed here: files
// are decoded and started as rendered, and the only gains are the crossfade, the loudness match and the few
// milliseconds of fade that keep a start from the middle, or a stop, from clicking.
//
//   const player = await createPlayer({ audio, base })   audio: audio.json; base: the URL its files are under
//   player.wake()                       inside a tap: makes (or remakes) the audio context, as iOS requires
//   await player.load(['1-1-1', ...])   decode these: the set that plays together (at most MAX_DECODED kept)
//   await player.play('1-1-1', { loop, from })    loop: false, true (the whole render) or [start s, end s]
//   await player.switchTo('2-1-1')      resolves {combo, at} when the crossfade starts (`at` on the audio clock)
//   player.stop({ fade })               a fade out: OUT_S by default, longer when a scene ends
//   player.playing                      the audible combo, or null;  player.wanted: the one asked for
//   player.position()                   seconds into the render, now;  player.duration: its length
//   player.onEnded(fn) / onChange(fn)   a play without loop reached its end / anything changed ({why, combo})
//   player.release(combos?)             drop decoded renders (every one not playing, if none are named)
//
// iOS: the context is made inside a tap (wake), and a page that went to the background stops what it plays; iOS
// often leaves the context interrupted, or running but silent, after that, so the next wake replaces it (decoded
// renders work in any context: they are kept).

export const MAX_DECODED = 4;           // a minute of stereo is about 20 MB decoded
const LEAD_S = 0.03;                    // a start or a switch is scheduled this far ahead, on a frame boundary
const XF_S = 0.06;                      // the crossfade
const IN_S = 0.005;                     // a start from the middle of a render fades in this fast
const OUT_S = 0.04;                     // a stop fades out
const POINTS = 65;                      // in each equal-power curve

const UP = Float32Array.from({ length: POINTS }, (_, i) => Math.sin((i / (POINTS - 1)) * Math.PI / 2));
const DOWN = Float32Array.from({ length: POINTS }, (_, i) => Math.cos((i / (POINTS - 1)) * Math.PI / 2));
const dbToGain = (db) => 10 ** ((Number.isFinite(db) ? db : 0) / 20);

/** A combo's key from the three parts' option ids: '<bed>-<drums>-<bass>', option 1 where none is chosen. */
export const comboKey = ({ bed, drums, bass } = {}) => `${bed ?? 1}-${drums ?? 1}-${bass ?? 1}`;
/** The option ids in a combo's key. */
export function comboParts(key) {
  const [bed, drums, bass] = String(key).split('-').map(Number);
  return { bed, drums, bass };
}

export async function createPlayer({ audio, base = '' }) {
  const combos = audio?.combos ?? {};
  const rate = audio?.sample_rate || 44100;
  const cache = new Map();              // combo -> {promise, buffer}; Map order is the LRU order
  const ended = new Set();
  const changed = new Set();
  let ctx = null;
  let stale = false;                    // the page has been in the background since the context was made
  let decoder = null;
  let queue = Promise.resolve();        // decodes run one at a time: less memory at once on a phone
  let set = [];                         // the combos that play together
  let session = null;                   // what is playing
  let token = 0;                        // a newer play or stop makes a pending play give up
  let last = 0;                         // the position when the last session stopped

  const has = (combo) => Boolean(combos[combo]?.file);
  const emit = (why, extra = {}) => { for (const fn of changed) fn({ why, combo: session?.audible ?? null, ...extra }); };

  // --- the context ------------------------------------------------------------------------------------------
  function wake() {
    if (ctx && (stale || ctx.state === 'closed')) replace();
    stale = false;
    if (!ctx) {
      try {
        ctx = new AudioContext({ latencyHint: 'interactive' });
      } catch {
        ctx = null;
        return null;
      }
      const mine = ctx;
      ctx.addEventListener('statechange', () => { if (mine === ctx) emit('context', { state: mine.state }); });
    }
    if (ctx.state !== 'running') ctx.resume().catch(() => {});
    try {
      if (navigator.audioSession) navigator.audioSession.type = 'playback';    // the ringer switch doesn't mute it
    } catch {
      // An older WebKit may refuse it.
    }
    // Older iOS unlocks the output only once a source has started inside the gesture: a frame of nothing.
    const blip = ctx.createBufferSource();
    blip.buffer = ctx.createBuffer(1, 1, ctx.sampleRate);
    blip.connect(ctx.destination);
    blip.start();
    return ctx;
  }

  function replace() {
    halt('background');
    const old = ctx;
    ctx = null;
    old.close().catch(() => {});
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'hidden') return;
    if (ctx) stale = true;
    if (session) halt('background');
  });

  // --- decoding ---------------------------------------------------------------------------------------------
  function ensure(combo) {
    let entry = cache.get(combo);
    if (entry) {
      cache.delete(combo);              // most recently used goes last
      cache.set(combo, entry);
      return entry;
    }
    entry = { buffer: null };
    const file = combos[combo]?.file;
    const bytes = file
      ? fetch(new URL(file, new URL(base || './', location.href)).href)
        .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(`${r.status} ${file}`))))
      : Promise.reject(new Error(`no render for ${combo}`));
    entry.promise = (queue = queue.catch(() => {}).then(() => bytes).then((data) => {
      if (cache.get(combo) !== entry) return null;                       // released while it was on its way
      // On the context when there is a sound one (at its rate); before a tap, or after the background, without one
      decoder ??= new OfflineAudioContext(2, 1, rate);
      return (ctx && !stale ? ctx : decoder).decodeAudioData(data);
    })).then((buffer) => {
      if (!buffer || cache.get(combo) !== entry) throw new Error(`${combo} was released`);
      entry.buffer = buffer;
      if (session && set.includes(combo)) join(session, combo);
      emit('loaded', { loaded: combo });
      return buffer;
    });
    entry.promise.catch((err) => {
      if (cache.get(combo) === entry) cache.delete(combo);
      if (!String(err?.message).endsWith('was released')) emit('error', { failed: combo, error: String(err?.message ?? err) });
    });
    cache.set(combo, entry);
    evict();
    return entry;
  }

  /** Keep at most MAX_DECODED, oldest use out first; never one that is playing or in the set. */
  function evict() {
    const busy = new Set([...set, ...(session ? session.voices.keys() : [])]);
    for (const combo of cache.keys()) {
      if (cache.size <= MAX_DECODED) break;
      if (!busy.has(combo)) cache.delete(combo);
    }
  }

  /** Decode these combos (the first ones first) and make them the set that plays together. Resolves with the
   * ones that are ready; a missing or broken render is left out. */
  async function load(list) {
    set = [...new Set(list)].filter(has);
    if (session) {                      // renders no longer in the set stop (they are silent: no click)
      for (const [combo, v] of session.voices) {
        if (set.includes(combo) || combo === session.audible || combo === session.wanted) continue;
        try { v.src.stop(); } catch { /* already ended */ }
        v.src.disconnect();
        session.voices.delete(combo);
      }
    }
    const entries = set.map((combo) => [combo, ensure(combo)]);
    evict();
    const got = await Promise.all(entries.map(([combo, e]) => e.promise.then(() => combo, () => null)));
    return got.filter(Boolean);
  }

  // --- playing ----------------------------------------------------------------------------------------------
  const frame = (t) => Math.ceil(t * ctx.sampleRate) / ctx.sampleRate;

  /** The playhead `elapsed` seconds after the session started. */
  function head(s, elapsed) {
    const p = s.from + Math.max(0, elapsed);
    if (!s.loop) return Math.min(p, s.length);
    const [a, b] = s.loop;
    return p < b ? p : a + ((p - a) % (b - a));
  }

  function voice(s, combo, when, level) {
    const src = ctx.createBufferSource();
    src.buffer = cache.get(combo).buffer;
    if (s.loop) {
      src.loop = true;
      src.loopStart = s.loop[0];
      src.loopEnd = s.loop[1];
    }
    const fade = ctx.createGain();
    fade.gain.value = level;
    const match = ctx.createGain();
    match.gain.value = dbToGain(combos[combo].gain_db);
    src.connect(fade);
    fade.connect(match);
    match.connect(s.master);
    src.onended = () => {
      src.disconnect();
      if (session === s && !s.loop && combo === s.audible) finish(s);
    };
    src.start(when, head(s, when - s.t0));
    const v = { src, fade, level };
    s.voices.set(combo, v);
    return v;
  }

  /** A render that finished decoding while the set plays: it starts silent, at the same playhead. */
  function join(s, combo) {
    if (s.voices.has(combo) || !ctx || session !== s) return;
    const when = frame(Math.max(ctx.currentTime + LEAD_S, s.t0));
    s.busy = Math.max(s.busy, when);
    voice(s, combo, when, 0);
    if (s.wanted === combo && s.audible !== combo) crossfade(s, combo);
  }

  /** From the audible render to `to`: an equal-power crossfade, scheduled after any still in flight, so each
   * gain's automation is only ever appended (never cut short, which could click). */
  function crossfade(s, to) {
    const at = frame(Math.max(ctx.currentTime + LEAD_S, s.busy));
    for (const [combo, v] of s.voices) {
      const level = combo === to ? 1 : 0;
      if (v.level === level) continue;
      v.fade.gain.setValueCurveAtTime(level ? UP : DOWN, at, XF_S);
      v.level = level;
    }
    s.busy = at + XF_S + 0.002;
    s.audible = to;
    s.switched = { combo: to, at };
    emit('switch', { at });
    return s.switched;
  }

  async function play(combo, { loop = false, from = 0 } = {}) {
    const mine = ++token;
    if (!ctx || stale) wake();
    if (!ctx) return false;
    if (session) halt('restart');
    if (!has(combo)) {
      emit('error', { failed: combo, error: `no render for ${combo}` });
      return false;
    }
    if (!set.includes(combo)) set = [combo, ...set];
    const entry = ensure(combo);
    let buffer;
    try {
      buffer = await entry.promise;
    } catch {
      return false;
    }
    if (mine !== token || !ctx) return false;
    if (ctx.state !== 'running') ctx.resume().catch(() => {});      // a context not running yet starts it all later
    const length = audio?.seconds && audio.seconds <= buffer.duration + 0.05 ? audio.seconds : buffer.duration;
    let span = null;
    if (loop) {
      const [a, b] = Array.isArray(loop) ? loop : [0, length];
      span = [Math.max(0, Math.min(a, buffer.duration - 0.1)), Math.min(b, buffer.duration)];
      if (span[1] - span[0] < 0.1) span = [0, length];
    }
    const start = Math.max(0, Math.min(from, (span ? span[1] : buffer.duration) - 0.01));
    const t0 = frame(ctx.currentTime + LEAD_S);
    const master = ctx.createGain();
    master.connect(ctx.destination);
    if (start > 0) {                                      // from the middle of a render: no click
      master.gain.setValueAtTime(0, t0);
      master.gain.linearRampToValueAtTime(1, t0 + IN_S);
    }
    const s = { t0, from: start, loop: span, length: buffer.duration, master, voices: new Map(), audible: combo,
                wanted: combo, busy: t0, switched: { combo, at: t0 } };
    session = s;
    voice(s, combo, t0, 1);
    for (const other of set) if (other !== combo && cache.get(other)?.buffer) voice(s, other, t0, 0);
    emit('play', { at: t0 });
    return true;
  }

  async function switchTo(combo) {
    const s = session;
    if (!s || !has(combo)) return null;
    s.wanted = combo;
    if (!set.includes(combo)) set = [...set, combo];
    const entry = ensure(combo);
    if (s.audible === combo) return { combo, at: ctx.currentTime };
    if (s.voices.has(combo)) return crossfade(s, combo);
    emit('pending', { pending: combo });
    try {
      await entry.promise;
    } catch {
      return null;
    }
    if (session !== s || s.wanted !== combo) return null;
    if (!s.voices.has(combo)) join(s, combo);
    else if (s.audible !== combo) crossfade(s, combo);
    return session === s && s.audible === combo ? s.switched : null;
  }

  function halt(why, fade = OUT_S) {
    const s = session;
    if (!s) return;
    session = null;
    last = position(s);
    const at = ctx.currentTime;
    const g = s.master.gain;
    if (typeof g.cancelAndHoldAtTime === 'function') g.cancelAndHoldAtTime(at);
    else { g.cancelScheduledValues(at); g.setValueAtTime(g.value, at); }
    g.linearRampToValueAtTime(0, at + fade);
    for (const v of s.voices.values()) {
      v.src.onended = null;
      try { v.src.stop(at + fade + 0.01); } catch { /* already ended */ }
    }
    setTimeout(() => s.master.disconnect(), (fade + 0.2) * 1000);
    emit(why, { combo: null, stopped: s.audible });
  }

  function finish(s) {
    if (session !== s) return;
    session = null;
    last = s.length;
    setTimeout(() => s.master.disconnect(), 200);
    emit('ended', { combo: null, stopped: s.audible });
    for (const fn of ended) fn(s.audible);
  }

  /** Stop, fading out over `fade` seconds (a few hundredths: no click; longer for a scene that ends). */
  function stop({ fade = OUT_S } = {}) {
    token += 1;
    halt('stop', Math.max(OUT_S, Math.min(2, fade)));
  }

  function position(s = session) {
    if (!s || !ctx) return last;
    return head(s, ctx.currentTime - s.t0);
  }

  function release(list) {
    const keep = new Set(session ? session.voices.keys() : []);
    for (const combo of list ?? [...cache.keys()]) if (!keep.has(combo)) cache.delete(combo);
    set = set.filter((combo) => cache.has(combo));
  }

  return {
    audio, base, has, wake, load, play, switchTo, stop, position, release,
    get playing() { return session?.audible ?? null; },
    get wanted() { return session?.wanted ?? null; },
    get looping() { return session?.loop ?? null; },
    get duration() { return audio?.seconds ?? session?.length ?? 0; },
    get context() { return ctx; },
    get decoded() { return [...cache.keys()].filter((c) => cache.get(c).buffer); },
    ready: (combo) => Boolean(cache.get(combo)?.buffer),
    onEnded(fn) { ended.add(fn); return () => ended.delete(fn); },
    onChange(fn) { changed.add(fn); return () => changed.delete(fn); },
  };
}
