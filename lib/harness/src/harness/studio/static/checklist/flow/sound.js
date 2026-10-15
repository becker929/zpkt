// The check's click: an interface sound, not music (docs/sound.md allows these), made on the spot like studio's
// ready cue. A short filtered noise tick for the contact and a quick high "tock" for the body, about 60 ms, quiet.
// The context is made on the first touch (iOS only starts one inside a gesture) and the click can be turned off.

const KEY = 'flow:sound';
const PEAK = 0.12;
let ctx = null;
let noise = null;

export const soundOn = () => { try { return localStorage.getItem(KEY) !== 'off'; } catch { return true; } };
export function setSound(on) { try { localStorage.setItem(KEY, on ? 'on' : 'off'); } catch { /* this visit only */ } }

/** Make (or resume) the context; call from inside a touch. */
export function wake() {
  if (!soundOn()) return;
  try {
    ctx ??= new AudioContext();
    if (ctx.state === 'suspended') ctx.resume();
  } catch { ctx = null; }
}

function noiseBuffer() {
  const len = Math.round(ctx.sampleRate * 0.03);
  const buf = ctx.createBuffer(1, len, ctx.sampleRate);
  const d = buf.getChannelData(0);
  let s = 0x2545f491;
  for (let i = 0; i < len; i++) { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; d[i] = ((s >>> 0) / 4294967296) * 2 - 1; }
  return buf;
}

/** The click. `strong` adds a low thump under it (a step finished). */
export function click(strong = false) {
  if (!soundOn() || !ctx || ctx.state !== 'running') return;
  const t = ctx.currentTime + 0.005;
  noise ??= noiseBuffer();
  const src = ctx.createBufferSource();
  src.buffer = noise;
  const bp = ctx.createBiquadFilter();
  bp.type = 'bandpass'; bp.frequency.value = 3800; bp.Q.value = 1.4;
  const ng = ctx.createGain();
  ng.gain.setValueAtTime(PEAK, t);
  ng.gain.exponentialRampToValueAtTime(0.001, t + 0.025);
  src.connect(bp).connect(ng).connect(ctx.destination);
  src.start(t); src.stop(t + 0.03);
  const tones = strong ? [[1760, 0.05, 0.7], [110, 0.12, 1]] : [[1760, 0.05, 0.7]];
  for (const [hz, len, gain] of tones) {
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.frequency.setValueAtTime(hz, t);
    osc.frequency.exponentialRampToValueAtTime(hz * 0.6, t + len);
    g.gain.setValueAtTime(PEAK * gain, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + len);
    osc.connect(g).connect(ctx.destination);
    osc.onended = () => g.disconnect();
    osc.start(t); osc.stop(t + len + 0.01);
  }
}
