// Sizes and packing: where each control sits on a surface. One layout for the armed card (live widgets, absolutely
// positioned) and the frozen snapshot, so freezing a card never moves anything. Pure functions, no DOM.
//
// Packing: controls keep the agent's order and fill rows of the card's width. Tall controls (fader, pads) stand as
// columns; the short ones in the same row (knobs, toggles) gather into one cluster that wraps beside them, so a
// toggle tucks under the knobs instead of taking a column of its own. An A/B deck always has a row to itself.

/** The width every surface is designed at (a phone's card). */
export const CARD_W = 328;
export const GAP = 6;
const TRANSPORT_H = 44;
export const DECK_ROW = 17;   // one line per version in a deck's list   // the A/B deck's row of buttons, live cards only

const SIZE = { knob: [68, 96], fader: [48, 150], toggle: [68, 50], ab: [CARD_W, 122] };
export const padCols = (c) => (c.pads.length <= 4 ? 2 : 4);
export const PAD = { pitch: 50, key: 46 };

/** A control's box. `live` adds room for parts only an armed card has. */
export function sizeOf(c, live = false) {
  if (c.kind === 'pads') return [padCols(c) * PAD.pitch + 4, Math.ceil(c.pads.length / padCols(c)) * PAD.pitch + 20];
  if (c.kind === 'deck') return [CARD_W, 34 + c.sources.length * DECK_ROW + (live ? TRANSPORT_H + 22 + Math.ceil(c.sources.length / 7) * 40 : 0)];
  const [w, h] = SIZE[c.kind];
  return [w, h + (live && c.kind === 'ab' ? TRANSPORT_H : 0)];
}

const isShort = (c) => c.kind === 'knob' || c.kind === 'toggle';

// Flow boxes into sub-rows of at most `width`. Returns their offsets and the block's size.
// A box shorter than its sub-row (a toggle among knobs) drops a little, so the switch lines up with the knob caps.
function flow(sizes, width) {
  let x = 0, y = 0, rowH = 0, w = 0, start = 0;
  const at = [];
  const settle = (end) => { for (let i = start; i < end; i++) at[i][1] += Math.min(18, Math.floor((rowH - sizes[i][1]) / 2)); start = end; };
  sizes.forEach(([bw, bh], i) => {
    if (x > 0 && x + bw > width) { settle(i); x = 0; y += rowH + GAP; rowH = 0; }
    at.push([x, y]);
    x += bw + GAP; rowH = Math.max(rowH, bh); w = Math.max(w, x - GAP);
  });
  settle(sizes.length);
  return { at, w, h: y + rowH };
}

// One row: its tall columns and the cluster of short controls. null if it does not fit in `width`.
function packRow(row, width, live) {
  const tall = row.filter((c) => !isShort(c)), short = row.filter(isShort);
  const tallW = tall.reduce((s, c) => s + sizeOf(c, live)[0] + GAP, 0);
  const tallH = Math.max(0, ...tall.map((c) => sizeOf(c, live)[1]));
  if (tallW - GAP > width) return null;
  let cluster = null;
  if (short.length) {
    const avail = width - tallW;
    cluster = flow(short.map((c) => sizeOf(c, live)), avail);
    const oneRow = Math.max(...short.map((c) => sizeOf(c, live)[1]));
    // Too wide, or it would stand much taller than its neighbours (beside a fader, two rows of knobs are fine).
    if (cluster.w > avail || cluster.h > Math.max(tallH ? tallH + 56 : 0, oneRow + 8)) return null;
  }
  // Positions, in the agent's order; the cluster stands where its first control was.
  const items = [];
  let x = 0, placed = false;
  for (const c of row) {
    if (isShort(c)) {
      if (placed) continue;
      placed = true;
      short.forEach((s, i) => items.push({ c: s, x: x + cluster.at[i][0], y: cluster.at[i][1] }));
      x += cluster.w + GAP;
    } else { items.push({ c, x, y: 0 }); x += sizeOf(c, live)[0] + GAP; }
  }
  return { items, w: x - GAP, h: Math.max(tallH, cluster?.h || 0) };
}

/** Where every control goes: { items: [{ c, x, y, w, h }], width, height }. */
export function layout(spec, width = CARD_W, live = false) {
  const rows = [];
  let cur = [];
  const close = () => { if (cur.length) { rows.push(packRow(cur, width, live) || packRow(cur, Infinity, live)); cur = []; } };
  for (const c of spec.controls) {
    if (c.kind === 'ab' || c.kind === 'deck') { close(); cur = [c]; close(); continue; }
    if (cur.length && !packRow([...cur, c], width, live)) close();
    cur.push(c);
  }
  close();
  const items = [];
  let y = 0, w = 0;
  for (const r of rows) {
    for (const it of r.items) { const [iw, ih] = sizeOf(it.c, live); items.push({ c: it.c, x: it.x, y: y + it.y, w: iw, h: ih }); }
    y += r.h + GAP + 4; w = Math.max(w, r.w);
  }
  return { items, width: w, height: Math.max(0, y - GAP - 4) };
}
