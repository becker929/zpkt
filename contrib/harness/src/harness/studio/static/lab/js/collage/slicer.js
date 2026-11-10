// The slicer: a region of the selected tape (from its cue, half a bar to 8 bars long) cut into 16 slices, equal
// or at the onsets, played from 16 pads or a 16-step pattern on the engine's 16ths.

import { bufferNow, equalCuts, onsets } from './sources.js';
import { saveState, state } from './state.js';
import { TAPE_BASE } from './fx.js';

export const REGION_BARS = [0.5, 1, 2, 4, 8];
const CUTS = new Map();

/** The region being sliced: {start, len} seconds in the source. At the clip's own transpose (ARC is +9 st in the
 *  set) the region still lasts its bars when played, so the slices in order are the region in time. */
export function regionOf(C, id = state.sel) {
  const bars = REGION_BARS[C.store.real('col.slice.bars')] ?? 1;
  const rate = C.G ? Math.pow(2, C.G.pitchOf(id) / 12) : 1;
  const want = bars * (C.engine.barSeconds || 1.5) * rate;
  const buf = bufferNow(C.engine, id);
  const dur = buf?.duration ?? C.src(id)?.seconds ?? want;
  const len = Math.min(want, dur);
  const cue = C.cue(id);
  return { start: Math.max(0, Math.min(dur - len, cue)), len, bars, dur };
}

/** The 16 cut points (seconds) of the region. */
export function cutsOf(C, id = state.sel) {
  const r = regionOf(C, id);
  const mode = C.store.real('col.slice.mode');
  const seed = C.dice ?? 0;
  const key = `${id}|${r.start.toFixed(4)}|${r.len}|${mode}|${seed}`;
  if (CUTS.has(key)) return CUTS.get(key);
  const buf = bufferNow(C.engine, id);
  let cuts;
  if (!buf) cuts = equalCuts(r.start, r.start + r.len);
  else if (mode === 1) cuts = onsets(buf, r.start, r.start + r.len, 16, { jitter: seed ? 2.5 : 0 });
  else if (seed) {
    // the dice on equal cuts: 16 cuts on the 32nd grid, never two on one point
    const grid = Array.from({ length: 31 }, (_, i) => i + 1).sort(() => Math.random() - 0.5).slice(0, 15).sort((a, b) => a - b);
    cuts = [r.start, ...grid.map((g) => r.start + (r.len * g) / 32)];
  } else cuts = equalCuts(r.start, r.start + r.len);
  CUTS.set(key, cuts);
  if (CUTS.size > 48) CUTS.delete(CUTS.keys().next().value);
  return cuts;
}

export function sliceOf(C, i, id = state.sel) {
  const cuts = cutsOf(C, id);
  const r = regionOf(C, id);
  return { a: cuts[i], b: i + 1 < cuts.length ? cuts[i + 1] : r.start + r.len };
}

/** Play slice i at `when` (audio clock, already early by the tape's gap), velocity 0..1. */
export function playSlice(C, i, when, vel = 1, id = state.sel) {
  if (!C.ready) return null;
  const { a, b } = sliceOf(C, i, id);
  const st = C.store.real('col.slice.pitch');
  const rate = Math.pow(2, (st + C.G.pitchOf(id)) / 12) * C.G.speed;
  const decay = C.store.real('col.slice.decay') / 1000;
  const dur = Math.max(0.02, Math.min((b - a) / rate, decay));
  const rev = C.store.real('col.slice.rev') === 1 || C.tapeRev();
  if (C.store.real('col.slice.choke') === 1) C.players.choke('slice', when);
  const v = C.players.play(id, { when, off: a, dur, st, rev, gain: 0.25 + 0.85 * vel, tag: 'slice', release: Math.min(0.05, dur / 3) });
  C.ev.emit('pad', i, when, vel);
  return v;
}

/** The pattern, on the engine's 16ths. */
export function seqStep(C, step, when) {
  if (!state.seq) return;
  const i = step % 16;
  const s = state.pattern[i];
  C.ev.emit('step', i, when);
  if (s == null || s < 0) return;
  const swing = C.store.real('col.slice.swing') / 100;
  const t = when - TAPE_BASE + (i % 2 ? swing * C.engine.stepSeconds * 0.66 : 0);
  playSlice(C, s, t, state.vel[i] ?? 0.9);
}

/** Record a pad hit into the nearest step (while the pattern runs with REC on). */
export function recordHit(C, pad, vel) {
  const p = C.engine.position();
  if (!p.playing || !state.seq || !state.rec) return -1;
  const i = Math.round(p.phase * 16) % 16;
  state.pattern[i] = pad;
  state.vel[i] = vel;
  saveState();
  C.ev.emit('pattern');
  return i;
}

/** The dice: new cut points, and the pattern re-dealt (the downbeat keeps slice 1). */
export function dice(C) {
  C.dice = (C.dice ?? 0) + 1;
  const pat = state.pattern;
  for (let i = 0; i < 16; i++) {
    if (i === 0) { pat[i] = 0; continue; }
    const r = Math.random();
    if (r < 0.22) pat[i] = -1;
    else if (r < 0.55) pat[i] = i;
    else pat[i] = Math.max(0, Math.min(15, i + Math.round((Math.random() * 2 - 1) * 5)));
    state.vel[i] = i % 4 === 0 ? 1 : i % 2 ? 0.6 + Math.random() * 0.3 : 0.85;
  }
  saveState();
  C.ev.emit('slices');
  C.ev.emit('pattern');
}

export function straight(C) {
  state.pattern = Array.from({ length: 16 }, (_, i) => i);
  state.vel = Array(16).fill(0.9);
  C.dice = 0;
  saveState();
  C.ev.emit('slices');
  C.ev.emit('pattern');
}
