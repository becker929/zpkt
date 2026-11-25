// The surface catalog: what an agent may put in a ```zpkt-surface block, validated and normalised.
// Pure functions, no DOM; the tests import this file directly.

export const KINDS = ['knob', 'fader', 'toggle', 'pads', 'ab', 'deck'];
export const DECK_MAX = 16;

const fin = (v, d) => (typeof v === 'number' && Number.isFinite(v) ? v : typeof v === 'string' && v.trim() && Number.isFinite(+v) ? +v : d);
// Text an agent wrote, made safe to draw and to export: no control characters or broken surrogate pairs (they are
// not valid XML, so the PNG export would fail), white space collapsed, cut by whole characters. Blank means default.
function txt(v, max = 60, d = '') {
  if (typeof v === 'number' && Number.isFinite(v)) v = String(v);
  if (typeof v !== 'string') return d;
  const clean = v.replace(/[\u0000-\u001f\u007f-\u009f\u2028\u2029]+/g, ' ').replace(/[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/g, '').replace(/\s+/g, ' ').trim();
  return [...clean].slice(0, max).join('').trim() || d;
}
const slot = (v) => { const n = fin(v, null); return n != null && n >= 0 && n < 16 ? Math.floor(n) : null; };
// Ids key plain objects (values, peaks, saved state), so one that names an Object member ("constructor") is replaced.
const idOf = (v, i) => (typeof v === 'string' && /^[\w.\-]{1,40}$/.test(v) && !(v in {}) ? v : `c${i}`);
const LIMIT = 1e9;                                             // ranges beyond this are not a control any more
const num6 = (v) => +Math.max(-LIMIT, Math.min(LIMIT, v)).toFixed(6);   // values are kept to 6 decimals everywhere

/** Waveform peaks as numbers 0..1, or null: whatever a spec or a saved state holds. */
export function cleanPeaks(p) {
  return Array.isArray(p) && p.length ? p.slice(0, 2000).map((x) => Math.max(0, Math.min(1, fin(x, 0)))) : null;
}

function track(t) {
  if (!t || typeof t !== 'object') return null;
  const src = txt(t.src, 2000);
  if (!src) return null;
  const peaks = cleanPeaks(t.peaks);
  return { label: txt(t.label, 30), src, bpm: +Math.max(20, Math.min(400, fin(t.bpm, 120))).toFixed(3), downbeatMs: Math.round(Math.max(0, Math.min(3.6e6, fin(t.downbeatMs, 0)))), peaks };
}

// `display`: what the instrument itself shows at even points from min to max ("30 Hz" … "18.5 kHz", or one name
// per step). The control shows these instead of its raw number (see shownAt).
function shown(d, id, warnings) {
  if (d == null) return null;
  const list = Array.isArray(d) ? d.slice(0, 33).map((x) => txt(x, 14)) : [];
  if (list.length < 2 || list.some((x) => !x)) { warnings.push(`"${id}": display needs 2 to 33 texts; ignored`); return null; }
  return list;
}

function control(c, i, id, warnings) {
  const kind = c.kind;
  // hands names the tracks it makes "panel <name>", and a mix panel's faders carry track names: drop the shared
  // prefix, or every fader on a phone fits to the same "panel…".
  const base = { kind, id, label: txt(c.label, 30).replace(/^panel\s+(?=\S)/i, '') || id.slice(0, 30) };
  if (kind === 'knob' || kind === 'fader') {
    let min = num6(fin(c.min, 0)), max = num6(fin(c.max, kind === 'fader' ? 1 : 100));
    if (max === min) max = min + 1;
    if (max < min) [min, max] = [max, min];
    let step = num6(Math.max(0, fin(c.step, 0)));
    if (step > max - min) { warnings.push(`${kind} "${id}": step ${step} is larger than its range; ignored`); step = 0; }
    const k = { ...base, min, max, step, unit: txt(c.unit, 6), midiSlot: slot(c.midiSlot) };
    const display = shown(c.display, id, warnings);
    return { ...k, value: quant(k, fin(c.value, min)), ...(display ? { display } : {}) };
  }
  if (kind === 'toggle') return { ...base, value: !!c.value, midiSlot: slot(c.midiSlot) };
  if (kind === 'pads') {
    const pads = (Array.isArray(c.pads) ? c.pads : []).slice(0, 16).map((p, k) => ({
      label: txt(p?.label, 16, String(k + 1)), src: txt(p?.src, 2000) || null, midiSlot: slot(p?.midiSlot === undefined ? k : p.midiSlot),
    }));
    if (!pads.length) { warnings.push(`pads "${id}" has no pads`); return null; }
    return { ...base, pads };
  }
  if (kind === 'deck') {
    // Any number of versions of the same bars (A, B, C, ...), switched on the beat. `matched`: the same render turned
    // to a common loudness by whoever made it (the page never changes a level). `pick`: the grid these came from.
    const seen = new Set();
    const sources = (Array.isArray(c.sources) ? c.sources : []).slice(0, DECK_MAX).map((s, k) => {
      const letter = String.fromCharCode(65 + k);   // a label is drawn on a button and used as the value: keep it plain
      const t = track({ bpm: c.bpm, downbeatMs: c.downbeatMs, ...s, label: typeof s?.label === 'string' && /^[\w .\-]{1,12}$/.test(s.label) ? s.label : letter });
      if (!t || !t.label || seen.has(t.label)) return null;
      seen.add(t.label);
      const matched = txt(s.matched, 2000);
      return { ...t, note: txt(s.note, 80), ...(matched ? { matched } : {}) };
    }).filter(Boolean);
    if (sources.length < 2) { warnings.push(`deck "${id}" needs at least two sources with a src`); return null; }
    const loop = { startBar: Math.max(1, Math.min(9999, Math.floor(fin(c.loop?.startBar, 1)))), bars: Math.max(1, Math.min(64, Math.floor(fin(c.loop?.bars, 8)))) };
    const pick = Number.isInteger(c.pick) && c.pick > 0 && c.pick < 1e6 ? { pick: c.pick } : {};
    return { ...base, sources, loop, quantize: ['now', 'beat', 'bar'].includes(c.quantize) ? c.quantize : 'bar', ...pick };
  }
  // ab
  const a = track(c.a), b = track(c.b);
  if (!a || !b) { warnings.push(`ab "${id}" needs a.src and b.src`); return null; }
  const loop = { startBar: Math.max(1, Math.min(9999, Math.floor(fin(c.loop?.startBar, 1)))), bars: Math.max(1, Math.min(64, Math.floor(fin(c.loop?.bars, 8)))) };
  const quantize = ['now', 'beat', 'bar'].includes(c.quantize) ? c.quantize : 'bar';
  if (a.bpm !== b.bpm) warnings.push(`ab "${id}": BPMs differ (${a.bpm} / ${b.bpm}); switching keeps A's clock and nothing is stretched`);
  return { ...base, a, b, loop, quantize };
}

/** Validate an agent's spec (JSON text or object). Throws when nothing is usable; skipped parts become warnings. */
export function validate(raw) {
  if (typeof raw === 'string') raw = JSON.parse(raw);
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('A surface must be a JSON object');
  const list = Array.isArray(raw.controls) ? raw.controls : [];
  if (!list.length) throw new Error('A surface needs a "controls" array');
  const warnings = [];
  const seen = new Set();
  const controls = [];
  list.slice(0, 32).forEach((c, i) => {
    if (!c || typeof c !== 'object') return warnings.push(`control ${i + 1} is not an object`);
    if (!KINDS.includes(c.kind)) return warnings.push(`control ${i + 1}: unknown kind "${txt(c.kind, 20)}"`);
    let id = idOf(c.id, i);
    for (let n = 2, base = id.slice(0, 34); seen.has(id); n++) id = `${base}_${n}`;   // a second "cutoff" becomes cutoff_2
    seen.add(id);
    const n = control(c, i, id, warnings);
    if (n) controls.push(n);
  });
  if (!controls.length) throw new Error('No usable controls' + (warnings.length ? `: ${warnings.join('; ')}` : ''));
  // `panel`: the name of the `hands panel` this card was printed by; it goes back with the card's state.
  const panel = typeof raw.panel === 'string' && /^[a-z0-9][a-z0-9-]{0,39}$/.test(raw.panel) ? { panel: raw.panel } : {};
  return { spec: { title: txt(raw.title, 80, 'Surface'), note: txt(raw.note, 240), ...panel, controls }, warnings };
}

/** The values a spec starts with (what the agent last rendered). */
export function defaults(spec) {
  const v = {};
  for (const c of spec.controls) {
    if ('value' in c) v[c.id] = c.value;
    if (c.kind === 'ab') v[c.id] = 'a';
    if (c.kind === 'deck') v[c.id] = c.sources[0].label;
  }
  return v;
}

/** Clamp and snap a knob/fader value. The result is always inside the range. */
export function quant(c, v) {
  v = Math.max(c.min, Math.min(c.max, v));
  if (c.step) {
    v = c.min + Math.round((v - c.min) / c.step) * c.step;
    if (v > c.max + 1e-9) v -= c.step;   // the last full step below the top
  }
  return Math.max(c.min, Math.min(c.max, +v.toFixed(6)));
}

/** A value from anywhere (a saved state, an old preset, MIDI) as this control can hold it; null if it cannot. */
export function coerce(c, v) {
  if (c.kind === 'knob' || c.kind === 'fader') { const n = fin(v, null); return n == null ? null : quant(c, n); }
  if (c.kind === 'toggle') return typeof v === 'boolean' ? v : null;
  if (c.kind === 'ab') return v === 'a' || v === 'b' ? v : null;
  if (c.kind === 'deck') return typeof v === 'string' && c.sources.some((s) => s.label === v) ? v : null;
  if (c.kind === 'pads') return typeof v === 'string' && c.pads.some((p) => p.label === v) ? v : null;
  return null;
}

/** A surface's values: the defaults, overlaid with every source in turn, keeping only what each control can hold. */
export function valuesOf(spec, ...sources) {
  const v = defaults(spec);
  for (const src of sources) {
    if (!src || typeof src !== 'object') continue;
    for (const c of spec.controls) {
      if (!Object.hasOwn(src, c.id)) continue;
      const x = coerce(c, src[c.id]);
      if (x != null) v[c.id] = x;
    }
  }
  return v;
}

// A displayed text as a number in its base unit: "1.2 kHz" is 1200 hz, "1.5 s" is 1500 ms. Null if it is a name.
const SCALE = { khz: ['hz', 1000], hz: ['hz', 1], s: ['ms', 1000], ms: ['ms', 1] };
function reading(text) {
  const m = /^\s*([-+]?\d+(?:\.\d+)?)\s*(.*?)\s*$/.exec(text);
  if (!m) return null;
  const [base, k] = SCALE[m[2].toLowerCase()] || [m[2].toLowerCase(), 1];
  return { x: +m[1] * k, base, unit: m[2] };
}
const sig3 = (x) => (Math.abs(x) >= 100 ? x.toFixed(0) : Math.abs(x) >= 10 ? x.toFixed(1) : x.toFixed(2));

/** What a control with a `display` shows at v: the text at that point, or a reading between its two neighbours
 *  (along a curve when both are above zero, since frequencies and times are laid out that way). */
export function shownAt(c, v) {
  const d = c.display, t = Math.max(0, Math.min(1, (v - c.min) / (c.max - c.min))) * (d.length - 1);
  const i = Math.min(d.length - 2, Math.floor(t)), f = t - i;
  if (f < 1e-6) return d[i];
  if (f > 1 - 1e-6) return d[i + 1];
  const a = reading(d[i]), b = reading(d[i + 1]);
  if (!a || !b || a.base !== b.base) return d[f < 0.5 ? i : i + 1];
  const x = a.x > 0 && b.x > 0 ? a.x * (b.x / a.x) ** f : a.x + (b.x - a.x) * f;
  if ((a.base === 'hz' || a.base === 'ms') && Math.abs(x) >= 1000) return `${sig3(x / 1000)} ${a.base === 'hz' ? 'kHz' : 's'}`;
  const unit = a.base === 'hz' ? 'Hz' : a.base === 'ms' ? 'ms' : (f < 0.5 ? a : b).unit;
  return unit ? `${sig3(x)} ${unit}` : sig3(x);
}

/** A value as the control shows it. */
export function fmt(c, v) {
  if (typeof v !== 'number') return String(v);
  if (c.display) return shownAt(c, v);
  const unit = c.unit ? ` ${c.unit}` : '';
  const big = Math.max(Math.abs(c.min), Math.abs(c.max));
  if (big >= 1e5) {   // too many digits for a control: 250k, 1.2M
    const [div, sfx] = big >= 1e9 ? [1e9, 'G'] : big >= 1e6 ? [1e6, 'M'] : [1e3, 'k'];
    const x = v / div;
    return (Math.abs(x) >= 100 ? x.toFixed(0) : Math.abs(x) >= 10 ? x.toFixed(1) : x.toFixed(2)) + sfx + unit;
  }
  const span = c.max - c.min;
  let d = span >= 100 ? 0 : span >= 10 ? 1 : span >= 0.1 ? 2 : 3;
  if (c.step) for (d = 0; d < 4 && Math.abs(c.step * 10 ** d - Math.round(c.step * 10 ** d)) > 1e-7; d++);   // as many decimals as the step has
  if (big >= 1e4) d = Math.min(d, 1);
  return v.toFixed(Math.min(d, 4)) + unit;
}

/** Controls whose value differs from what the agent rendered: changes not yet audible. */
export const changed = (spec, values) => spec.controls.filter((k) => 'value' in k && values[k.id] !== k.value);
