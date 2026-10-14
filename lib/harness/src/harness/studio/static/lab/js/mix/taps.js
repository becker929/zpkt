// The mix surface's ears: nodes hung off the engine's master and returns while the surface is open, and nothing
// else. Every connection made here is remembered and undone by detach().
//
//   master.out -> tap -> the meter worklet (loudness, true peak, crest, low-end correlation; js/mix/loudness-worklet.js)
//                     -> L/R analysers (spectrum, 32k FFT) and L/R scope analysers, and a 120 Hz low band for the scope
//   master.glue -> an analyser (the clipper's input level)
//   master.reverbOut -> return A's meter
//   master.delayOut (return B, after its level) -> return B's meter
//   a bus's output -> the EQ editor's analyser (one bus at a time)

const loaded = new WeakMap();          // AudioContext -> addModule promise (a module loads once per context)

export function attachTaps(engine, onMeter) {
  const ctx = engine.ctx, m = engine.master;
  const links = [];
  const own = [];
  const link = (from, to, out, inp) => {
    if (out == null) from.connect(to); else from.connect(to, out, inp ?? 0);
    links.push([from, to, out, inp]);
    return to;
  };
  const node = (n) => { own.push(n); return n; };
  const analyser = (size, smooth = 0) => { const a = node(ctx.createAnalyser()); a.fftSize = size; a.smoothingTimeConstant = smooth; a.minDecibels = -140; a.maxDecibels = 0; return a; };
  const t = { ctx, alive: true, worklet: null, workletFailed: false };

  t.tap = node(ctx.createGain());
  link(m.out, t.tap);
  const split = node(ctx.createChannelSplitter(2));
  link(t.tap, split);
  t.specL = analyser(32768); t.specR = analyser(32768);
  link(split, t.specL, 0, 0); link(split, t.specR, 1, 0);
  t.scL = analyser(2048); t.scR = analyser(2048);
  link(split, t.scL, 0, 0); link(split, t.scR, 1, 0);
  // the low band for the scope: 4th-order low-pass at 120 Hz
  const lp1 = node(ctx.createBiquadFilter()), lp2 = node(ctx.createBiquadFilter());
  lp1.type = lp2.type = 'lowpass'; lp1.frequency.value = lp2.frequency.value = 120;
  lp1.Q.value = -5.33; lp2.Q.value = 2.32;            // Q in dB: 0.541 and 1.307, a Butterworth pair
  link(t.tap, lp1); link(lp1, lp2);
  const split2 = node(ctx.createChannelSplitter(2));
  link(lp2, split2);
  t.lowL = analyser(4096); t.lowR = analyser(4096);
  link(split2, t.lowL, 0, 0); link(split2, t.lowR, 1, 0);
  // the clipper's input
  t.glue = analyser(2048);
  link(m.glue, t.glue);
  // returns
  t.retA = analyser(1024);
  link(m.reverbOut, t.retA);
  t.retB = analyser(1024);
  link(m.delayOut, t.retB);
  // the EQ editor's bus
  t.eq = analyser(8192, 0);
  t.eqBus = null;

  /** Return B at `lin` (0 = silent, 1 = 0 dB): the engine's own return level. */
  t.setRetB = (lin) => engine.setMaster('delayLevel', lin);

  /** Point the EQ analyser at a bus ('kick', 'perc', 'sfx'). */
  t.eqSource = (name) => {
    if (t.eqBus === name) return;
    if (t.eqBus) { try { engine.bus(t.eqBus).output.disconnect(t.eq); } catch { /* gone */ } }
    t.eqBus = name;
    if (name) engine.bus(name).output.connect(t.eq);
  };

  // the meter
  const url = new URL('./loudness-worklet.js', import.meta.url).href;
  let job = loaded.get(ctx);
  if (!job && ctx.audioWorklet) { job = ctx.audioWorklet.addModule(url); loaded.set(ctx, job); }
  (job ?? Promise.reject(new Error('no AudioWorklet'))).then(() => {
    if (!t.alive) return;
    const w = new AudioWorkletNode(ctx, 'hw002-mix-meter', {
      numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
      channelCount: 2, channelCountMode: 'explicit', channelInterpretation: 'speakers',
    });
    t.sink = node(ctx.createGain()); t.sink.gain.value = 0;
    link(t.tap, w);
    w.connect(t.sink).connect(ctx.destination);       // keeps the worklet pulled on every browser; silent
    w.port.onmessage = (e) => { if (t.alive) onMeter(e.data); };
    t.worklet = w;
  }).catch(() => { t.workletFailed = true; });

  t.reset = () => t.worklet?.port.postMessage({ type: 'reset' });

  t.detach = () => {
    if (!t.alive) return;
    t.alive = false;
    t.setRetB(1);
    if (t.eqBus) { try { engine.bus(t.eqBus).output.disconnect(t.eq); } catch { /* gone */ } }
    if (t.worklet) {
      t.worklet.port.onmessage = null;
      t.worklet.port.postMessage({ type: 'stop' });
      try { t.worklet.disconnect(); } catch { /* fine */ }
      try { t.worklet.port.close(); } catch { /* fine */ }
    }
    for (const [from, to, out, inp] of links.reverse()) {
      try { if (out == null) from.disconnect(to); else from.disconnect(to, out, inp ?? 0); } catch { /* already */ }
    }
    for (const n of own) { try { n.disconnect(); } catch { /* fine */ } }
  };
  return t;
}

/** {rms, peak} in dBFS of an analyser's last block. */
export function levelOf(an, buf) {
  an.getFloatTimeDomainData(buf);
  let sum = 0, peak = 0;
  for (let i = 0; i < buf.length; i++) { const x = buf[i]; sum += x * x; const a = x < 0 ? -x : x; if (a > peak) peak = a; }
  return { rms: 10 * Math.log10(sum / buf.length + 1e-18), peak: 20 * Math.log10(peak + 1e-9) };
}
