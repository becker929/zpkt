// Drawing: every control as an SVG string. The same code draws live widgets, frozen snapshots and the PNG export,
// so a frozen card looks exactly like the armed one did. A value that differs from the rendered one is drawn as a
// dashed ghost: a change that is not yet audible. Pure functions, no DOM.
//
// The look (chosen from image rounds, 17 November 2026): only the controls are physical. Machined aluminium knobs
// (black-anodised at night), a slotted fader, ceramic pads, and a smoked-glass waveform window, on a quiet card.
// Lime is the accent (arcs, fader fill, lit pads, lane A); lane B is neutral. Materials are gradients from palette.js.
import { fmt, coerce, cleanPeaks } from './spec.js';
import { fit, widthOf } from './text.js';
import { PAL_CSS } from './palette.js';
import { sizeOf, layout, padCols, PAD, CARD_W, DECK_ROW } from './layout.js';

export { PAL_CSS, sizeOf };
export const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
const st = (o) => `style="${Object.entries(o).map(([k, v]) => `${k}:${v}`).join(';')}"`;
const FONT = 'system-ui,sans-serif', MONO = 'ui-monospace,Menlo,monospace';

/** Where an A/B lane's waveform sits inside the ab control (shared with the playhead). */
export const AB_LANE = { x: 40, a: 8, b: 56, h: 42, width: (c) => sizeOf(c)[0] - 48 };

/** Gradients and the shadow every drawing refers to. One copy per <svg>; the ids are the same everywhere. */
export function defs(P = PAL_CSS) {
  const stop = (o, c) => `<stop offset="${o}" ${st({ 'stop-color': c })}/>`;
  const lin = (id, x2, y2, stops, extra = '', x1 = 0) => `<linearGradient id="${id}" x1="${x1}" y1="0" x2="${x2}" y2="${y2}" ${extra}>${stops}</linearGradient>`;
  return '<defs>' +
    lin('zk-cap', 1, 1, stop(0, P.k1) + stop(0.5, P.k2) + stop(1, P.k3)) +            // metal, lit from the top left
    lin('zk-face', 1, 1, stop(0, P.k3) + stop(0.45, P.k2) + stop(1, P.k1)) +          // the turned face, lit the other way
    lin('zk-arc', 61, 0, stop(0, P.arcA) + stop(1, P.arcB), 'gradientUnits="userSpaceOnUse"', 7) +
    lin('zk-key', 0, 1, stop(0, P.key1) + stop(1, P.key2)) +
    lin('zk-glass', 0, 1, stop(0, P.g1) + stop(1, P.g2)) +
    `<filter id="zk-sh" x="-30%" y="-30%" width="160%" height="170%"><feDropShadow dx="0" dy="1.5" stdDeviation="1.4" ${st({ 'flood-color': '#000', 'flood-opacity': P.shadow })}/></filter>` +
    '</defs>';
}

const A0 = Math.PI * 0.75, A1 = Math.PI * 2.25;
const angle = (c, v) => A0 + ((v - c.min) / (c.max - c.min)) * (A1 - A0);
function arc(cx, cy, r, a0, a1) {
  const p = (a) => [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  const [x0, y0] = p(a0), [x1, y1] = p(a1);
  return `M${x0.toFixed(2)} ${y0.toFixed(2)}A${r} ${r} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}
// Centred text. `max` is the room it has in px: longer text is cut with an ellipsis.
const text = (x, y, s, P, o = {}, max = 0) => {
  const px = parseFloat(o['font-size']) || 11;
  if (max) s = fit(String(s), max, px, o['font-family'] === MONO);
  return label(x, y, s, P, o);
};
const label = (x, y, s, P, o = {}) => `<text x="${x}" y="${y}" text-anchor="middle" ${st({ fill: P.mute, 'font-size': '11px', 'font-family': FONT, ...o })}>${esc(s)}</text>`;

// A value under its control. If number and unit do not fit, the size steps down, then the unit goes. The style is
// chosen from the control's widest values, not the current one, so the text never changes size while it is dragged.
const VALUE_STYLES = [[true, true, 12], [true, true, 10.5], [true, false, 10.5], [false, false, 12], [false, false, 10.5]];   // unit, space, size
const FADER_STYLES = [[true, false, 10.5], [false, false, 12], [false, false, 10.5]];   // a fader is narrow: every fader reads the same way
function valueText(x, y, c, v, P, ghost, w) {
  const o = { fill: ghost ? P.ghost : P.ink, 'font-family': MONO };
  const show = (val, [unit, space]) => { const s = fmt(unit ? c : { ...c, unit: '' }, val); return space ? s : s.replace(' ', ''); };
  const widest = [c.min, c.max, c.min + (c.max - c.min) / 3];
  const styles = c.kind === 'fader' ? FADER_STYLES : VALUE_STYLES;
  const style = styles.find((st) => widest.every((val) => { const s = show(val, st); return fit(s, w - 2, st[2], true) === s; })) || styles[styles.length - 1];
  return text(x, y, show(v, style), P, { ...o, 'font-size': `${style[2]}px` }, w - 2);
}

function knob(c, v, P, w) {
  const cx = w / 2, cy = 34, r = 27, ghost = v !== c.value;
  const a = angle(c, v), ab = angle(c, c.value);
  const ring = (col, o = {}) => st({ fill: 'none', stroke: col, 'stroke-width': 5, 'stroke-linecap': 'round', ...o });
  return `<path d="${arc(cx, cy, r, A0, A1)}" ${ring(P.well)}/>` +
    `<path d="${arc(cx, cy, r, A0, Math.max(A0 + 0.001, ghost ? ab : a))}" ${ring('url(#zk-arc)')}/>` +
    (ghost ? `<path d="${arc(cx, cy, r, Math.min(a, ab), Math.max(a, ab) + 0.0001)}" ${ring(P.ghost, { 'stroke-linecap': 'butt', 'stroke-dasharray': '3 4' })}/>` : '') +
    // the knob: a knurled skirt, a bevelled cap and a turned face
    `<circle cx="${cx}" cy="${cy}" r="20" filter="url(#zk-sh)" ${st({ fill: 'url(#zk-cap)', stroke: P.kedge, 'stroke-width': 0.6 })}/>` +
    `<circle cx="${cx}" cy="${cy}" r="18.7" ${st({ fill: 'none', stroke: P.knurl, 'stroke-width': 2.2, 'stroke-dasharray': '1.1 1.5' })}/>` +
    `<circle cx="${cx}" cy="${cy}" r="15.8" ${st({ fill: 'url(#zk-face)', stroke: P.kedge, 'stroke-width': 0.4, 'stroke-opacity': 0.5 })}/>` +
    `<circle cx="${cx}" cy="${cy}" r="13.8" ${st({ fill: 'url(#zk-cap)' })}/>` +
    `<line x1="${cx + 5 * Math.cos(a)}" y1="${cy + 5 * Math.sin(a)}" x2="${cx + 12.5 * Math.cos(a)}" y2="${cy + 12.5 * Math.sin(a)}" ${st({ stroke: ghost ? P.ghost : P.kptr, 'stroke-width': 2.4, 'stroke-linecap': 'round' })}/>` +
    valueText(cx, cy + 44, c, v, P, ghost, w);
}

function fader(c, v, P, w, h) {
  const x = w / 2, top = 12, bot = h - 44, ghost = v !== c.value;
  const y = (val) => bot - ((val - c.min) / (c.max - c.min)) * (bot - top);
  const line = (y1, y2, col, width, o = {}) => `<line x1="${x}" y1="${y1}" x2="${x}" y2="${y2}" ${st({ stroke: col, 'stroke-width': width, 'stroke-linecap': 'round', ...o })}/>`;
  let ticks = '';
  for (let i = 0; i <= 4; i++) { const ty = top + ((bot - top) * i) / 4; ticks += `<path d="M${x - 15} ${ty}h5M${x + 10} ${ty}h5" ${st({ stroke: P.line, 'stroke-width': 1 })}/>`; }
  return ticks + line(top, bot, P.slot, 6) + line(y(c.value), bot, P.acc, 3) +
    (ghost ? line(Math.min(y(v), y(c.value)), Math.max(y(v), y(c.value)), P.ghost, 3, { 'stroke-linecap': 'butt', 'stroke-dasharray': '3 4' }) : '') +
    `<rect x="${x - 15}" y="${y(v) - 8}" width="30" height="16" rx="4" filter="url(#zk-sh)" ${st({ fill: 'url(#zk-cap)', stroke: ghost ? P.ghost : P.kedge, 'stroke-width': ghost ? 1.5 : 0.6 })}/>` +
    `<path d="M${x - 9} ${y(v)}h18" ${st({ stroke: ghost ? P.ghost : P.acc, 'stroke-width': 2, 'stroke-linecap': 'round' })}/>` +
    valueText(x, h - 21, c, v, P, ghost, w);
}

function toggle(c, v, P, w) {
  const on = !!v, ghost = on !== c.value;
  return `<rect x="${w / 2 - 22}" y="4" width="44" height="24" rx="12" ${st({ fill: on ? (ghost ? P.ghost : P.acc) : P.well, ...(ghost ? { stroke: P.ghost, 'stroke-dasharray': '3 3', 'stroke-width': 1.5 } : {}) })}/>` +
    `<circle cx="${on ? w / 2 + 10 : w / 2 - 10}" cy="16" r="9.5" filter="url(#zk-sh)" ${st({ fill: 'url(#zk-cap)', stroke: P.kedge, 'stroke-width': 0.5 })}/>`;
}

// A pad's name: one line if it fits (smaller if need be), else two lines broken at a space or hyphen.
function padLabel(s, x, y, max, P, o) {
  for (const px of [12, 10]) if (fit(s, max, px) === s) return label(x, y + 4, s, P, { ...o, 'font-size': `${px}px` });
  const cut = [...s.matchAll(/[ \-–]/g)].map((m) => m.index + 1).sort((a, b) => Math.abs(a - s.length / 2) - Math.abs(b - s.length / 2))[0];
  if (!cut) return text(x, y + 4, s, P, { ...o, 'font-size': '10px' }, max);
  return text(x, y - 2, s.slice(0, cut).trim(), P, { ...o, 'font-size': '10px' }, max) + text(x, y + 9, s.slice(cut).trim(), P, { ...o, 'font-size': '10px' }, max);
}

function pads(c, P, lit = {}) {
  const cols = padCols(c), { pitch, key } = PAD;
  return c.pads.map((p, k) => {
    const px = 4 + (k % cols) * pitch, py = 2 + Math.floor(k / cols) * pitch, on = lit[k], dy = on ? 1.5 : 0;
    return `<g data-pad="${k}">` +
      `<rect x="${px}" y="${py + 2}" width="${key}" height="${key}" rx="9" ${st({ fill: on ? P.acc : P.keyedge })}/>` +   // the key's edge
      `<rect x="${px}" y="${py + dy}" width="${key}" height="${key - 1}" rx="9" ${st({ fill: on ? P.acc : 'url(#zk-key)', stroke: on ? P.acc : P.line, 'stroke-width': 1 })}/>` +
      (p.src ? `<circle cx="${px + key - 8}" cy="${py + 8 + dy}" r="2" ${st({ fill: on ? P.onacc : P.mute })}/>` : '') +   // it has a file to play
      padLabel(p.label, px + key / 2, py + key / 2 + dy, key - 6, P, { fill: on ? P.onacc : P.ink, 'pointer-events': 'none' }) + '</g>';
  }).join('');
}

function abLane(t, name, on, peaks, region, P, c) {
  const { x: X, h: H } = AB_LANE, y0 = AB_LANE[name], W = AB_LANE.width(c);
  const col = name === 'a' ? P.acc : P.acc2;   // A is lime, B is neutral, always
  peaks = cleanPeaks(peaks);
  const n = peaks?.length || 0;
  let path = '';
  for (let i = 0; i < n; i++) {
    const x = X + (i / n) * W, amp = Math.max(0.5, (peaks[i] * (H - 6)) / 2);
    path += `M${x.toFixed(1)} ${(y0 + H / 2 - amp).toFixed(1)}V${(y0 + H / 2 + amp).toFixed(1)}`;
  }
  return `<rect x="${X}" y="${y0}" width="${W}" height="${H}" ${st({ fill: col, opacity: on ? 0.16 : 0.04 })}/>` +
    `<rect x="8" y="${y0 + 6}" width="26" height="${H - 12}" rx="6" ${st({ fill: on ? col : 'none', stroke: col, 'stroke-opacity': on ? 1 : 0.5 })}/>` +
    text(21, y0 + H / 2 + 5, name.toUpperCase(), P, { fill: on ? P.onacc : col, 'font-size': '13px', 'font-weight': 700 }) +
    (region ? `<rect x="${X + region[0] * W}" y="${y0}" width="${Math.max(1, (region[1] - region[0]) * W)}" height="${H}" ${st({ fill: '#fff', opacity: 0.07 })}/>` : '') +
    (n ? `<path d="${path}" ${st({ stroke: col, 'stroke-width': Math.max(0.6, (W / n) * 0.7).toFixed(2), opacity: on ? 1 : 0.5 })}/>`
       : text(X + W / 2, y0 + H / 2 + 4, 'arm to load the waveform', P, { fill: P.gtext, opacity: 0.5 })) +
    `<text x="${X + 5}" y="${y0 + 11}" ${st({ fill: P.gtext, opacity: 0.6, 'font-size': '9.5px', 'font-family': FONT })}>${esc(fit(t.label, W - 12, 9.5))}</text>`;
}

const span01 = (r) => (Array.isArray(r) && r.length === 2 && r.every((x) => x >= 0 && x <= 1) && r[1] >= r[0] ? r : null);

function ab(c, v, P, w, h, extra) {
  const peaks = extra.peaks || {}, region = extra.region || {};
  const side = v === 'b' ? 'b' : 'a';
  const top = AB_LANE.a - 6, H = AB_LANE.b + AB_LANE.h + 6 - top, mid = (AB_LANE.a + AB_LANE.h + AB_LANE.b) / 2;
  return `<rect x="1" y="${top}" width="${w - 2}" height="${H}" rx="10" ${st({ fill: 'url(#zk-glass)', stroke: P.gedge, 'stroke-width': 1 })}/>` +     // smoked glass
    `<path d="M${w * 0.55} ${top + 1}H${w - 11}a9 9 0 0 1 9 9V${top + H * 0.8}Z" ${st({ fill: '#fff', opacity: 0.045 })}/>` +                              // its sheen
    `<path d="M${AB_LANE.x} ${mid}H${w - 8}" ${st({ stroke: '#fff', 'stroke-opacity': 0.08 })}/>` +
    abLane(c.a, 'a', side === 'a', cleanPeaks(peaks.a) || c.a.peaks, span01(region.a), P, c) + abLane(c.b, 'b', side === 'b', cleanPeaks(peaks.b) || c.b.peaks, span01(region.b), P, c) +
    '<g class="zs-ph"></g>';
}

// A deck of versions: one line each, the letter and what was different about it; the one heard is marked.
function deck(c, v, P, w) {
  return c.sources.map((s, i) => {
    const y = 6 + i * DECK_ROW, on = s.label === v;
    return `<rect x="4" y="${y}" width="22" height="${DECK_ROW - 3}" rx="3" ${st({ fill: on ? P.arcA : 'none', stroke: on ? P.arcA : P.mute, 'stroke-width': 1 })}/>` +
      `<text x="15" y="${y + 11}" text-anchor="middle" ${st({ fill: on ? '#111' : P.ink, 'font-size': '11px', 'font-weight': 700, 'font-family': FONT })}>${esc(s.label)}</text>` +
      `<text x="32" y="${y + 11}" ${st({ fill: on ? P.ink : P.mute, 'font-size': '11.5px', 'font-family': FONT })}>${esc(fit(s.note || s.src.split('/').pop(), w - 38, 11.5))}</text>`;
  }).join('');
}

/** One control's drawing in its own box. extra: { lit } for pads, { peaks, region } for ab. */
export function draw(c, v, P = PAL_CSS, extra = {}) {
  const [w, h] = sizeOf(c);
  v = coerce(c, v) ?? (c.kind === 'ab' ? 'a' : c.kind === 'deck' ? c.sources[0].label : c.value);   // never draw a value the control cannot hold
  if (c.kind === 'deck') return deck(c, v, P, w) + label(w / 2, 6 + c.sources.length * DECK_ROW + 16, fit(c.label, w - 8, 11.5) , P, { 'font-size': '11.5px' });
  const body = c.kind === 'knob' ? knob(c, v, P, w)
    : c.kind === 'fader' ? fader(c, v, P, w, h)
    : c.kind === 'toggle' ? toggle(c, v, P, w)
    : c.kind === 'pads' ? pads(c, P, extra.lit)
    : c.kind === 'ab' ? ab(c, v, P, w, h, extra) : '';
  if (c.kind !== 'ab') return body + text(w / 2, h - 5, c.label, P, { 'font-size': '11.5px' }, w - 2);
  // The deck's caption keeps its facts whole and gives the name what room is left.
  const facts = ` · bars ${c.loop.startBar}–${c.loop.startBar + c.loop.bars - 1} · ${c.a.bpm} BPM`;
  return body + label(w / 2, h - 5, fit(c.label, Math.max(40, w - 8 - widthOf(facts, 11.5)), 11.5) + facts, P, { 'font-size': '11.5px' });
}

/** The static snapshot of a whole surface: what a frozen card shows, and the PNG export (with header). */
export function snapshotSVG(spec, values, peaks = {}, { P = PAL_CSS, width = CARD_W, header = false, regions = {} } = {}) {
  const L = layout(spec, width);
  const top = header ? 30 : 0, H = L.height + top + 4;
  if (!header) width = Math.max(L.width, 200);   // in a card it hugs its controls, exactly as the armed body does
  // Each control is its own nested <svg>, which clips: nothing a control draws can reach its neighbour.
  const body = L.items.map(({ c, x, y, w, h }) =>
    `<svg x="${x}" y="${y + top}" width="${w}" height="${h}">${draw(c, Object.hasOwn(values || {}, c.id) ? values[c.id] : c.value, P, { peaks: peaks?.[c.id], region: regions?.[c.id] })}</svg>`).join('');
  const head = header ? `<rect width="${width}" height="${H}" ${st({ fill: P.bg })}/><text x="2" y="18" ${st({ fill: P.ink, 'font-size': '15px', 'font-weight': 600, 'font-family': FONT })}>${esc(fit(spec.title, width - 6, 15.5))}</text>` : '';
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${H}" width="${width}" height="${H}" role="img" aria-label="${esc(spec.title)} (frozen)">${defs(P)}${head}${body}</svg>`;
}
