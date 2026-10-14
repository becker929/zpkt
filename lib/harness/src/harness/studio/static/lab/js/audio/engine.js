// The lab's sound: HW002's own stems on a 160 BPM bar clock, through channel strips and a master bus, so every
// control is heard as it moves. It is a sketch of the set, not the set: Live's devices are approximated with Web
// Audio (a waveshaper for COLDFIRE and Decapitator, biquads for EQ Eight, DynamicsCompressor for Glue).
//
//   engine.start() / stop()         the transport (the first call must come from a tap: iPhone audio)
//   engine.position()               {bar, beat, step, phase} now
//   engine.onStep(fn)               fn(step, when, bar) for every 16th, scheduled ~120 ms ahead (sample-accurate)
//   engine.onBar(fn)                fn(bar, when) for every bar, ahead
//   engine.bus(name)                a Channel: 'kick', 'perc', 'sfx' (the stems), and any other a surface asks for
//   engine.stems.sequence           what plays: [{kick: srcBar|-1, perc: .., sfx: ..}, ...] one entry per bar
//   engine.buffer(id)               a decoded source from the manifest (stems, clips, kick hits, the whole song)
//   engine.sketch(key, fn)          fn(v, info) whenever a param with that `sketch` key changes (several fns may
//                                   share a key). v is the change from the set (info.delta), in the param's unit,
//                                   unless the key says '@norm', '@dnorm' (0..1 change), or '@real'. info: {real,
//                                   norm, set, delta, dnorm, p}. The stems already carry the set's sound, so every
//                                   sketch is silent at the set's value and plays only the difference.
//   engine.bind(store)              wires every param's `sketch` to its functions

import { Channel } from './channel.js';
import { setNorm as setNormOf } from '../params.js';

const LOOKAHEAD = 0.12;           // s scheduled ahead
const TICK_MS = 25;
const XF = 0.004;                 // s crossfade between bar segments

export class Engine {
  constructor({ audioBase = './audio/' } = {}) {
    this.audioBase = audioBase;
    this.ctx = null;
    this.bpm = 160;
    this.barSeconds = 1.5;
    this.manifest = null;
    this.buffers = new Map();
    this.loading = new Map();
    this.buses = new Map();
    this.sketches = new Map();
    this.stepFns = new Set();
    this.barFns = new Set();
    this.playing = false;
    this.t0 = 0;
    this.nextStep = 0;
    this.timer = 0;
    this.stems = new Stems(this);
    this.store = null;
  }

  // --- set up ----------------------------------------------------------------------------------------------
  /** The context and the master chain; call from a tap. */
  async unlock() {
    if (!this.ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      this.ctx = new AC({ latencyHint: 'interactive' });
      this._master();
      for (const name of ['kick', 'perc', 'sfx', 'set']) this.bus(name);
      for (const fn of this.readyFns ?? []) safe(fn, this);
      if (this.store) this._applyAll();
    }
    if (this.ctx.state !== 'running') await this.ctx.resume();
    return this.ctx;
  }

  _master() {
    const ctx = this.ctx;
    const m = this.master = {};
    m.input = ctx.createGain();
    // the returns: A a reverb, B a tempo delay
    m.reverb = ctx.createConvolver();
    m.reverbIn = ctx.createGain(); m.reverbOut = ctx.createGain(); m.reverbOut.gain.value = 0.9;
    m.reverbIn.connect(m.reverb).connect(m.reverbOut).connect(m.input);
    this.setReverb(2.2, 0.5);
    m.delayIn = ctx.createGain();
    m.delay = ctx.createDelay(4); m.delay.delayTime.value = (60 / this.bpm) * 0.75;
    m.feedback = ctx.createGain(); m.feedback.gain.value = 0.35;
    m.delayTone = ctx.createBiquadFilter(); m.delayTone.type = 'bandpass'; m.delayTone.frequency.value = 1800; m.delayTone.Q.value = 0.6;
    m.delayIn.connect(m.delay).connect(m.delayTone).connect(m.feedback).connect(m.delay);
    m.delayTone.connect(m.input);
    // the bus: glue, a clipper, a ceiling
    m.glue = ctx.createDynamicsCompressor();
    m.glue.threshold.value = 0; m.glue.ratio.value = 1; m.glue.attack.value = 0.01; m.glue.release.value = 0.2; m.glue.knee.value = 6;
    m.clipPre = ctx.createGain(); m.clip = ctx.createWaveShaper(); m.clipPost = ctx.createGain();
    m.clip.curve = softClip(0.92); m.clip.oversample = '4x';
    m.limiter = ctx.createDynamicsCompressor();
    m.limiter.threshold.value = -0.3; m.limiter.ratio.value = 20; m.limiter.attack.value = 0.001; m.limiter.release.value = 0.05; m.limiter.knee.value = 0;
    m.out = ctx.createGain();
    m.analyser = ctx.createAnalyser(); m.analyser.fftSize = 4096; m.analyser.smoothingTimeConstant = 0.7;
    // loudness: K-weighting into its own analyser
    const shelf = ctx.createBiquadFilter(); shelf.type = 'highshelf'; shelf.frequency.value = 1681; shelf.gain.value = 4;
    const rlb = ctx.createBiquadFilter(); rlb.type = 'highpass'; rlb.frequency.value = 38; rlb.Q.value = 0.5;
    m.k = ctx.createAnalyser(); m.k.fftSize = 4096;
    m.input.connect(m.glue).connect(m.clipPre).connect(m.clip).connect(m.clipPost).connect(m.limiter).connect(m.out);
    m.out.connect(ctx.destination);
    m.out.connect(m.analyser);
    m.out.connect(shelf).connect(rlb).connect(m.k);
    this._lufs = { blocks: [], last: -70 };
  }

  /** A generated room: `seconds` of decaying noise, `damp` 0..1 darker. */
  setReverb(seconds = 2.2, damp = 0.5) {
    const ctx = this.ctx;
    if (!ctx) return;
    const len = Math.max(0.1, seconds) * ctx.sampleRate;
    const ir = ctx.createBuffer(2, len, ctx.sampleRate);
    for (let c = 0; c < 2; c++) {
      const d = ir.getChannelData(c);
      let lp = 0;
      for (let i = 0; i < len; i++) {
        const t = i / len;
        lp += (Math.random() * 2 - 1 - lp) * (1 - damp * 0.92);
        d[i] = lp * Math.pow(1 - t, 2.2) * (i < 64 ? i / 64 : 1);
      }
    }
    this.master.reverb.buffer = ir;
  }

  bus(name) {
    if (!this.buses.has(name)) {
      if (!this.ctx) throw new Error('engine.bus before unlock()');
      const ch = new Channel(this.ctx, name, { sends: [this.master.reverbIn, this.master.delayIn] });
      ch.connect(this.master.input);
      this.buses.set(name, ch);
    }
    return this.buses.get(name);
  }

  // --- sources -----------------------------------------------------------------------------------------------
  async loadManifest() {
    if (this.manifest) return this.manifest;
    const res = await fetch(`${this.audioBase}manifest.json`, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`no lab audio (${res.status}): run \`harness lab-audio\` on the Mac`);
    this.manifest = await res.json();
    this.bpm = this.manifest.bpm ?? 160;
    this.barSeconds = this.manifest.bar_seconds ?? 240 / this.bpm;
    this.stems.reset();
    return this.manifest;
  }

  /** Every source in the manifest: [{id, kind, title, file, seconds, ...}]. */
  sources() {
    const m = this.manifest;
    if (!m) return [];
    return [
      ...m.stems.map((s) => ({ ...s, kind: 'stem' })),
      ...(m.full ? [{ ...m.full, kind: 'full' }] : []),
      ...m.clips.map((s) => ({ ...s, kind: 'clip' })),
      ...m.kicks.map((s) => ({ ...s, kind: 'kick' })),
    ];
  }

  /** A source decoded (and lined up on its first sound, so stems share one grid). Cached. */
  async buffer(id) {
    if (this.buffers.has(id)) return this.buffers.get(id);
    if (this.loading.has(id)) return this.loading.get(id);
    const src = this.sources().find((s) => s.id === id);
    if (!src) throw new Error(`no source ${id}`);
    const job = (async () => {
      await this.unlock();
      const bytes = await (await fetch(this.audioBase + src.file)).arrayBuffer();
      let buf = await this.ctx.decodeAudioData(bytes);
      if (src.head) buf = align(this.ctx, buf, src.head, Math.round((src.seconds || buf.duration) * buf.sampleRate));
      this.buffers.set(id, buf);
      this.loading.delete(id);
      return buf;
    })();
    this.loading.set(id, job);
    return job;
  }

  // --- the clock -----------------------------------------------------------------------------------------------
  get stepSeconds() { return this.barSeconds / 16; }

  async start(fromBar = 0) {
    await this.unlock();
    await this.stems.load();
    if (this.playing) return;
    this.playing = true;
    this.t0 = this.ctx.currentTime + 0.08 - fromBar * this.barSeconds;
    this.nextStep = fromBar * 16;
    this._tick();
    this.timer = setInterval(() => this._tick(), TICK_MS);
    this._emitState();
  }

  stop() {
    if (!this.playing) return;
    this.playing = false;
    clearInterval(this.timer);
    this.stems.stopAll();
    for (const fn of this.stopFns ?? []) fn();
    this._emitState();
  }

  /** fn(engine) once the context and buses exist (now, if they do). */
  onReady(fn) { (this.readyFns ??= new Set()).add(fn); if (this.ctx) safe(fn, this); return () => this.readyFns.delete(fn); }

  onStop(fn) { (this.stopFns ??= new Set()).add(fn); return () => this.stopFns.delete(fn); }
  onState(fn) { (this.stateFns ??= new Set()).add(fn); return () => this.stateFns.delete(fn); }
  _emitState() { for (const fn of this.stateFns ?? []) fn(this.playing); }

  onStep(fn) { this.stepFns.add(fn); return () => this.stepFns.delete(fn); }
  onBar(fn) { this.barFns.add(fn); return () => this.barFns.delete(fn); }

  /** {bar, beat, step, phase (0..1 in the bar), time} now; bar counts from 0 and keeps counting. */
  position() {
    if (!this.ctx || !this.playing) return { bar: 0, beat: 0, step: 0, phase: 0, playing: false };
    const t = (this.ctx.currentTime - this.t0) / this.barSeconds;
    const bar = Math.floor(t);
    const phase = t - bar;
    return { bar, beat: Math.floor(phase * 4), step: Math.floor(phase * 16), phase, playing: true, t };
  }

  /** The audio-clock time of 16th `step` (counted from bar 0). */
  timeOf(step) { return this.t0 + step * this.stepSeconds; }

  _tick() {
    const until = this.ctx.currentTime + LOOKAHEAD;
    while (this.timeOf(this.nextStep) < until) {
      const step = this.nextStep;
      const when = this.timeOf(step);
      const bar = Math.floor(step / 16);
      if (step % 16 === 0) {
        this.stems.scheduleBar(bar, when);
        for (const fn of this.barFns) safe(fn, bar, when);
      }
      for (const fn of this.stepFns) safe(fn, step, when, bar);
      this.nextStep++;
    }
  }

  // --- params -> sound -----------------------------------------------------------------------------------------
  /** Register how the phone sounds a param: fn(real, norm, param). Keys are the params' `sketch` (before any @). */
  sketch(key, fn) {
    if (!this.sketches.has(key)) this.sketches.set(key, new Set());
    this.sketches.get(key).add(fn);
    if (this.store && this.ctx) this._applyKey(key);
    return () => this.sketches.get(key)?.delete(fn);
  }

  bind(store) {
    this.store = store;
    store.onAny((id) => this._apply(id));
    if (this.ctx) this._applyAll();
  }

  _apply(id) {
    if (!this.ctx || !this.store) return;
    const p = this.store.params.byId.get(id);
    if (!p?.sketch) return;
    const norm = this.store.live(id);
    const real = this.store.real(id);
    const set = p.set ?? p.min;
    const info = { real, norm, set, delta: real - set, dnorm: norm - setNormOf(p), p, id };
    for (const key of [].concat(p.sketch)) {
      const [name, mode = 'delta'] = key.split('@');
      const fns = this.sketches.get(name);
      const list = fns?.size ? [...fns] : [this._busSketch(name)].filter(Boolean);
      const v = mode === 'norm' ? norm : mode === 'dnorm' ? info.dnorm : mode === 'real' ? real : info.delta;
      for (const fn of list) safe(fn, v, info);
    }
  }

  _applyKey(key) {
    for (const p of this.store.params.list) if ([].concat(p.sketch ?? []).some((k) => k.split('@')[0] === key)) this._apply(p.id);
  }

  _applyAll() { for (const p of this.store.params.list) this._apply(p.id); }

  /** 'ch.<bus>.<prop>' and 'master.<prop>' need no registration. */
  _busSketch(name) {
    const parts = name.split('.');
    if (parts[0] === 'ch' && parts.length === 3) return (v) => this.bus(parts[1]).set(parts[2], v);
    if (parts[0] === 'master') return (v) => this.setMaster(parts[1], v);
    return null;
  }

  setMaster(prop, v) {
    const m = this.master, t = this.ctx.currentTime;
    const r = (param, x) => param.setTargetAtTime(x, t, 0.02);
    switch (prop) {
      case 'glueThreshold': return r(m.glue.threshold, v);
      case 'glueRatio': return r(m.glue.ratio, v);
      case 'glueAttack': return r(m.glue.attack, v / 1000);
      case 'glueRelease': return r(m.glue.release, v / 1000);
      case 'clipDrive': r(m.clipPre.gain, Math.pow(10, v / 20)); return r(m.clipPost.gain, Math.pow(10, -v / 40));
      case 'ceiling': return r(m.limiter.threshold, v);
      case 'volume': return r(m.out.gain, Math.pow(10, v / 20));
      case 'reverbSize': this._size = v; return this._debounced('rv', () => this.setReverb(v, this._damp ?? 0.5));
      case 'reverbDamp': this._damp = v; return this._debounced('rv', () => this.setReverb(this._size ?? 2.2, v));
      case 'reverbLevel': return r(m.reverbOut.gain, v);
      case 'delayTime': return r(m.delay.delayTime, v * 60 / this.bpm);          // beats
      case 'delayFeedback': return r(m.feedback.gain, v);
      default: return undefined;
    }
  }

  _debounced(key, fn, ms = 120) {
    this._db ??= new Map();
    clearTimeout(this._db.get(key));
    this._db.set(key, setTimeout(fn, ms));
  }

  // --- meters ------------------------------------------------------------------------------------------------
  /** Momentary loudness (LUFS, ~400 ms, approximate K-weighting) and the master's peak (dBFS). */
  loudness() {
    if (!this.ctx) return { lufs: -70, peak: -70 };
    const m = this.master;
    const buf = this._kbuf ??= new Float32Array(m.k.fftSize);
    m.k.getFloatTimeDomainData(buf);
    let sum = 0;
    for (const x of buf) sum += x * x;
    const L = this._lufs;
    L.blocks.push(sum / buf.length);
    if (L.blocks.length > 5) L.blocks.shift();
    const ms = L.blocks.reduce((a, b) => a + b, 0) / L.blocks.length;
    const lufs = -0.691 + 10 * Math.log10(ms * 2 + 1e-12);        // two channels summed; the analyser sees a downmix
    const pbuf = this._pbuf ??= new Float32Array(m.analyser.fftSize);
    m.analyser.getFloatTimeDomainData(pbuf);
    let peak = 0;
    for (const x of pbuf) { const a = Math.abs(x); if (a > peak) peak = a; }
    return { lufs: Math.max(-70, lufs), peak: 20 * Math.log10(peak + 1e-9) };
  }

  /** The master's spectrum (dB per bin), into `out` (Float32Array of analyser.frequencyBinCount). */
  spectrum(out) { this.master?.analyser.getFloatFrequencyData(out); return out; }
}

/** The stems on the bar clock: each bar of each stem is played from the source bar `sequence` names. */
class Stems {
  constructor(engine) {
    this.e = engine;
    this.names = [];
    this.sequence = [];            // per output bar: {stemName: srcBar or -1}
    this.loop = true;
    this.useMix = false;           // play the set's own mix stem instead (A/B against the sketch)
    this.enabled = true;           // false: the stems stay silent (the arranger's whole-song player, a solo synth)
    this.voices = new Set();
    this.fns = new Set();
  }

  reset() {
    const m = this.e.manifest;
    this.names = m.stems.filter((s) => s.id !== 'mix').map((s) => s.id);
    this.bars = Math.round(Math.min(...m.stems.map((s) => s.bars)));
    this.sequence = Array.from({ length: this.bars }, (_, i) => Object.fromEntries(this.names.map((n) => [n, i])));
  }

  async load() {
    if (!this.e.manifest) await this.e.loadManifest();
    await Promise.all([...this.names, 'mix'].map((n) => this.e.buffer(n).catch(() => null)));
  }

  /** Called when the sequence changes, so views can redraw. */
  onChange(fn) { this.fns.add(fn); return () => this.fns.delete(fn); }
  changed() { for (const fn of this.fns) fn(this.sequence); }

  setSequence(seq) { this.sequence = seq; this.changed(); }

  scheduleBar(bar, when) {
    const seq = this.sequence;
    if (!seq.length || this.enabled === false) return;      // a surface playing something else turns the stems off
    if (!this.loop && bar >= seq.length) return;
    const entry = seq[bar % seq.length];
    this.current = { bar, index: bar % seq.length, when };
    const e = this.e, bs = e.barSeconds;
    const play = (bufName, src, busName, gain = 1) => {
      const buf = e.buffers.get(bufName);
      if (!buf || src < 0) return;
      const node = e.ctx.createBufferSource();
      node.buffer = buf;
      const g = e.ctx.createGain();
      const start = Math.max(when - XF, e.ctx.currentTime);
      g.gain.setValueAtTime(0, start);
      g.gain.linearRampToValueAtTime(gain, when + XF);
      g.gain.setValueAtTime(gain, when + bs - XF);
      g.gain.linearRampToValueAtTime(0, when + bs + XF);
      node.connect(g).connect(e.bus(busName).input);
      const offset = Math.max(0, src * bs - (when - start));
      node.start(start, offset, bs + 2 * XF + (when - start));
      this.voices.add(node);
      node.onended = () => this.voices.delete(node);
    };
    if (this.useMix) { play('mix', entry.kick ?? bar % this.bars, 'set'); return; }
    for (const name of this.names) play(name, entry[name] ?? -1, name);
  }

  stopAll() {
    for (const v of this.voices) { try { v.stop(); } catch { /* already ended */ } }
    this.voices.clear();
  }
}

function softClip(k = 0.9, n = 4096) {
  const c = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const x = (i / (n - 1)) * 2 - 1;
    const a = Math.abs(x);
    c[i] = a < k ? x : Math.sign(x) * (k + (1 - k) * Math.tanh((a - k) / (1 - k)));
  }
  return c;
}

/** Shift `buf` so its first sound lands where the source's first sound was (the manifest's `head`). */
function align(ctx, buf, head, frames) {
  const ref = new Int16Array(Uint8Array.from(atob(head.pcm), (c) => c.charCodeAt(0)).buffer);
  const n = Math.min(ref.length, 1024);
  if (!n) return buf;
  const L = buf.getChannelData(0), R = buf.numberOfChannels > 1 ? buf.getChannelData(1) : L;
  let best = 0, bestScore = -Infinity;
  for (let lag = -2400; lag <= 2400; lag += 1) {
    const at = head.at + lag;
    if (at < 0 || at + n > L.length) continue;
    let dot = 0;
    for (let i = 0; i < n; i += 2) dot += ((L[at + i] + R[at + i]) * 0.5) * ref[i];
    if (dot > bestScore) { bestScore = dot; best = lag; }
  }
  if (!best && buf.length === frames) return buf;
  const out = ctx.createBuffer(buf.numberOfChannels, frames || buf.length, buf.sampleRate);
  for (let c = 0; c < buf.numberOfChannels; c++) {
    const src = buf.getChannelData(c), dst = out.getChannelData(c);
    for (let i = 0; i < dst.length; i++) { const j = i + best; dst[i] = j >= 0 && j < src.length ? src[j] : 0; }
  }
  return out;
}

function safe(fn, ...args) {
  try { fn(...args); } catch (err) { console.error(err); }
}
