// A channel strip in Web Audio: the phone's sketch of a track or group in the set.
//
//   in -> trim -> low cut -> low shelf -> 3 bells -> high shelf -> high cut
//      -> drive (pre gain, waveshaper, post gain; dry/wet) -> compressor (dry/wet: parallel)
//      -> low band (mono when bass mono is on) + high band (width) -> pan -> fader -> out
//   post-fader sends A (reverb) and B (delay)
//
// Setters take the units the params use (dB, Hz, 0..1); set(prop, value) is what the param bindings call.

const DRIVE_DB = 36;            // drive 1.0 = +36 dB into the shaper

export function shaperCurve(kind = 'tanh', n = 4096) {
  const c = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const x = (i / (n - 1)) * 2 - 1;
    let y;
    switch (kind) {
      case 'hard': y = Math.max(-1, Math.min(1, x * 1.0)); break;
      case 'fold': y = Math.sin(x * Math.PI * 1.5) * 0.9; break;                  // wavefolder (COLDFIRE's B side)
      case 'tube': y = x >= 0 ? Math.tanh(x * 1.3) : Math.tanh(x * 0.8) * 0.9; break;   // asymmetric, even harmonics
      case 'bit': y = Math.round(x * 12) / 12; break;                              // Erosion-ish grit
      default: y = Math.tanh(x * 1.6) / Math.tanh(1.6);
    }
    c[i] = y;
  }
  return c;
}

const CURVES = new Map();
const curve = (kind) => { if (!CURVES.has(kind)) CURVES.set(kind, shaperCurve(kind)); return CURVES.get(kind); };
const dbToGain = (db) => Math.pow(10, db / 20);

/** An M/S width stage: w = 0 mono, 1 as is, 2 twice as wide. */
class Width {
  constructor(ctx) {
    this.in = ctx.createChannelSplitter(2);
    this.out = ctx.createChannelMerger(2);
    this.ll = ctx.createGain(); this.lr = ctx.createGain(); this.rl = ctx.createGain(); this.rr = ctx.createGain();
    this.in.connect(this.ll, 0); this.in.connect(this.rl, 0);
    this.in.connect(this.lr, 1); this.in.connect(this.rr, 1);
    this.ll.connect(this.out, 0, 0); this.lr.connect(this.out, 0, 0);
    this.rl.connect(this.out, 0, 1); this.rr.connect(this.out, 0, 1);
    this.set(1);
  }
  set(w, t = 0, ctx = null) {
    const a = (1 + w) / 2, b = (1 - w) / 2;
    const at = ctx ? ctx.currentTime : 0;
    for (const [g, v] of [[this.ll, a], [this.rr, a], [this.lr, b], [this.rl, b]]) {
      if (ctx) g.gain.setTargetAtTime(v, at, t || 0.02); else g.gain.value = v;
    }
  }
}

export class Channel {
  constructor(ctx, name, { sends = [] } = {}) {
    this.ctx = ctx;
    this.name = name;
    const g = () => ctx.createGain();
    const f = (type, freq, q = 0.707) => { const b = ctx.createBiquadFilter(); b.type = type; b.frequency.value = freq; b.Q.value = q; return b; };
    this.input = g();
    this.trim = g();
    this.hp = f('highpass', 10);
    this.low = f('lowshelf', 80); this.low.gain.value = 0;
    this.bells = [f('peaking', 250, 0.9), f('peaking', 1600, 0.9), f('peaking', 5000, 0.9)];
    this.bells.forEach((b) => { b.gain.value = 0; });
    this.high = f('highshelf', 8000); this.high.gain.value = 0;
    this.lp = f('lowpass', 22000);
    // drive, with dry/wet
    this.driveIn = g(); this.dry = g(); this.wet = g(); this.pre = g(); this.post = g(); this.driveOut = g();
    this.shaper = ctx.createWaveShaper(); this.shaper.curve = curve('tanh'); this.shaper.oversample = '2x';
    this.driveIn.connect(this.dry).connect(this.driveOut);
    this.driveIn.connect(this.pre).connect(this.shaper).connect(this.post).connect(this.wet).connect(this.driveOut);
    this.wet.gain.value = 0;
    // compressor, parallel
    this.compIn = g(); this.compDry = g(); this.compWet = g(); this.compOut = g(); this.makeup = g();
    this.comp = ctx.createDynamicsCompressor();
    this.comp.threshold.value = 0; this.comp.ratio.value = 1; this.comp.attack.value = 0.003; this.comp.release.value = 0.1; this.comp.knee.value = 3;
    this.compAlign = ctx.createDelay(0.05); this.compAlign.delayTime.value = 0.006;   // DynamicsCompressor's look-ahead
    this.compIn.connect(this.compAlign).connect(this.compDry).connect(this.compOut);
    this.compIn.connect(this.comp).connect(this.makeup).connect(this.compWet).connect(this.compOut);
    this.compWet.gain.value = 0;
    // bass mono: an LR4 crossover; the low band's width is 0 when on
    this.xLow = [f('lowpass', 120), f('lowpass', 120)];
    this.xHigh = [f('highpass', 120), f('highpass', 120)];
    this.wLow = new Width(ctx); this.wHigh = new Width(ctx);
    this.stereoOut = g();
    this.compOut.connect(this.xLow[0]).connect(this.xLow[1]).connect(this.wLow.in);
    this.compOut.connect(this.xHigh[0]).connect(this.xHigh[1]).connect(this.wHigh.in);
    this.wLow.out.connect(this.stereoOut); this.wHigh.out.connect(this.stereoOut);
    this.pan = ctx.createStereoPanner();
    this.fader = g();
    this.mute = g();
    this.output = g();
    this.meter = ctx.createAnalyser(); this.meter.fftSize = 1024;

    this.input.connect(this.trim).connect(this.hp).connect(this.low);
    let last = this.low;
    for (const b of this.bells) { last.connect(b); last = b; }
    last.connect(this.high).connect(this.lp).connect(this.driveIn);
    this.driveOut.connect(this.compIn);
    this.stereoOut.connect(this.pan).connect(this.fader).connect(this.mute).connect(this.output);
    this.mute.connect(this.meter);
    this.sends = sends.map((dest) => { const s = g(); s.gain.value = 0; this.mute.connect(s).connect(dest); return s; });
    this.state = { width: 1, bassMono: 0, bassMonoFreq: 120, drive: 0, driveType: 'tanh' };
  }

  connect(dest) { this.output.connect(dest); return this; }

  /**
   * An extra filter by name, made on first use and spliced in before the drive: band('sub30', 'lowshelf', 30).
   * Sketches use these to put a change where the set's own EQ band is. Returns the BiquadFilterNode.
   */
  band(name, type = 'peaking', freq = 1000, q = 0.9) {
    this.extra ??= new Map();
    if (this.extra.has(name)) return this.extra.get(name);
    const b = this.ctx.createBiquadFilter();
    b.type = type; b.frequency.value = freq; b.Q.value = q; b.gain.value = 0;
    const last = this.extra.size ? [...this.extra.values()].at(-1) : this.lp;
    last.disconnect(this.driveIn);
    last.connect(b).connect(this.driveIn);
    this.extra.set(name, b);
    return b;
  }

  /** Ramp an extra band's gain (dB) or frequency (Hz). */
  bandGain(name, db, type, freq, q) { this._ramp(this.band(name, type, freq, q).gain, db); }
  bandFreq(name, hz) { this._ramp(this.extra.get(name).frequency, hz); }

  _ramp(param, v, t = 0.02) { param.setTargetAtTime(v, this.ctx.currentTime, t); }

  /** prop in the units below. Unknown props are ignored (a param with no sketch yet). */
  set(prop, v) {
    const r = (p, x) => this._ramp(p, x);
    switch (prop) {
      case 'trim': return r(this.trim.gain, dbToGain(v));                 // dB
      case 'gain': case 'fader': return r(this.fader.gain, dbToGain(v));  // dB
      case 'faderLin': return r(this.fader.gain, v);                      // 0..1 linear
      case 'mute': return r(this.mute.gain, v ? 0 : 1);
      case 'on': return r(this.mute.gain, v ? 1 : 0);
      case 'pan': return r(this.pan.pan, v);                              // -1..1
      case 'lowCut': return r(this.hp.frequency, v);                      // Hz
      case 'highCut': return r(this.lp.frequency, v);                     // Hz
      case 'lowGain': return r(this.low.gain, v);                         // dB
      case 'lowFreq': return r(this.low.frequency, v);
      case 'highGain': return r(this.high.gain, v);
      case 'highFreq': return r(this.high.frequency, v);
      case 'b1Gain': return r(this.bells[0].gain, v);
      case 'b1Freq': return r(this.bells[0].frequency, v);
      case 'b1Q': return r(this.bells[0].Q, v);
      case 'b2Gain': return r(this.bells[1].gain, v);
      case 'b2Freq': return r(this.bells[1].frequency, v);
      case 'b2Q': return r(this.bells[1].Q, v);
      case 'b3Gain': return r(this.bells[2].gain, v);
      case 'b3Freq': return r(this.bells[2].frequency, v);
      case 'b3Q': return r(this.bells[2].Q, v);
      case 'drive': {                                                    // 0..1
        this.state.drive = v;
        r(this.pre.gain, dbToGain(v * DRIVE_DB));
        r(this.post.gain, dbToGain(-v * DRIVE_DB * 0.72));
        return;
      }
      case 'driveMix': r(this.wet.gain, v); return r(this.dry.gain, 1 - v);   // 0..1
      case 'driveType': this.shaper.curve = curve(v); this.state.driveType = v; return;
      case 'compThreshold': return r(this.comp.threshold, v);             // dB
      case 'compRatio': return r(this.comp.ratio, v);
      case 'compAttack': return r(this.comp.attack, v / 1000);            // ms
      case 'compRelease': return r(this.comp.release, v / 1000);          // ms
      case 'compMakeup': return r(this.makeup.gain, dbToGain(v));         // dB
      case 'compMix': r(this.compWet.gain, v); return r(this.compDry.gain, 1 - v);
      case 'width': this.state.width = v; return this._width();            // 0..2
      case 'bassMono': this.state.bassMono = v ? 1 : 0; return this._width();
      case 'bassMonoFreq': {
        for (const b of [...this.xLow, ...this.xHigh]) r(b.frequency, v);
        return;
      }
      case 'sendA': return this.sends[0] && r(this.sends[0].gain, v);      // 0..1
      case 'sendB': return this.sends[1] && r(this.sends[1].gain, v);
      default: return undefined;
    }
  }

  _width() {
    this.wHigh.set(this.state.width, 0.02, this.ctx);
    this.wLow.set(this.state.bassMono ? 0 : this.state.width, 0.02, this.ctx);
  }

  /** {rms, peak} in dBFS of the last ~23 ms. */
  level() {
    const buf = this._buf ??= new Float32Array(this.meter.fftSize);
    this.meter.getFloatTimeDomainData(buf);
    let sum = 0, peak = 0;
    for (const x of buf) { sum += x * x; const a = Math.abs(x); if (a > peak) peak = a; }
    const rms = Math.sqrt(sum / buf.length);
    return { rms: 20 * Math.log10(rms + 1e-9), peak: 20 * Math.log10(peak + 1e-9) };
  }
}
