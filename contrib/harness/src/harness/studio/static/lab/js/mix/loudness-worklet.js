// The mix surface's meter, on the audio thread: everything a loudness and density meter needs, from the master.
//
//   BS.1770-4 K-weighting (pre-filter shelf + RLB high-pass, coefficients for this sample rate)
//   momentary (400 ms), short-term (3 s), integrated (gated: -70 LUFS absolute, -10 LU relative) and LRA
//   true peak: 4x oversampled with a 48-tap polyphase interpolator; sample peak
//   PLR (max true peak - integrated) and PSR (3 s true peak - short-term)
//   block crest as the references were measured (peak / RMS per 400 ms block, both channels pooled; the median
//   over the loud blocks of the last 30 s)
//   low end below 120 Hz (20-120 Hz, 4th-order band): L/R correlation and side - mid, 400 ms and 3 s; full-band
//   correlation
//
// Every 100 ms it posts one message: {t, m, s, i, lra, tp, tpMax, sp, plr, psr, crest, crestMed, corrLow,
// corrLowS, smLow, corrFull, ms}. `ms` is that 100 ms block's K-weighted power (the A/B level match uses it),
// `t` the audio-clock time at its end. Post {type: 'reset'} to restart the integrated, LRA, max peak and crest.

const LOG = (p) => (p > 0 ? -0.691 + 10 * Math.log10(p) : -120);
const DB = (x) => (x > 0 ? 20 * Math.log10(x) : -120);

class Biquad {
  constructor([b0, b1, b2, a1, a2]) { this.b0 = b0; this.b1 = b1; this.b2 = b2; this.a1 = a1; this.a2 = a2; this.z1 = 0; this.z2 = 0; }
  run(x) {
    const y = this.b0 * x + this.z1;
    this.z1 = this.b1 * x - this.a1 * y + this.z2;
    this.z2 = this.b2 * x - this.a2 * y;
    return y;
  }
}

/** BS.1770 stage 1 (the head's high shelf) at sample rate fs (libebur128's derivation). */
function kShelf(fs) {
  const f0 = 1681.974450955533, G = 3.999843853973347, Q = 0.7071752369554196;
  const K = Math.tan(Math.PI * f0 / fs), Vh = Math.pow(10, G / 20), Vb = Math.pow(Vh, 0.4996667741545416);
  const a0 = 1 + K / Q + K * K;
  return [(Vh + Vb * K / Q + K * K) / a0, 2 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0,
    2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0];
}

/** BS.1770 stage 2 (RLB high-pass). */
function kHighpass(fs) {
  const f0 = 38.13547087602444, Q = 0.5003270373238773;
  const K = Math.tan(Math.PI * f0 / fs), a0 = 1 + K / Q + K * K;
  return [1, -2, 1, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0];
}

/** RBJ low/high-pass. */
function pass(type, f, q, fs) {
  const w = 2 * Math.PI * f / fs, c = Math.cos(w), al = Math.sin(w) / (2 * q), a0 = 1 + al;
  const b = type === 'lp' ? [(1 - c) / 2, 1 - c, (1 - c) / 2] : [(1 + c) / 2, -(1 + c), (1 + c) / 2];
  return [b[0] / a0, b[1] / a0, b[2] / a0, -2 * c / a0, (1 - al) / a0];
}

// 4th-order Butterworth = two biquads with these Qs
const BW4 = [0.5411961, 1.3065630];

// 4x true-peak interpolator: a 48-tap windowed sinc, 12 taps per phase
const TAPS = (() => {
  const N = 48, h = new Float64Array(N);
  let sum = 0;
  for (let n = 0; n < N; n++) {
    const x = (n - (N - 1) / 2) / 4;
    const sinc = x === 0 ? 1 : Math.sin(Math.PI * x) / (Math.PI * x);
    const t = n / (N - 1);
    const win = 0.35875 - 0.48829 * Math.cos(2 * Math.PI * t) + 0.14128 * Math.cos(4 * Math.PI * t) - 0.01168 * Math.cos(6 * Math.PI * t);
    h[n] = sinc * win; sum += h[n];
  }
  for (let n = 0; n < N; n++) h[n] *= 4 / sum;
  // phases[k][j] = h[4j + k]
  return [0, 1, 2, 3].map((k) => Float64Array.from({ length: 12 }, (_, j) => h[4 * j + k]));
})();

const RING = 30;                 // 100 ms blocks kept: 3 s
const HIST = 1200;               // loudness histogram: -100 .. +20 LUFS in 0.1 dB bins

class MixMeter extends AudioWorkletProcessor {
  constructor() {
    super();
    const fs = sampleRate;
    this.fs = fs;
    this.block = Math.round(fs * 0.1);
    this.k = [0, 1].map(() => [new Biquad(kShelf(fs)), new Biquad(kHighpass(fs))]);
    this.low = [0, 1].map(() => [
      new Biquad(pass('hp', 20, BW4[0], fs)), new Biquad(pass('hp', 20, BW4[1], fs)),
      new Biquad(pass('lp', 120, BW4[0], fs)), new Biquad(pass('lp', 120, BW4[1], fs))]);
    this.hist = [new Float64Array(24), new Float64Array(24)];   // true-peak history per channel, written twice
    this.hi = 0;
    this.n = 0;
    this.acc = this.zero();
    this.ring = [];
    this.alive = true;
    this.reset();
    this.port.onmessage = (e) => {
      if (e.data?.type === 'reset') this.reset();
      if (e.data?.type === 'stop') this.alive = false;
    };
  }

  zero() { return { k: 0, tp: 0, sp: 0, raw: 0, lrL: 0, llL: 0, rrL: 0, mmL: 0, ssL: 0, lr: 0, ll: 0, rr: 0 }; }

  reset() {
    this.iCount = new Float64Array(HIST); this.iPow = new Float64Array(HIST);
    this.sCount = new Float64Array(HIST);
    this.tpMax = 0;
    this.crests = [];            // [crest, level] per 400 ms block, last 30 s
    this.crestAcc = { peak: 0, raw: 0, n: 0, blocks: 0 };
  }

  process(inputs) {
    const inp = inputs[0];
    if (!this.alive) return false;
    if (!inp || !inp.length) return true;
    const L = inp[0], R = inp[1] ?? inp[0];
    const [kL1, kL2] = this.k[0], [kR1, kR2] = this.k[1];
    const [lA, lB, lC, lD] = this.low[0], [rA, rB, rC, rD] = this.low[1];
    const hL = this.hist[0], hR = this.hist[1];
    const P = TAPS;
    const a = this.acc;
    for (let i = 0; i < L.length; i++) {
      const xl = L[i], xr = R[i];
      // K-weighted power
      const kl = kL2.run(kL1.run(xl)), kr = kR2.run(kR1.run(xr));
      a.k += kl * kl + kr * kr;
      // raw
      a.raw += xl * xl + xr * xr;
      const al = xl < 0 ? -xl : xl, ar = xr < 0 ? -xr : xr;
      if (al > a.sp) a.sp = al;
      if (ar > a.sp) a.sp = ar;
      a.lr += xl * xr; a.ll += xl * xl; a.rr += xr * xr;
      // the low band
      const ll = lD.run(lC.run(lB.run(lA.run(xl)))), lr = rD.run(rC.run(rB.run(rA.run(xr))));
      a.lrL += ll * lr; a.llL += ll * ll; a.rrL += lr * lr;
      const m = (ll + lr) * 0.5, s = (ll - lr) * 0.5;
      a.mmL += m * m; a.ssL += s * s;
      // true peak: the newest sample at hist[hi] (and hi + 12), so hist[hi + j] is j samples back
      const hi = this.hi = this.hi === 0 ? 11 : this.hi - 1;
      hL[hi] = hL[hi + 12] = xl; hR[hi] = hR[hi + 12] = xr;
      for (let k = 0; k < 4; k++) {
        const ph = P[k];
        let yl = 0, yr = 0;
        for (let j = 0; j < 12; j++) { yl += ph[j] * hL[hi + j]; yr += ph[j] * hR[hi + j]; }
        if (yl < 0) yl = -yl;
        if (yr < 0) yr = -yr;
        if (yl > a.tp) a.tp = yl;
        if (yr > a.tp) a.tp = yr;
      }
      if (++this.n >= this.block) this.flush();
    }
    return true;
  }

  flush() {
    const a = this.acc, n = this.n;
    this.n = 0;
    this.acc = this.zero();
    const blk = { k: a.k / n, tp: Math.max(a.tp, a.sp), sp: a.sp, raw: a.raw, n,
      lrL: a.lrL, llL: a.llL, rrL: a.rrL, mmL: a.mmL, ssL: a.ssL, lr: a.lr, ll: a.ll, rr: a.rr };
    this.ring.push(blk);
    if (this.ring.length > RING) this.ring.shift();
    const r = this.ring, len = r.length;
    const mean = (from) => { let s = 0; for (let i = from; i < len; i++) s += r[i].k; return s / (len - from); };
    const mPow = len >= 4 ? mean(len - 4) : mean(0);
    const sPow = mean(0);
    const M = LOG(mPow), S = LOG(sPow);
    // gating blocks: the 400 ms window every 100 ms (75 % overlap)
    if (len >= 4 && M > -70) {
      const bin = Math.max(0, Math.min(HIST - 1, Math.round((M + 100) * 10)));
      this.iCount[bin] += 1; this.iPow[bin] += mPow;
    }
    if (len >= RING && S > -70) {
      const bin = Math.max(0, Math.min(HIST - 1, Math.round((S + 100) * 10)));
      this.sCount[bin] += 1;
    }
    // integrated
    let c = 0, p = 0;
    for (let b = 0; b < HIST; b++) { c += this.iCount[b]; p += this.iPow[b]; }
    let I = -120;
    if (c > 0) {
      const gate = LOG(p / c) - 10;
      const g0 = Math.max(0, Math.ceil((gate + 100) * 10));
      let c2 = 0, p2 = 0;
      for (let b = g0; b < HIST; b++) { c2 += this.iCount[b]; p2 += this.iPow[b]; }
      I = c2 > 0 ? LOG(p2 / c2) : -120;
    }
    // LRA: 10th to 95th percentile of short-term values above (ungated mean - 20 LU)
    let lra = 0;
    {
      let cs = 0, ps = 0;
      for (let b = 0; b < HIST; b++) if (this.sCount[b]) { cs += this.sCount[b]; ps += this.sCount[b] * Math.pow(10, ((b / 10 - 100) + 0.691) / 10); }
      if (cs > 0) {
        const g0 = Math.max(0, Math.ceil((LOG(ps / cs) - 20 + 100) * 10));
        let tot = 0;
        for (let b = g0; b < HIST; b++) tot += this.sCount[b];
        if (tot > 1) {
          let run = 0, lo = null, hi = null;
          for (let b = g0; b < HIST; b++) {
            run += this.sCount[b];
            if (lo === null && run >= tot * 0.1) lo = b;
            if (hi === null && run >= tot * 0.95) { hi = b; break; }
          }
          if (lo !== null && hi !== null) lra = (hi - lo) / 10;
        }
      }
    }
    // peaks
    let tp3 = 0;
    for (const b of r) if (b.tp > tp3) tp3 = b.tp;
    if (blk.tp > this.tpMax) this.tpMax = blk.tp;
    // block crest: non-overlapping 400 ms blocks
    const ca = this.crestAcc;
    ca.peak = Math.max(ca.peak, blk.sp); ca.raw += blk.raw; ca.n += n; ca.blocks += 1;
    let crest = this.lastCrest ?? null;
    if (ca.blocks >= 4) {
      const rms = Math.sqrt(ca.raw / (2 * ca.n));
      const level = DB(rms);
      if (level > -80) {
        crest = DB(ca.peak) - level;
        this.crests.push([crest, level]);
        if (this.crests.length > 75) this.crests.shift();
      }
      this.lastCrest = crest;
      this.crestAcc = { peak: 0, raw: 0, n: 0, blocks: 0 };
    }
    let crestMed = null;
    if (this.crests.length) {
      let top = -Infinity;
      for (const [, lv] of this.crests) if (lv > top) top = lv;
      const v = this.crests.filter(([, lv]) => lv > top - 20).map(([c0]) => c0).sort((x, y) => x - y);
      crestMed = v.length ? (v.length % 2 ? v[(v.length - 1) / 2] : (v[v.length / 2 - 1] + v[v.length / 2]) / 2) : null;
    }
    // stereo
    const sum = (from, key) => { let s = 0; for (let i = from; i < len; i++) s += r[i][key]; return s; };
    const corr = (from, a1, b1, c1) => { const d = Math.sqrt(sum(from, b1) * sum(from, c1)); return d > 1e-12 ? sum(from, a1) / d : null; };
    const f4 = Math.max(0, len - 4);
    const mm = sum(0, 'mmL'), ss = sum(0, 'ssL');
    this.port.postMessage({
      t: currentTime + 128 / this.fs,
      m: M, s: S, i: I, lra,
      tp: DB(tp3), tpMax: DB(this.tpMax), sp: DB(blk.sp),
      plr: I > -70 ? DB(this.tpMax) - I : null,
      psr: S > -70 ? DB(tp3) - S : null,
      crest, crestMed,
      corrLow: corr(f4, 'lrL', 'llL', 'rrL'), corrLowS: corr(0, 'lrL', 'llL', 'rrL'),
      smLow: mm > 1e-12 ? 10 * Math.log10((ss + 1e-20) / mm) : null,
      lowLevel: LOG((sum(f4, 'llL') + sum(f4, 'rrL')) / (Math.max(1, len - f4) * this.block)),
      corrFull: corr(f4, 'lr', 'll', 'rr'),
      ms: blk.k,
    });
  }
}

registerProcessor('hw002-mix-meter', MixMeter);
