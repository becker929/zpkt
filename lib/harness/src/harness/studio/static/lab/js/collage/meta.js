// What the collage calls each of the set's sources, and the small facts it needs about them.
//
// The manifest names a clip by its file and track ("2023-11-14_bodhi-anthony-tech-01_9_stems_sound 4_ synth"); the
// shelf calls it what Anthony would ("Synth"). Matched on track + title, so the ids can move.

export const META = [
  { test: /rumble|\(bounce\)/i, name: 'Rumble', long: 'The rumble bounce', tag: 'KICK GRP', color: '#b48cff' },
  { test: /2022-05-30-005/, name: 'Splash', long: 'The noise splash', tag: 'PERC', color: '#dcdcef' },
  { test: /arc raiders/i, name: 'ARC Raiders', long: 'Bastion Encounter, game audio', tag: 'SFX', color: '#ff9ee6' },
  { test: /2022-06-02-001/, name: 'Chord loop', long: 'The processed synth chord loop', tag: 'SFX', color: '#e0b7ff' },
  { test: /sound 4/i, name: 'Synth', long: '2023 session: sound 4 synth', tag: 'BREAK', color: '#8fb8ff' },
  { test: /horn/i, name: 'Horn', long: '2023 session: synth horn', tag: 'BREAK', color: '#ffc58f' },
  { test: /2023-10-07/, name: '10-07 rec', long: 'The 2023-10-07 recording', tag: 'BREAK', color: '#9fe3ff' },
  { test: /beatbox/i, name: 'Beatbox', long: 'The "wuh" before the kick', tag: 'BREAK', color: '#ff8fa3' },
];

export const RS_COLOR = '#f2ecdf';

export function metaFor(clip) {
  const key = `${clip.track ?? ''} ${clip.title ?? ''}`;
  return META.find((m) => m.test.test(key)) ?? { name: clip.title?.slice(0, 14) ?? clip.id, long: clip.title ?? '', tag: 'CLIP', color: '#e0b7ff' };
}

/** "0:12.4" from seconds. */
export function clock(s, digits = 1) {
  if (!Number.isFinite(s)) return '-:--';
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return `${m}:${r.toFixed(digits).padStart(digits ? 3 + digits : 2, '0')}`;
}

/** "bar 9.3" for a 16th count from the bed's start. */
export function barBeat(steps) {
  const bar = Math.floor(steps / 16) + 1;
  const beat = Math.floor((steps % 16) / 4) + 1;
  const six = steps % 4;
  return six ? `${bar}.${beat}.${six + 1}` : `${bar}.${beat}`;
}

/** A length in 16ths, the way a producer says it. */
export function lenText(steps) {
  if (steps % 16 === 0) return steps === 16 ? '1 bar' : `${steps / 16} bars`;
  if (steps === 8) return '1/2 bar';
  if (steps === 4) return '1 beat';
  if (steps % 4 === 0) return `${steps / 4} beats`;
  return `${steps}/16`;
}
