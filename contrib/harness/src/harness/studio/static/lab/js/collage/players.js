// Region players: a piece of a source from an offset for a duration, at a pitch, maybe backwards, with a short
// fade at each end. Audition, the slicer's pads and steps, and the bed all play through here, on the audio clock.
// Live voices are tracked so the tape's varispeed can bend them, a choke group can cut them, and the shelf's reels
// know what is sounding.

import { bufferNow, reversedPiece } from './sources.js';
import { hold } from './fx.js';

const MAX_VOICES = 40;

export class Players {
  constructor(G, engine) {
    this.G = G;
    this.engine = engine;
    this.live = new Set();
  }

  /**
   * Play `dur` seconds (on the clock) of source `id` from `off` seconds, at `when`. opts: st (semitones on top of
   * the clip's own transpose), gain, rev, attack, release, tag (a choke group), color.
   */
  play(id, { when, off = 0, dur = 1, st = 0, gain = 1, rev = false, attack = 0.004, release = 0.02, tag = null } = {}) {
    const G = this.G;
    if (G.disposed) return null;
    const ctx = G.ctx;
    const buf = bufferNow(this.engine, id);
    if (!buf) return null;
    when = Math.max(when ?? ctx.currentTime, ctx.currentTime + 0.005);
    const base = Math.pow(2, (st + G.pitchOf(id)) / 12);
    const rate = base * G.speed;
    const span = Math.min(dur * rate, buf.duration - off);
    if (span <= 0.005) return null;
    dur = span / rate;
    const node = ctx.createBufferSource();
    let start = off;
    if (rev) { node.buffer = reversedPiece(ctx, buf, off, span); start = 0; if (!node.buffer) return null; }
    else node.buffer = buf;
    node.playbackRate.value = rate;
    const env = ctx.createGain();
    const a = Math.min(attack, dur / 3), r = Math.min(release, dur / 3);
    env.gain.value = 0;
    env.gain.setValueAtTime(0, when);
    env.gain.linearRampToValueAtTime(gain, when + a);
    env.gain.setValueAtTime(gain, when + dur - r);
    env.gain.linearRampToValueAtTime(0, when + dur);
    node.connect(env).connect(G.input(id));
    node.start(when, start);
    node.stop(when + dur + 0.02);
    const v = { node, env, id, when, end: when + dur, base, tag, gain, rate, st, off, span, rev };
    this.live.add(v);
    node.onended = () => { this.live.delete(v); try { env.disconnect(); } catch { /* */ } };
    if (this.live.size > MAX_VOICES) {
      const oldest = [...this.live].sort((x, y) => x.when - y.when)[0];
      this.stop(oldest);
    }
    return v;
  }

  /** Fade a voice out at `at` (now by default). */
  stop(v, at = this.G.ctx.currentTime, fade = 0.015) {
    if (!v || !this.live.has(v)) return;
    at = Math.max(at, this.G.ctx.currentTime);
    if (at <= v.when) { try { v.node.stop(); } catch { /* */ } this.live.delete(v); return; }
    hold(v.env.gain, at);
    v.env.gain.linearRampToValueAtTime(0, at + fade);
    try { v.node.stop(at + fade + 0.01); } catch { /* */ }
    v.end = Math.min(v.end, at + fade);
  }

  /** Cut every voice of a choke group at `at`. */
  choke(tag, at) { for (const v of this.live) if (v.tag === tag && v.when < at + 1e-4) this.stop(v, at, 0.008); }

  stopTag(tag) { for (const v of [...this.live]) if (v.tag === tag) this.stop(v); }
  stopAll() { for (const v of [...this.live]) this.stop(v); }

  /** Varispeed: bend every live voice to the tape's speed. */
  setSpeed(s) {
    const t = this.G.ctx.currentTime;
    for (const v of this.live) { v.node.playbackRate.setTargetAtTime(v.base * s, t, 0.04); v.rate = v.base * s; }
  }

  /** The clip's transpose moved: bend that source's live voices. */
  repitch(id) {
    const t = this.G.ctx.currentTime;
    for (const v of this.live) {
      if (v.id !== id) continue;
      v.base = Math.pow(2, (v.st + this.G.pitchOf(id)) / 12);
      v.node.playbackRate.setTargetAtTime(v.base * this.G.speed, t, 0.04);
    }
  }

  /** How many voices of source `id` are sounding now (for the reels). */
  sounding(id) {
    const t = this.G.ctx.currentTime;
    let k = 0;
    for (const v of this.live) if (v.id === id && v.when <= t && v.end > t) k++;
    return k;
  }

  /** Where in source `id` its voices are now (seconds), for playheads. */
  heads(id) {
    const t = this.G.ctx.currentTime, out = [];
    for (const v of this.live) {
      if (v.id !== id || v.when > t || v.end <= t) continue;
      const done = Math.min(v.span, (t - v.when) * v.rate);
      out.push({ pos: v.rev ? v.off + v.span - done : v.off + done, tag: v.tag });
    }
    return out;
  }
}
