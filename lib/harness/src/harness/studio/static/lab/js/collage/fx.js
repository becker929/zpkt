// The collage's effect units, sketched in Web Audio: Supermassive (a swelling delay-hall), FlexVerb (a short bright
// room), the Break bus's Hybrid reverb (its decay is a knob), and the tape machine every collage sound passes
// through (wow, flutter, tape stop and start).

/** A stereo impulse: `seconds` of decaying noise. damp 0..1 darker; swell 0..1 a slow bloom (Supermassive). */
export function impulse(ctx, seconds, { damp = 0.5, swell = 0, pre = 0.008 } = {}) {
  const sr = ctx.sampleRate;
  const len = Math.max(64, Math.floor(Math.min(10, Math.max(0.1, seconds)) * sr));
  const ir = ctx.createBuffer(2, len, sr);
  const preN = Math.floor(pre * sr);
  for (let c = 0; c < 2; c++) {
    const d = ir.getChannelData(c);
    let lp = 0;
    const k = 1 - damp * 0.9;
    for (let i = preN; i < len; i++) {
      const t = (i - preN) / (len - preN);
      lp += (Math.random() * 2 - 1 - lp) * (k * (1 - t * damp * 0.6));
      const env = Math.pow(1 - t, 2.4) * (swell ? Math.min(1, (t + 0.02) / (0.02 + swell * 0.35)) : 1);
      d[i] = lp * env;
    }
    // normalise roughly so longer rooms do not get louder
    let s = 0;
    for (let i = 0; i < len; i += 7) s += d[i] * d[i];
    const g = 0.6 / Math.sqrt(1e-9 + s * 7);
    for (let i = 0; i < len; i++) d[i] *= g;
  }
  return ir;
}

class Unit {
  constructor(ctx) { this.ctx = ctx; this.nodes = []; this.in = this.n(ctx.createGain()); this.out = this.n(ctx.createGain()); }
  n(node) { this.nodes.push(node); return node; }
  dispose() {
    for (const node of this.nodes) { try { node.disconnect(); } catch { /* gone */ } try { node.stop?.(); } catch { /* not started */ } }
  }
}

/** Supermassive: an echo (time is a knob on the ARC track) feeding a 5.5 s hall that blooms in. */
export class Massive extends Unit {
  constructor(ctx, { time = 0.28125, feedback = 0.42 } = {}) {
    super(ctx);
    this.hall = this.n(ctx.createConvolver());
    this.hall.buffer = impulse(ctx, 5.5, { damp: 0.55, swell: 0.6, pre: 0.02 });
    this.echo = this.n(ctx.createDelay(2.5));
    this.echo.delayTime.value = time;
    this.fb = this.n(ctx.createGain()); this.fb.gain.value = feedback;
    this.tone = this.n(ctx.createBiquadFilter()); this.tone.type = 'lowpass'; this.tone.frequency.value = 4200; this.tone.Q.value = -3;
    this.toHall = this.n(ctx.createGain()); this.toHall.gain.value = 0.9;
    this.echoOut = this.n(ctx.createGain()); this.echoOut.gain.value = 0.45;
    this.in.connect(this.echo);
    this.echo.connect(this.tone).connect(this.fb).connect(this.echo);
    this.tone.connect(this.echoOut).connect(this.out);
    this.in.connect(this.toHall).connect(this.hall);
    this.tone.connect(this.hall);
    this.hall.connect(this.out);
    this.out.gain.value = 1.1;
  }

  setTime(s) { this.echo.delayTime.setTargetAtTime(Math.max(0.01, s), this.ctx.currentTime, 0.05); }
}

/** FlexVerb: a 1.3 s bright room. */
export class Room extends Unit {
  constructor(ctx) {
    super(ctx);
    this.conv = this.n(ctx.createConvolver());
    this.conv.buffer = impulse(ctx, 1.3, { damp: 0.2 });
    this.in.connect(this.conv).connect(this.out);
  }
}

/** The Break bus's Hybrid: a hall whose decay follows its knob (rebuilt, debounced, when it moves). */
export class Hybrid extends Unit {
  constructor(ctx) {
    super(ctx);
    this.conv = this.n(ctx.createConvolver());
    this.conv.buffer = impulse(ctx, 3.5, { damp: 0.45 });
    this.seconds = 3.5;
    this.in.connect(this.conv).connect(this.out);
    this.timer = 0;
  }

  setDecay(s) {
    if (Math.abs(s - this.seconds) < 0.02) return;
    this.seconds = s;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { this.conv.buffer = impulse(this.ctx, Math.min(10, s), { damp: 0.45 }); }, 120);
  }

  dispose() { clearTimeout(this.timer); super.dispose(); }
}

// --- the tape machine ---------------------------------------------------------------------------------------------
/** Freeze an AudioParam where it is now and drop what was scheduled after. */
export function hold(param, t) {
  if (param.cancelAndHoldAtTime) { param.cancelAndHoldAtTime(t); return t + 0.002; }
  const v = param.value;
  param.cancelScheduledValues(t);
  param.setValueAtTime(v, t);
  return t + 0.002;
}

export const TAPE_BASE = 0.012;           // s every collage sound is late by (the heads' gap); schedules subtract it
const LINE_MAX = 6;

/**
 * Two delay lines, so a tape start can jump back onto the grid without a click. A tape stop ramps the delay up
 * (the read head slows to 0: pitch falls to nothing), a start ramps it from 0 back up to speed, then crossfades to a
 * fresh line on the grid. Wow and flutter are slow and fast LFOs on the delay time.
 */
export class Tape extends Unit {
  constructor(ctx) {
    super(ctx);
    const line = () => {
      const d = this.n(ctx.createDelay(LINE_MAX)); d.delayTime.value = TAPE_BASE;
      const g = this.n(ctx.createGain());
      this.in.connect(d).connect(g).connect(this.out);
      return { d, g };
    };
    this.lines = [line(), line()];
    this.lines[1].g.gain.value = 0;
    this.active = 0;
    this.wow = this.n(ctx.createOscillator()); this.wow.frequency.value = 0.55;
    this.wowAmt = this.n(ctx.createGain()); this.wowAmt.gain.value = 0;
    this.flut = this.n(ctx.createOscillator()); this.flut.frequency.value = 9.3;
    this.flutAmt = this.n(ctx.createGain()); this.flutAmt.gain.value = 0;
    this.wow.connect(this.wowAmt); this.flut.connect(this.flutAmt);
    for (const l of this.lines) { this.wowAmt.connect(l.d.delayTime); this.flutAmt.connect(l.d.delayTime); }
    this.wow.start(); this.flut.start();
    this.state = 'run';           // run | stopping | stopped | starting
    this.t0 = 0; this.T = 1;
    this.timers = [];
  }

  setWow(x) { this.wowAmt.gain.setTargetAtTime(x * 0.0042, this.ctx.currentTime, 0.05); }
  setFlutter(x) { this.flutAmt.gain.setTargetAtTime(x * 0.00028, this.ctx.currentTime, 0.05); }

  /** The tape's speed now, 0..1 (for the reels). */
  speed() {
    const t = this.ctx.currentTime - this.t0;
    if (this.state === 'stopping') return Math.max(0, 1 - t / this.T);
    if (this.state === 'stopped') return 0;
    if (this.state === 'starting') return Math.min(1, t / this.T);
    return 1;
  }

  _clear() { for (const t of this.timers) clearTimeout(t); this.timers = []; }
  _later(s, fn) { this.timers.push(setTimeout(fn, Math.max(0, s * 1000))); }

  /** Slow the tape to a stop over T seconds. */
  stop(T = 0.9) {
    if (this.state === 'stopped' || this.state === 'stopping') return;
    this._clear();
    const ctx = this.ctx, now = ctx.currentTime + 0.005;
    const from = this.state === 'starting' ? this.speed() : 1;
    const { d, g } = this.lines[this.active];
    const N = 48, curve = new Float32Array(N);
    const base = this.state === 'starting' ? d.delayTime.value : TAPE_BASE;
    // speed v(t) = from * (1 - t/T): delay grows by the integral of (1 - v)
    for (let i = 0; i < N; i++) { const t = T * i / (N - 1); curve[i] = Math.min(LINE_MAX - 0.1, base + t - from * (t - t * t / (2 * T))); }
    d.delayTime.setValueCurveAtTime(curve, hold(d.delayTime, now), T);
    hold(g.gain, now);
    g.gain.setTargetAtTime(0, now + T * 0.85, T * 0.05 + 0.01);
    this.state = 'stopping'; this.t0 = now; this.T = T;
    this._later(T + 0.05, () => {
      this.state = 'stopped';
      d.delayTime.cancelScheduledValues(0);
      d.delayTime.setValueAtTime(TAPE_BASE, ctx.currentTime + 0.01);
    });
  }

  /** Bring the tape up to speed over T seconds, then land back on the grid. */
  start(T = 0.5) {
    if (this.state === 'run' || this.state === 'starting') return;
    this._clear();
    const ctx = this.ctx, now = ctx.currentTime + 0.005;
    const { d, g } = this.lines[this.active];
    const base = this.state === 'stopping' ? d.delayTime.value : TAPE_BASE;
    const from = this.state === 'stopping' ? this.speed() : 0;
    const N = 48, curve = new Float32Array(N);
    // speed v(t) = from + (1 - from) t/T
    for (let i = 0; i < N; i++) { const t = T * i / (N - 1); curve[i] = Math.min(LINE_MAX - 0.1, base + (1 - from) * (t - t * t / (2 * T))); }
    d.delayTime.setValueCurveAtTime(curve, hold(d.delayTime, now), T);
    hold(g.gain, now);
    g.gain.linearRampToValueAtTime(1, now + 0.03);
    this.state = 'starting'; this.t0 = now; this.T = T;
    this._later(T + 0.02, () => {
      // back on the grid: crossfade to the other line, sitting at the heads' gap
      const t = ctx.currentTime + 0.01;
      const old = this.lines[this.active], nu = this.lines[1 - this.active];
      nu.d.delayTime.cancelScheduledValues(0); nu.d.delayTime.setValueAtTime(TAPE_BASE, t);
      nu.g.gain.cancelScheduledValues(0); nu.g.gain.setValueAtTime(0, t); nu.g.gain.linearRampToValueAtTime(1, t + 0.04);
      old.g.gain.cancelScheduledValues(0); old.g.gain.setValueAtTime(1, t); old.g.gain.linearRampToValueAtTime(0, t + 0.04);
      this.active = 1 - this.active;
      this.state = 'run';
      this._later(0.1, () => { old.d.delayTime.cancelScheduledValues(0); old.d.delayTime.setValueAtTime(TAPE_BASE, ctx.currentTime + 0.01); });
    });
  }

  dispose() { this._clear(); super.dispose(); }
}
