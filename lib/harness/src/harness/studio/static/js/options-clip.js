// A file of options played on the audio clock (options.js). The Mac's `play` sweeps them; a tap holds one.
//
// Sweep: option k sounds during bar k, so one pass is a bar of each, in order. Hold: the picked option loops its own
// bars until stopped (at most HOLD_S). Picking another option, in either, holds the new one a few milliseconds later
// at the same place in its bars, with a short crossfade; a sweep that is touched becomes a hold. Every option is
// read at the same phase, (t - t0) mod its length, so a switch never jumps in the bar.
//
// Each piece that sounds is a voice: a looping source over its option's part of the file, then a fade (for the
// crossfades), then the option's match gain, which all its voices share, so the loudness toggle is one ramp each.
import { firstPick, matchGain, offsetAt } from './options.js';

const START_LEAD_S = 0.03;
const SWITCH_LEAD_S = 0.015;
const XF_S = 0.012;
const ATTACK_S = 0.003;       // the very first voice: just enough not to click
const MATCH_RAMP_S = 0.03;
export const HOLD_S = 600;    // a held option stops by itself after ten minutes

export class OptionsClip {
  #ctx = null;
  #buffer = null;           // decoded, once started
  #loading = null;
  #matches = [];            // per option: a gain at its match level, into the output
  #voices = [];             // {src, fade, index, from, to}, in the order they start
  #hold = null;
  #sentinel = null;         // silent; it ends when the clip does
  #endAt = 0;
  #finished = false;
  #resolve;
  t0 = 0;                   // audio-clock time where every option's bars begin
  duration = 0;             // one pass: a bar of each option (sweep), or one option's bars (hold)
  error = null;
  options = null;
  ab = null;

  /** `load()` resolves to {buffer, options}; `mode` is 'sweep' or 'hold'; `pick` the option to hold. */
  constructor({ seq, kind = 'music', loops = 1, load, onFirstSound, mode = 'sweep', pick = null, match = false }) {
    this.seq = seq;
    this.kind = kind;
    this.loops = Math.max(1, loops | 0);
    this.load = load;
    this.onFirstSound = onFirstSound;
    this.mode = mode;
    this.pick = pick;
    this.match = match;
    this.done = new Promise((resolve) => (this.#resolve = resolve));
  }

  prepare() {
    if (!this.#loading) {
      this.#loading = this.load();
      this.#loading.catch(() => {});
    }
    return this.#loading;
  }

  get stopAt() {
    return this.#endAt;
  }

  async start(ctx, out) {
    let loaded;
    try {
      loaded = await this.prepare();
      if (!loaded.options) throw new Error('the message has no options');
    } catch (err) {
      this.error = err;
      this.#finish('failed');
      return;
    }
    if (this.#finished) return;
    const o = (this.options = loaded.options);
    this.#ctx = ctx;
    this.#buffer = loaded.buffer;
    this.#matches = o.options.map((opt) => {
      const g = ctx.createGain();
      g.gain.value = matchGain(opt, this.match);
      g.connect(out);
      return g;
    });
    const rate = ctx.sampleRate;
    this.t0 = Math.ceil((ctx.currentTime + START_LEAD_S) * rate) / rate;
    if (this.mode === 'sweep') {
      const n = o.options.length;
      this.duration = n * o.bar_seconds;
      this.#endAt = this.t0 + this.loops * this.duration;
      for (let pass = 0; pass < this.loops; pass += 1) {
        for (let k = 0; k < n; k += 1) {
          const from = this.t0 + (pass * n + k) * o.bar_seconds;
          this.#voice(k, from, from + o.bar_seconds, pass || k ? XF_S : ATTACK_S);
        }
      }
    } else {
      this.pick ??= firstPick(o);
      this.duration = o.span;
      this.#endAt = this.t0 + HOLD_S;
      this.#hold = this.#voice(this.pick, this.t0, this.#endAt, ATTACK_S);
    }
    const sentinel = ctx.createConstantSource();
    sentinel.offset.value = 0;
    sentinel.connect(out);
    sentinel.onended = () => this.#finish('played');
    sentinel.start(this.t0);
    sentinel.stop(this.#endAt);
    this.#sentinel = sentinel;
    this.onFirstSound?.(this.t0 - ctx.currentTime);
  }

  /** Hold option `index` from now on, at the same place in its bars. Before the start, it is what starts. */
  setPick(index) {
    this.pick = index;
    if (this.#finished) return;
    if (!this.#ctx) {
      this.mode = 'hold';
      return;
    }
    if (this.mode === 'hold' && this.#hold?.index === index) return;
    const at = this.#ctx.currentTime + SWITCH_LEAD_S;
    if (this.mode === 'sweep') {
      this.mode = 'hold';
      this.duration = this.options.span;
      for (const v of this.#voices) if (v.to > at) this.#cut(v, at);
      this.#setEnd(at + HOLD_S);
    } else if (this.#hold) {
      this.#cut(this.#hold, at);
    }
    this.#voices = this.#voices.filter((v) => v.to + XF_S > this.#ctx.currentTime);
    this.#hold = this.#voice(index, at, this.#endAt, XF_S);
  }

  /** Play every option at one loudness (on), or at Live's own levels. */
  setMatch(on) {
    this.match = on;
    if (!this.#ctx) return;
    const t = this.#ctx.currentTime;
    this.options.options.forEach((opt, i) => {
      const g = this.#matches[i].gain;
      g.cancelScheduledValues(t);
      g.setValueAtTime(g.value, t);
      g.linearRampToValueAtTime(matchGain(opt, on), t + MATCH_RAMP_S);
    });
  }

  /** Something from the Mac is waiting: a held option ends at the next bar line. */
  yieldAtBar() {
    if (this.mode !== 'hold' || !this.#ctx || this.#finished) return;
    const bar = this.options.bar_seconds;
    const soon = this.#ctx.currentTime + SWITCH_LEAD_S;
    const at = this.t0 + Math.ceil((soon - this.t0) / bar - 1e-6) * bar;
    if (at >= this.#endAt) return;
    for (const v of this.#voices) if (v.to > at) this.#cut(v, at);
    this.#setEnd(at + XF_S);
  }

  /** Loop counts belong to sweeps the Mac asked for; a card of options has no loop control. */
  setLoops() {}

  /** {t (s into the pass), pass, option (the one sounding), sweeping}, or null before it starts. */
  position(heardAt) {
    if (!this.options || heardAt < this.t0) return null;
    const elapsed = Math.min(heardAt, this.#endAt) - this.t0;
    let option = this.pick ?? 0;
    for (const v of this.#voices) {
      if (v.from > heardAt) break;
      option = v.index;
    }
    const pass = Math.floor(elapsed / this.duration);
    return { t: elapsed - pass * this.duration, pass, option, sweeping: this.mode === 'sweep' };
  }

  stop() {
    if (this.#ctx && !this.#finished) {
      const at = this.#ctx.currentTime;
      for (const v of this.#voices) if (v.to > at) this.#cut(v, at);
      if (this.#sentinel) this.#sentinel.onended = null;
      try {
        this.#sentinel?.stop();
      } catch {
        // Already ended.
      }
    }
    this.#finish('stopped');
  }

  // One option, sounding from `from` to `to` (then a crossfade's length more, fading out), faded in over `fadeIn`.
  #voice(index, from, to, fadeIn) {
    const ctx = this.#ctx;
    const o = this.options;
    const src = ctx.createBufferSource();
    src.buffer = this.#buffer;
    src.loop = true;
    src.loopStart = index * o.span;
    src.loopEnd = (index + 1) * o.span;
    const fade = ctx.createGain();
    src.connect(fade);
    fade.connect(this.#matches[index]);
    fade.gain.setValueAtTime(0, from);
    fade.gain.linearRampToValueAtTime(1, from + fadeIn);
    fade.gain.setValueAtTime(1, to);
    fade.gain.linearRampToValueAtTime(0, to + XF_S);
    src.start(from, offsetAt(o, index, from, this.t0));
    src.stop(to + XF_S);
    const voice = { src, fade, index, from, to };
    this.#voices.push(voice);
    return voice;
  }

  // End a voice at `at` instead, fading out over a crossfade. One that has not started yet never sounds.
  #cut(voice, at) {
    voice.to = at;
    if (voice.from >= at) {
      voice.fade.disconnect();
      return;
    }
    const g = voice.fade.gain;
    if (typeof g.cancelAndHoldAtTime === 'function') g.cancelAndHoldAtTime(at);
    else {
      g.cancelScheduledValues(at);
      g.setValueAtTime(g.value, at);
    }
    g.linearRampToValueAtTime(0, at + XF_S);
    try {
      voice.src.stop(at + XF_S);
    } catch {
      // Already ended.
    }
  }

  #setEnd(at) {
    this.#endAt = at;
    try {
      this.#sentinel?.stop(at);       // the last call to stop() is the one that counts
    } catch {
      // Already ended.
    }
  }

  #finish(outcome) {
    if (this.#finished) return;
    this.#finished = true;
    this.#voices = [];
    this.#hold = null;
    this.#resolve(outcome);
  }
}
