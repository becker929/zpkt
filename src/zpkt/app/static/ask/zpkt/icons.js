// Inline SVG icons (never emoji: iOS draws them as colour emoji). All use currentColor.
const svg = (body) => `<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">${body}</svg>`;
const line = 'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"';

export const ICON = {
  screen: svg(`<rect x="3" y="4.5" width="18" height="12" rx="2" ${line}/><path d="M8.5 20h7M12 16.5V20" ${line}/>`),
  image: svg(`<rect x="3.5" y="4.5" width="17" height="15" rx="2" ${line}/><circle cx="9" cy="10" r="1.6" ${line}/><path d="M20.5 16l-5-5-8 8.5" ${line}/>`),
  close: svg(`<path d="M6 6l12 12M18 6L6 18" ${line}/>`),
};
