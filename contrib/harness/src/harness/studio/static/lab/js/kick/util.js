// The kick surface's small parts: one frame loop that draws only what is on screen, canvas sizing, a Max-style
// number box, and the colours a canvas needs (it cannot read CSS variables).

import { drag, h, standard } from '../ui.js';
import { follow, shortLabel, writer } from '../widgets/core.js';

export const C = {
  bg: '#0a0a0b', steel0: '#111214', steel1: '#17191c', steel2: '#202328', steel3: '#2c3036', steel4: '#3b4048',
  text: '#e9e7e2', text2: '#a4a19a', text3: '#6d6a65',
  hazard: '#ff5a1f', acid: '#c6ff3d', lcd: '#ffb547', cold: '#59c7ff', alarm: '#ff2e4d',
};
export const rgba = (hex, a) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
};
export const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';

/**
 * One requestAnimationFrame loop for the surface. add(el, draw, {always}) draws `el`'s picture when it is on screen:
 * every frame if `always`, else when marked dirty (mark()). Stops on unmount.
 */
export class Painter {
  constructor(ctx) {
    this.items = [];
    this.alive = true;
    this.io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        const it = this.items.find((x) => x.el === e.target);
        if (it) { it.visible = e.isIntersecting; if (it.visible) it.dirty = true; }
      }
    });
    const loop = (t) => {
      if (!this.alive) return;
      for (const it of this.items) {
        if (!it.visible || it.broken || !(it.always || it.dirty)) continue;
        it.dirty = false;
        try { it.draw(t); } catch (err) { it.broken = true; console.error(err); }
      }
      this.raf = requestAnimationFrame(loop);
    };
    this.raf = requestAnimationFrame(loop);
    ctx.own(() => { this.alive = false; cancelAnimationFrame(this.raf); this.io.disconnect(); this.items.length = 0; });
  }

  add(el, draw, { always = false } = {}) {
    const it = { el, draw, always, visible: false, dirty: true };
    this.items.push(it);
    this.io.observe(el);
    return () => { it.dirty = true; };
  }
}

/** A canvas filling its box: fit() sizes it for the screen and returns {g, W, H, k (device px per CSS px), w, h}. */
export function canvas(cls = 'kx-cv') {
  const cv = h('canvas', { class: cls });
  cv.fit = () => {
    const r = cv.getBoundingClientRect();
    const k = Math.min(3, window.devicePixelRatio || 1);
    const W = Math.max(1, Math.round(r.width * k)), H = Math.max(1, Math.round(r.height * k));
    if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
    const g = cv.getContext('2d');
    g.setTransform(1, 0, 0, 1, 0, 0);
    return { g, W, H, k, w: r.width, h: r.height };
  };
  return cv;
}

/**
 * Max's number box for one param: an LCD with its label. Drag up or right to raise (`span` px for the whole range;
 * two fingers or hold-then-drag: fine). Double tap: the set's value. Long press: the inspector.
 */
export function numbox(ctx, id, { label, span = 240, cls = '' } = {}) {
  const p = ctx.params.get(id);
  const w = writer(ctx, id, 'numbox');
  const val = h('b', { class: 'kx-num-v' });
  const el = h('div', {
    class: `kx-num ${cls}`.trim(), role: 'slider', tabindex: '0', 'aria-label': p.label, dataset: { kparam: id },
  }, h('span', { class: 'kx-num-l', text: label ?? shortLabel(p) }), val);
  follow(ctx, id, (_v, _real, text) => {
    val.textContent = text;
    el.setAttribute('aria-valuetext', text);
    el.classList.toggle('is-set', ctx.store.isSet(id));
  });
  drag(el, {
    onStart: () => { w.begin(); el.classList.add('is-touched'); },
    onMove: (dx, dy) => w.add((dx - dy) / span),
    onEnd: () => { w.end(); el.classList.remove('is-touched'); },
  });
  standard(el, ctx.store, id);
  return el;
}

/** A plain titled panel in the lab's rack style, with our own class. */
export function panel(title, { sub, cls = '', note } = {}, ...children) {
  return h('section', { class: `rack kx-rack ${cls}`.trim() },
    h('div', { class: 'rack-head' }, h('span', { class: 'rack-title', text: title }), sub ? h('span', { class: 'rack-sub', text: sub }) : null),
    ...children,
    note ? h('p', { class: 'rack-note', text: note }) : null);
}

/** Log-frequency axis helpers for a plot from f0 to f1 over a width. */
export function logAxis(f0, f1) {
  const l0 = Math.log(f0), l1 = Math.log(f1);
  return { x: (f, W) => ((Math.log(f) - l0) / (l1 - l0)) * W, f: (x, W) => Math.exp(l0 + (x / W) * (l1 - l0)) };
}

export const fmtHz = (f) => (f >= 1000 ? `${(f / 1000).toFixed(f >= 10000 ? 0 : 1)}k` : `${Math.round(f)}`);
