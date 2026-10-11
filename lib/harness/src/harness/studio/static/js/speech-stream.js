// One speech stream from the Mac: s16le PCM chunks, scheduled back to back on the audio clock.
//
// Chunks arrive over the network unevenly (the Mac sends 0.1 s frames). Playback starts once JITTER_S of audio is
// buffered (or the stream has ended), and later chunks are scheduled exactly where the previous one ends, so there
// are no gaps unless the network falls behind; a late chunk restarts just ahead of the clock.
//
// The browser resamples each buffer to the context's rate on its own, so a buffer cut off from its neighbours comes
// out wrong at its edges: a click at every seam. Each buffer therefore carries the sample before it and the sample
// after it, and plays only its own part. The newest chunk waits for the next one (its first sample is the one after)
// until the stream ends or the audio before it is about to run out.

const JITTER_S = 0.12;
const LEAD_S = 0.03;
const LATE_S = 0.01;
const HOLD_S = 0.05;        // the newest chunk is played without the sample after it this long before it is due

export class SpeechStream {
  kind = 'speech';
  #pending = [];            // Float32Array chunks waiting to be scheduled
  #buffered = 0;            // seconds in #pending
  #sources = new Set();
  #ctx = null;
  #out = null;
  #next = 0;                // audio-clock time where the next chunk starts
  #tail = null;             // the last sample scheduled, when the next chunk follows it without a gap
  #hold = 0;                // timer: play the held chunk before the audio runs out
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
    if (!n) return;
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
    const ready = this.#ended ? this.#pending.length : this.#pending.length - 1;
    if (ready > 0) this.#play(this.#pending.splice(0, ready), this.#ended ? null : this.#pending[0][0]);
    this.#holdUntilDue();
    this.#settle();
  }

  /** `chunks` back to back as one buffer, after what is scheduled; `after` is the sample that follows them, or null. */
  #play(chunks, after) {
    const ctx = this.#ctx;
    const now = ctx.currentTime;
    if (this.#next < now + LATE_S) {
      this.#next = now + LEAD_S;
      this.#tail = null;                             // a fresh start: nothing plays right before it
    }
    const n = chunks.reduce((sum, c) => sum + c.length, 0);
    const before = this.#tail === null ? 0 : 1;
    const buffer = ctx.createBuffer(1, before + n + (after === null ? 0 : 1), this.rate);
    const data = buffer.getChannelData(0);
    if (before) data[0] = this.#tail;
    let at = before;
    for (const c of chunks) {
      data.set(c, at);
      at += c.length;
      this.#buffered -= c.length / this.rate;
    }
    if (after !== null) data[at] = after;
    this.#tail = data[at - 1];
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(this.#out);
    src.onended = () => {
      this.#sources.delete(src);
      this.#settle();
    };
    src.start(this.#next, before / this.rate, n / this.rate);
    if (this.onFirstSound) {
      this.onFirstSound(this.#next - now);
      this.onFirstSound = null;
    }
    this.#sources.add(src);
    this.#next += n / this.rate;
    if (!this.#pending.length) this.#buffered = 0;
  }

  /** The held chunk plays without the sample after it if the next chunk has not come by the time it is due. */
  #holdUntilDue() {
    clearTimeout(this.#hold);
    if (!this.#playing || this.#ended || !this.#pending.length) return;
    const due = (this.#next - this.#ctx.currentTime - HOLD_S) * 1000;
    this.#hold = setTimeout(() => {
      if (this.#finished || this.#ended || !this.#pending.length) return;
      this.#play(this.#pending.splice(0), null);
    }, Math.max(0, due));
  }

  #settle() {
    if (this.#ended && this.#playing && !this.#pending.length && !this.#sources.size) this.#finish('played');
  }

  #finish(outcome) {
    if (this.#finished) return;
    this.#finished = true;
    clearTimeout(this.#hold);
    this.#resolve(outcome);
  }
}
