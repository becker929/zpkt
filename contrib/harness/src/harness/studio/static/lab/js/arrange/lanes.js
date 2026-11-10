// What the Short plays besides the stems' whole bars, on the engine's own bar clock (engine.onBar gives each bar's
// audio-clock time ~120 ms ahead; every voice here starts on it, sample-accurate):
//
//   shape    a bar of the canonical Short's perc stem (batch 4.3 track 1): its real A, AB, ABC, ABCD bars and its
//            splash bars, on the perc bus
//   hats     a bar masked to a layer set the canonical Short has no bar of (hats.js), on the perc bus
//   part     the first beats of a bar before a pre-kick gap (kick, perc, SFX, chord or break, cut on the beat)
//   splash   the noise splash's own sample (src-2), shaped into the canonical long splash, cut after N beats
//   wuh      the song's last beats before the kick comes back after its break (the beatbox "wuh"), on the break bus
//   brk      a bar of the song's own break (bars 81-96 of the whole song), on the break bus
//   chord    a bar of the chord loop (the SFX stem's chord-only bars 17-24), on the chord bus
//   countIn  four clicks
//
// Each sequence entry carries these under `x`; the engine ignores keys it does not know. Buses: 'arr-break',
// 'arr-chord', 'arr-click' are this surface's own; the stems' buses are shared ('kick', 'perc', 'sfx').

import { HatMasks } from './hats.js';

const XF = 0.004;                  // the engine's own crossfade between bar segments
const SONG_BREAK = [80, 96];       // 0-based bars of the whole song
const KICK_BACK = 96;              // 0-based bar where the song's kick returns after the break

export class Lanes {
  constructor(engine, data) {
    this.e = engine;
    this.data = data;
    this.voices = new Set();
    this.masks = new HatMasks(data.hats);
    this.splashLevel = 1;
    this.nodes = null;
    this.wantFull = false;
  }

  /** Buses and gain nodes; call once the context exists. */
  init() {
    if (this.nodes) return;
    const e = this.e, ctx = e.ctx;
    const splash = ctx.createGain();
    splash.gain.value = this.splashLevel;
    splash.connect(e.bus('perc').input);
    this.nodes = { splash, brk: e.bus('arr-break'), chord: e.bus('arr-chord'), click: e.bus('arr-click') };
  }

  dispose() {
    this.stopAll();
    try { this.nodes?.splash.disconnect(); } catch { /* gone */ }
    this.nodes = null;
  }

  /** Decode what the lanes need; the whole song only when a plan asks for it (it is 270 s of audio). */
  async prepare({ full = false } = {}) {
    const e = this.e;
    if (!e.ctx || !e.manifest || this._preparing) return;
    this._preparing = true;
    try {
      this.init();
      // the masks start from a bar with all four layers: the canonical Short's own (it has the layers' masks'
      // source), or the lab's perc stem in a build without it
      const shape = this.hasSource('shape-perc');
      const id = shape ? 'shape-perc' : 'perc';
      const src = e.buffers.get(id) ?? await e.buffer(id).catch(() => null);
      if (src && !this.masks.bands && !this.masks.failed) {
        this.masks.prepare(e.ctx, src, shape ? this.data.hats.shape_source_bar ?? 15 : this.data.hats.source_bar ?? 12);
        if (this.masks.bands) this.masks.warm();
      }
    } finally { this._preparing = false; }
    if (this.hasSource(this.data.splash.src) && !e.buffers.has(this.data.splash.src)) e.buffer(this.data.splash.src).catch(() => null);
    if (full || this.wantFull) this.loadFull();
  }

  loadFull() {
    this.wantFull = true;
    if (!this.e.ctx || !this.e.manifest?.full || this.e.buffers.has('full') || this._fullJob) return this._fullJob;
    this._fullJob = this.e.buffer('full').then((b) => { this._fullJob = null; this.onFull?.(b); return b; })
      .catch((err) => { this._fullJob = null; console.warn('whole song', err); return null; });
    return this._fullJob;
  }

  get hasFull() { return this.e.buffers.has('full'); }

  hasSource(id) { return this.e.sources().some((x) => x.id === id); }

  setSplashLevel(db) {
    this.splashLevel = Math.pow(10, db / 20);
    if (this.nodes) this.nodes.splash.gain.setTargetAtTime(this.splashLevel, this.e.ctx.currentTime, 0.02);
  }

  // --- voices ------------------------------------------------------------------------------------------------
  /** One buffer segment: from `offset` s of `buf`, at `when`, for `dur` s, into `dest`, with the engine's fades. */
  voice(buf, offset, when, dur, dest, { gain = 1, fadeOut = XF } = {}) {
    if (!buf || !dest || dur <= 0) return null;
    const ctx = this.e.ctx;
    const node = ctx.createBufferSource();
    node.buffer = buf;
    const g = ctx.createGain();
    const start = Math.max(when - XF, ctx.currentTime);
    g.gain.setValueAtTime(0, start);
    g.gain.linearRampToValueAtTime(gain, when + XF);
    g.gain.setValueAtTime(gain, Math.max(when + XF, when + dur - fadeOut));
    g.gain.linearRampToValueAtTime(0, when + dur + XF);
    node.connect(g).connect(dest);
    const off = Math.max(0, offset - (when - start));
    if (off >= buf.duration) return null;
    node.start(start, off, dur + 2 * XF + (when - start));
    this._track(node, g);
    return node;
  }

  _track(node, g) {
    this.voices.add(node);
    node.onended = () => { this.voices.delete(node); try { g.disconnect(); } catch { /* gone */ } };
  }

  stopAll() {
    for (const v of this.voices) { try { v.stop(); } catch { /* not started or ended */ } }
    this.voices.clear();
  }

  /** Schedule the lanes of one sequence entry, for the bar that starts at `when`. */
  schedule(entry, when) {
    const x = entry?.x;
    if (!x || !this.e.ctx) return;
    this.init();
    const e = this.e, bs = e.barSeconds, beat = bs / 4;
    const bus = (name) => e.bus(name).input;
    if (x.countIn) { this.clicks(when); return; }
    if (x.hats) this.voice(this.masks.buffer(x.hats), 0, when, bs, bus('perc'));
    if (x.shape != null) this.voice(e.buffers.get('shape-perc'), x.shape * bs, when, bs, bus('perc'));
    if (x.chord != null) this.voice(e.buffers.get('sfx'), (x.chordBar ?? 16 + x.chord) * bs, when, bs, this.nodes.chord.input);
    if (x.brk != null) this.voice(e.buffers.get('full'), x.brk * bs, when, bs, this.nodes.brk.input);
    if (x.part) {
      const p = x.part, dur = p.until * beat, cut = 0.006;
      for (const name of ['kick', 'perc', 'sfx']) if (p[name] >= 0) this.voice(e.buffers.get(name), p[name] * bs, when, dur, bus(name), { fadeOut: cut });
      if (p.hats) this.voice(this.masks.buffer(p.hats), 0, when, dur, bus('perc'), { fadeOut: cut });
      if (p.shape != null) this.voice(e.buffers.get('shape-perc'), p.shape * bs, when, dur, bus('perc'), { fadeOut: cut });
      if (p.chord != null) this.voice(e.buffers.get('sfx'), (p.chordBar ?? 16 + p.chord) * bs, when, dur, this.nodes.chord.input, { fadeOut: cut });
      if (p.brk != null) this.voice(e.buffers.get('full'), p.brk * bs, when, dur, this.nodes.brk.input, { fadeOut: cut });
    }
    if (x.wuh) {
      const full = e.buffers.get('full');
      if (full) {
        const dur = x.wuh.beats * beat;
        this.voice(full, KICK_BACK * bs - dur, when + x.wuh.at * beat, dur, this.nodes.brk.input, { fadeOut: 0.012 });
      } else this.loadFull();
    }
    if (x.brk != null && !e.buffers.get('full')) this.loadFull();
    if (x.splash) this.splash(when, x.splash.beats);
  }

  /** The splash: src-2 shaped per 16th into the canonical long splash, cut after `beats`. */
  splash(when, beats) {
    const e = this.e, ctx = e.ctx;
    const buf = e.buffers.get(this.data.splash.src);
    if (!buf) { if (this.hasSource(this.data.splash.src)) e.buffer(this.data.splash.src).catch(() => null); return; }
    const g16 = this.data.splash.gain16;
    const step = e.barSeconds / 16;
    const dur = beats * 4 * step;
    const node = ctx.createBufferSource();
    node.buffer = buf;
    const g = ctx.createGain();
    const at = (j) => Math.pow(10, (g16[Math.min(j, 29)] ?? 0) / 20);
    const start = Math.max(when, ctx.currentTime);
    g.gain.setValueAtTime(0, start);
    g.gain.linearRampToValueAtTime(at(0), start + 0.003);
    for (let j = 1; j < beats * 4; j++) g.gain.linearRampToValueAtTime(at(j), when + (j + 0.5) * step);
    g.gain.setValueAtTime(at(beats * 4 - 1), when + dur - 0.012);
    g.gain.linearRampToValueAtTime(0, when + dur);
    node.connect(g).connect(this.nodes.splash);
    node.start(start, (this.data.splash.at ?? 0) / 44100 + (start - when), Math.max(0.01, dur - (start - when)) + 0.01);
    this._track(node, g);
  }

  clicks(when) {
    const ctx = this.e.ctx, beat = this.e.barSeconds / 4;
    for (let k = 0; k < 4; k++) {
      const t = when + k * beat;
      if (t < ctx.currentTime) continue;
      const o = ctx.createOscillator();
      o.type = 'square';
      o.frequency.value = k === 0 ? 1760 : 1320;
      const g = ctx.createGain();
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(k === 0 ? 0.22 : 0.14, t + 0.002);
      g.gain.exponentialRampToValueAtTime(0.0005, t + 0.05);
      o.connect(g).connect(this.nodes.click.input);
      o.start(t); o.stop(t + 0.06);
      this._track(o, g);
    }
  }
}

export { SONG_BREAK, KICK_BACK };
