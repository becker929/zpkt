// The resampler's tape head, on the audio thread: copies exactly the frames it was asked for (from `start`, `frames`
// long, in the context's frame count) and posts them back. Sample-accurate, so a resample lands on the bar.

class Rec extends AudioWorkletProcessor {
  constructor() {
    super();
    this.job = null;
    this.port.onmessage = (e) => {
      const { start, frames } = e.data;
      this.job = { start, frames, L: new Float32Array(frames), R: new Float32Array(frames) };
    };
  }

  process(inputs) {
    const j = this.job;
    if (!j) return true;
    const input = inputs[0] || [];
    const n = input[0] ? input[0].length : 128;
    const f0 = currentFrame;
    const a = Math.max(f0, j.start), b = Math.min(f0 + n, j.start + j.frames);
    if (b > a && input[0]) {
      const l = input[0], r = input[1] || input[0];
      for (let f = a; f < b; f++) { j.L[f - j.start] = l[f - f0]; j.R[f - j.start] = r[f - f0]; }
    }
    if (f0 + n >= j.start + j.frames) {
      this.port.postMessage({ L: j.L, R: j.R }, [j.L.buffer, j.R.buffer]);
      this.job = null;
    }
    return true;
  }
}

registerProcessor('hw002-collage-rec', Rec);
