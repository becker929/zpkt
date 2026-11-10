// The kick's arithmetic, shared by the synth (js/kick/synth.js), the drawers and the scope: the envelopes, the
// saturation curves, EQ responses as Web Audio computes them, an FFT, rooms, note names.
//
// `v` everywhere is a plain object of values by param id, in the params' units (Hz, ms, dB, %).

export const db2g = (db) => Math.pow(10, db / 20);
export const g2db = (g) => 20 * Math.log10(Math.max(1e-9, g));
const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
const smooth = (u) => { u = clamp(u, 0, 1); return u * u * (3 - 2 * u); };
const bump = (t, a, b) => (t <= a || t >= b ? 0 : 0.5 - 0.5 * Math.cos(((t - a) / (b - a)) * 2 * Math.PI));

export const BEAT = 0.375;                    // s at 160 BPM
export const OFF_HZ = 8;                      // the scoop "off": its 48 dB/oct cut far under the music
// Butterworth, 8th order, as four biquads: 48 dB/oct. Web Audio reads a high-pass's Q in dB.
export const BW8_Q = [0.5098, 0.6013, 0.9000, 2.5629];
export const BW8_QDB = BW8_Q.map((q) => 20 * Math.log10(q));

// --- envelopes -----------------------------------------------------------------------------------------------------
/** The body's pitch (Hz) `t` s after the hit: from start, falling towards end with time constant `fall`. */
export function pitchAt(v, t, k = LAYER.main) {
  const s = v['ks.pitchStart'] * k.start, e = v['ks.pitchEnd'] * k.end, tau = Math.max(0.002, (v['ks.pitchDecay'] / 1000) * k.fall);
  return e + (s - e) * Math.exp(-Math.max(0, t) / tau);
}
export const pitchSpan = (v, k = LAYER.main) => clamp((6 * v['ks.pitchDecay'] * k.fall) / 1000, 0.03, 1.5);

/** The decay's exponent: 50 % is a straight line, higher falls away faster. */
export const ampExp = (v) => Math.pow(2, ((v['ks.ampCurve'] - 50) / 50) * 2.5);

/** The body's level (0..1) `t` s after the hit, before the transient shaper. */
export function ampBase(v, t, k = LAYER.main) {
  const hold = (v['ks.ampHold'] / 1000) * k.hold, dec = Math.max(0.005, (v['ks.ampDecay'] / 1000) * k.decay);
  if (t < 0) return 0;
  if (t < 0.0012) return t / 0.0012;
  if (t < hold) return 1;
  const u = (t - hold) / dec;
  return u >= 1 ? 0 : Math.pow(1 - u, ampExp(v));
}
export const ampLength = (v, k = LAYER.main) => Math.max(0.01, (v['ks.ampHold'] * k.hold + v['ks.ampDecay'] * k.decay) / 1000);

/**
 * The kHs Transient Shaper on Clubby 052 as a gain (linear) over time. A sketch of the plugin, fitted to HW002's
 * kick (it starts quiet and swells to its loudest just before the offbeat, then stops):
 *   attack   lifts (above 50 %) or softens (below) the first few ms; 50 % leaves them alone
 *   pump     dips the body just after the transient and lets it swell back by about 120 ms
 *   sustain  lifts or drops everything after about 60 ms
 */
export function shaperGain(v, t) {
  const atk = (v['kick.attack'] ?? 47.65) / 100, pump = (v['kick.pump'] ?? 53.9) / 100, sus = (v['kick.sustain'] ?? 0) / 100;
  t = Math.max(0, t);
  const dip = 1 - smooth((t - 0.01) / 0.17);
  const db = (atk - 0.5) * 24 * Math.exp(-t / 0.009) - pump * 22 * dip + sus * 12 * smooth((t - 0.06) / 0.1);
  return db2g(db);
}

/** The transient shaper's lift (or cut) of the very start, linear: what it does to the click. */
export const attackGain = (v) => db2g(((v['kick.attack'] ?? 47.65) / 100 - 0.5) * 24);

/** The drum rack's voices, each a variation of the drawn envelopes. */
export const LAYER = {
  main: { start: 1, end: 1, fall: 1, hold: 1, decay: 1 },                       // Clubby 052: the drawn kick
  l060: { start: 0.62, end: 1.62, fall: 0.55, hold: 0.4, decay: 1.6 },        // Clubby 060: a shorter knock, higher
  off: { start: 0.7, end: 2.3, fall: 0.3, hold: 0.08, decay: 0.85, short: true },  // the offbeat pad: a short knock
};

/** A layer's level curve (Float32Array, `n` points over its length), before any distortion. */
export function ampCurve(v, k = LAYER.main, n = 384) {
  const len = ampLength(v, k);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) out[i] = ampBase(v, (i / (n - 1)) * len, k);
  out[n - 1] = 0;
  return { curve: out, len };
}

/** The transient shaper's gain over the main layer's length (it comes after the layer's own COLDFIRE). */
export function transientCurve(v, n = 256) {
  const len = ampLength(v, LAYER.main);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) out[i] = shaperGain(v, (i / (n - 1)) * len);
  return { curve: out, len };
}

/** The 052 layer's own COLDFIRE: dB into its shaper. */
export const gritDb = (v) => (Math.max(0, v['ks.grit'] ?? 15) / 100) * 30;

/** The main layer's level as heard: the body through its grit (a soft clip) and the transient shaper. */
export function heardAmp(v, t) {
  const g = Math.pow(10, gritDb(v) / 20);
  const x = ampBase(v, t) * g;
  return Math.min(1, SHAPES.grit(Math.min(HEADROOM, x))) * shaperGain(v, t);
}

export function pitchCurve(v, k = LAYER.main, ratio = 1, n = 256) {
  const len = pitchSpan(v, k);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) out[i] = Math.min(20000, pitchAt(v, (i / (n - 1)) * len, k) * ratio);
  return { curve: out, len };
}

/** The rumble's gain over one beat (LFOTool's shape): down on the kick, swelling back by about 3/4 of the beat. */
export function duckShape(depth, n = 256) {
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const u = i / (n - 1);
    const s = u < 0.1 ? 1 : 1 - smooth((u - 0.1) / 0.62);
    out[i] = 1 - depth * s;
  }
  out[n - 1] = 1;
  return out;
}

// --- saturation --------------------------------------------------------------------------------------------------
// A waveshaper's curve spans -1..1; ours stands for an input of -H..H, so a hot signal is shaped, not cut flat.
export const HEADROOM = 4;

const knee = (x, k) => { const a = Math.abs(x); return a < k ? x : Math.sign(x) * (k + (1 - k) * Math.tanh((a - k) / (1 - k))); };

/** Transfer functions: x in signal units (about -4..4) -> y (about -1..1). */
export const SHAPES = {
  coldfire: (x) => knee(x * 0.9, 0.5) * 0.85 + Math.tanh(x * 1.3) * 0.15,
  grit: (x) => knee(x, 0.82),                                                // the 052 layer's own COLDFIRE: hard
  roar: (x) => (x >= 0 ? Math.tanh(x * 1.4) : Math.tanh(x * 0.9) * 0.92),
  A: (x) => Math.tanh(x),                                                    // Ampex: tape, round and even
  E: (x) => Math.tanh(x * 1.25 + 0.18 * x * x / (1 + Math.abs(x))) * 0.95,  // EMI: a console, a little lean
  N: (x) => { const y = Math.tanh(x * 0.9); return (y + 0.22 * y * y * (x > 0 ? 1 : 0.6)) * 0.85; },  // Neve: transformer, thick
  T: (x) => { const y = Math.tanh(x * 1.8); return Math.sign(y) * Math.min(1, Math.abs(y) * 1.12); },  // Thermionic: hot, flat-topped
  P: (x) => { const y = Math.tanh(x * 2.4); return Math.abs(x) > 1.3 ? y * (1 - 0.18 * Math.sin((Math.abs(x) - 1.3) * 3)) : y; },  // Pentode: hard, fizzing
};
export const STYLES = ['A', 'E', 'N', 'T', 'P'];

const CURVES = new Map();
/** The WaveShaperNode curve for a shape, cached. */
export function shaperCurve(name, n = 2048) {
  if (CURVES.has(name)) return CURVES.get(name);
  const f = SHAPES[name] ?? SHAPES.A;
  const c = new Float32Array(n);
  for (let i = 0; i < n; i++) c[i] = f(((i / (n - 1)) * 2 - 1) * HEADROOM);
  CURVES.set(name, c);
  return c;
}

/** Drive % -> dB into the shaper (COLDFIRE and Decapitator both: 0-100 % is 0-30 dB). */
export const driveDb = (pct) => (Math.max(0, pct) / 100) * 30;

// --- EQ responses (Web Audio's biquads, Audio EQ Cookbook) -----------------------------------------------------------
/** |H| in dB of a BiquadFilterNode of `type` at frequency f. Q as Web Audio reads it (dB for low/high-pass). */
export function biquadDb(type, f0, gainDb, q, f, fs = 48000) {
  const w0 = (2 * Math.PI * f0) / fs, cw = Math.cos(w0), sw = Math.sin(w0);
  const A = Math.pow(10, gainDb / 40);
  let b0, b1, b2, a0, a1, a2;
  if (type === 'peaking') {
    const al = sw / (2 * q);
    b0 = 1 + al * A; b1 = -2 * cw; b2 = 1 - al * A; a0 = 1 + al / A; a1 = -2 * cw; a2 = 1 - al / A;
  } else if (type === 'lowshelf' || type === 'highshelf') {
    const al = (sw / 2) * Math.SQRT2, sA = 2 * Math.sqrt(A) * al;
    if (type === 'lowshelf') {
      b0 = A * ((A + 1) - (A - 1) * cw + sA); b1 = 2 * A * ((A - 1) - (A + 1) * cw); b2 = A * ((A + 1) - (A - 1) * cw - sA);
      a0 = (A + 1) + (A - 1) * cw + sA; a1 = -2 * ((A - 1) + (A + 1) * cw); a2 = (A + 1) + (A - 1) * cw - sA;
    } else {
      b0 = A * ((A + 1) + (A - 1) * cw + sA); b1 = -2 * A * ((A - 1) + (A + 1) * cw); b2 = A * ((A + 1) + (A - 1) * cw - sA);
      a0 = (A + 1) - (A - 1) * cw + sA; a1 = 2 * ((A - 1) - (A + 1) * cw); a2 = (A + 1) - (A - 1) * cw - sA;
    }
  } else {                                                    // lowpass / highpass, Q in dB
    const al = sw / (2 * Math.pow(10, q / 20));
    if (type === 'highpass') { b0 = (1 + cw) / 2; b1 = -(1 + cw); b2 = (1 + cw) / 2; }
    else { b0 = (1 - cw) / 2; b1 = 1 - cw; b2 = (1 - cw) / 2; }
    a0 = 1 + al; a1 = -2 * cw; a2 = 1 - al;
  }
  const w = (2 * Math.PI * f) / fs, c1 = Math.cos(w), s1 = Math.sin(w), c2 = Math.cos(2 * w), s2 = Math.sin(2 * w);
  const nr = b0 + b1 * c1 + b2 * c2, ni = -(b1 * s1 + b2 * s2);
  const dr = a0 + a1 * c1 + a2 * c2, di = -(a1 * s1 + a2 * s2);
  return 10 * Math.log10((nr * nr + ni * ni) / (dr * dr + di * di) + 1e-30);
}

/** The kick group's two EQ Eights as the set has them, as bands: [{id, type, f, gain, q, pre}]. */
export function kickEqBands(v) {
  return [
    { id: 'kick.sub30', type: 'lowshelf', f: 30, gain: v['kick.sub30'], q: 0.71, pre: true, label: '30' },
    { id: 'kick.sub35', type: 'lowshelf', f: 35, gain: v['kick.sub35'], q: 0.71, pre: false, label: '35' },
    { id: 'kick.body', type: 'peaking', f: 62.5, gain: v['kick.body'], q: 0.82, pre: true, label: '62' },
    { id: 'kick.push', type: 'peaking', f: 330, gain: v['kick.push'], q: 1.0, pre: true, label: '330' },
    { id: 'kick.colour', type: 'peaking', f: v['kick.colourFreq'], gain: v['kick.colour'], q: 1.2, pre: false, label: 'COL', freqId: 'kick.colourFreq' },
    { id: 'kick.air', type: 'highshelf', f: 5000, gain: v['kick.air'], q: 0.71, pre: false, label: '5k' },
  ];
}

// --- FFT -----------------------------------------------------------------------------------------------------------
const TW = new Map();
/** In-place radix-2 FFT of (re, im), length a power of two. */
export function fft(re, im) {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) { let t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; }
  }
  if (!TW.has(n)) {
    const c = new Float64Array(n / 2), s = new Float64Array(n / 2);
    for (let i = 0; i < n / 2; i++) { c[i] = Math.cos((-2 * Math.PI * i) / n); s[i] = Math.sin((-2 * Math.PI * i) / n); }
    TW.set(n, [c, s]);
  }
  const [cs, sn] = TW.get(n);
  for (let size = 2; size <= n; size <<= 1) {
    const half = size >> 1, step = n / size;
    for (let i = 0; i < n; i += size) {
      for (let j = 0, k = 0; j < half; j++, k += step) {
        const a = i + j, b = a + half;
        const tr = re[b] * cs[k] - im[b] * sn[k], ti = re[b] * sn[k] + im[b] * cs[k];
        re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti;
      }
    }
  }
}

/**
 * The power spectrum of `x` (mono Float32Array) zero-padded to `n`: {power (per bin), df}. Hann window.
 * `bandDb(lo, hi)` sums a band in dB relative to full scale (a full-scale sine reads about 0 dB).
 */
export function spectrum(x, fs, n = 32768) {
  const re = new Float64Array(n), im = new Float64Array(n);
  const m = Math.min(x.length, n);
  let wsum = 0;
  for (let i = 0; i < m; i++) { const w = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (m - 1)); re[i] = x[i] * w; wsum += w; }
  fft(re, im);
  const power = new Float64Array(n / 2);
  const norm = 4 / (wsum * wsum);
  for (let i = 0; i < n / 2; i++) power[i] = (re[i] * re[i] + im[i] * im[i]) * norm;
  const df = fs / n;
  const bandDb = (lo, hi) => {
    let s = 0;
    for (let i = Math.max(1, Math.floor(lo / df)); i <= Math.min(n / 2 - 1, Math.ceil(hi / df)); i++) s += power[i];
    return 10 * Math.log10(s + 1e-20);
  };
  /** dB at f, smoothed over a 1/`frac` octave. */
  const at = (f, frac = 6) => bandDb(f / Math.pow(2, 0.5 / frac), f * Math.pow(2, 0.5 / frac));
  return { power, df, bandDb, at };
}

// --- rooms ---------------------------------------------------------------------------------------------------------
/**
 * A generated stereo room: `seconds` long, `cutoff` Hz of darkness (two one-pole low-passes on the noise), `spread`
 * 0..1 how different the two sides are (0: mono, 1: unrelated noise).
 */
export function room(ac, seconds, cutoff, { seed = 1, pre = 0.004, spread = 0.75 } = {}) {
  const fs = ac.sampleRate;
  const len = Math.max(64, Math.round(seconds * fs));
  const ir = ac.createBuffer(2, len, fs);
  const a = 1 - Math.exp((-2 * Math.PI * cutoff) / fs);
  let r = seed * 9301 + 49297;
  const rnd = () => { r = (r * 16807) % 2147483647; return (r / 2147483647) * 2 - 1; };
  const t60 = seconds * 0.9;
  const L = ir.getChannelData(0), R = ir.getChannelData(1);
  const p0 = Math.round(pre * fs);
  const wc = Math.sqrt(1 - spread * spread * 0.5), ws = spread * Math.SQRT1_2;
  let c1 = 0, c2 = 0, l1 = 0, l2 = 0, q1 = 0, q2 = 0;
  for (let i = 0; i < len; i++) {
    const t = i / fs;
    c1 += (rnd() - c1) * a; c2 += (c1 - c2) * a;
    l1 += (rnd() - l1) * a; l2 += (l1 - l2) * a;
    q1 += (rnd() - q1) * a; q2 += (q1 - q2) * a;
    const env = i < p0 ? 0 : Math.exp((-6.9 * (t - pre)) / t60) * Math.min(1, (i - p0) / (0.012 * fs));
    L[i] = (c2 * wc + l2 * ws) * env;
    R[i] = (c2 * wc + q2 * ws) * env;
  }
  return ir;
}

/** A click: a burst of noise and an impulse, rung through a wide band-pass at `tone` Hz, peak 1. */
export function clickBuffer(ac, tone) {
  const fs = ac.sampleRate, len = Math.round(0.045 * fs);
  const buf = ac.createBuffer(1, len, fs);
  const d = buf.getChannelData(0);
  const w0 = (2 * Math.PI * Math.min(tone, fs * 0.45)) / fs, al = Math.sin(w0) / (2 * 0.8);
  const b0 = al, b2 = -al, a0 = 1 + al, a1 = -2 * Math.cos(w0), a2 = 1 - al;
  let x1 = 0, x2 = 0, y1 = 0, y2 = 0, r = 12345, peak = 1e-9;
  for (let i = 0; i < len; i++) {
    r = (r * 16807) % 2147483647;
    const t = i / fs;
    const x = (i === 0 ? 2 : 0) + ((r / 2147483647) * 2 - 1) * (t < 0.002 ? 1 : Math.exp(-(t - 0.002) / 0.01));
    const y = (b0 * x + b2 * x2 - a1 * y1 - a2 * y2) / a0;
    x2 = x1; x1 = x; y2 = y1; y1 = y;
    d[i] = y * (i > len - 96 ? (len - i) / 96 : 1);
    peak = Math.max(peak, Math.abs(d[i]));
  }
  for (let i = 0; i < len; i++) d[i] /= peak;
  return buf;
}

// --- names ---------------------------------------------------------------------------------------------------------
const NOTES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
/** "G1" for 49 Hz (A4 = 440). */
export function noteName(f) {
  const m = Math.round(69 + 12 * Math.log2(f / 440));
  return `${NOTES[((m % 12) + 12) % 12]}${Math.floor(m / 12) - 1}`;
}

/** HW002's kick, measured (one beat of the kick stem): the body's pitch over time, [ms, Hz]. */
export const SET_PITCH = [[41, 196], [51, 190], [58, 159], [73, 133], [81, 113], [92, 100], [103, 90], [115, 83], [129, 71], [145, 64], [161, 61], [181, 50]];

/** The references against HW002 (30 s peak windows of the mixes). */
export const REF = {
  sub: { hw: -34.4, lo: -27.6, hi: -22.6, f: 31.6 },         // the 31.6 Hz band, dB
  crest: { hw: 8.7, lo: 4.4, hi: 6.6 },                      // block crest, dB
};
