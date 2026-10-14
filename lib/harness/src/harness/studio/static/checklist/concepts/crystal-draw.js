// The crystal, drawn: a pure function of the track and the set of cleared items, so the same state always draws the
// same picture, whatever order the items were cleared in, and the picture cannot grow without real progress.
//
// Seven arms at fixed angles, one per spine step (I at the top, then clockwise). Each item is one faceted shard on
// its step's arm: its shape comes from hash(track, step, item) and its place from the item's index, so a shard never
// moves when another is cleared. The step's last item is the arm's spire, straight out and longest; the others fan
// off its axis in pairs, further out and shorter the later they come. A cleared item is solid glass; an open one is a faint outline,
// not yet crystallised. The seed at the centre is the track itself, there from the start: it can be released as is.
import { hash, rng } from './model.js';

export const SIZE = 400;
const C = SIZE / 2;
const SPIRE = 150;           // the longest shard's length
const LIGHT = -130;          // the light comes from the upper left (degrees)

const f = (x) => (Math.round(x * 10) / 10).toString();
const pts = (list) => list.map(([x, y]) => `${f(x)},${f(y)}`).join(' ');

/** Where an item's shard sits and its shape, in the order it is drawn. */
function layout(track, step, s, nSteps) {
  const axis = -90 + (s * 360) / nSteps;
  const n = step.items.length;
  return step.items.map((it, k) => {
    const r = rng(hash(`${track}|${step.id}|${it.id}`));
    const spire = k === n - 1;
    const m = spire ? 0 : Math.floor(k / 2) + 1;              // its pair along the arm (1 nearest the seed)
    const side = k % 2 ? 1 : -1;
    // the spire runs straight out from the seed; the others branch off its axis, further out the later they come,
    // leaning away from it and shorter towards the tip, like frost on a stem
    const at = spire ? 4 : 14 + (m - 1) * (100 / Math.max(1, Math.ceil((n - 1) / 2))) + r() * 6;
    const lean = spire ? (r() - 0.5) * 3 : side * (26 + r() * 12);
    const len = SPIRE * (spire ? 0.94 + r() * 0.06 : Math.max(0.2, 0.62 - (m - 1) * 0.09 + (r() - 0.5) * 0.12));
    const width = (spire ? 13 : 8) + r() * 4;
    const ridge = (r() - 0.5) * 0.5;                           // where the middle facet sits across the shard
    const shoulder = 0.68 + r() * 0.16;                        // where the faces start to converge on the tip
    const tilt = (r() - 0.5) * 0.18;                           // a tip slightly off-axis
    const rad = (axis * Math.PI) / 180;
    const root = [C + Math.cos(rad) * at, C + Math.sin(rad) * at];
    return { it, k, spire, angle: axis + lean, len, width, root, ridge, shoulder, tilt };
  });
}

/** One shard in its own coordinates: rooted at (0, 0), pointing along +x. Three visible facets of a six-sided
 * prism with a pointed termination, shaded by which way it faces the light. */
function shard(g, done, key) {
  const { len: L, width: w, ridge, shoulder, tilt } = g;
  const h = w / 2, sx = L * shoulder, ty = L * tilt * 0.12;
  const a = -h * 0.36 + ridge * h, b = h * 0.36 + ridge * h;   // the two inner edges
  const tip = [L, ty];
  const nx = L * 0.1, k = 0.5;                                // the root narrows too: a shard is pointed at both ends
  const top = [[0, -h * k], [nx, -h], [sx, -h * 0.92], tip, [sx, a], [nx, a], [0, a * k]];
  const mid = [[0, a * k], [nx, a], [sx, a], tip, [sx, b], [nx, b], [0, b * k]];
  const bot = [[0, b * k], [nx, b], [sx, b], tip, [sx, h * 0.92], [nx, h], [0, h * k]];
  const facing = Math.cos(((g.angle - LIGHT) * Math.PI) / 180);  // 1: points into the light
  const [lit, dim] = facing > 0 ? ['f1', 'f3'] : ['f3', 'f1'];
  const [x, y] = g.root;
  const outline = `M${pts([[0, -h * k], [nx, -h], [sx, -h * 0.92], tip, [sx, h * 0.92], [nx, h], [0, h * k]]).replaceAll(' ', 'L')}Z`;
  const t = `translate(${f(x)} ${f(y)}) rotate(${f(g.angle)})`;
  const cls = `shard ${done ? 'solid' : 'trace'}${g.spire ? ' spire' : ''}`;
  if (!done) return `<g class="${cls}" data-key="${key}" transform="${t}"><path class="edge" d="${outline}"/></g>`;
  const inner = `M${pts([[0, a * k], [nx, a], [sx, a], tip]).replaceAll(' ', 'L')}M${pts([[0, b * k], [nx, b], [sx, b], tip]).replaceAll(' ', 'L')}`;
  return `<g class="${cls}" data-key="${key}" transform="${t}"><g class="grow">`
    + `<polygon class="${lit}" points="${pts(top)}"/><polygon class="f2" points="${pts(mid)}"/>`
    + `<polygon class="${dim}" points="${pts(bot)}"/>`
    + `<path class="edge" d="${outline}"/><path class="edge inner" d="${inner}"/></g></g>`;
}

/** The seed: a small hexagon cut into six facets. */
function seed(track) {
  const r = rng(hash(`${track}|seed`));
  const rot = r() * 60, R = 11;
  const corner = (i) => {
    const t = ((rot + i * 60) * Math.PI) / 180;
    return [C + Math.cos(t) * R, C + Math.sin(t) * R];
  };
  const faces = [0, 1, 2, 3, 4, 5].map((i) => `<polygon class="${['f1', 'f2', 'f3'][i % 3]}" points="${pts([[C, C], corner(i), corner(i + 1)])}"/>`);
  return `<g class="seed">${faces.join('')}<polygon class="edge" points="${pts([0, 1, 2, 3, 4, 5].map(corner))}"/></g>`;
}

/** A wedge per arm to tap, and its numeral at the rim. */
function arm(step, s, nSteps) {
  const axis = -90 + (s * 360) / nSteps, half = 180 / nSteps;
  const at = (deg, r) => [C + Math.cos((deg * Math.PI) / 180) * r, C + Math.sin((deg * Math.PI) / 180) * r];
  const [x1, y1] = at(axis - half, C), [x2, y2] = at(axis + half, C), [lx, ly] = at(axis, C - 18);
  return `<path class="hit" data-step="${step.id}" d="M${C},${C}L${f(x1)},${f(y1)}A${C},${C} 0 0 1 ${f(x2)},${f(y2)}Z"/>`
    + `<text class="num" data-step="${step.id}" x="${f(lx)}" y="${f(ly)}">${step.n}</text>`;
}

/** The crystal as SVG markup: `doneKeys` holds `step.item` keys (a Set or an array). Shards are drawn in the data's
 * order, never the set's, so the markup is byte-identical for the same set however it was reached. */
export function drawCrystal(data, doneKeys) {
  const done = doneKeys instanceof Set ? doneKeys : new Set(doneKeys);
  const n = data.steps.length;
  let count = 0;
  const arms = data.steps.map((step, s) => {
    const shapes = layout(data.track, step, s, n);
    // traces under, glass over; within each, the spire last so it sits on top of its fan
    const order = [...shapes].sort((p, q) => (p.spire - q.spire) || (q.k - p.k));
    const traces = order.filter((g) => !done.has(`${step.id}.${g.it.id}`)).map((g) => shard(g, false, `${step.id}.${g.it.id}`));
    count += shapes.filter((g) => done.has(`${step.id}.${g.it.id}`)).length;
    const solids = order.filter((g) => done.has(`${step.id}.${g.it.id}`)).map((g) => shard(g, true, `${step.id}.${g.it.id}`));
    return `<g class="arm" data-step="${step.id}">${traces.join('')}${solids.join('')}</g>`;
  });
  const hits = data.steps.map((step, s) => arm(step, s, n)).join('');
  return `<svg class="crystal" viewBox="0 0 ${SIZE} ${SIZE}" xmlns="http://www.w3.org/2000/svg" role="img" `
    + `aria-label="${data.track}: ${count} items crystallised">`
    + `<g class="hits">${hits}</g>${arms.join('')}${seed(data.track)}</svg>`;
}
