// The lab's small helpers: building elements, touch gestures sized for a big phone, haptics, toasts, and the
// inspector sheet every control opens on a long press.

import { format, setNorm, toReal } from './params.js';

const SVG = 'http://www.w3.org/2000/svg';

/** An element. Props: class, text, dataset, style (object), on<event>, anything else as an attribute. */
export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  return fill(el, props, children);
}

/** An SVG element, same props as h(). */
export function s(tag, props = {}, ...children) {
  const el = document.createElementNS(SVG, tag);
  return fill(el, props, children);
}

function fill(el, props, children) {
  for (const [key, value] of Object.entries(props)) {
    if (value == null || value === false) continue;
    if (key === 'class') el.setAttribute('class', value);
    else if (key === 'text') el.textContent = value;
    else if (key === 'dataset') Object.assign(el.dataset, value);
    else if (key === 'style' && typeof value === 'object') {
      for (const [k, v] of Object.entries(value)) if (k.startsWith('--')) el.style.setProperty(k, v); else el.style[k] = v;
    }
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat()) if (child != null && child !== false) el.append(child);
  return el;
}

export const clamp = (x, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, x));
export const lerp = (a, b, t) => a + (b - a) * t;

// --- haptics ---------------------------------------------------------------------------------------------------
// iPhone Safari has no vibrate(); toggling an <input switch> through its label gives a system tick (iOS 18+).
let lastTick = 0;
export function haptic(strong = false) {
  const now = performance.now();
  if (now - lastTick < 35) return;
  lastTick = now;
  if (navigator.vibrate) { navigator.vibrate(strong ? 18 : 6); return; }
  document.querySelector('label.haptic')?.click();
}

// --- gestures --------------------------------------------------------------------------------------------------
/**
 * Drag on `el`: onMove(dx, dy, {fine, x, y, e}) in CSS px since the last move. Two fingers down (or a press held
 * still for 350 ms before moving) is fine mode: a quarter of the speed. Calls onTap(e) for a press that did not move.
 */
export function drag(el, { onStart, onMove, onEnd, onTap, slop = 4 } = {}) {
  el.style.touchAction = 'none';
  let id = null, x0 = 0, y0 = 0, lx = 0, ly = 0, moved = false, t0 = 0, fine = false;
  const fingers = new Set();
  el.addEventListener('pointerdown', (e) => {
    fingers.add(e.pointerId);
    if (fingers.size > 1) { fine = true; return; }
    id = e.pointerId; x0 = lx = e.clientX; y0 = ly = e.clientY; moved = false; t0 = performance.now(); fine = false;
    try { el.setPointerCapture?.(e.pointerId); } catch { /* a synthetic pointer (tests) has nothing to capture */ }
    onStart?.(e);
  });
  el.addEventListener('pointermove', (e) => {
    if (e.pointerId !== id) return;
    if (!moved && Math.hypot(e.clientX - x0, e.clientY - y0) < slop) return;
    if (!moved) { moved = true; if (performance.now() - t0 > 350) fine = true; }
    const k = fine || e.altKey ? 0.25 : 1;
    onMove?.((e.clientX - lx) * k, (e.clientY - ly) * k, { fine: k < 1, x: e.clientX, y: e.clientY, e });
    lx = e.clientX; ly = e.clientY;
  });
  const up = (e) => {
    fingers.delete(e.pointerId);
    if (e.pointerId !== id) return;
    id = null;
    if (!moved && e.type === 'pointerup') onTap?.(e);
    onEnd?.(e, moved);
  };
  el.addEventListener('pointerup', up);
  el.addEventListener('pointercancel', up);
}

/** fn(e) after a press held still for `ms`. */
export function longPress(el, fn, ms = 480) {
  let timer = 0, x = 0, y = 0;
  const clear = () => clearTimeout(timer);
  el.addEventListener('pointerdown', (e) => {
    x = e.clientX; y = e.clientY;
    clear();
    timer = setTimeout(() => { haptic(true); fn(e); }, ms);
  });
  el.addEventListener('pointermove', (e) => { if (Math.hypot(e.clientX - x, e.clientY - y) > 8) clear(); });
  el.addEventListener('pointerup', clear);
  el.addEventListener('pointercancel', clear);
  el.addEventListener('contextmenu', (e) => e.preventDefault());
}

/** fn(e) on a second tap within 300 ms (a press that moved, a drag, is not a tap). */
export function doubleTap(el, fn) {
  let last = -Infinity, x = 0, y = 0;
  el.addEventListener('pointerdown', (e) => { x = e.clientX; y = e.clientY; });
  el.addEventListener('pointerup', (e) => {
    if (Math.hypot(e.clientX - x, e.clientY - y) > 10) { last = -Infinity; return; }
    const now = performance.now();
    if (now - last < 300) { last = -Infinity; fn(e); } else last = now;
  });
}

// --- toasts and the inspector -------------------------------------------------------------------------------
export function toast(text, ms = 1600) {
  const box = document.getElementById('toasts');
  if (!box) return;
  const el = h('div', { class: 'toast', text });
  box.append(el);
  setTimeout(() => el.remove(), ms);
}

let sheetStore = null;
export function initInspector(store) { sheetStore = store; }

/** The bottom sheet for one param: Live's knob id, the set's value and now, what experiments found, reset. */
export function inspect(id) {
  const store = sheetStore;
  const sheet = document.getElementById('inspector');
  if (!store || !sheet || !store.params.has(id)) return;        // a widget's own setting, not one of the lab's params
  const p = store.params.get(id);
  const now = toReal(p, store.get(id));
  const close = () => { sheet.hidden = true; document.removeEventListener('pointerdown', outside, true); };
  const outside = (e) => { if (!sheet.contains(e.target)) close(); };
  sheet.replaceChildren(...[
    h('div', { class: 'sheet-grip' }),
    h('h2', { text: p.label }),
    h('div', { class: 'live', text: p.live ? `Live: ${p.live}` : 'An arrangement choice (no single knob in Live)' }),
    h('div', { class: 'vals' },
      h('div', { class: 'val is-set' }, h('span', { text: 'In the set' }), h('b', { text: format(p, p.set ?? toReal(p, setNorm(p))) })),
      h('div', { class: 'val' }, h('span', { text: 'Here now' }), h('b', { text: format(p, now) }))),
    p.tried ? h('p', { class: 'finding', text: `Tried: ${format(p, p.tried[0])} to ${format(p, p.tried[1])}.` }) : null,
    p.note ? h('p', { class: 'finding', text: p.note }) : null,
    h('div', { class: 'acts' },
      h('button', { type: 'button', text: 'Close', onclick: close }),
      h('button', { type: 'button', class: 'primary', text: 'Back to the set', onclick: () => { store.reset(id, { source: 'inspector' }); haptic(true); close(); } })),
  ].filter(Boolean));
  sheet.hidden = false;
  setTimeout(() => document.addEventListener('pointerdown', outside, true), 0);
}

/** Wire the lab's standard touches onto a control: double tap resets to the set, long press inspects. */
export function standard(el, store, id, { double = true } = {}) {
  if (double) doubleTap(el, () => { store.reset(id, { source: 'doubletap' }); haptic(true); toast(`${store.params.get(id).label}: the set's value`); });
  longPress(el, () => inspect(id));
}
