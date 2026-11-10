// The collage's tapes: the set's eight source clips (from the manifest) and the resamples made here. Each has an
// id, a name, the bus it plays through, and where the set uses it. Buffers come from the engine (decoded once)
// or from memory (resamples). Also: waveform peaks, onsets for the slicer, and reversed pieces for backwards play.

import { metaFor, RS_COLOR } from './meta.js';
import { state } from './state.js';

/** Every tape on the shelf, in shelf order. */
export function sourceList(engine) {
  const m = engine.manifest;
  const bar = engine.barSeconds || 1.5;
  const list = (m?.clips ?? []).map((c, i) => {
    const meta = metaFor(c);
    // uses: [start bar, end bar, start s, end s] in the file as served (lab_audio.py reads them through the warp markers)
    const uses = (c.uses ?? []).map(([a, b, s0 = 0, s1]) => ({ bar: a, bars: b - a, off: s0, len: s1 != null ? s1 - s0 : (b - a) * bar }))
      .filter((u) => u.off < (c.seconds || Infinity));
    return {
      id: c.id, kind: 'clip', n: i + 1, name: meta.name, long: meta.long, tag: meta.tag, color: meta.color,
      track: c.track, group: c.group, brk: /break/i.test(c.group ?? ''), seconds: c.seconds, uses, bus: `col-${c.id}`,
    };
  });
  for (const r of state.rs) {
    list.push({
      id: r.id, kind: 'rs', n: list.length + 1, name: r.name, long: `${r.bars} ${r.bars === 1 ? 'bar' : 'bars'} resampled ${r.made}`,
      tag: 'RESAMPLE', color: RS_COLOR, track: '11-Audio', group: 'SFX group', brk: false, seconds: r.buffer.duration,
      uses: [], bus: 'col-rs',
    });
  }
  return list;
}

export function findSource(engine, id) { return sourceList(engine).find((s) => s.id === id) ?? null; }

/** A tape's uses as merged [start, end] seconds (overlapping uses drawn once). */
export function useSpans(src) {
  const xs = (src?.uses ?? []).map((u) => [u.off, u.off + u.len]).sort((a, b) => a[0] - b[0]);
  const out = [];
  for (const [a, b] of xs) { const last = out.at(-1); if (last && a <= last[1]) last[1] = Math.max(last[1], b); else out.push([a, b]); }
  return out;
}

/** The decoded buffer now, or null (not loaded yet). */
export function bufferNow(engine, id) {
  if (String(id).startsWith('rs-')) return state.rs.find((r) => r.id === id)?.buffer ?? null;
  return engine.buffers.get(id) ?? null;
}

export async function loadBuffer(engine, id) {
  if (String(id).startsWith('rs-')) return bufferNow(engine, id);
  return engine.buffer(id);
}

/** Where a source starts when it is first picked: the set's first use of it. */
export function defaultCue(src) { return src?.uses?.[0]?.off ?? 0; }

/**
 * `t`, or the first sound after it when `t` sits in silence (a cue the set starts on a quiet pickup, or a margin
 * lab_audio.py kept around the part the set plays), so a cue always lands on sound.
 */
export function soundFrom(buf, t) {
  const P = peaksNow(buf);
  if (!P) return t;
  const b0 = Math.max(0, Math.floor((t * P.rate) / P.hop));
  const look = Math.ceil((0.5 * P.rate) / P.hop);
  let quiet = true;
  for (let b = b0; b < Math.min(P.n, b0 + look); b++) if (Math.max(P.mx[b], -P.mn[b]) > P.peak * 0.03) { quiet = false; break; }
  if (!quiet) return t;
  for (let b = b0; b < P.n; b++) if (Math.max(P.mx[b], -P.mn[b]) > P.peak * 0.06) return Math.max(0, (b * P.hop) / P.rate - 0.01);
  return t;
}

// --- peaks ------------------------------------------------------------------------------------------------------
const PEAKS = new WeakMap();
const HOP = 128;

/** min/max per 128 frames, both channels summed. Built in slices so a 150 s source does not stall a frame. */
export async function buildPeaks(buf) {
  if (PEAKS.has(buf)) return PEAKS.get(buf);
  const n = Math.ceil(buf.length / HOP);
  const mn = new Float32Array(n), mx = new Float32Array(n);
  const L = buf.getChannelData(0), R = buf.numberOfChannels > 1 ? buf.getChannelData(1) : L;
  const CHUNK = 4096;                          // bins per slice (~0.5 M samples)
  let peak = 1e-4;
  for (let i0 = 0; i0 < n; i0 += CHUNK) {
    const i1 = Math.min(n, i0 + CHUNK);
    for (let i = i0; i < i1; i++) {
      let lo = 0, hi = 0;
      const a = i * HOP, b = Math.min(a + HOP, L.length);
      for (let j = a; j < b; j++) { const x = (L[j] + R[j]) * 0.5; if (x < lo) lo = x; else if (x > hi) hi = x; }
      mn[i] = lo; mx[i] = hi;
      if (hi > peak) peak = hi;
      if (-lo > peak) peak = -lo;
    }
    if (i1 < n) await new Promise((r) => setTimeout(r, 0));
  }
  const t = { hop: HOP, rate: buf.sampleRate, mn, mx, n, peak };
  PEAKS.set(buf, t);
  return t;
}

export const peaksNow = (buf) => (buf ? PEAKS.get(buf) ?? null : null);

/**
 * Draw [t0, t1] seconds of a buffer's peaks into a canvas rect as a mirrored wave. opts: color, glow, gain
 * (normalise), alpha.
 */
export function drawWave(g, buf, t0, t1, x, y, w, h, { color = '#e0b7ff', gain = 1, alpha = 1, local = false } = {}) {
  const P = peaksNow(buf);
  if (!P || w < 2 || t1 <= t0) return;
  const mid = y + h / 2;
  const cols = Math.floor(w);
  const binsPerPx = ((t1 - t0) * P.rate / P.hop) / w;
  const lo = new Float32Array(cols + 1), hi = new Float32Array(cols + 1);
  if (binsPerPx >= 1) {
    for (let c = 0; c <= cols; c++) {
      const b0 = Math.floor((t0 * P.rate) / P.hop + c * binsPerPx);
      const b1 = Math.max(b0 + 1, Math.floor((t0 * P.rate) / P.hop + (c + 1) * binsPerPx));
      let a = 0, z = 0;
      for (let b = Math.max(0, b0); b < Math.min(P.n, b1); b++) { if (P.mn[b] < a) a = P.mn[b]; if (P.mx[b] > z) z = P.mx[b]; }
      lo[c] = a; hi[c] = z;
    }
  } else {
    // zoomed in past the peak table: read the samples
    const L = buf.getChannelData(0), R = buf.numberOfChannels > 1 ? buf.getChannelData(1) : L;
    const spp = ((t1 - t0) * buf.sampleRate) / w;
    for (let c = 0; c <= cols; c++) {
      const s0 = Math.floor(t0 * buf.sampleRate + c * spp), s1 = Math.max(s0 + 1, Math.floor(t0 * buf.sampleRate + (c + 1) * spp));
      let a = 0, z = 0;
      for (let j = Math.max(0, s0); j < Math.min(L.length, s1); j++) { const v = (L[j] + R[j]) * 0.5; if (v < a) a = v; if (v > z) z = v; }
      lo[c] = a; hi[c] = z;
    }
  }
  let peak = P.peak;
  if (local) { peak = 1e-4; for (let c = 0; c <= cols; c++) peak = Math.max(peak, hi[c], -lo[c]); peak = Math.max(peak, P.peak * 0.05); }
  const k = gain / peak;
  g.save();
  g.globalAlpha = alpha;
  g.fillStyle = color;
  g.beginPath();
  g.moveTo(x, mid - Math.min(1, hi[0] * k) * h / 2);
  for (let c = 1; c <= cols; c++) g.lineTo(x + c, mid - Math.min(1, hi[c] * k) * h / 2);
  for (let c = cols; c >= 0; c--) g.lineTo(x + c, mid - Math.max(-1, lo[c] * k) * h / 2);
  g.closePath();
  g.fill();
  g.restore();
}

/** The loudest sample (both channels summed) in [t0, t1), from the peak table. */
export function peakIn(buf, t0, t1) {
  const P = peaksNow(buf);
  if (!P) return 1;
  let pk = 1e-4;
  for (let b = Math.max(0, Math.floor((t0 * P.rate) / P.hop)); b < Math.min(P.n, Math.ceil((t1 * P.rate) / P.hop)); b++) pk = Math.max(pk, P.mx[b], -P.mn[b]);
  return pk;
}

// --- onsets -----------------------------------------------------------------------------------------------------
/** `count` cut points in [t0, t1) where the sound jumps (energy rise), always starting at t0, sorted. */
export function onsets(buf, t0, t1, count = 16, { jitter = 0 } = {}) {
  const sr = buf.sampleRate, hop = 256;
  const a = Math.max(0, Math.floor(t0 * sr)), b = Math.min(buf.length, Math.floor(t1 * sr));
  const L = buf.getChannelData(0), R = buf.numberOfChannels > 1 ? buf.getChannelData(1) : L;
  const frames = Math.floor((b - a) / hop);
  if (frames < count * 2) return equalCuts(t0, t1, count);
  const env = new Float32Array(frames);
  for (let f = 0; f < frames; f++) {
    let s = 0;
    const j0 = a + f * hop;
    for (let j = j0; j < j0 + hop; j++) { const x = L[j] + R[j]; s += x * x; }
    env[f] = Math.log10(1e-7 + s / hop);
  }
  const flux = new Float32Array(frames);
  for (let f = 1; f < frames; f++) flux[f] = Math.max(0, env[f] - env[f - 1]) * (1 + (jitter ? Math.random() * jitter : 0));
  const minGap = Math.max(2, Math.floor(frames / (count * 3)));
  const cand = [];
  for (let f = 1; f < frames - 1; f++) if (flux[f] > 0 && flux[f] >= flux[f - 1] && flux[f] >= flux[f + 1]) cand.push(f);
  cand.sort((x, y) => flux[y] - flux[x]);
  const picked = [0];
  for (const f of cand) {
    if (picked.length >= count) break;
    if (picked.every((p) => Math.abs(p - f) >= minGap)) picked.push(f);
  }
  const cuts = picked.map((f) => t0 + (f * hop) / sr).sort((x, y) => x - y);
  // too few onsets: fill the longest gaps
  while (cuts.length < count) {
    let gi = 0, gl = -1;
    for (let i = 0; i < cuts.length; i++) { const e = i + 1 < cuts.length ? cuts[i + 1] : t1; if (e - cuts[i] > gl) { gl = e - cuts[i]; gi = i; } }
    cuts.splice(gi + 1, 0, cuts[gi] + gl / 2);
  }
  return cuts;
}

export function equalCuts(t0, t1, count = 16) { return Array.from({ length: count }, (_, i) => t0 + (t1 - t0) * i / count); }

// --- backwards ----------------------------------------------------------------------------------------------------
const REV = new WeakMap();           // buffer -> Map(key -> reversed piece), for pieces of half a second and more

/** A buffer holding [start, start + dur) of `buf`, reversed. Grains get a fresh one; longer pieces are kept. */
export function reversedPiece(ctx, buf, start, dur) {
  const sr = buf.sampleRate;
  const a = Math.max(0, Math.floor(start * sr)), b = Math.min(buf.length, Math.ceil((start + dur) * sr));
  const n = b - a;
  if (n < 2) return null;
  if (dur >= 0.5) {
    if (!REV.has(buf)) REV.set(buf, new Map());
    const m = REV.get(buf), key = `${a}|${n}`;
    if (m.has(key)) return m.get(key);
    const out = reverse(ctx, buf, a, b);
    m.set(key, out);
    if (m.size > 6) m.delete(m.keys().next().value);
    return out;
  }
  return reverse(ctx, buf, a, b);
}

function reverse(ctx, buf, a, b) {
  const n = b - a, sr = buf.sampleRate;
  const out = ctx.createBuffer(buf.numberOfChannels, n, sr);
  for (let c = 0; c < buf.numberOfChannels; c++) {
    const src = buf.getChannelData(c), dst = out.getChannelData(c);
    for (let i = 0; i < n; i++) dst[i] = src[b - 1 - i];
  }
  return out;
}
