// The arranger: arr.* -> the engine's sequence (engine.stems.setSequence), bars copied whole from the stems on the
// 160 BPM grid, plus the lanes (lanes.js) for what the stems cannot hold. It also says how loud each bar of the
// Short is, from the offline bar library (data/arrange-bars.json), for the energy curve.
//
// Which source bars (0-based, of the lab's 24-bar stems = the song's bars 121-144):
//   kick   scooped: 0, 1 (the song's 121-122, its 126 Hz low cut on), alternating; full: 8-23 by phrase
//   sfx    the ARC RAIDERS hit: 8, 9; the chord loop: 16-23 (its 8-bar cycle starts on 16), on the chord lane
//   perc   with the canonical Short's stems in the manifest (`shape`, batch 4.3 track 1): its own bars of each layer
//          set, A 0-3, AB 6-7, ABC 8-11, ABCD 13-19, and its real long splash (bars 4-5, into AB) and short splash
//          (bar 12, over ABCD) where a splash lands on that layer set at that length; played by the lanes.
//          Layer sets the canonical Short has no bar of (A+C, B alone...) are a masked bar (hats.js).
//          Without `shape` (a stand-in build): the lab's perc stem, all four layers on 8-23, fewer layers masked.

import { plan as makePlan, readValues, BAR_S } from './model.js';

const full = (i) => 8 + (i % 16);
const SONG_BREAK0 = 80;

/** The song's break bar (0-based) for bar k of a break `len` bars long: its last `len` bars, into the kick. */
export function breakBar(k, len) {
  return SONG_BREAK0 + (((16 - (len % 16)) % 16) + k) % 16;
}

/** The canonical Short's perc bars for a layer set (null: it has none), from the bar library. */
function shapeBars(data, set) {
  return data.shape?.states?.[set]?.bars ?? null;
}

/**
 * One sequence entry per bar of a plan. `shape`: use the canonical Short's perc bars (the manifest has them).
 * Each entry: {kick, perc, sfx} (stem bars or -1) and `x` for the lanes: hats (a masked set), shape (a canonical
 * perc bar), chord, brk, splash (the shaped sample), realSplash (the canonical bar carries it), wuh, part.
 */
export function toSequence(pl, { shape = false, data = null } = {}) {
  const songStyle = (pl.values.breakStyle ?? 0) < 0.5;
  const bars = pl.bars;
  const real = new Map();                       // bar -> canonical perc bar holding a real splash
  if (shape && data?.shape) {
    const sp = data.shape.splash ?? { long: [4, 5], short: [12] };
    const clean = (b) => b && !b.gap && !b.brk && !b.splash;
    for (const b of bars) {
      if (!b.splash || b.gap) continue;
      if (b.splash.long && b.splash.beats === 8 && b.hats === 'AB' && bars[b.i + 1]?.hats === 'AB' && clean(bars[b.i + 1])) {
        real.set(b.i, sp.long[0]); real.set(b.i + 1, sp.long[1]);
      } else if (!b.splash.long && b.splash.beats === 3 && b.hats === 'ABCD') real.set(b.i, sp.short[0]);
    }
  }
  return bars.map((b) => {
    const kick = b.kick === 'scoop' ? b.i % 2 : b.kick === 'full' ? full(b.i) : -1;
    let perc = -1, hats = null, shapeBar = null;
    const own = shape ? shapeBars(data, b.hats) : null;
    if (real.has(b.i)) shapeBar = real.get(b.i);
    else if (own) {
      // the canonical bar at the same place when it holds this set (so the set's Short is batch 4.3 track 1, bar
      // for bar), else its bars of this set in turn from where the run of this set began
      let run = b.i;
      while (run > 0 && bars[run - 1].hats === b.hats && !bars[run - 1].brk) run--;
      shapeBar = own.includes(b.i) ? b.i : own[(b.i - run) % own.length];
    }
    else if (b.hats === 'ABCD') perc = full(b.i);
    else if (b.hats) hats = b.hats;
    const sfx = b.arc === 0 ? 8 : b.arc === 1 ? 9 : -1;
    const brk = b.brk && songStyle ? breakBar(b.brk.k, b.brk.len) : null;
    const splash = real.has(b.i) ? null : b.splash;
    const x = { i: b.i, hats, shape: shapeBar, chord: b.chord, brk, splash, realSplash: real.has(b.i), wuh: b.wuh, part: null };
    if (b.gap) {
      if (b.gap.from > 0) x.part = { kick, perc, sfx, hats, shape: shapeBar, chord: b.chord, brk, until: b.gap.from };
      x.hats = null; x.shape = null; x.chord = null; x.brk = null;
      return { kick: -1, perc: -1, sfx: -1, x };
    }
    return { kick, perc, sfx, x };
  });
}

/** How loud a hat layer set is ({lufs, hi}): the canonical Short's own bars, or the masked bar. */
export function hatLevel(data, set, shape) {
  if (!set) return { lufs: -70, hi: -60 };
  const own = shape ? data.shape?.states?.[set] : null;
  if (own) return own;
  const table = shape && data.hats.shape_subsets ? data.hats.shape_subsets : data.hats.subsets;
  return table[set] ?? { lufs: -70, hi: -60 };
}

export const COUNT_IN = { kick: -1, perc: -1, sfx: -1, x: { countIn: true } };

/** The sequence for stems shorter than the bar library's 24 bars (a stand-in build): source bars wrap. */
export function fitBars(seq, bars) {
  if (!(bars > 0) || bars >= 24) return seq;
  const w = (n) => (n >= 0 ? n % bars : n);
  const chord = (x) => (x?.chord != null ? (16 + x.chord) % bars : undefined);
  return seq.map((e) => ({
    kick: w(e.kick), perc: w(e.perc), sfx: w(e.sfx),
    x: e.x && {
      ...e.x, chordBar: chord(e.x),
      part: e.x.part && { ...e.x.part, kick: w(e.x.part.kick), perc: w(e.x.part.perc), sfx: w(e.x.part.sfx), chordBar: chord(e.x.part) },
    },
  }));
}

/** Bars from several sequences in turn, `every` bars each (Anthony's A/B inside one track). */
export function interleave(seqs, every = 2) {
  const n = Math.max(...seqs.map((s) => s.length));
  const out = [], which = [];
  for (let i = 0; i < n; i++) {
    const v = Math.floor(i / every) % seqs.length;
    const s = seqs[v];
    const e = s[i % s.length];
    out.push({ ...e, x: { ...e.x, variant: v } });
    which.push(v);
  }
  return { seq: out, which };
}

/** How loud each bar is (LUFS, from the bar library), and what makes it up. */
export function energy(pl, data, levels = {}, { shape = false } = {}) {
  const P = (lufs) => Math.pow(10, lufs / 10);
  const st = data.stems, song = data.song;
  const dl = { splash: 0, break: 0, chord: 0, ...levels };
  const seq = toSequence(pl, { shape, data });
  const splashAdd = new Float64Array(pl.L);
  seq.forEach((e, i) => {
    const sp = e.x.splash ?? e.x.part?.splash;
    if (!sp) return;
    const beats = data.splash.beat_lufs;
    for (let j = 0; j < sp.beats; j++) {
      const bar = i + Math.floor(j / 4);
      if (bar >= pl.L) break;
      splashAdd[bar] += P((beats[j] ?? -70) + dl.splash) / 4;
    }
  });
  const wuhAdd = new Float64Array(pl.L);
  for (const b of pl.bars) {
    if (!b.wuh) continue;
    const beats = song.pre_kick_beats_lufs;
    for (let j = 0; j < b.wuh.beats; j++) {
      const at = b.wuh.at + j;
      const bar = b.i + Math.floor(at / 4);
      if (bar >= pl.L) break;
      wuhAdd[bar] += P((beats[8 - b.wuh.beats + j] ?? -30) + dl.break) / 4;
    }
  }
  return seq.map((e, i) => {
    const parts = { kick: 0, perc: 0, sfx: 0, chord: 0, splash: splashAdd[i], brk: 0, wuh: wuhAdd[i] };
    const add = (x, scale) => {
      if (x.kick >= 0) parts.kick += P(st.kick[x.kick].lufs) * scale;
      if (x.perc >= 0) parts.perc += P(st.perc[x.perc].lufs) * scale;
      if (x.hats) parts.perc += P(hatLevel(data, x.hats, shape).lufs) * scale;
      if (x.shape != null) parts.perc += P(data.shape.perc[x.shape].lufs) * scale;
      if (x.sfx >= 0) parts.sfx += P(st.sfx[x.sfx].lufs) * scale;
      if (x.chord != null) parts.chord += P(st.sfx[16 + x.chord].lufs + dl.chord) * scale;
      if (x.brk != null && song.lufs[x.brk] != null) parts.brk += P(song.lufs[x.brk] + dl.break) * scale;
    };
    add({ ...e, hats: e.x.hats, shape: e.x.shape, chord: e.x.chord, brk: e.x.brk }, 1);
    if (e.x.part) add(e.x.part, e.x.part.until / 4);
    const sum = Object.values(parts).reduce((a, b) => a + b, 0);
    return { lufs: sum > 0 ? 10 * Math.log10(sum) : -70, parts };
  });
}

/**
 * The arranger on a surface: keeps the engine's sequence equal to the plan (with the count-in and the loop),
 * schedules the lanes on every bar, and tells the views when the plan changes.
 */
export class Arranger {
  constructor(ctx, data, lanes) {
    this.ctx = ctx;
    this.e = ctx.engine;
    this.store = ctx.store;
    this.data = data;
    this.lanes = lanes;
    this.loop = true;
    this.countIn = false;
    this.offset = 0;               // the absolute bar where index 0 of the Short plays (mod length)
    this.rotated = false;          // the sequence is in its playing form (rotated by offset)
    this.abc = null;               // {plans: [p, p, p], seqs, which, hold: -1|0..2, axis}
    this.fns = new Set();
    this.pl = null;
    this.seq = [];
    this.applied = null;
    this._queued = false;
    this.mode = 'short';           // 'short' | 'song' (the whole-song map plays) | 'audition' (the bar library)
  }

  onChange(fn) { this.fns.add(fn); return () => this.fns.delete(fn); }

  /** The canonical Short's stems are in the manifest (before it loads: the bar library says they exist). */
  get useShape() {
    const m = this.e.manifest;
    return m ? !!m.shape?.some((x) => x.id === 'shape-perc') : !!this.data.shape;
  }

  /** The energy of a plan, as this arranger would play it. */
  energy(pl, levels) { return energy(pl, this.data, levels, { shape: this.useShape }); }

  /** The plan from the store now (or from a snapshot). */
  plan(snap = null) { return makePlan(readValues(this.store, snap)); }

  /** Recompute (coalesced): call from sketches and store listeners. */
  invalidate() {
    if (this._queued) return;
    this._queued = true;
    queueMicrotask(() => { this._queued = false; this.recompute(); });
  }

  recompute() {
    this.pl = this.plan();
    const opts = { shape: this.useShape, data: this.data };
    this.base = toSequence(this.pl, opts);
    if (this.abc) {
      this.abc.plans = this.abc.make();
      this.abc.seqs = this.abc.plans.map((p) => toSequence(p, opts));
      const { seq, which } = this.abc.hold >= 0 ? { seq: this.abc.seqs[this.abc.hold], which: null } : interleave(this.abc.seqs, 2);
      this.seq = seq; this.abc.which = which;
    } else this.seq = this.base;
    this.apply();
    const wantFull = this.seq.some((x) => x.x?.wuh || x.x?.brk != null || x.x?.part?.brk != null);
    if (wantFull && this.e.ctx) this.lanes.loadFull();
    for (const fn of this.fns) fn(this.pl);
  }

  /** The sequence the engine should hold now. */
  form() {
    const s = this.seq;
    if (!s.length) return s;
    const playing = this.e.playing;
    if (this.countIn && !(playing && this.rotated)) return [COUNT_IN, ...s];
    if (this.offset % s.length === 0) return s;
    const L = s.length, off = this.offset;
    return s.map((_, j) => s[(((j - off) % L) + L) % L]);
  }

  apply() {
    if (!this.e.manifest || this.mode !== 'short') return;
    const seq = fitBars(this.form(), this.e.stems.bars);
    this.applied = seq;
    this.e.stems.loop = this.loop;
    this.e.stems.setSequence(seq);
  }

  /** Called from the engine's bar clock (after the stems for `bar` were scheduled). */
  bar(bar, when) {
    const e = this.e;
    if (this.mode !== 'short' || !e.stems.enabled || e.stems.useMix) return;
    if (this.e.stems.sequence !== this.applied) return;
    const seq = this.applied;
    if (!seq.length) return;
    if (!e.stems.loop && bar >= seq.length) {
      if (bar === seq.length) {
        const ms = Math.max(0, (when - e.ctx.currentTime) * 1000);
        clearTimeout(this._end);
        this._end = setTimeout(() => { if (e.playing) e.stop(); }, ms + 20);
      }
      return;
    }
    this.lanes.schedule(seq[bar % seq.length], when);
    // after the count-in bar, a looping Short turns to its playing form: index 0 at absolute bar 1
    if (this.countIn && this.loop && !this.rotated && bar >= 0 && seq[0]?.x?.countIn) {
      this.rotated = true;
      this.offset = 1;
      this.apply();
    }
  }

  /** Back to the resting form (the transport stopped). */
  stopped() {
    clearTimeout(this._end);
    this.rotated = false;
    this.offset = 0;
    this.apply();
  }

  /** Where the Short is now: {i (bar index in the Short, or -1 in the count-in), t (s into it), L, variant}. */
  where() {
    const p = this.e.position();
    const L = this.seq.length;
    if (!p.playing || !L || this.mode !== 'short') return null;
    const off = this.rotated ? this.offset : this.countIn ? 1 : 0;
    let t = p.t - off;
    if (t < 0) return { i: -1, t, L, count: Math.floor(p.phase * 4) + 1 };
    if (this.loop) t = ((t % L) + L) % L;
    else if (t >= L) return { i: L, t: L, L, done: true };
    const i = Math.floor(t);
    const variant = this.abc?.which ? this.abc.which[i] : (this.abc ? this.abc.hold : null);
    return { i, t, L, variant };
  }

  /** What this build of the lab's audio lacks, in words (a stand-in manifest has no whole song, fewer bars...). */
  missing() {
    const m = this.e.manifest;
    if (!m) return [];
    const out = [];
    if (!m.full) out.push('No whole song in this build: the song\'s break, the "wuh" and the map\'s playback stay silent.');
    const bars = this.e.stems.bars;
    if (bars > 0 && bars < 24) out.push(`The stems hold ${bars} bars, not 24: the Short reuses them in turn.`);
    if (!this.useShape) out.push('No canonical Short stems in this build: every hat layer set is a masked sketch.');
    if (!this.lanes.hasSource(this.data.splash.src)) out.push('No splash sample (src-2) in this build: the splashes stay silent.');
    if (!m.tracks?.length) out.push('No arrangement in the manifest: the whole song\'s map has no tracks.');
    return out;
  }

  /** Seconds of the Short (the variant or plan now). */
  get seconds() { return this.seq.length * BAR_S; }
}
