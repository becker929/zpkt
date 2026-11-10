// FOUND: a random but musical found sound. A tape, a place in it where something starts, a pitch from a short list
// that sits with the track (unison, octaves, fourths and fifths down), a length on the grid; it lands on the bed at a
// bar that suits it (a fill before a four-bar line, or a downbeat) and plays from the next bar.

import { toast } from '../ui.js';
import { bufferNow, onsets } from './sources.js';
import { freeLane, LOOP, place } from './bed.js';
import { clock, lenText } from './meta.js';

const pick = (xs) => xs[Math.floor(Math.random() * xs.length)];

export function found(C) {
  if (!C.ready) { toast('Start the engine first'); return null; }
  const ready = C.sources.filter((s) => bufferNow(C.engine, s.id));
  if (!ready.length) { toast('The tapes are still loading'); return null; }
  const weights = ready.map((s) => (s.kind === 'rs' ? 1.6 : s.tag === 'KICK GRP' ? 0.4 : 1));
  let r = Math.random() * weights.reduce((a, b) => a + b, 0), src = ready[0];
  for (let i = 0; i < ready.length; i++) { r -= weights[i]; if (r <= 0) { src = ready[i]; break; } }
  const buf = bufferNow(C.engine, src.id);
  const len = pick([4, 8, 8, 8, 16, 16, 32]);
  const span = (len * C.engine.stepSeconds);
  const t0 = Math.random() * Math.max(0, buf.duration - span - 3);
  const cuts = onsets(buf, t0, Math.min(buf.duration, t0 + 3), 4);
  const off = Math.min(buf.duration - span, cuts[1] ?? cuts[0] ?? t0);
  const st = pick([0, 0, 0, 0, -12, -12, -5, -7, 7, 12, -24]);
  const rev = Math.random() < 0.16;
  const item = { src: src.id, off: Math.max(0, off), len, st, rev };
  // where it lands: short ones fill the last beat(s) before a 4-bar line, long ones sit on a downbeat
  const bars = len >= 16 ? [0, 4, 8, 12, 16, 20] : [3, 7, 11, 15, 19, 23];
  const order = bars.sort(() => Math.random() - 0.5);
  let clip = null;
  for (const bar of order) {
    const start = len >= 16 ? bar * 16 : bar * 16 + 16 - len;
    if (start + len > LOOP) continue;
    const lane = freeLane(start, len, Math.floor(Math.random() * 6));
    if (lane >= 0) { clip = place(C, item, lane, start); break; }
  }
  if (!clip) clip = place(C, item, Math.floor(Math.random() * 6), order[0] * 16);
  C.setLoaded(item);
  C.auditionItem(item);
  const where = `bar ${Math.floor(clip.start / 16) + 1}`;
  toast(`Found: ${src.name} ${clock(item.off)}${st ? `, ${st > 0 ? '+' : ''}${st} st` : ''}${rev ? ', backwards' : ''}, ${lenText(len)} at ${where}`, 2600);
  return clip;
}
