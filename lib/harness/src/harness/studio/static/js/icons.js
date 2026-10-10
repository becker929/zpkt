// Inline SVG icons drawn with currentColor. Never emoji or symbol glyphs: iOS can render
// characters such as a play triangle as a colour emoji.

const SHAPES = {
  mic: '<rect x="9" y="3" width="6" height="11.5" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0"/><path d="M12 18v3"/>',
  send: '<path d="M12 19.5V5"/><path d="M5.5 11.5 12 5l6.5 6.5"/>',
  stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="2.2" fill="currentColor" stroke="none"/>',
  play: '<path d="M8.5 5.6v12.8a1 1 0 0 0 1.53.85l10.2-6.4a1 1 0 0 0 0-1.7l-10.2-6.4a1 1 0 0 0-1.53.85z" fill="currentColor" stroke="none"/>',
  pause: '<rect x="6.5" y="5.5" width="4" height="13" rx="1.3" fill="currentColor" stroke="none"/><rect x="13.5" y="5.5" width="4" height="13" rx="1.3" fill="currentColor" stroke="none"/>',
  keyboard: '<rect x="2.5" y="6" width="19" height="12" rx="2.5"/><path d="M6.5 10h.01M10 10h.01M14 10h.01M17.5 10h.01M7.5 14h9"/>',
  more: '<circle cx="5.5" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="18.5" cy="12" r="1.5" fill="currentColor" stroke="none"/>',
  close: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
  chevron: '<path d="M7 10l5 5 5-5"/>',
  check: '<path d="M5.5 12.5l4 4 9-9.5"/>',
  cross: '<path d="M7.5 7.5l9 9M16.5 7.5l-9 9"/>',
  down: '<path d="M12 5v13.5"/><path d="M5.5 12.5 12 19l6.5-6.5"/>',
  image: '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><circle cx="9" cy="10" r="1.7"/><path d="M20.5 15.5l-4.5-4.5-8.5 8"/>',
  minus: '<path d="M6.5 12h11"/>',
  plus: '<path d="M12 6.5v11M6.5 12h11"/>',
  loop: '<path d="M17 3l3 3-3 3"/><path d="M4 11.5V10a4 4 0 0 1 4-4h12"/><path d="M7 21l-3-3 3-3"/><path d="M20 12.5V14a4 4 0 0 1-4 4H4"/>',
  note: '<path d="M9 17.5V5.5l10.5-2v12"/><circle cx="6.5" cy="17.5" r="2.5"/><circle cx="17" cy="15.5" r="2.5"/>',
  compose: '<path d="M12 20h8.5"/><path d="M15.8 4.2a2 2 0 0 1 2.9 2.9L7.5 18.3l-3.8 1 1-3.8z"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  external: '<path d="M14 4.5h5.5V10"/><path d="M19.5 4.5l-8.5 8.5"/><path d="M18.5 14v3.5a2 2 0 0 1-2 2h-10a2 2 0 0 1-2-2v-10a2 2 0 0 1 2-2H10"/>',
  refresh: '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4.5v4.8h-4.8"/>',
  waves: '<path d="M4 12h.01M8 9v6M12 6v12M16 9v6M20 12h.01"/>',
};

const templates = new Map();

/** A decorative <svg> for a named icon; the control around it carries the accessible label. */
export function icon(name, className = '') {
  let tpl = templates.get(name);
  if (!tpl) {
    if (!(name in SHAPES)) throw new Error(`no icon named ${name}`);
    tpl = document.createElement('template');
    tpl.innerHTML = `<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${SHAPES[name]}</svg>`;
    templates.set(name, tpl);
  }
  const svg = tpl.content.firstElementChild.cloneNode(true);
  svg.classList.add('icon');
  if (className) svg.classList.add(...className.split(/\s+/).filter(Boolean));
  return svg;
}

/** Replace each `<i data-icon="name">` placeholder in the static markup with its icon. */
export function hydrateIcons(root = document) {
  for (const el of root.querySelectorAll('[data-icon]')) el.replaceWith(icon(el.dataset.icon, el.className));
}
