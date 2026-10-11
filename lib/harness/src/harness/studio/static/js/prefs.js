// The phone's preferences, kept in localStorage and sent to the Mac in `hello` and `prefs`.
import { Emitter } from './emitter.js';

const KEY = 'studio.prefs';

/** Screenshot levels, from fewest to most shots. A page shows its level and every level below it. */
export const SHOT_LEVELS = ['none', 'major', 'minor', 'firehose'];

const DEFAULTS = { autoplay: true, shots: 'major', handsfree: true, keepMic: true, phoneMic: true };
export const PAGE_ONLY = ['keepMic', 'phoneMic'];       // how this phone handles its mic; the Mac has no use for it

export class Prefs extends Emitter {
  #values;

  constructor() {
    super();
    this.#values = { ...DEFAULTS, ...load() };
    if (!SHOT_LEVELS.includes(this.#values.shots)) this.#values.shots = DEFAULTS.shots;
  }

  get(key) {
    return this.#values[key];
  }

  set(key, value) {
    if (this.#values[key] === value) return;
    this.#values[key] = value;
    try {
      localStorage.setItem(KEY, JSON.stringify(this.#values));
    } catch {
      // Private mode or full storage: the preference still holds for this visit.
    }
    this.emit('change', { key, value });
  }

  /** The wire form: `{autoplay, shots, handsfree}`. */
  get values() {
    return Object.fromEntries(Object.entries(this.#values).filter(([key]) => !PAGE_ONLY.includes(key)));
  }
}

function load() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || '{}');
    return Object.fromEntries(Object.entries(saved).filter(([key]) => key in DEFAULTS));
  } catch {
    return {};
  }
}
