// The tweaks panel: how the checklist page is built, changed live. It slides in from the right on a tab-shaped
// handle. Each tweak is a data attribute on <html> (CSS reads it) and a value the page's code can ask for; they are
// kept in this browser.

const KEY = 'checklist:tweaks';

export const TWEAKS = [
  { id: 'look', label: 'Look', options: [['game', 'Game'], ['plain', 'Plain']], value: 'game' },
  { id: 'folding', label: 'Folding', options: [['on', 'On'], ['off', 'Off, all open']], value: 'on' },
  { id: 'check', label: 'Check an item by', options: [['hold', 'Holding it'], ['tap', 'Tapping its box']], value: 'hold' },
  { id: 'objective', label: 'Current objective', options: [
    ['full', 'Panel'], ['strip', 'Strip'], ['header', 'Header'], ['spine', 'Gems'], ['hidden', 'Off']], value: 'strip' },
  { id: 'spine', label: 'The seven gems', options: [['on', 'Show'], ['off', 'Hide']], value: 'on' },
  { id: 'details', label: 'Tap an item', options: [['inline', 'Sub-list below'], ['drill', 'Its own page']], value: 'inline' },
  { id: 'go', label: 'Studio button on each item', options: [['on', 'On'], ['off', 'Off']], value: 'off' },
  { id: 'path', label: 'The path line', options: [['on', 'On'], ['off', 'Off']], value: 'on' },
  { id: 'fog', label: 'Fog past the agent', options: [['on', 'On'], ['off', 'Off']], value: 'on' },
  { id: 'effects', label: 'Clearing effects', options: [['full', 'Full'], ['subtle', 'Subtle'], ['off', 'Off']], value: 'full' },
  { id: 'hold', label: 'Hold to clear', options: [['300', 'Short'], ['520', 'Medium'], ['800', 'Long']], value: '520' },
  { id: 'density', label: 'Density', options: [['comfy', 'Roomy'], ['compact', 'Compact']], value: 'comfy' },
  { id: 'brackets', label: 'Corner brackets', options: [['on', 'On'], ['off', 'Off']], value: 'on' },
];

// The simplest page: every switch at its plainest.
const SIMPLEST = {
  look: 'plain', folding: 'off', check: 'tap', objective: 'header', spine: 'off', go: 'off', path: 'off', fog: 'off',
  effects: 'off', density: 'compact', brackets: 'off',
};

let values = {};
const listeners = new Set();

export const tweak = (id) => values[id];

/** Run `fn` on a tap of `el`. It acts on the touch itself (pointerdown and pointerup within 12 px): iPhone WebKit can
 * swallow the click that follows a touch when it thinks the page changed under the finger, and this page animates
 * constantly. A click with no pointer (the keyboard) still works. */
export function onTap(el, fn) {
  let down = null;
  el.addEventListener('pointerdown', (e) => { down = [e.clientX, e.clientY]; });
  el.addEventListener('pointerup', (e) => {
    const ok = down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) < 12;
    down = null;
    if (ok) fn(e);
  });
  el.addEventListener('pointercancel', () => { down = null; });
  el.addEventListener('click', (e) => { if (e.detail === 0) fn(e); else if (el.tagName === 'A') e.preventDefault(); });
}
export const onTweak = (fn) => listeners.add(fn);

function apply() {
  for (const t of TWEAKS) document.documentElement.dataset[t.id] = values[t.id];
  for (const fn of listeners) fn(values);
}

function store() { try { localStorage.setItem(KEY, JSON.stringify(values)); } catch { /* this visit only */ } }

export function initTweaks(h, haptic) {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(KEY)) || {}; } catch { saved = {}; }
  for (const t of TWEAKS) values[t.id] = t.options.some(([v]) => v === saved[t.id]) ? saved[t.id] : t.value;

  const panel = document.getElementById('tweaks-panel');
  const reset = h('button', { type: 'button', class: 'tw-reset', text: 'Back to the defaults' });
  onTap(reset, () => { for (const t of TWEAKS) values[t.id] = t.value; store(); haptic(true); paint(); apply(); });
  const simplest = h('button', { type: 'button', class: 'tw-reset tw-simplest', text: 'Simplest' });
  onTap(simplest, () => { Object.assign(values, SIMPLEST); store(); haptic(true); paint(); apply(); });
  const groups = TWEAKS.map((t) => {
    const seg = h('div', { class: 'seg', role: 'radiogroup', 'aria-label': t.label },
      t.options.map(([v, text]) => {
        const b = h('button', { type: 'button', role: 'radio', 'data-v': v, text });
        onTap(b, () => { values[t.id] = v; store(); haptic(); paint(); apply(); });
        return b;
      }));
    return h('div', { class: 'tw', 'data-id': t.id }, h('div', { class: 'tw-label', text: t.label }), seg);
  });
  const paint = () => {
    for (const g of panel.querySelectorAll('.tw')) {
      for (const b of g.querySelectorAll('button')) b.setAttribute('aria-checked', String(b.dataset.v === values[g.dataset.id]));
    }
  };
  panel.replaceChildren(
    h('div', { class: 'tw-head' }, h('b', { text: 'Build' }), h('span', { text: 'How this page is put together' })),
    simplest,
    ...groups,
    reset);
  paint();

  const aside = document.getElementById('tweaks'), tab = document.getElementById('tweaks-tab'), scrim = document.getElementById('scrim');
  const setOpen = (open) => {
    aside.classList.toggle('open', open); scrim.classList.toggle('show', open);
    tab.setAttribute('aria-expanded', String(open)); haptic();
  };
  onTap(tab, () => setOpen(!aside.classList.contains('open')));
  onTap(scrim, () => setOpen(false));
  apply();
}
