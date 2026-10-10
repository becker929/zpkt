// One speech stream from the Mac: s16le PCM chunks, scheduled back to back on the audio clock.
//
// Chunks arrive over the network unevenly. Playback starts once JITTER_S of audio is buffered (or the
// stream has ended), and later chunks are scheduled exactly where the previous one ends, so there are
// no gaps unless the network falls behind; a late chunk restarts just ahead of the clock.

const JITTER_S = 0.12;
const LEAD_S = 0.03;
const LATE_S = 0.01;

export class SpeechStream {
  kind = 'speech';
  #pending = [];            // Float32Array chunks waiting to be scheduled
  #buffered = 0;            // seconds in #pending
  #sources = new Set();
  #ctx = null;
  #out = null;
  #next = 0;                // audio-clock time where the next chunk starts
  #playing = false;
  #ended = false;
  #finished = false;
  #resolve;

  constructor({ stream, seq, rate, onFirstSound }) {
    this.stream = stream;
    this.seq = seq;
    this.rate = rate;
    this.onFirstSound = onFirstSound;
    this.done = new Promise((resolve) => (this.#resolve = resolve));
  }

  /** `pcm` is a DataView over s16le samples. */
  push(pcm) {
    if (this.#finished || this.#ended) return;
    const n = pcm.byteLength >> 1;
    const samples = new Float32Array(n);
    for (let i = 0; i < n; i += 1) samples[i] = pcm.getInt16(i * 2, true) / 32768;
    this.#pending.push(samples);
    this.#buffered += n / this.rate;
    this.#pump();
  }

  /** The Mac sent the stream's end: play what is left, then finish. */
  end() {
    this.#ended = true;
    this.#pump();
  }

  /** Its turn in the queue has come. */
  start(ctx, out) {
    this.#ctx = ctx;
    this.#out = out;
    this.#pump();
  }

  stop() {
    for (const src of this.#sources) {
      src.onended = null;
      try {
        src.stop();
      } catch {
        // Already stopped.
      }
    }
    this.#sources.clear();
    this.#pending = [];
    this.#finish('stopped');
  }

  #pump() {
    if (!this.#ctx || this.#finished) return;
    if (!this.#playing) {
      if (this.#buffered < JITTER_S && !this.#ended) return;
      this.#playing = true;
      this.#next = this.#ctx.currentTime + LEAD_S;
    }
    for (const samples of this.#pending) {
      const now = this.#ctx.currentTime;
      if (this.#next < now + LATE_S) this.#next = now + LEAD_S;
      const buffer = this.#ctx.createBuffer(1, samples.length, this.rate);
      buffer.copyToChannel(samples, 0);
      const src = this.#ctx.createBufferSource();
      src.buffer = buffer;
      src.connect(this.#out);
      src.onended = () => {
        this.#sources.delete(src);
        this.#settle();
      };
      src.start(this.#next);
      if (this.onFirstSound) {
        this.onFirstSound(this.#next - now);
        this.onFirstSound = null;
      }
      this.#sources.add(src);
      this.#next += buffer.duration;
    }
    this.#pending = [];
    this.#buffered = 0;
    this.#settle();
  }

  #settle() {
    if (this.#ended && this.#playing && !this.#pending.length && !this.#sources.size) this.#finish('played');
  }

  #finish(outcome) {
    if (this.#finished) return;
    this.#finished = true;
    this.#resolve(outcome);
  }
}
