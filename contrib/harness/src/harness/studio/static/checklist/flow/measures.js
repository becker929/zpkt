// The done measures (mocked): how settled an item looks, from where its current render sits against the reference
// zone on a few dimensions and whether the last batches are converging. Mocked: the zones stand in for the four
// references' measurements and the values for the renders'; both are deterministic, so the same item and choice always
// give the same estimate. They encourage the commit; they never decide it.
import { hash, rng } from '../concepts/model.js';

const clamp = (x) => Math.max(0, Math.min(1, x));
export const EDGE = 0.1;      // the 10 % beyond the zone, where the deliberate extremes live

// Each dimension sits on a 0..1 track; `zone` is the references' range on it.
const DIMS = {
  'kick.drive': [
    { id: 'sub', label: 'Sub weight', zone: [0.5, 0.74] },
    { id: 'click', label: 'Click', zone: [0.4, 0.64] },
    { id: 'density', label: 'Harmonic density', zone: [0.42, 0.7] },
    { id: 'decay', label: 'Decay', zone: [0.38, 0.6] },
  ],
  'kick.eq': [
    { id: 'sub', label: 'Sub', zone: [0.52, 0.76] },
    { id: 'body', label: 'Body', zone: [0.36, 0.6] },
    { id: 'push', label: 'Push', zone: [0.44, 0.66] },
    { id: 'colour', label: 'Mid warmth', zone: [0.4, 0.62] },
  ],
};
const GENERIC = [
  { id: 'level', label: 'Level against the references', zone: [0.42, 0.66] },
  { id: 'tilt', label: 'Tonal tilt', zone: [0.36, 0.6] },
  { id: 'crest', label: 'Crest', zone: [0.44, 0.7] },
];

export const DRIVE = [37, 41, 45, 50];          // batch 8.1's renders (mocked)
export const EQ_STOPS = 7;                       // the mid-warmth macro's rendered stops (mocked)
export const TAKES = ['A', 'B', 'C'];            // a generic item's takes (mocked)

/** What each dimension measures for a choice: `drive` is an index into DRIVE (or 'neither'), `eq` a stop, a generic
 * item a take index. 'neither' keeps the previous batch's sound. */
function values(key, dims, choice, seed) {
  const r = rng(seed);
  const jit = dims.map(() => (r() - 0.5) * 0.06);
  if (key === 'kick.drive') {
    const t = choice === 'neither' ? -0.25 : (DRIVE[choice] - 37) / 13;          // 0 at 37 %, 1 at 50 %
    return [0.72 - t * 0.3, 0.3 + t * 0.48, 0.2 + t * 0.7, 0.56 - t * 0.12].map((v, i) => clamp(v + jit[i]));
  }
  if (key === 'kick.eq') {
    const t = choice / (EQ_STOPS - 1);                                             // 0 cold .. 1 warm
    return [0.7 - t * 0.12, 0.22 + t * 0.5, 0.62 - t * 0.2, 0.18 + t * 0.7].map((v, i) => clamp(v + jit[i]));
  }
  const spread = choice === 1 ? 0.16 : 0.42 + choice * 0.06;                      // take B sits nearest the zones
  return dims.map((d, i) => clamp((d.zone[0] + d.zone[1]) / 2 + (r() - 0.5) * spread + (choice - 1) * 0.06 * (i % 2 ? 1 : -1)));
}

/** The movement between the last batches on this item (a shrinking series when it is converging), ending at the
 * current choice's distance from the middle of the zones. */
function movement(dims, seed) {
  const r = rng(seed ^ 0x9e3779b9);
  const miss = dims.reduce((a, d) => a + Math.abs(d.value - (d.zone[0] + d.zone[1]) / 2), 0) / dims.length;
  const start = 0.5 + r() * 0.2;
  const series = [start, start * (0.62 + r() * 0.1), start * (0.4 + r() * 0.08), start * (0.27 + r() * 0.06)];
  series.push(clamp(miss * 1.6));
  return series;
}

/** The estimate for an item at a choice: { settled 0..1, inZone: {n, of}, converging, dims, movement, words }. */
export function estimate(step, item, choice) {
  const key = `${step.id}.${item.id}`;
  const base = DIMS[key] ?? GENERIC;
  const seed = hash(`${key}|${choice}`);
  const v = values(key, base, choice, seed);
  const dims = base.map((d, i) => {
    const value = v[i];
    const inZone = value >= d.zone[0] && value <= d.zone[1];
    const edge = !inZone && value >= d.zone[0] - EDGE && value <= d.zone[1] + EDGE;
    return { ...d, value, inZone, edge };
  });
  const n = dims.filter((d) => d.inZone).length;
  const mv = movement(dims, hash(key));
  const converging = mv[mv.length - 1] < mv[mv.length - 2];
  const nearness = dims.reduce((a, d) => a + (d.inZone ? 1 : d.edge ? 0.5 : 0), 0) / dims.length;
  const settled = clamp(0.56 * nearness + 0.24 * (converging ? 1 : 0.2) + 0.12 * (1 - mv[mv.length - 1]));      // tops out near 90 %: never certain
  const words = settled >= 0.75 ? ['Looks settled.', 'Commit?']
    : settled >= 0.5 ? ['Nearly there.', 'Commit now, or try another?']
    : ['Still moving.', 'Commit anyway?'];
  return { settled, inZone: { n, of: dims.length }, converging, dims, movement: mv, words };
}
