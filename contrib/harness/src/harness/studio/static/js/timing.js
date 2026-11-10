// Timing marks measured on the phone, sent to the Mac (`mark`), which keeps them with its own marks
// for the turn (GET /studio/api/timings). They are durations, so the two clocks never need syncing.

export class Timing {
  turn = null;            // the turn in progress, from the Mac's phase and listen messages
  recent = [];            // the last marks, for debugging on the phone

  constructor(send) {
    this.send = send;
  }

  /** `extra` holds numbers or short strings the Mac stores alongside (e.g. {mode: 'playback'}). */
  mark(name, ms, extra = {}, turn = this.turn) {
    const msg = { type: 'mark', turn, name, ms: Math.round(ms), ...extra };
    this.recent.push(msg);
    if (this.recent.length > 40) this.recent.shift();
    this.send(msg);
  }
}
