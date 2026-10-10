// The iOS audio session: "playback" for every sound, "play-and-record" only while the mic is open.
//
// With a Bluetooth headset (a car), an open mic moves it to its call profile (mono, phone quality);
// playback alone keeps it in its media profile. Left to itself the phone guesses and flips between
// the two mid-sound. Safari 16.4+ lets a page say which it wants (navigator.audioSession.type). Each
// switch then waits for the route to settle before anything plays or records. Phones without the
// API still wait, so their headsets can settle too; desktops without it do not.
import { sleep } from './dom.js';

export const ROUTE_SETTLE_MS = 1200;   // what /skrng's review and talk pages learned on an iPhone; tune it here

const OUTPUT = 'playback';
const INPUT = 'play-and-record';

export class AudioSession {
  #api = navigator.audioSession ?? null;
  #mode = null;
  #ready = Promise.resolve();

  /** `settleMs` overrides the default (the page takes ?settle=<ms> for tuning on the phone). */
  constructor({ timing, settleMs = null }) {
    this.timing = timing;
    this.settleMs = settleMs ?? (this.#api || navigator.maxTouchPoints > 0 ? ROUTE_SETTLE_MS : 0);
  }

  get mode() {
    return this.#mode;
  }

  /** Resolves once the route is ready for output. */
  forOutput() {
    return this.#switch(OUTPUT);
  }

  /** Resolves once the route is ready for the mic. */
  forInput() {
    return this.#switch(INPUT);
  }

  #switch(mode) {
    if (this.#mode === mode) return this.#ready;
    this.#mode = mode;
    try {
      if (this.#api) this.#api.type = mode;
    } catch {
      // An older WebKit may refuse a type; the wait below still lets the headset settle.
    }
    const started = performance.now();
    this.#ready = sleep(this.settleMs).then(() => {
      if (this.#mode === mode && this.settleMs > 0) {
        this.timing.mark('route_settle', performance.now() - started, { mode });
      }
    });
    return this.#ready;
  }
}
