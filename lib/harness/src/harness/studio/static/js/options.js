// Options: N renders baked in Live and put end to end in one file (hands plan slider|line|options). The page keeps
// the file decoded and switches between the options itself, so moving a slider asks nothing of the Mac.

/** The music message's `options`, with defaults: {layout, name, bar_seconds, bars, span, now, options}, or null. */
export function normaliseOptions(o) {
  if (!o || !(Number(o.bar_seconds) > 0) || !Array.isArray(o.options) || o.options.length < 2) return null;
  const bars = Math.max(1, Number(o.bars) || 1);
  const options = o.options.map((x, i) => ({ label: String(x?.label ?? i + 1), match_db: Number(x?.match_db) || 0 }));
  const now = Number.isInteger(o.now) && o.now >= 0 && o.now < options.length ? o.now : null;
  return {
    layout: o.layout === 'buttons' ? 'buttons' : 'slider',
    name: String(o.name ?? ''),
    bar_seconds: Number(o.bar_seconds),
    bars,
    span: bars * Number(o.bar_seconds),      // one option's length in the file
    now,
    options,
  };
}

/** The gain that plays an option level-matched, or 1 at Live's own level. */
export const matchGain = (option, on) => (on ? 10 ** (option.match_db / 20) : 1);

/** Where an option is read at time `t`, with `t0` the anchor: every option at the same place in its bars. */
export const offsetAt = (o, index, t, t0) => index * o.span + mod(t - t0, o.span);

/** In a sweep, which option sounds `t` seconds into a pass: one bar each, in order. */
export const sweepIndex = (o, t) => Math.min(o.options.length - 1, Math.max(0, Math.floor(t / o.bar_seconds + 1e-6)));

/** The pick a page shows first: the option that sounds like the set now, else the first. */
export const firstPick = (o) => o.now ?? 0;

function mod(a, n) {
  return ((a % n) + n) % n;
}
