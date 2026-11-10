// The Short as data: the arr.* values -> a plan, one entry per bar, that says what plays there.
//
// Pure functions, no audio: the arranger turns a plan into the engine's sequence, the timeline draws it, the A/B/C
// rack makes three of them. Bars are 0-based here; the controls show them 1-based, as Live does.
//
// How the values read (the set's values give batch 4.3 track 1, the canonical shape):
//   length            the Short's bars, everything included (target 22-33 bars, 33-50 s)
//   intro             bars of the scooped kick from bar 1 (the kick with its 126 Hz low cut)
//   kickIn            where the full kick enters; bars between the scoop and it have no kick
//   preKick           before every kick entry: the song's own "wuh" (the beatbox and the break's last beats),
//                     a silence, or straight in; preKickBeats long
//   hatA..hatD        where each hat layer enters; the drop (the last dropBars bars) has all four
//   splashEvery       a long splash on every kick entry, a short one every 4/8/16 bars after it ("once": only the long)
//   breakOn/At/Bars   a break: no kick, the song's own break bars (or the stems thinned to hat A)
//   secondBreak       a second one (break2At, break2Bars)
//   sfxBuild          where the ARC RAIDERS hit lands: bar 1, with the kick, at the drop, or never; again every 16
//   chord             the chord loop under every bar outside the breaks

export const BAR_S = 1.5;
export const TARGET = { lo: 33, hi: 50 };                       // seconds
export const LAYERS = ['A', 'B', 'C', 'D'];
export const PRE_KICK = ['wuh', 'silence', 'straight in'];
export const SPLASH_EVERY = [4, 8, 16, 0];                     // 0: once
export const SFX_AT = ['from the start', 'with the kick', 'at the drop', 'withheld'];

/** The arr.* params a plan reads, keyed by the short names below. */
export const KEYS = {
  length: 'arr.length', intro: 'arr.intro', kickIn: 'arr.kickIn', preKick: 'arr.preKick', preKickBeats: 'arr.preKickBeats',
  hatA: 'arr.hatA', hatB: 'arr.hatB', hatC: 'arr.hatC', hatD: 'arr.hatD',
  splashEvery: 'arr.splashEvery', splashLong: 'arr.splashLong', splashShort: 'arr.splashShort',
  breakOn: 'arr.breakOn', breakAt: 'arr.breakAt', breakBars: 'arr.breakBars', breakStyle: 'arr.breakStyle',
  secondBreak: 'arr.secondBreak', break2At: 'arr.break2At', break2Bars: 'arr.break2Bars',
  chord: 'arr.chord', sfxBuild: 'arr.sfxBuild', dropBars: 'arr.dropBars',
  splashLevel: 'arr.splashLevel', breakLevel: 'arr.breakLevel', chordLevel: 'arr.chordLevel', chordWidth: 'arr.chordWidth',
};

/** Read the plan's values (real units) from the store, or from a snapshot of normalised values. */
export function readValues(store, snap = null) {
  const v = {};
  for (const [k, id] of Object.entries(KEYS)) {
    if (!store.params.has(id)) continue;
    const p = store.params.get(id);
    v[k] = snap && id in snap ? realOf(p, snap[id]) : store.real(id);
  }
  return v;
}

function realOf(p, n) {
  // the same as params.toReal, kept here so the model has no imports
  n = Math.min(1, Math.max(0, n));
  if (p.scale === 'toggle') return n >= 0.5 ? 1 : 0;
  if (p.scale === 'enum') return Math.round(n * (p.options.length - 1));
  if (p.scale === 'log') return p.min * Math.pow(p.max / p.min, n);
  const v = p.min + (p.max - p.min) * n;
  return p.step ? Math.round(v / p.step) * p.step : v;
}

const r = Math.round;

/**
 * The plan: {L, seconds, bars: [...], breaks: [{from, to}], entries: [bar], drop: {from, to}, sfxAt, notes: [...]}.
 * Each bar: {i, kick: 'scoop'|'full'|null, hats: 'ABCD'-subset string, brk: {k, len, n}|null, drop, entry (a kick
 * entry), gap: {from: beat}|null (the pre-kick gap starts in this bar), wuh: {beats}|null (starts in this bar at
 * gap.from), splash: {beats, long}|null, arc: 0|1|null, chord: phase|null}.
 */
export function plan(v) {
  const L = Math.max(4, r(v.length ?? 20));
  const bars = Array.from({ length: L }, (_, i) => ({
    i, kick: null, hats: '', brk: null, drop: false, entry: false, gap: null, wuh: null, splash: null, arc: null, chord: null,
  }));
  const notes = [];

  // breaks (merged where they touch)
  const spans = [];
  if (v.breakOn >= 0.5 && v.breakBars > 0) spans.push([r(v.breakAt) - 1, r(v.breakAt) - 1 + r(v.breakBars)]);
  if (v.secondBreak >= 0.5 && (v.break2Bars ?? 0) > 0) spans.push([r(v.break2At ?? 25) - 1, r(v.break2At ?? 25) - 1 + r(v.break2Bars)]);
  const breaks = [];
  for (const [a0, b0] of spans.sort((x, y) => x[0] - y[0])) {
    const a = Math.max(0, a0), b = Math.min(L, b0);
    if (b <= a) { notes.push('A break sits past the end of the Short.'); continue; }
    const last = breaks.at(-1);
    if (last && a <= last.to) last.to = Math.max(last.to, b); else breaks.push({ from: a, to: b });
  }
  breaks.forEach((s, n) => { for (let i = s.from; i < s.to; i++) bars[i].brk = { k: i - s.from, len: s.to - s.from, n }; });

  // the drop: the last dropBars bars
  const dropBars = Math.min(L, r(v.dropBars ?? 8));
  const drop = { from: L - dropBars, to: L };
  for (let i = drop.from; i < L; i++) bars[i].drop = true;

  // the kick
  const intro = r(v.intro ?? 4), kickIn = r(v.kickIn ?? 5);
  for (const b of bars) {
    if (b.brk) continue;
    const n = b.i + 1;
    if (n >= kickIn || b.drop) b.kick = 'full';
    else if (n <= intro) b.kick = 'scoop';
  }
  const entries = [];
  for (const b of bars) {
    if (b.kick === 'full' && (b.i === 0 ? false : bars[b.i - 1].kick !== 'full')) { b.entry = true; entries.push(b.i); }
  }
  if (bars[0].kick === 'full') { bars[0].entry = true; entries.unshift(0); }

  // the hats: each layer from its bar; the drop has all four; a break thins (song style: none, stems style: A)
  const hat = { A: v.hatA ?? 1, B: v.hatB ?? 5, C: v.hatC ?? 9, D: v.hatD ?? 13 };
  for (const b of bars) {
    if (b.brk) { b.hats = (v.breakStyle ?? 0) >= 0.5 ? 'A' : ''; continue; }
    b.hats = b.drop ? 'ABCD' : LAYERS.filter((x) => b.i + 1 >= r(hat[x])).join('');
  }

  // the pre-kick gap before every kick entry (not at bar 1)
  const style = r(v.preKick ?? 0), beats = r(v.preKickBeats ?? 4);
  if (style < 2 && beats > 0) {
    for (const e of entries) {
      if (e === 0) continue;
      const start = Math.max(0, e * 4 - beats);              // in beats
      const first = Math.floor(start / 4);
      for (let j = first; j < e; j++) {
        const from = Math.max(0, start - j * 4);
        bars[j].gap = { from, style };
      }
      if (style === 0) bars[first].wuh = { beats: e * 4 - start, at: start - first * 4 };
    }
  }

  // splashes: long on every kick entry, short every N bars after it until the next break or entry
  const every = SPLASH_EVERY[r(v.splashEvery ?? 1)] ?? 8;
  const long = r(v.splashLong ?? 8), short = r(v.splashShort ?? 3);
  for (const e of entries) {
    bars[e].splash = { beats: long, long: true };
    if (!every) continue;
    for (let i = e + every; i < L; i += every) {
      if (bars[i].brk || bars[i].entry || bars[i].kick !== 'full') break;
      bars[i].splash = { beats: short, long: false };
    }
  }

  // SFX: the ARC RAIDERS hit (two bars) where SFX enters, then every 16 bars; the chord loop outside the breaks
  const sfxMode = r(v.sfxBuild ?? 0);
  const songBreak = (b) => b.brk && (v.breakStyle ?? 0) < 0.5;
  let sfxAt = null;
  if (sfxMode === 0) sfxAt = 0;
  else if (sfxMode === 1) sfxAt = entries[0] ?? null;
  else if (sfxMode === 2) sfxAt = drop.from;
  if (sfxAt != null) {
    for (let h = sfxAt; h < L; h += 16) {
      if (songBreak(bars[h])) continue;
      bars[h].arc = 0;
      if (h + 1 < L && !songBreak(bars[h + 1])) bars[h + 1].arc = 1;
    }
  }
  if (v.chord >= 0.5) for (const b of bars) if (!songBreak(b)) b.chord = b.i % 8;

  // what Anthony's rules say about this one
  const seconds = L * BAR_S;
  if (seconds < TARGET.lo) notes.push(`${seconds} s: under the 33-50 s target.`);
  if (seconds > TARGET.hi) notes.push(`${seconds} s: over the 33-50 s target.`);
  const scoop = Math.min(intro, kickIn - 1);
  if (scoop === 1) notes.push('Never open on a single bar: the scoop lasts one.');
  if (scoop < 1) notes.push('"Final arrangement starts with the scooped kick": this one starts on the full kick.');
  if (!breaks.length) notes.push('No break. Every reference has two of 8+ bars.');
  else if (breaks.length === 1) notes.push('One break. Every reference has two.');
  if (every === 4) notes.push('A splash every 4 bars: "too many splashes".');

  return { L, seconds, bars, breaks, entries, drop, sfxAt, notes, values: { ...v } };
}

/** Sections for the timeline's top lane: runs of bars with the same character, labelled. */
export function sections(pl) {
  const out = [];
  const name = (b) => {
    if (b.brk) return 'BREAK';
    if (b.kick === 'scoop') return 'SCOOP';
    if (!b.kick) return 'NO KICK';
    if (b.drop) return 'DROP';
    return b.hats || 'KICK';
  };
  for (const b of pl.bars) {
    const n = name(b);
    const last = out.at(-1);
    if (last && last.name === n && !(b.entry && n !== 'DROP')) last.to = b.i + 1;
    else out.push({ name: n, from: b.i, to: b.i + 1 });
  }
  return out;
}

/** The bars where the hat set changes (for the staircase): [{bar, hats}] */
export function hatSteps(pl) {
  const out = [];
  for (const b of pl.bars) if (!out.length || out.at(-1).hats !== b.hats) out.push({ bar: b.i, hats: b.hats });
  return out;
}
