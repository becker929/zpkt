// RESAMPLE: record `seconds` of a node's output from `when` (audio clock) into a new AudioBuffer. An AudioWorklet
// copies the exact frames; where there is no AudioWorklet, a ScriptProcessor does it to within a block.

const READY = new WeakMap();

function workletReady(ctx) {
  if (!ctx.audioWorklet) return Promise.resolve(false);
  if (!READY.has(ctx)) {
    READY.set(ctx, ctx.audioWorklet.addModule(new URL('./recorder-worklet.js', import.meta.url).href)
      .then(() => true).catch((err) => { console.warn('collage: no AudioWorklet recorder', err); return false; }));
  }
  return READY.get(ctx);
}

/** Load the worklet ahead of the first REC (so pressing REC never waits on a fetch). */
export function warmRecorder(ctx) { return workletReady(ctx); }

/**
 * Resolve to an AudioBuffer of `seconds` from `source`, starting at `when`. `cancel` (an object) gets a
 * cancel() you can call to abandon it.
 */
export async function record(ctx, source, { when, seconds, cancel = {} }) {
  const frames = Math.round(seconds * ctx.sampleRate);
  const startFrame = Math.round(when * ctx.sampleRate);
  const sink = ctx.createGain();
  sink.gain.value = 0;
  sink.connect(ctx.destination);
  const done = (L, R) => {
    const buf = ctx.createBuffer(2, frames, ctx.sampleRate);
    buf.getChannelData(0).set(L.subarray(0, frames));
    buf.getChannelData(1).set(R.subarray(0, frames));
    return buf;
  };
  if (await workletReady(ctx)) {
    const node = new AudioWorkletNode(ctx, 'hw002-collage-rec', {
      numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [2], channelCount: 2, channelCountMode: 'explicit',
    });
    source.connect(node);
    node.connect(sink);
    try {
      return await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error('the recorder did not answer')), (when - ctx.currentTime + seconds + 3) * 1000);
        cancel.cancel = () => { clearTimeout(timeout); reject(new Error('cancelled')); };
        node.port.onmessage = (e) => { clearTimeout(timeout); resolve(done(e.data.L, e.data.R)); };
        node.port.postMessage({ start: startFrame, frames });
      });
    } finally {
      try { source.disconnect(node); } catch { /* */ }
      try { node.disconnect(); sink.disconnect(); } catch { /* */ }
      node.port.onmessage = null;
    }
  }
  // fallback: a ScriptProcessor, aligned by each block's playbackTime
  const sp = ctx.createScriptProcessor(4096, 2, 2);
  const L = new Float32Array(frames), R = new Float32Array(frames);
  source.connect(sp);
  sp.connect(sink);
  try {
    return await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('the recorder did not answer')), (when - ctx.currentTime + seconds + 3) * 1000);
      cancel.cancel = () => { clearTimeout(timeout); reject(new Error('cancelled')); };
      sp.onaudioprocess = (e) => {
        const f0 = Math.round(e.playbackTime * ctx.sampleRate);
        const inL = e.inputBuffer.getChannelData(0), inR = e.inputBuffer.numberOfChannels > 1 ? e.inputBuffer.getChannelData(1) : inL;
        const n = inL.length;
        const a = Math.max(f0, startFrame), b = Math.min(f0 + n, startFrame + frames);
        for (let f = a; f < b; f++) { L[f - startFrame] = inL[f - f0]; R[f - startFrame] = inR[f - f0]; }
        if (f0 + n >= startFrame + frames) { clearTimeout(timeout); resolve(done(L, R)); }
      };
    });
  } finally {
    sp.onaudioprocess = null;
    try { source.disconnect(sp); sp.disconnect(); sink.disconnect(); } catch { /* */ }
  }
}
