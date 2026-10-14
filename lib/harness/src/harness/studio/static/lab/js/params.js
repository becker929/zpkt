// HW002's parameters: what each control is, in Live's terms and the phone's.
//
// data/params.json lists them. Each one:
//   id       short name used everywhere on the page ("kick.drive")
//   live     the knob in Live, as hands names it: "track|device|param" (null for an arrangement choice)
//   stage    collage | arrange | kick | mix
//   group    the rack it sits in on its stage
//   label    what the control says
//   unit     % dB Hz ms st x bars beats ("" for none)
//   min max  the range in that unit; scale lin | log | db | enum | toggle
//   set      the value in the set now (HW002_121): the acid mark on every control, and what "reset" goes to
//   tried    [lo, hi] the range an experiment tried (a lighter band), optional
//   note     what was found ("batch 8.1: 37-50% is the target"), optional
//   options  labels for an enum
//   sketch   how the phone's own sound follows it (the engine binds these), optional
//
// The store keeps every value normalised 0..1; these turn that into the unit and back, and into text.

// data/extras-<stage>.json (optional, one per surface) add the phone's own controls: a kick synth's pitch drop, a
// grain size. They have origin "phone" and no `live` knob; they are not among HW002's 100.
export const STAGES = ['collage', 'arrange', 'kick', 'mix', 'play'];

export async function loadParams(base = './data/') {
  const res = await fetch(`${base}params.json`, { cache: 'no-cache' });
  if (!res.ok) throw new Error(`params: ${res.status}`);
  const data = await res.json();
  const extras = await Promise.all(STAGES.map(async (stage) => {
    try {
      const r = await fetch(`${base}extras-${stage}.json`, { cache: 'no-cache' });
      if (!r.ok) return [];
      const list = (await r.json()).params ?? [];
      return list.map((p) => ({ stage, origin: 'phone', live: null, ...p }));
    } catch { return []; }
  }));
  return new Params([...(data.params ?? data), ...extras.flat()]);
}

export class Params {
  constructor(list) {
    this.list = list.map((p) => ({ scale: 'lin', unit: '', ...p }));
    this.byId = new Map(this.list.map((p) => [p.id, p]));
  }

  get(id) {
    const p = this.byId.get(id);
    if (!p) throw new Error(`no param ${id}`);
    return p;
  }

  has(id) { return this.byId.has(id); }
  stage(stage) { return this.list.filter((p) => p.stage === stage); }
  group(stage, group) { return this.list.filter((p) => p.stage === stage && p.group === group); }
  groups(stage) { return [...new Set(this.stage(stage).map((p) => p.group))]; }
}

const clamp = (x, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, x));

/** 0..1 -> the param's unit. */
export function toReal(p, n) {
  n = clamp(n);
  switch (p.scale) {
    case 'log': return p.min * Math.pow(p.max / p.min, n);
    case 'toggle': return n >= 0.5 ? 1 : 0;
    case 'enum': return Math.round(n * (p.options.length - 1));
    case 'db':                                  // dB faders: more travel near 0 dB, like a console
    default: {
      const v = p.min + (p.max - p.min) * n;
      return p.step ? Math.round(v / p.step) * p.step : v;
    }
  }
}

/** The param's unit -> 0..1. */
export function toNorm(p, v) {
  switch (p.scale) {
    case 'log': return clamp(Math.log(v / p.min) / Math.log(p.max / p.min));
    case 'toggle': return v ? 1 : 0;
    case 'enum': return p.options.length > 1 ? clamp(v / (p.options.length - 1)) : 0;
    default: return p.max === p.min ? 0 : clamp((v - p.min) / (p.max - p.min));
  }
}

/** The set's value, normalised. */
export const setNorm = (p) => toNorm(p, p.set ?? p.min);

/** A value as the control shows it: "37 %", "2.2 kHz", "-4.0 dB", "On". */
export function format(p, v, { unit = true } = {}) {
  if (p.scale === 'toggle') return v ? (p.on ?? 'On') : (p.off ?? 'Off');
  if (p.scale === 'enum') return p.options[v] ?? String(v);
  const u = p.unit;
  let text;
  if (u === 'Hz') text = v >= 1000 ? `${(v / 1000).toFixed(v >= 10000 ? 1 : 2)} k` : `${v.toFixed(v < 100 ? 1 : 0)} `;
  else if (u === '%') text = `${v.toFixed(Math.abs(v) < 10 ? 1 : 0)} `;
  else if (u === 'dB') text = `${v > 0 ? '+' : ''}${v.toFixed(1)} `;
  else if (u === 'ms') text = `${v.toFixed(v < 10 ? 1 : 0)} `;
  else if (u === 'st') text = `${v > 0 ? '+' : ''}${v.toFixed(Math.abs(v) < 10 && !Number.isInteger(v) ? 1 : 0)} `;
  else if (Number.isInteger(p.step) || u === 'bars' || u === 'beats') text = `${Math.round(v)} `;
  else text = `${Math.abs(v) < 10 ? v.toFixed(2) : v.toFixed(1)} `;
  return unit ? (text + (u === 'Hz' ? 'Hz' : u)).trim() : text.trim();
}
