// Small shared pieces for the mix surface: colours for canvas, canvas sizing, one frame loop that only draws what is
// on screen, biquad maths for EQ curves, and a canvas that lets the page scroll except where it can be grabbed.

import { h } from '../ui.js';

/** The lab's tokens, read once (a canvas cannot use var()). */
export function colours() {
  const cs = getComputedStyle(document.documentElement);
  const v = (n, d) => cs.getPropertyValue(n).trim() || d;
  return {
    acid: v('--acid', '#c6ff3d'), lcd: v('--lcd', '#ffb547'), cold: v('--cold', '#59c7ff'),
    hazard: v('--hazard', '#ff5a1f'), alarm: v('--alarm', '#ff2e4d'), text: v('--text', '#e9e7e2'),
    text2: v('--text-2', '#a4a19a'), text3: v('--text-3', '#6d6a65'), steel3: v('--steel-3', '#2c3036'),
    steel4: v('--steel-4', '#3b4048'), steel1: v('--steel-1', '#17191c'), bg: v('--bg', '#0a0a0b'),
    kick: v('--stage-kick', '#ff5a1f'), collage: v('--stage-collage', '#e0b7ff'),
  };
}

/** '#rrggbb' + alpha -> rgba(). */
export function rgba(hex, a) {
  const n = parseInt(hex.replace('#', ''), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

export const dbToLin = (db) => Math.pow(10, db / 20);
export const fmt = (x, d = 1, plus = false) => (x == null || !Number.isFinite(x) ? '—' : `${plus && x > 0 ? '+' : ''}${x.toFixed(d)}`);

/**
 * The surface's frame loop: add({el, draw(now)}) draws only while `el` is on screen and the page is visible.
 * stop() cancels everything.
 */
export function frameLoop() {
  const items = new Set();
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) for (const it of items) if (it.el === e.target) it.visible = e.isIntersecting;
  }, { threshold: 0 });
  const sizes = new WeakMap();
  const ro = new ResizeObserver((entries) => {
    for (const e of entries) sizes.set(e.target, { w: e.contentRect.width, h: e.contentRect.height });
  });
  let raf = 0, alive = true;
  const stats = { frames: 0, ms: 0 };          // time spent drawing (for the console: lab.mix.loop.stats)
  const frame = (now) => {
    if (!alive) return;
    raf = requestAnimationFrame(frame);
    if (document.hidden) return;
    const t0 = performance.now();
    for (const it of items) if (it.visible || it.always) { try { it.draw(now); } catch (err) { console.error(err); it.visible = false; it.always = false; } }
    stats.frames++; stats.ms += performance.now() - t0;
  };
  raf = requestAnimationFrame(frame);
  return {
    add(it) { it.visible = false; items.add(it); io.observe(it.el); return () => { items.delete(it); io.unobserve(it.el); }; },
    /** Track a canvas's CSS size (cheap: no layout reads per frame). */
    watch(cv) { ro.observe(cv); },
    size(cv) { return sizes.get(cv) ?? { w: cv.clientWidth, h: cv.clientHeight }; },
    stop() { alive = false; cancelAnimationFrame(raf); io.disconnect(); ro.disconnect(); items.clear(); },
    get count() { return items.size; },
    stats,
  };
}

/** A canvas sized to its box at the device's pixel ratio; returns the 2D context in CSS px. */
export function fit(loop, cv) {
  const { w, h: hh } = loop.size(cv);
  const dpr = Math.min(3, window.devicePixelRatio || 1);
  const W = Math.max(1, Math.round(w * dpr)), H = Math.max(1, Math.round(hh * dpr));
  if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { g, w, h: hh, dpr };
}

export function canvas(cls, loop) {
  const cv = h('canvas', { class: cls });
  loop.watch(cv);
  return cv;
}

// --- EQ maths (RBJ cookbook), magnitude in dB at frequency f ------------------------------------------------------
export function biquadCoefs(type, f0, q, gainDb, fs = 48000) {
  const A = Math.pow(10, gainDb / 40), w = 2 * Math.PI * Math.min(f0, fs * 0.49) / fs;
  const c = Math.cos(w), s = Math.sin(w);
  let b0, b1, b2, a0, a1, a2;
  if (type === 'peaking') {
    const al = s / (2 * q);
    b0 = 1 + al * A; b1 = -2 * c; b2 = 1 - al * A; a0 = 1 + al / A; a1 = -2 * c; a2 = 1 - al / A;
  } else if (type === 'lowshelf' || type === 'highshelf') {
    // WebAudio's shelves use S = 1
    const al = s / 2 * Math.SQRT2, sq = 2 * Math.sqrt(A) * al;
    if (type === 'lowshelf') {
      b0 = A * ((A + 1) - (A - 1) * c + sq); b1 = 2 * A * ((A - 1) - (A + 1) * c); b2 = A * ((A + 1) - (A - 1) * c - sq);
      a0 = (A + 1) + (A - 1) * c + sq; a1 = -2 * ((A - 1) + (A + 1) * c); a2 = (A + 1) + (A - 1) * c - sq;
    } else {
      b0 = A * ((A + 1) + (A - 1) * c + sq); b1 = -2 * A * ((A - 1) + (A + 1) * c); b2 = A * ((A + 1) + (A - 1) * c - sq);
      a0 = (A + 1) - (A - 1) * c + sq; a1 = 2 * ((A - 1) - (A + 1) * c); a2 = (A + 1) - (A - 1) * c - sq;
    }
  } else if (type === 'highpass' || type === 'lowpass') {
    const al = s / (2 * q);
    if (type === 'highpass') { b0 = (1 + c) / 2; b1 = -(1 + c); b2 = (1 + c) / 2; } else { b0 = (1 - c) / 2; b1 = 1 - c; b2 = (1 - c) / 2; }
    a0 = 1 + al; a1 = -2 * c; a2 = 1 - al;
  } else return null;
  return [b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0];
}

export function magDb(co, f, fs = 48000) {
  if (!co) return 0;
  const [b0, b1, b2, a1, a2] = co, w = 2 * Math.PI * f / fs;
  const c1 = Math.cos(w), s1 = Math.sin(w), c2 = Math.cos(2 * w), s2 = Math.sin(2 * w);
  const nr = b0 + b1 * c1 + b2 * c2, ni = -(b1 * s1 + b2 * s2);
  const dr = 1 + a1 * c1 + a2 * c2, di = -(a1 * s1 + a2 * s2);
  return 10 * Math.log10((nr * nr + ni * ni) / (dr * dr + di * di) + 1e-30);
}

/**
 * Let the page scroll over a canvas except where a finger lands on something it can grab: touch-action pan-y, and
 * a touchstart that claims the touch when `grab(point)` says so (or when two fingers land).
 */
export function scrollable(el, grab) {
  el.style.touchAction = 'pan-y';
  el.addEventListener('touchstart', (e) => {
    const t = e.touches[0];
    if (e.touches.length > 1 || (t && grab({ clientX: t.clientX, clientY: t.clientY }))) e.preventDefault();
  }, { passive: false });
}
