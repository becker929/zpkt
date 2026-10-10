// A decoded file played `loops` times in a row: a render, or a replay of something said.
//
// One looping AudioBufferSourceNode, started on a sample frame and stopped exactly `loops` file
// lengths later, so the repeats are sample-accurate and the count is exact.

const START_LEAD_S = 0.03;

export class Clip {
  #source = null;
  #buffer = null;
  #ctx = null;
  #finished = false;
  #resolve;
  t0 = 0;                   // audio-clock time of the first sample
  duration = 0;             // one pass, seconds
  error = null;

  /** `load()` resolves to {buffer, ab}; `kind` is the message's kind. */
  constructor({ seq, kind, loops, load, onFirstSound }) {
    this.seq = seq;
    this.kind = kind;
    this.loops = loops;
    this.load = load;
    this.onFirstSound = onFirstSound;
    this.ab = null;
    this.done = new Promise((resolve) => (this.#resolve = resolve));
  }

  /** Fetch and decode ahead of its turn. */
  prepare() {
    if (!this.#buffer) {
      this.#buffer = this.load();
      this.#buffer.catch(() => {});
    }
    return this.#buffer;
  }

  get stopAt() {
    return this.t0 + this.loops * this.duration;
  }

  async start(ctx, out) {
    let loaded;
    try {
      loaded = await this.prepare();
    } catch (err) {
      this.error = err;
      this.#finish('failed');
      return;
    }
    if (this.#finished) return;
    const { buffer, ab } = loaded;
    this.ab = ab;
    this.#ctx = ctx;
    this.duration = buffer.duration;
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.loop = true;
    src.connect(out);
    src.onended = () => this.#finish('played');
    const rate = ctx.sampleRate;
    this.t0 = Math.ceil((ctx.currentTime + START_LEAD_S) * rate) / rate;
    src.start(this.t0);
    src.stop(this.stopAt);
    this.#source = src;
    this.onFirstSound?.(this.t0 - ctx.currentTime);
  }

  /** Change how many passes play, while playing: the last call to stop() is the one that counts. */
  setLoops(loops) {
    this.loops = loops;
    if (!this.#source) return;
    try {
      this.#source.stop(Math.max(this.stopAt, this.#ctx.currentTime));
    } catch {
      // Already ended.
    }
  }

  /** Where playback is: seconds into the current pass, and which pass. Null before it starts. */
  position(heardAt) {
    if (!this.#source || heardAt < this.t0) return null;
    const elapsed = Math.min(heardAt, this.stopAt) - this.t0;
    const pass = Math.min(Math.floor(elapsed / this.duration), this.loops - 1);
    return { t: elapsed - pass * this.duration, pass };
  }

  stop() {
    if (this.#source) {
      this.#source.onended = null;
      try {
        this.#source.stop();
      } catch {
        // Already ended.
      }
    }
    this.#finish('stopped');
  }

  #finish(outcome) {
    if (this.#finished) return;
    this.#finished = true;
    this.#resolve(outcome);
  }
}
