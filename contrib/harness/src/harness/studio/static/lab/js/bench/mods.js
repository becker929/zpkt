// The Bench's modulators: Max's signal objects as control sources on the bar clock.
//
//   cycle~   a sine LFO
//   phasor~  a ramp (up or down)
//   noise    random steps, held for each period (sample and hold)
//   step     a 16-step sequence over its period (draw the steps on its display)
//   env      a drawn shape over its period (draw it with a finger)
//
// Each has a rate (1/16 of a bar up to 16 bars, on the bar grid: phase 0 is a downbeat) and a depth (how much of
// the patched param's range it moves). cycle~ and noise swing both ways around the knob (±) or only up (+);
// phasor~, step and env only push up. Patch an outlet into a param object's inlet and the param moves (a
// modulation on top of its knob, not saved); into another modulator's inlet, it scales that one's depth.

import { h, haptic, s } from '../ui.js';
import { fitCanvas, HEX, localCtx, rgba } from '../widgets/kit.js';
import { numberBox } from '../widgets/numbox.js';

export const RATES = [
  ['1/16', 1 / 16], ['1/8', 1 / 8], ['1 beat', 1 / 4], ['2 beats', 1 / 2], ['1 bar', 1], ['2 bars', 2], ['4 bars', 4], ['8 bars', 8], ['16 bars', 16],
];
const rateIndex = (bars) => Math.max(0, RATES.findIndex((r) => Math.abs(r[1] - bars) < 1e-6));

export const MODS = {
  cycle: { cls: 'cycle~', about: 'A sine LFO: the param swells and falls.', rate: 4, depth: 20, pol: 0 },
  phasor: { cls: 'phasor~', about: 'A ramp: the param climbs through the period and drops back.', rate: 1, depth: 25, dir: 0 },
  noise: { cls: 'noise', about: 'Random steps: a new value each period, held.', rate: 1 / 4, depth: 15, pol: 0, glide: 0 },
  step: { cls: 'step', about: 'A 16-step sequence over the period. Draw the steps.', rate: 1, depth: 30 },
  env: { cls: 'env', about: 'A shape you draw, over the period.', rate: 1, depth: 30 },
};

const frac = (x) => x - Math.floor(x);
const hash = (k, seed) => { const x = Math.sin((k + 1) * 12.9898 + seed * 78.233) * 43758.5453; return frac(x); };
const smooth = (t) => t * t * (3 - 2 * t);

/** A default pattern for `step`: accents on the offbeats, a lift at the end of the bar. */
export const defaultSteps = () => [0, 0, 0.7, 0, 0, 0, 0.7, 0.2, 0, 0, 0.7, 0, 0.3, 0.5, 0.8, 1];
/** A default shape for `env`: four pumps a bar (a sidechain duck turned upside down: up on the offbeat). */
export const defaultEnv = () => Array.from({ length: 32 }, (_, i) => { const x = frac(i / 8); return Math.round(Math.pow(Math.sin(Math.PI * x), 2) * 100) / 100; });

/** The settings a modulator keeps in the patch (obj.state), with its type's defaults filled in. */
export function modState(type, state = {}) {
  const d = MODS[type];
  return {
    rate: d.rate, depth: d.depth, pol: d.pol ?? 0, dir: d.dir ?? 0, glide: d.glide ?? 0, seed: Math.floor(Math.random() * 1000),
    ...(type === 'step' ? { steps: defaultSteps() } : {}), ...(type === 'env' ? { env: defaultEnv() } : {}),
    ...state,
  };
}

/** The modulator's raw shape at bar time t: -1..1 for a two-way swing, 0..1 for one-way. Returns [value, phase]. */
export function shape(type, st, t) {
  const bars = st.rate || 1;
  const ph = frac(t / bars);
  switch (type) {
    case 'cycle': return [st.pol ? 0.5 - 0.5 * Math.cos(2 * Math.PI * ph) : Math.sin(2 * Math.PI * ph), ph];
    case 'phasor': return [st.dir ? 1 - ph : ph, ph];
    case 'noise': {
      const k = Math.floor(t / bars);
      let v = hash(k, st.seed);
      if (st.glide > 0) v = hash(k - 1, st.seed) + (v - hash(k - 1, st.seed)) * smooth(Math.min(1, ph / Math.max(0.01, st.glide / 100)));
      return [st.pol ? v : v * 2 - 1, ph];
    }
    case 'step': {
      const steps = st.steps ?? defaultSteps();
      return [steps[Math.min(steps.length - 1, Math.floor(ph * steps.length))] ?? 0, ph];
    }
    case 'env': {
      const env = st.env ?? defaultEnv();
      const x = ph * env.length, i = Math.floor(x), f = x - i;
      const a = env[i % env.length], b = env[(i + 1) % env.length];
      return [a + (b - a) * f, ph];
    }
    default: return [0, ph];
  }
}

export const twoWay = (type, st) => (type === 'cycle' || type === 'noise') && !st.pol;

/**
 * The modulator's body in its object box: a display (the shape over one period with a moving playhead; draw on
 * it for step and env), a two-way/one-way switch where it has one, and number boxes for rate and depth.
 * Returns {el, draw(t, out), title()}.
 */
export function modBody(octx, obj, onChange) {
  const type = obj.type, st = obj.state;
  const defs = [
    { id: 'rate', label: 'Rate', short: 'rate', scale: 'enum', options: RATES.map((r) => r[0]), min: 0, max: RATES.length - 1, set: rateIndex(MODS[type].rate) },
    { id: 'depth', label: 'Depth', short: 'depth', unit: '%', min: 0, max: 100, set: MODS[type].depth },
  ];
  const lctx = localCtx(octx, defs, { rate: rateIndex(st.rate) / (RATES.length - 1), depth: st.depth / 100 }, (id, _v, real) => {
    if (id === 'rate') st.rate = RATES[Math.round(real)][1];
    if (id === 'depth') st.depth = real;
    onChange();
  });

  let ver = 0;                                              // bumps when the shape changes, so the display redraws it
  const changed = () => { ver++; onChange(); };
  const cv = h('canvas', { class: 'md-cv' });
  const chip = (type === 'cycle' || type === 'noise' || type === 'phasor')
    ? h('button', { type: 'button', class: 'md-chip', 'aria-label': type === 'phasor' ? 'Ramp up or down' : 'Both ways or up only' })
    : null;
  const paintChip = () => { if (chip) chip.textContent = type === 'phasor' ? (st.dir ? 'down' : 'up') : st.pol ? '+' : '±'; };
  paintChip();
  chip?.addEventListener('click', (e) => {
    e.stopPropagation();
    if (type === 'phasor') st.dir = st.dir ? 0 : 1; else st.pol = st.pol ? 0 : 1;
    paintChip(); haptic(); changed();
  });
  const display = h('div', { class: `md-display${type === 'step' || type === 'env' ? ' is-draw' : ''}` }, cv, chip);
  const el = h('div', { class: 'md' }, display,
    h('div', { class: 'md-ctl' }, numberBox(lctx, 'rate', { width: 84 }), numberBox(lctx, 'depth', { width: 66 })));

  if (type === 'step' || type === 'env') drawOn(display, cv, st, type, changed);

  // the display: one period of the shape, a playhead, the output level
  let shapeCache = null, cacheKey = '';
  const draw = (t, out) => {
    const { g, W, H, d } = fitCanvas(cv);
    const win = type === 'noise' ? Math.floor(t / st.rate / 4) : 0;
    const key = `${win}:${W}x${H}:${ver}:${st.rate}`;
    const two = twoWay(type, st);
    const Y = (v) => (two ? H / 2 - v * (H / 2 - 4 * d) : H - 3 * d - v * (H - 7 * d));
    if (key !== cacheKey) {
      cacheKey = key;
      shapeCache = new Path2D();
      if (type === 'step') {
        const n = st.steps.length;
        for (let i = 0; i < n; i++) shapeCache.rect((i / n) * W + d, Y(st.steps[i]), W / n - 2 * d, Y(0) - Y(st.steps[i]));
      } else {
        const N = 96;
        for (let i = 0; i <= N; i++) {
          const v = type === 'noise' ? shape(type, st, (win * 4 + (i / N) * 4) * st.rate - 1e-9)[0] : shape(type, { ...st, rate: 1 }, i / N)[0];
          if (i) shapeCache.lineTo((i / N) * W, Y(v)); else shapeCache.moveTo(0, Y(v));
        }
      }
    }
    g.clearRect(0, 0, W, H);
    g.strokeStyle = 'rgba(255,255,255,0.06)'; g.lineWidth = d;
    g.beginPath();
    for (let i = 1; i < 4; i++) { g.moveTo((W * i) / 4, 0); g.lineTo((W * i) / 4, H); }
    if (two) { g.moveTo(0, H / 2); g.lineTo(W, H / 2); }
    g.stroke();
    const [, ph] = shape(type, st, t);
    const px = type === 'noise' ? ((t / st.rate) % 4) / 4 * W : ph * W;
    if (type === 'step') {
      g.fillStyle = rgba(HEX.cold, 0.55); g.fill(shapeCache);
      const n = st.steps.length, i = Math.min(n - 1, Math.floor(ph * n));
      g.fillStyle = HEX.cold; g.fillRect((i / n) * W + d, Y(st.steps[i]), W / n - 2 * d, Y(0) - Y(st.steps[i]) + 0.01);
    } else {
      g.strokeStyle = rgba(HEX.cold, 0.9); g.lineWidth = 1.6 * d; g.stroke(shapeCache);
    }
    g.fillStyle = 'rgba(255,255,255,0.5)'; g.fillRect(px - 0.5 * d, 0, d, H);
    const depth = Math.max(0.0001, st.depth / 100);
    const v = out / depth;
    g.fillStyle = '#fff'; g.shadowColor = HEX.cold; g.shadowBlur = 8 * d;
    g.beginPath(); g.arc(px, Y(Math.max(-1, Math.min(1, v))), 3.2 * d, 0, Math.PI * 2); g.fill();
    g.shadowBlur = 0;
  };
  const title = () => `${MODS[type].cls} ${RATES[rateIndex(st.rate)]?.[0] ?? ''}`;
  return { el, draw, title };
}

/** Draw the steps or the env shape with a finger (absolute: the display is a drawing). */
function drawOn(display, cv, st, type, onChange) {
  display.style.touchAction = 'none';
  const list = () => (type === 'step' ? st.steps : st.env);
  let pid = null, last = null;
  const at = (e) => {
    const r = cv.getBoundingClientRect();
    const n = list().length;
    const i = Math.max(0, Math.min(n - 1, Math.floor(((e.clientX - r.left) / r.width) * n)));
    const v = Math.max(0, Math.min(1, 1 - (e.clientY - r.top - 3) / (r.height - 7)));
    return { i, v: Math.round(v * 20) / 20 };
  };
  const put = (e) => {
    const cur = at(e), arr = list();
    if (last && last.i !== cur.i) {
      const dir = cur.i > last.i ? 1 : -1;
      for (let j = last.i + dir; j !== cur.i; j += dir) arr[j] = last.v + (cur.v - last.v) * ((j - last.i) / (cur.i - last.i));
    }
    if (arr[cur.i] !== cur.v && type === 'step') haptic();
    arr[cur.i] = cur.v;
    last = cur;
    onChange();                                             // the display redraws as you draw; the patch saves (debounced)
  };
  display.addEventListener('pointerdown', (e) => {
    if (e.target.closest('.md-chip') || pid != null) return;
    pid = e.pointerId; last = null;
    try { display.setPointerCapture(e.pointerId); } catch { /* synthetic pointer */ }
    put(e);
  });
  display.addEventListener('pointermove', (e) => { if (e.pointerId === pid) put(e); });
  const up = (e) => { if (e.pointerId !== pid) return; pid = null; last = null; onChange(); };
  display.addEventListener('pointerup', up);
  display.addEventListener('pointercancel', up);
}

/** A tiny icon per modulator for the toolbox. */
export function modIcon(type) {
  const d = {
    cycle: 'M2 12c2.5-8 5.5-8 8 0s5.5 8 8 0',
    phasor: 'M2 18L11 6v12l9-12v12',
    noise: 'M2 14h4v-6h4v9h4v-12h4v7h4',
    step: 'M3 18v-5M7 18v-9M11 18v-3M15 18v-11M19 18v-7',
    env: 'M2 18C5 4 7 4 9 12s4 6 6 0 4-8 7 6',
  }[type];
  return s('svg', { viewBox: '0 0 24 24', class: 'bn-ic', 'aria-hidden': 'true' }, s('path', { d }));
}
