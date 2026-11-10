// Hat layer sets the canonical Short has no bar of (A+C, B alone, ...; or every set, in a build without its
// stems), sketched from a bar that holds all four layers: it is split into four bands (under 2 kHz, 2-5 kHz,
// 5-9 kHz, over 9 kHz; the bands add back up to the bar exactly) and each band is turned down, 64 times a bar,
// to where the chosen layers play. The masks come from batch 4.3 track 1's own perc stem, where the layers enter
// one at a time (data/arrange-bars.json, `hats`). Measured offline, the masked bars step up like the canonical
// shape's: A, AB +1.1 LU, ABC +2.9 LU, ABCD +2.7 LU.

const SPLITS_DEFAULT = [2000, 5000, 9000];

function lowpass(f0, rate, q = Math.SQRT1_2) {
  const w = 2 * Math.PI * f0 / rate, c = Math.cos(w), a = Math.sin(w) / (2 * q), a0 = 1 + a;
  return [(1 - c) / 2 / a0, (1 - c) / a0, (1 - c) / 2 / a0, -2 * c / a0, (1 - a) / a0];
}

/** x filtered by a biquad twice (a 4th-order Linkwitz-Riley low pass), from silence. */
function lr4(x, k) {
  const y = new Float32Array(x.length);
  const [b0, b1, b2, a1, a2] = k;
  let x1 = 0, x2 = 0, y1 = 0, y2 = 0, u1 = 0, u2 = 0, z1 = 0, z2 = 0;
  for (let n = 0; n < x.length; n++) {
    const xn = x[n];
    const yn = b0 * xn + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2;
    x2 = x1; x1 = xn; y2 = y1; y1 = yn;
    const zn = b0 * yn + b1 * u1 + b2 * u2 - a1 * z1 - a2 * z2;
    u2 = u1; u1 = yn; z2 = z1; z1 = zn;
    y[n] = zn;
  }
  return y;
}

/** Four bands of x that sum to x: low pass, then low pass the rest, and so on. */
function split(x, rate, splits) {
  const out = [];
  let rest = x;
  for (const f of splits) {
    const lo = lr4(rest, lowpass(f, rate));
    const next = new Float32Array(rest.length);
    for (let n = 0; n < rest.length; n++) next[n] = rest[n] - lo[n];
    out.push(lo);
    rest = next;
  }
  out.push(rest);
  return out;
}

export class HatMasks {
  /** data: arrange-bars.json's `hats`. */
  constructor(data) {
    this.data = data;
    this.buffers = new Map();       // subset ('AB') -> AudioBuffer, one bar (+ a little)
    this.bands = null;
    this.ready = false;
  }

  /** Split bar `bar` of `perc` (a perc stem with all four layers there) into bands, once. */
  prepare(ctx, perc, sourceBar = this.data.source_bar ?? 12) {
    if (this.bands || this.failed || !perc) return;
    const rate = perc.sampleRate, bar = Math.round(rate * 1.5);
    const warm = Math.round(rate * 0.12), tail = Math.round(rate * 0.012);
    const have = Math.floor(perc.length / bar);
    if (have < 1) { this.failed = true; return; }                     // a stem shorter than a bar: no masks
    const src = Math.min(sourceBar, have - 1);
    const a = Math.max(0, src * bar - warm), b = Math.min(perc.length, (src + 1) * bar + tail);
    const splits = this.data.splits ?? SPLITS_DEFAULT;
    this.bands = [];
    for (let c = 0; c < perc.numberOfChannels; c++) {
      const x = perc.getChannelData(c).subarray(a, b);
      this.bands.push(split(x, rate, splits).map((band) => band.subarray(src * bar - a)));
    }
    this.rate = rate; this.bar = bar; this.len = this.bands[0][0].length; this.ctx = ctx;
    if (this.len < 1) { this.bands = null; this.failed = true; }
  }

  /** The per-sample gain envelope of each band for a subset (smoothed over ~2 ms). */
  envelopes(subset) {
    const { masks, slots = 16 } = this.data;
    const nBands = this.bands[0].length;
    const perSlot = this.bar / (4 * slots);
    const smooth = Math.exp(-1 / (0.002 * this.rate));
    return Array.from({ length: nBands }, (_, k) => {
      const g = new Float32Array(4 * slots);
      for (let s = 0; s < 4 * slots; s++) {
        let pw = 0;
        for (const L of subset) pw += Math.pow(10, (masks[L]?.[k]?.[s % slots] ?? -60) / 10);
        g[s] = Math.sqrt(Math.min(1, pw));
      }
      const env = new Float32Array(this.len);
      let y = g[0];
      for (let n = 0; n < this.len; n++) {
        const s = Math.min(4 * slots - 1, Math.floor((n % this.bar) / perSlot));
        y = g[s] + (y - g[s]) * smooth;
        env[n] = y;
      }
      return env;
    });
  }

  /** The masked bar for a subset of 'ABCD' (cached). Null until prepare() ran. */
  buffer(subset) {
    if (!this.bands || !subset || this.len < 1) return null;
    if (this.buffers.has(subset)) return this.buffers.get(subset);
    const env = this.envelopes(subset);
    const out = this.ctx.createBuffer(this.bands.length, this.len, this.rate);
    this.bands.forEach((bands, c) => {
      const y = out.getChannelData(c);
      bands.forEach((band, k) => { const e = env[k]; for (let n = 0; n < y.length; n++) y[n] += band[n] * e[n]; });
    });
    this.buffers.set(subset, out);
    return out;
  }

  /** Make every subset now, a few per frame, so the first play does not wait. */
  async warm(yieldFn = () => new Promise((r) => setTimeout(r, 0))) {
    const all = [];
    for (let m = 1; m < 16; m++) all.push('ABCD'.split('').filter((_, j) => m >> j & 1).join(''));
    for (const s of all) { this.buffer(s); await yieldFn(); }
    this.ready = true;
  }
}
