// The bed: clips of any tape (a region, a slice, a resample) laid on six lanes over the stems' 24-bar loop, played
// on the engine's 16ths. Positions are in 16ths from the loop's start. Two presets lay out what the set itself has:
// its collage in these 24 bars, and its break (bars 81-96), the collage's busiest place.

import { bufferNow, soundFrom } from './sources.js';
import { saveState, state } from './state.js';
import { TAPE_BASE } from './fx.js';

export const BARS = 24;
export const LOOP = BARS * 16;
export const LANES = 6;

/** The engine's 16th -> the bed's 16th. */
export const bedPos = (step) => ((step % LOOP) + LOOP) % LOOP;

export function bedStep(C, step, when) {
  const s = bedPos(step);
  if (C.chase) { C.chase = false; chase(C, s, when); }
  for (const c of state.bed) if (c.start === s && !c.mute) playClip(C, c, when, 0);
}

function playClip(C, c, when, into = 0) {
  if (!bufferNow(C.engine, c.src)) return;
  const st = C.engine.stepSeconds;
  const rate = Math.pow(2, ((c.st ?? 0) + C.G.pitchOf(c.src)) / 12) * C.G.speed;
  const dur = (c.len - into) * st;
  const off = c.rev ? c.off : c.off + into * st * rate;
  C.players.play(c.src, {
    when: when - TAPE_BASE, off, dur, st: c.st ?? 0, rev: !!c.rev || C.tapeRev(), gain: c.gain ?? 1, tag: `bed:${c.id}`,
    attack: into ? 0.01 : 0.003, release: 0.012,
  });
}

/** Start the clips already under way (opening the collage, or the transport starting mid-loop), unless they play. */
function chase(C, s, when) {
  const playing = new Set([...C.players.live].map((v) => v.tag));
  for (const c of state.bed) {
    if (c.start < s && s < c.start + c.len && !c.mute && !playing.has(`bed:${c.id}`)) playClip(C, c, when, s - c.start);
  }
}

/** Lay `item` ({src, off, len, st, rev, gain}) on `lane` at 16th `start`. Returns the clip. */
export function place(C, item, lane, start) {
  const len = Math.max(1, Math.min(item.len ?? 16, LOOP));
  start = Math.max(0, Math.min(LOOP - 1, Math.round(start)));
  const clip = {
    id: `c${++state.clipN}`, src: item.src, lane: Math.max(0, Math.min(LANES - 1, lane)), start,
    len: Math.min(len, LOOP - start), off: item.off ?? 0, st: item.st ?? 0, rev: !!item.rev, gain: item.gain ?? 1,
  };
  state.bed.push(clip);
  saveState();
  C.ev.emit('bed');
  return clip;
}

export function remove(C, clip) {
  state.bed = state.bed.filter((c) => c !== clip);
  C.players?.stopTag(`bed:${clip.id}`);
  saveState();
  C.ev.emit('bed');
}

/** A lane with room for [start, start + len), or -1. */
export function freeLane(start, len, prefer = 0) {
  for (let k = 0; k < LANES; k++) {
    const lane = (prefer + k) % LANES;
    if (!state.bed.some((c) => c.lane === lane && c.start < start + len && start < c.start + c.len)) return lane;
  }
  return -1;
}

function remember() { state.bedPrev = state.bed.map((c) => ({ ...c })); }

export function undoBed(C) {
  if (!state.bedPrev) return false;
  const now = state.bed;
  state.bed = state.bedPrev;
  state.bedPrev = now;
  C.players?.stopAll();
  saveState();
  C.ev.emit('bed');
  return true;
}

export function clearBed(C) {
  remember();
  state.bed = [];
  C.players?.stopAll();
  saveState();
  C.ev.emit('bed');
}

/** The set's own collage clips between bar `from` and `from + 24`, as bed clips (lane per track). */
export function setClips(C, from, to, { tracks: want } = {}) {
  const m = C.engine.manifest;
  if (!m) return [];
  const sources = new Map(C.sources.map((s) => [s.id, s]));
  const out = [];
  const lanes = new Map();
  for (const t of m.tracks ?? []) {
    if (want && !want.test(t.group ?? '')) continue;
    for (const [a, b, id] of t.clips ?? []) {
      if (!id || !String(id).startsWith('src-') || b <= from || a >= to) continue;
      const src = sources.get(id);
      if (!src || src.tag === 'KICK GRP') continue;
      if (!lanes.has(t.name)) lanes.set(t.name, lanes.size);
      const use = src.uses.find((u) => Math.abs(u.bar - a) < 0.01) ?? src.uses[0];
      const a2 = Math.max(a, from), b2 = Math.min(b, to);
      const into = (a2 - a) * C.engine.barSeconds;
      const buf = bufferNow(C.engine, id);
      const off = use?.off ?? 0;
      out.push({
        src: id, lane: lanes.get(t.name), start: Math.round((a2 - from) * 16), len: Math.max(1, Math.round((b2 - a2) * 16)),
        off: (buf ? soundFrom(buf, off) : off) + into, st: 0, rev: false, gain: 1, track: t.name,
      });
    }
  }
  return out;
}

export function preset(C, which) {
  const clips = which === 'break'
    ? setClips(C, 80, 96, { tracks: /break/i })
    : setClips(C, 0, BARS, { tracks: /sfx|perc/i });
  if (!clips.length) return 0;
  remember();
  C.players?.stopAll();
  state.bed = clips.map((c) => ({ ...c, id: `c${++state.clipN}`, lane: Math.min(LANES - 1, c.lane) }));
  saveState();
  C.chase = true;
  C.ev.emit('bed');
  return clips.length;
}

/** The set's clips in the bed's 24 bars, for the faint reference lane. */
export function ghosts(C) { return setClips(C, 0, BARS, { tracks: /sfx|perc|break/i }); }
