// Inline SVG icons (never emoji: iOS draws ▶ ■ ★ as colour emoji). All use currentColor.
const svg = (body) => `<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">${body}</svg>`;
const STAR = 'M12 3.5l2.6 5.5 6 .7-4.5 4.1 1.2 5.9L12 16.8l-5.3 2.9 1.2-5.9L3.4 9.7l6-.7z';
const line = 'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"';

export const ICON = {
  star: svg(`<path d="${STAR}" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>`),
  starOn: svg(`<path d="${STAR}" fill="currentColor"/>`),
  play: svg('<path d="M7 4.5v15l13-7.5z" fill="currentColor"/>'),
  stop: svg('<rect x="6" y="6" width="12" height="12" rx="1.5" fill="currentColor"/>'),
  reset: svg(`<path d="M5 12a7 7 0 1 0 2.1-5M5 4v4h4" ${line}/>`),
  screen: svg(`<rect x="3" y="4.5" width="18" height="12" rx="2" ${line}/><path d="M8.5 20h7M12 16.5V20" ${line}/>`),
  surface: svg(`<circle cx="8" cy="9" r="3.5" ${line}/><circle cx="16" cy="9" r="3.5" ${line}/><path d="M5 17.5h14" ${line}/>`),
  image: svg(`<rect x="3.5" y="4.5" width="17" height="15" rx="2" ${line}/><circle cx="9" cy="10" r="1.6" ${line}/><path d="M20.5 16l-5-5-8 8.5" ${line}/>`),
  library: svg(`<path d="M5 4.5v15M9.5 4.5v15M14 5l4.5 14" ${line}/>`),
  midi: svg(`<circle cx="12" cy="12" r="8.5" ${line}/><circle cx="8" cy="11" r=".9" fill="currentColor"/><circle cx="16" cy="11" r=".9" fill="currentColor"/><circle cx="10" cy="8" r=".9" fill="currentColor"/><circle cx="14" cy="8" r=".9" fill="currentColor"/><circle cx="12" cy="7.2" r=".9" fill="currentColor"/>`),
  close: svg(`<path d="M6 6l12 12M18 6L6 18" ${line}/>`),
};
