// The player engine. Sound rule: no instruments in the browser. It only plays rendered files as they are (a playback
// library would be allowed for this too); no synthesis, no effects, no mix moves.
// One AudioContext for the page, a small cache of decoded files, one-shots for pads, and the A/B deck.

let ctx = null;
const bufs = new Map(); // url -> Promise<AudioBuffer>, least recently used first

export function audio() {
  if (!ctx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) throw new Error('This browser has no Web Audio');
    ctx = new AC();
  }
  if (ctx.state === 'suspended') ctx.resume();
  return ctx;
}

export function load(url) {
  if (bufs.has(url)) { const p = bufs.get(url); bufs.delete(url); bufs.set(url, p); return p; }
  const p = fetch(url).then(async (r) => {
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `HTTP ${r.status}`);
    return audio().decodeAudioData(await r.arrayBuffer());
  });
  p.catch(() => bufs.delete(url));
  bufs.set(url, p);
  while (bufs.size > 6) bufs.delete(bufs.keys().next().value); // decoded audio is big: keep a few files only
  return p;
}
export const forget = (url) => bufs.delete(url);

/** Play a file once, as rendered (pads). */
export async function oneShot(url) {
  const a = audio();
  const s = a.createBufferSource();
  s.buffer = await load(url);
  s.connect(a.destination);
  s.start();
  return s;
}

/** Waveform peaks (0..1) of a decoded file, for drawing. */
export function peaksOf(b, n = 360) {
  const d = b.getChannelData(0), d2 = b.numberOfChannels > 1 ? b.getChannelData(1) : null;
  const per = Math.max(1, Math.floor(d.length / n));
  const out = [];
  for (let i = 0; i < n; i++) {
    let m = 0;
    for (let j = i * per, e = Math.min(d.length, j + per); j < e; j += 4) { const x = Math.abs(d[j]) + (d2 ? Math.abs(d2[j]) : 0); if (x > m) m = x; }
    out.push(+Math.min(1, d2 ? m / 2 : m).toFixed(3));
  }
  return out;
}

const barLen = (bpm) => 240 / bpm; // 4/4

/** Loop region in seconds of one track: from its downbeat, startBar for N bars. */
export function loopOf(t, loop, duration) {
  const s = t.downbeatMs / 1000 + (loop.startBar - 1) * barLen(t.bpm);
  const e = Math.min(duration, s + loop.bars * barLen(t.bpm));
  // A loop that starts past the end of the file (a wrong bar or downbeat) would be silence: play the whole file.
  return e - s >= 0.05 ? [s, e] : [0, duration];
}

/** When a switch requested at `now` lands: the next beat or bar of the deck's clock, or right away. */
export function switchTime(now, t0, bpm, quantize) {
  const q = quantize === 'bar' ? barLen(bpm) : quantize === 'beat' ? 60 / bpm : 0;
  return q ? t0 + Math.ceil((now - t0 + 0.01) / q) * q : now + 0.01;
}

/**
 * A deck: renders loop locked to one clock (the first one's bar grid); one is heard, the others run silent.
 * Two of them (a, b) is the A/B deck; a deck of versions has as many as it was given, keyed by their letters.
 * Switching swaps them on the next beat or bar with an equal-power declick, so it never clicks or loses the beat.
 * Events: onStatus(text), onFrame({ side, frac }) while playing, onSwitched(side) when a switch becomes audible.
 */
export class Deck {
  constructor(spec, urls, { onStatus = () => {}, onFrame = () => {}, onSwitched = () => {} } = {}) {
    Object.assign(this, { spec, urls, onStatus, onFrame, onSwitched });
    this.keys = Object.keys(urls);
    this.playing = false;
    this.side = this.keys[0];
  }

  async load() {
    this.onStatus('loading…');
    const got = await Promise.all(this.keys.map((k) => load(this.urls[k])));
    if (this.dead) return null;
    this.buf = Object.fromEntries(this.keys.map((k, i) => [k, got[i]]));
    this.loops = Object.fromEntries(this.keys.map((k) => [k, loopOf(this.spec[k], this.spec.loop, this.buf[k].duration)]));
    const whole = this.keys.filter((s) => this.loops[s][0] === 0 && this.loops[s][1] === this.buf[s].duration && this.spec.loop.startBar > 1);
    this.onStatus(whole.length ? `ready · bar ${this.spec.loop.startBar} is past the end of ${whole.map((s) => s.toUpperCase()).join(' and ')}, playing the whole file` : 'ready');
    return {
      peaks: Object.fromEntries(this.keys.map((k) => [k, peaksOf(this.buf[k])])),
      region: Object.fromEntries(this.keys.map((k) => [k, this.loops[k].map((x) => x / this.buf[k].duration)])),
    };
  }

  play(side) {
    if (!this.buf) return this.onStatus('still loading…');
    if (this.playing) this.stop();
    const a = audio(), first = this.keys[0];
    this.side = this.target = side;
    this.t0 = a.currentTime + 0.08;
    this.loopLen = Math.max(0.05, this.loops[first][1] - this.loops[first][0]);
    this.srcs = {}; this.gains = {};
    for (const s of this.keys) {
      const src = a.createBufferSource();
      src.buffer = this.buf[s];
      src.loop = true;
      [src.loopStart, src.loopEnd] = this.loops[s];
      const g = a.createGain();
      g.gain.value = s === side ? 1 : 0;
      src.connect(g).connect(a.destination);
      src.start(this.t0, this.loops[s][0]);
      this.srcs[s] = src; this.gains[s] = g;
    }
    this.playing = true;
    const tick = () => {
      if (!this.playing) return;
      const now = a.currentTime;
      if (now >= this.t0) {
        const pos = (now - this.t0) % this.loopLen;
        const beat = 60 / this.spec[first].bpm;
        this.onStatus(`bar ${this.spec.loop.startBar + Math.floor(pos / (beat * 4))}.${1 + Math.floor((pos % (beat * 4)) / beat)}`);
        this.onFrame({ side: this.side, frac: pos / this.loopLen });
      }
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  }

  stop() {
    this.playing = false;
    cancelAnimationFrame(this.raf);
    clearTimeout(this.pendT);
    for (const s of Object.values(this.srcs || {})) try { s.stop(); } catch {}
    this.srcs = null;
    this.onStatus('stopped');
  }

  /** Returns seconds until the switch is audible (0 when stopped: it just takes effect next play). */
  switchTo(side) {
    if (!this.playing) { this.side = this.target = side; return 0; }
    const a = audio(), now = a.currentTime;
    if (side === this.target) return Math.max(0, (this.switchAt || 0) - now);   // already there, or on its way: fading again would click
    this.target = side;
    if (side === this.side) {   // back to the side still heard: call the pending switch off
      clearTimeout(this.pendT);
      this.switchAt = 0;
      for (const s of this.keys) try { const g = this.gains[s].gain; g.cancelScheduledValues(now); g.setValueAtTime(s === side ? 1 : 0, now); } catch {}
      return 0;
    }
    const at = switchTime(now, this.t0, this.spec[this.keys[0]].bpm, this.spec.quantize);
    const n = 16, up = new Float32Array(n), down = new Float32Array(n);
    for (let i = 0; i < n; i++) { const x = i / (n - 1); up[i] = Math.sin((x * Math.PI) / 2); down[i] = Math.cos((x * Math.PI) / 2); }
    for (const s of this.keys) {
      const g = this.gains[s].gain;
      if (s !== side && s !== this.side) {   // a third version, silent or on its way in from a switch that never landed: just off
        try { g.cancelScheduledValues(now); g.setValueAtTime(0, now); } catch {}
        continue;
      }
      // A fade that is already running cannot be cancelled cleanly everywhere; then the gain is simply set.
      try {
        g.cancelScheduledValues(now);
        g.setValueAtTime(g.value, now);
        g.setValueCurveAtTime(s === side ? up : down, at, 0.012);
      } catch { try { g.cancelScheduledValues(0); g.setValueAtTime(s === side ? 1 : 0, at + 0.02); } catch {} }
    }
    clearTimeout(this.pendT);
    this.switchAt = at;
    this.pendT = setTimeout(() => { this.side = side; this.switchAt = 0; this.onSwitched(side); }, Math.max(0, (at - now) * 1000));
    return at - now;
  }

  /** Freeze: stop and let the decoded files go. */
  destroy() {
    this.dead = true;
    if (this.playing) this.stop();
    for (const k of this.keys) forget(this.urls[k]);
    this.buf = null;
  }
}
