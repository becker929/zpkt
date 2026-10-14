// The granular player: short windowed pieces of a source ("grains"), scheduled on the audio clock a little ahead,
// like the engine's own steps. A voice is a finger (or a frozen finger, or the drifting ghost): it has a position in
// the source and sprays grains around it. Size, density, spray, pitch, backwards chance and stereo spread come from
// the store each tick. Bounded: at most 5 voices, 150 grains a second between them, 56 grains alive at once.

import { bufferNow, reversedPiece } from './sources.js';

const LOOKAHEAD = 0.1;
const TICK_MS = 25;
export const MAX_LIVE = 56;
const MAX_RATE = 150;
const MAX_VOICES = 5;
const HANN = Float32Array.from({ length: 33 }, (_, i) => 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / 32));

export class Grains {
  /** read() -> {size s, density /s, spray 0..1, pitch st, rev 0..1, drift 0..1, pan 0..1, ymode 0..2, sync 0..3} */
  constructor(G, engine, read) {
    this.G = G;
    this.engine = engine;
    this.read = read;
    this.voices = new Map();
    this.recent = [];
    this.live = 0;
    this.fired = 0;
    this.timer = 0;
  }

  start() { if (!this.timer) this.timer = setInterval(() => this.tick(), TICK_MS); }
  stop() { clearInterval(this.timer); this.timer = 0; this.releaseAll(); }

  _bus(src) {
    const ctx = this.G.ctx;
    const out = ctx.createGain();
    const panL = ctx.createStereoPanner(), panR = ctx.createStereoPanner();
    panL.connect(out); panR.connect(out);
    out.connect(this.G.input(src));
    return { out, panL, panR };
  }

  /** A finger down (or moved) at `pos` seconds in `src`; y 0 (top) .. 1 (bottom). */
  hold(key, src, pos, y = 0.5, { ghost = false, amp = 1 } = {}) {
    let v = this.voices.get(key);
    if (v && v.src !== src) { this._kill(v); v = null; }
    if (!v) {
      if (this.voices.size >= MAX_VOICES) {
        const spare = [...this.voices.values()].find((x) => x.frozen || x.ghost);
        if (!spare) return null;
        this._kill(spare);
      }
      v = {
        key, src, pos, y, held: !ghost, frozen: false, ghost, amp, wander: 0, tgt: 0, tgtT: 0, alt: 0, lastEnd: 0,
        next: this.G.ctx.currentTime + 0.004, born: performance.now(), ...this._bus(src),
      };
      this.voices.set(key, v);
    } else Object.assign(v, { pos, y, held: !ghost, frozen: false });
    return v;
  }

  move(key, pos, y) { const v = this.voices.get(key); if (v) { v.pos = pos; if (y != null) v.y = y; } }

  /** A finger up: the voice stops, or with freeze on it keeps playing where it was. */
  lift(key, freeze = false) {
    const v = this.voices.get(key);
    if (!v) return;
    if (freeze) { v.held = false; v.frozen = true; } else this._kill(v);
  }

  releaseFrozen() { for (const v of [...this.voices.values()]) if (v.frozen) this._kill(v); }
  releaseAll() { for (const v of [...this.voices.values()]) this._kill(v); }
  has(key) { return this.voices.has(key); }

  _kill(v) {
    this.voices.delete(v.key);
    const wait = Math.max(0, v.lastEnd - this.G.ctx.currentTime) + 0.1;
    setTimeout(() => { try { v.out.disconnect(); v.panL.disconnect(); v.panR.disconnect(); } catch { /* */ } }, wait * 1000);
  }

  tick() {
    const G = this.G;
    if (G.disposed || !this.voices.size) return;
    const ctx = G.ctx, now = ctx.currentTime;
    const P = this.read();
    const n = this.voices.size;
    const dens = Math.min(P.density, MAX_RATE / n);
    const dt = TICK_MS / 1000;
    const pos = this.engine.position();
    const sync = P.sync && pos.playing ? this.engine.stepSeconds / [1, 1, 2, 4][P.sync] : 0;
    for (const v of this.voices.values()) {
      // drift: glide towards a new random offset every second or so
      const R = P.drift * (v.ghost ? (v.range ?? 4) : 1.5);
      v.tgtT -= dt;
      if (v.tgtT <= 0) { v.tgt = R ? (Math.random() * 2 - 1) * R : 0; v.tgtT = 0.6 + Math.random() * 1.4; }
      if (!R) v.tgt = 0;
      v.wander += (v.tgt - v.wander) * (1 - Math.exp(-dt / 0.7));
      v.panL.pan.value = -P.pan; v.panR.pan.value = P.pan;
      if (sync) {
        if (v.next < now + 0.004 || !v.synced) {
          const k = Math.ceil((now + 0.006 - this.engine.t0) / sync);
          v.next = this.engine.t0 + k * sync;
          v.synced = true;
        }
      } else {
        v.synced = false;
        if (v.next < now) v.next = now + 0.004;
      }
      let guard = 0;
      while (v.next < now + LOOKAHEAD && guard++ < 16) {
        this._fire(v, v.next, P, sync ? 1 / sync : dens);
        v.next += sync || (1 / dens) * (0.85 + Math.random() * 0.3);
      }
    }
  }

  _fire(v, when, P, dens) {
    if (this.live >= MAX_LIVE) return;
    const ctx = this.G.ctx;
    const buf = bufferNow(this.engine, v.src);
    if (!buf) return;
    let size = P.size, st = P.pitch + this.G.pitchOf(v.src), spray = P.spray;
    const y = v.y ?? 0.5;
    if (P.ymode === 0) size *= Math.pow(2, (y - 0.5) * 3.2);            // high: short grains, low: long
    else if (P.ymode === 1) st += Math.round((0.5 - y) * 24);           // high: up to +12 st, low: down to -12
    else spray = Math.min(1, Math.max(0, spray + (0.5 - y) * 1.4));     // high: wide spray, low: tight
    size = Math.min(1.2, Math.max(0.006, size));
    const rate = Math.pow(2, st / 12) * this.G.speed;
    const span = size * rate;
    let at = v.pos + v.wander + (v.tilt ?? 0) + (Math.random() * 2 - 1) * spray;
    at = Math.min(buf.duration - span - 0.002, Math.max(0, at));
    if (at < 0) return;
    const rev = P.rev > 0 && Math.random() < P.rev;
    const node = ctx.createBufferSource();
    let start = at;
    if (rev) { node.buffer = reversedPiece(ctx, buf, at, span); start = 0; if (!node.buffer) return; }
    else node.buffer = buf;
    node.playbackRate.value = rate;
    const env = ctx.createGain();
    env.gain.value = 0;
    const amp = (v.amp * 0.9) / Math.sqrt(Math.max(1, dens * size));
    const curve = HANN.map((x) => x * amp);
    env.gain.setValueCurveAtTime(curve, when, size);
    node.connect(env).connect(v.alt ? v.panR : v.panL);
    v.alt ^= 1;
    node.start(when, start);
    node.stop(when + size + 0.005);
    this.live++;
    this.fired++;
    node.onended = () => { this.live--; try { env.disconnect(); } catch { /* */ } };
    v.lastEnd = Math.max(v.lastEnd, when + size);
    this.recent.push({ src: v.src, pos: at, span, when, size, rev, key: v.key, jy: Math.random() * 2 - 1 });
    if (this.recent.length > 260) this.recent.splice(0, 60);
  }
}
