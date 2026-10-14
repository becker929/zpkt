// Small parts the collage's panels share: canvases sized to the screen, inline SVG icons, a latching button, a
// Max-style number box (drag up and down to change it), and a tiny event bus.

import { drag, h, haptic } from '../ui.js';

/** Keep a canvas's backing store at its CSS size x device pixels. Returns {g, w, h, dpr, dirty()}. */
export function fit(canvas, onResize) {
  const st = { g: canvas.getContext('2d'), w: 0, h: 0, dpr: 1, changed: true };
  const measure = () => {
    const r = canvas.getBoundingClientRect();
    const dpr = Math.min(3, window.devicePixelRatio || 1);
    const W = Math.max(1, Math.round(r.width * dpr)), H = Math.max(1, Math.round(r.height * dpr));
    if (W !== canvas.width || H !== canvas.height) { canvas.width = W; canvas.height = H; st.changed = true; }
    st.w = r.width; st.h = r.height; st.dpr = dpr;
    if (st.changed) onResize?.(st);
  };
  st.measure = measure;
  st.ro = new ResizeObserver(measure);
  st.ro.observe(canvas);
  measure();
  return st;
}

// --- icons (24 x 24, stroked) -------------------------------------------------------------------------------------
const P = {
  grain: '<circle cx="5" cy="7" r="1.6"/><circle cx="11" cy="5" r="1.1"/><circle cx="17" cy="8" r="2"/><circle cx="8" cy="13" r="2.2"/><circle cx="15" cy="15" r="1.3"/><circle cx="6" cy="19" r="1.1"/><circle cx="19" cy="19" r="1.7"/>',
  slice: '<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>',
  tape: '<circle cx="7" cy="11" r="4"/><circle cx="17" cy="11" r="4"/><circle cx="7" cy="11" r="1"/><circle cx="17" cy="11" r="1"/><path d="M3 19h18M7 15l-2 4M17 15l2 4"/>',
  bed: '<path d="M3 6h18M3 12h18M3 18h18"/><rect x="5" y="4" width="6" height="4" rx="1"/><rect x="12" y="10" width="7" height="4" rx="1"/><rect x="4" y="16" width="9" height="4" rx="1"/>',
  rack: '<circle cx="7" cy="8" r="3.2"/><circle cx="17" cy="8" r="3.2"/><path d="M7 8l1.6-2M17 8l-2 .8"/><path d="M5 15v6M12 15v6M19 15v6"/><rect x="3.5" y="16" width="3" height="2" rx=".6"/><rect x="10.5" y="18" width="3" height="2" rx=".6"/><rect x="17.5" y="15.5" width="3" height="2" rx=".6"/>',
  dice: '<rect x="3.5" y="3.5" width="17" height="17" rx="4"/><circle cx="8.5" cy="8.5" r="1.3" fill="currentColor"/><circle cx="15.5" cy="15.5" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/><circle cx="15.5" cy="8.5" r="1.3" fill="currentColor"/><circle cx="8.5" cy="15.5" r="1.3" fill="currentColor"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
  play: '<path d="M8 5v14l11-7z"/>',
  rec: '<circle cx="12" cy="12" r="6.5" fill="currentColor"/>',
  freeze: '<path d="M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9M9.5 4.5L12 7l2.5-2.5M9.5 19.5L12 17l2.5 2.5"/>',
  ghost: '<path d="M6 20V10a6 6 0 0 1 12 0v10l-2-1.5-2 1.5-2-1.5-2 1.5-2-1.5z"/><circle cx="10" cy="10" r="1" fill="currentColor"/><circle cx="14" cy="10" r="1" fill="currentColor"/>',
  minus: '<path d="M6 12h12"/>',
  plus: '<path d="M6 12h12M12 6v12"/>',
  undo: '<path d="M9 7L4 12l5 5"/><path d="M4 12h10a6 6 0 0 1 0 12"/>',
  trash: '<path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13"/>',
  ear: '<path d="M7 10a5 5 0 0 1 10 0c0 3-3 4-3 7a3 3 0 0 1-6 0"/><path d="M10 10a2 2 0 0 1 4 0"/>',
  arrowL: '<path d="M15 5l-7 7 7 7"/>',
  arrowR: '<path d="M9 5l7 7-7 7"/>',
  up: '<path d="M6 15l6-6 6 6"/>',
  down: '<path d="M6 9l6 6 6-6"/>',
  rev: '<path d="M20 12H5M10 6l-6 6 6 6"/><path d="M20 6v12"/>',
  tilt: '<rect x="8" y="3.5" width="8" height="17" rx="2" transform="rotate(-20 12 12)"/><path d="M3.5 17.5a9 9 0 0 0 4 3.5M20.5 6.5a9 9 0 0 0-4-3.5"/>',
  scissors: '<circle cx="6" cy="7" r="2.6"/><circle cx="6" cy="17" r="2.6"/><path d="M8.2 8.4L20 17M8.2 15.6L20 7"/>',
};

export function icon(name, cls = '') {
  const span = h('span', { class: `cl-ico ${cls}`.trim(), 'aria-hidden': 'true' });
  span.innerHTML = `<svg viewBox="0 0 24 24">${P[name] ?? ''}</svg>`;
  return span;
}

/** A latching hardware button with an LED: latch(label, {icon, on, onChange}) -> el with .set(bool). */
export function latch(label, { icon: ic, on = false, onChange, cls = '', title } = {}) {
  const el = h('button', { type: 'button', class: `cl-latch ${cls}`.trim(), 'aria-pressed': String(on), title: title ?? label },
    h('i', { class: 'cl-led' }), ic ? icon(ic) : null, h('span', { text: label }));
  el.set = (v) => { on = !!v; el.setAttribute('aria-pressed', String(on)); el.classList.toggle('is-on', on); };
  el.set(on);
  el.addEventListener('click', () => { el.set(!on); haptic(); onChange?.(on); });
  return el;
}

/** A momentary hardware button: push(label, fn, {icon}). */
export function push(label, fn, { icon: ic, cls = '', title } = {}) {
  const el = h('button', { type: 'button', class: `cl-push ${cls}`.trim(), title: title ?? label, 'aria-label': title ?? label },
    ic ? icon(ic) : null, label ? h('span', { text: label }) : null);
  el.addEventListener('click', (e) => { haptic(); fn(e); });
  return el;
}

/**
 * A Max number box: an LCD you drag up (more) or down (less), in steps; arrows to tap. opts: label, get(), set(v),
 * fmt(v), step, min, max, px (pixels per step).
 */
export function numbox({ label, get, set, fmt = String, step = 1, min = -Infinity, max = Infinity, px = 14 }) {
  const lcd = h('span', { class: 'cl-num-lcd' });
  const dn = h('button', { type: 'button', class: 'cl-num-arr', 'aria-label': `${label} down` }, icon('down'));
  const up = h('button', { type: 'button', class: 'cl-num-arr', 'aria-label': `${label} up` }, icon('up'));
  const el = h('div', { class: 'cl-num' }, h('span', { class: 'cl-num-label', text: label }), h('div', { class: 'cl-num-row' }, dn, lcd, up));
  const render = () => { lcd.textContent = fmt(get()); };
  const bump = (d) => {
    const v = Math.min(max, Math.max(min, Math.round((get() + d * step) / step) * step));
    if (v !== get()) { set(v); haptic(); }
    render();
  };
  dn.addEventListener('click', () => bump(-1));
  up.addEventListener('click', () => bump(1));
  let acc = 0;
  drag(lcd, {
    onStart: () => { acc = 0; },
    onMove: (_dx, dy, { fine }) => {
      acc -= dy / (fine ? px * 2 : px);
      while (acc >= 1) { bump(1); acc -= 1; }
      while (acc <= -1) { bump(-1); acc += 1; }
    },
  });
  el.render = render;
  render();
  return el;
}

/** A tiny event bus. */
export function bus() {
  const map = new Map();
  return {
    on(evt, fn) { if (!map.has(evt)) map.set(evt, new Set()); map.get(evt).add(fn); return () => map.get(evt)?.delete(fn); },
    emit(evt, ...args) { for (const fn of map.get(evt) ?? []) { try { fn(...args); } catch (err) { console.error(err); } } },
  };
}
