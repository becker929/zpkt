// The drawing palette: which CSS custom property each material and colour comes from (values in zpkt.css, with a
// light and a dark set). In the page, drawings refer to the variables, so they follow the theme by themselves. An
// exported image has no stylesheet, so capture.js resolves the same names to concrete colours first.

export const PAL_VARS = {
  ink: '--ink', mute: '--mute', line: '--line', bg: '--panel',
  acc: '--zs',          // lime: the accent, knob arcs, fader fill, lit pads, lane A
  acc2: '--zs2',        // neutral: lane B
  onacc: '--zs-on',     // text and marks drawn on the accent
  ghost: '--zs-ghost',  // a change that is not yet audible
  arcA: '--zk-arc-a', arcB: '--zk-arc-b',            // the knob's value arc (one colour)
  k1: '--zk-1', k2: '--zk-2', k3: '--zk-3',          // metal: highlight, body, shade
  knurl: '--zk-knurl', kedge: '--zk-edge', kptr: '--zk-ptr', shadow: '--zk-shadow',
  well: '--z-well', slot: '--z-slot',                // the arc's track and toggle; the fader's slot
  key1: '--z-key1', key2: '--z-key2', keyedge: '--z-keyedge',   // ceramic pads
  g1: '--zg-1', g2: '--zg-2', gedge: '--zg-edge', gtext: '--zg-text',   // the smoked-glass window
};

/** For drawings inside the page. */
export const PAL_CSS = Object.fromEntries(Object.entries(PAL_VARS).map(([k, v]) => [k, `var(${v})`]));

/** For drawings outside the page (an exported image): the variables' current values. */
export function resolvePalette(el = document.documentElement) {
  const cs = getComputedStyle(el);
  return Object.fromEntries(Object.entries(PAL_VARS).map(([k, v]) => [k, cs.getPropertyValue(v).trim() || '#888']));
}
