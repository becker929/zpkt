// A/B files alternate two versions every `every` bars. Which one sounds at a given moment.

/** The music message's `ab`, with defaults: {bar_seconds, bars, first, every, labels: {A, B}}, or null. */
export function normaliseAb(ab) {
  if (!ab || !(Number(ab.bar_seconds) > 0)) return null;
  const labels = Array.isArray(ab.labels) ? { A: ab.labels[0], B: ab.labels[1] } : ab.labels ?? {};
  return {
    bar_seconds: Number(ab.bar_seconds),
    bars: Number(ab.bars) || 0,
    first: ab.first === 'B' ? 'B' : 'A',
    every: Math.max(1, Number(ab.every) || 1),
    labels: { A: labels.A ?? '', B: labels.B ?? '' },
  };
}

/** The side sounding `t` seconds into one pass of the file. */
export function abSide(ab, t) {
  const bar = Math.floor(t / ab.bar_seconds + 1e-6);
  const firstHalf = Math.floor(bar / ab.every) % 2 === 0;
  return firstHalf ? ab.first : ab.first === 'A' ? 'B' : 'A';
}
