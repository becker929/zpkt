// Small DOM and formatting helpers shared by the views.

/**
 * Build an element. Props: `class`, `text`, `dataset`, `on<event>` listeners, anything else as
 * an attribute (true sets it empty, false or null leaves it out). Children may be nodes or strings.
 */
export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value == null || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'text') el.textContent = value;
    else if (key === 'dataset') Object.assign(el.dataset, value);
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat()) if (child != null && child !== false) el.append(child);
  return el;
}

/** Set text only when it changed, so patching a bubble in place does not touch the layout needlessly. */
export function setText(el, text) {
  const value = text ?? '';
  if (el.textContent !== value) el.textContent = value;
}

/** Seconds as m:ss (or h:mm:ss). */
export function fmtClock(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '';
  const s = Math.round(seconds);
  const hh = Math.floor(s / 3600);
  const mm = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, '0');
  return hh ? `${hh}:${String(mm).padStart(2, '0')}:${ss}` : `${mm}:${ss}`;
}

/** Milliseconds for a timing column: 840 ms, 1.4 s, 2 m 05 s. */
export function fmtMs(ms) {
  if (!Number.isFinite(ms)) return '';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`;
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)} m ${String(s % 60).padStart(2, '0')} s`;
}

export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
