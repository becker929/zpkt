// The mic, resampled to 16 kHz mono and cut into signed 16-bit little-endian frames for the Mac.
//
// Runs on the audio thread. The input arrives at the context's rate (44.1 or 48 kHz on a phone) in
// 128-sample blocks; a windowed-sinc low-pass filter (cut just under the new Nyquist, so nothing
// above 8 kHz folds back into the speech band) is evaluated at each output instant.

const HALF_WIDTH = 10;       // filter half-width, in output samples
const PHASES = 256;          // fractional positions with a precomputed filter row

class Resampler {
  constructor(inRate, outRate) {
    this.step = inRate / outRate;                         // input samples per output sample
    const scale = Math.max(1, this.step);
    this.half = Math.ceil(HALF_WIDTH * scale);            // taps on each side, in input samples
    this.taps = 2 * this.half;
    const cutoff = 0.45 / scale;                          // cycles per input sample
    this.table = new Float32Array((PHASES + 1) * this.taps);
    for (let p = 0; p <= PHASES; p += 1) {
      const row = p * this.taps;
      let sum = 0;
      for (let j = 0; j < this.taps; j += 1) {
        const x = p / PHASES + this.half - 1 - j;          // input samples from the output instant to tap j
        const u = x / this.half;
        const window = 0.42 + 0.5 * Math.cos(Math.PI * u) + 0.08 * Math.cos(2 * Math.PI * u);
        const v = sinc(2 * cutoff * x) * window;
        this.table[row + j] = v;
        sum += v;
      }
      for (let j = 0; j < this.taps; j += 1) this.table[row + j] /= sum;   // unity gain
    }
    this.buf = new Float32Array(this.taps + 4096);
    this.len = this.half;                                 // silence before the first sample
    this.pos = this.half;                                 // the next output instant, in buf samples
  }

  /** Feed input samples; `emit(y)` gets each output sample. */
  process(input, emit) {
    if (this.len + input.length > this.buf.length) {
      const bigger = new Float32Array(2 * (this.len + input.length));
      bigger.set(this.buf.subarray(0, this.len));
      this.buf = bigger;
    }
    this.buf.set(input, this.len);
    this.len += input.length;
    while (Math.floor(this.pos) + this.half < this.len) {
      const i0 = Math.floor(this.pos);
      const row = Math.round((this.pos - i0) * PHASES) * this.taps;
      const base = i0 - this.half + 1;
      let y = 0;
      for (let j = 0; j < this.taps; j += 1) y += this.buf[base + j] * this.table[row + j];
      emit(y);
      this.pos += this.step;
    }
    const used = Math.floor(this.pos) - this.half + 1;
    if (used > 0) {
      this.buf.copyWithin(0, used, this.len);
      this.len -= used;
      this.pos -= used;
    }
  }
}

function sinc(x) {
  if (x === 0) return 1;
  const px = Math.PI * x;
  return Math.sin(px) / px;
}

class MicFrames extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const { rate = 16000, frameMs = 20 } = options.processorOptions ?? {};
    this.resampler = new Resampler(sampleRate, rate);
    this.frameLength = Math.round((rate * frameMs) / 1000);
    this.stopped = false;
    this.emit = (y) => this.push(y);
    this.newFrame();
    this.port.onmessage = (e) => {
      if (e.data === 'stop') this.stopped = true;
    };
  }

  newFrame() {
    this.frame = new DataView(new ArrayBuffer(this.frameLength * 2));
    this.fill = 0;
    this.energy = 0;
  }

  push(y) {
    const s = y > 1 ? 1 : y < -1 ? -1 : y;
    this.frame.setInt16(this.fill * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    this.energy += s * s;
    this.fill += 1;
    if (this.fill === this.frameLength) {
      const rms = Math.sqrt(this.energy / this.frameLength);
      this.port.postMessage({ pcm: this.frame.buffer, rms }, [this.frame.buffer]);
      this.newFrame();
    }
  }

  process(inputs) {
    if (this.stopped) return false;
    const channels = inputs[0];
    if (channels?.length) {
      let mono = channels[0];
      if (channels.length > 1) {
        mono = new Float32Array(mono.length);
        for (const ch of channels) for (let i = 0; i < ch.length; i += 1) mono[i] += ch[i] / channels.length;
      }
      this.resampler.process(mono, this.emit);
    }
    return true;
  }
}

registerProcessor('mic-frames', MicFrames);
