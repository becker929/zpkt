// The repair board as a juice object. The splash shows the committed item's step as a row of large tiles, and under
// it the whole track as a small 49-cell board. An open tile is broken (its four pieces knocked apart, one lost a
// little further) and grimy; a cleared one is whole, pale, with its rune (a mark that is the same for an item
// everywhere). On a commit the tile restores itself, with no scrubbing: the grime lifts off, the pieces snap home,
// the rune draws in and a gold glint crosses it. Everything is drawn from hash(track, step, item), so the same done set
// always draws the same board.
import { hash, rng } from '../../concepts/model.js';
import { asSet, bump, ease, el, f, fadeIn, keyFor, lerp, tween, wait } from './fx.js';

export const label = 'Repair';

const T = 100, GAP = 16, W = 600;          // a tile, the gap between tiles, the drawing's width
const CELL = 13, CGAP = 3;                 // the small board's cells

function grid(n) {
  const cols = n <= 5 ? n : Math.ceil(n / 2);
  return { cols, rows: Math.ceil(n / cols) };
}

/** Where everything sits for one step: its tiles, the small board and the drawing's height. */
function layout(data, sid) {
  const step = data.steps.find((s) => s.id === sid) ?? data.steps[0];
  const { cols, rows } = grid(step.items.length);
  const tw = cols * T + (cols - 1) * GAP;
  const x0 = (W - tw) / 2, y0 = 74;
  const tiles = step.items.map((it, k) => ({
    it, k, x: x0 + (k % cols) * (T + GAP), y: y0 + Math.floor(k / cols) * (T + GAP),
  }));
  const by = y0 + rows * T + (rows - 1) * GAP + 56;
  const maxN = Math.max(...data.steps.map((s) => s.items.length));
  const bw = maxN * CELL + (maxN - 1) * CGAP;
  const bx = (W - bw) / 2;
  const H = by + data.steps.length * (CELL + CGAP) + 34;
  return { step, tiles, bx, by, H };
}

/** The rune: a path through three or four points of a 3×3 grid, the same for an item everywhere. */
function rune(track, sid, iid) {
  const r = rng(hash(`${track}|${sid}|${iid}|rune`));
  const pts = [];
  const used = new Set();
  const n = 3 + Math.floor(r() * 2);
  while (pts.length < n) {
    const i = Math.floor(r() * 9);
    if (used.has(i)) continue;
    used.add(i);
    pts.push([28 + (i % 3) * 22, 28 + Math.floor(i / 3) * 22]);
  }
  return `M${pts.map(([x, y]) => `${x},${y}`).join('L')}`;
}

/** A broken tile's four pieces, the grime on them, and how far each piece has been knocked out of place. */
function broken(track, sid, iid) {
  const r = rng(hash(`${track}|${sid}|${iid}|tile`));
  const c = [38 + r() * 24, 38 + r() * 24];
  const e = { t: [30 + r() * 40, 0], r: [T, 30 + r() * 40], b: [30 + r() * 40, T], l: [0, 30 + r() * 40] };
  const mid = (p) => [lerp(c[0], p[0], 0.5) + (r() - 0.5) * 12, lerp(c[1], p[1], 0.5) + (r() - 0.5) * 12];
  const m = { t: mid(e.t), r: mid(e.r), b: mid(e.b), l: mid(e.l) };
  const shapes = [
    [[0, 0], e.t, m.t, c, m.l, e.l],
    [e.t, [T, 0], e.r, m.r, c, m.t],
    [c, m.r, e.r, [T, T], e.b, m.b],
    [e.l, m.l, c, m.b, e.b, [0, T]],
  ];
  const lost = Math.floor(r() * 4);
  const pieces = shapes.map((pts, i) => {
    const cx = pts.reduce((a, p) => a + p[0], 0) / pts.length, cy = pts.reduce((a, p) => a + p[1], 0) / pts.length;
    const away = Math.atan2(cy - 50, cx - 50);
    const d = i === lost ? 9 + r() * 5 : 2.5 + r() * 3.5;
    return { pts, cx, cy, dx: Math.cos(away) * d, dy: Math.sin(away) * d, a: (r() - 0.5) * (i === lost ? 22 : 9), lost: i === lost };
  });
  const grime = Array.from({ length: 7 + Math.floor(r() * 5) }, () => ({
    x: 8 + r() * 84, y: 8 + r() * 84, rx: 3 + r() * 10, ry: 2 + r() * 6, rot: r() * 180, o: 0.14 + r() * 0.22,
  }));
  const drips = Array.from({ length: Math.floor(r() * 2) }, () => ({ x: 12 + r() * 76, y: r() * 20, l: 14 + r() * 26 }));
  return { pieces, grime, drips };
}

function tile(track, sid, t, done, id) {
  const key = `${sid}.${t.it.id}`;
  const at = `translate(${f(t.x)} ${f(t.y)})`;
  const gate = t.it.gate ? '<path class="rp-gate" d="M86 6 L94 14 L86 22 L78 14 Z"/>' : '';
  if (done) {
    return `<g class="rp-tile done" data-key="${key}" transform="${at}"><rect class="rp-face" width="${T}" height="${T}" rx="5"/>`
      + `<path class="rp-rune" d="${rune(track, sid, t.it.id)}"/><text class="rp-n" x="8" y="${T - 9}">${t.k + 1}</text>${gate}</g>`;
  }
  const { pieces, grime, drips } = broken(track, sid, t.it.id);
  const pcs = pieces.map((p, i) => `<polygon class="rp-pc${p.lost ? ' lost' : ''}" data-i="${i}" data-dx="${f(p.dx)}" data-dy="${f(p.dy)}" data-a="${f(p.a)}" data-cx="${f(p.cx)}" data-cy="${f(p.cy)}" `
    + `points="${p.pts.map(([x, y]) => `${f(x)},${f(y)}`).join(' ')}" transform="translate(${f(p.dx)} ${f(p.dy)}) rotate(${f(p.a)} ${f(p.cx)} ${f(p.cy)})"/>`).join('');
  const gm = grime.map((g) => `<ellipse class="rp-gm" cx="${f(g.x)}" cy="${f(g.y)}" rx="${f(g.rx)}" ry="${f(g.ry)}" transform="rotate(${f(g.rot)} ${f(g.x)} ${f(g.y)})" style="opacity:${g.o.toFixed(2)}"/>`).join('')
    + drips.map((d) => `<path class="rp-gm rp-drip" d="M${f(d.x)} ${f(d.y)} v${f(d.l)}"/>`).join('');
  return `<g class="rp-tile open" data-key="${key}" transform="${at}"><g class="rp-pcs">${pcs}</g>`
    + `<g class="rp-grime" clip-path="url(#${id}-${key.replace('.', '-')})">${gm}</g>${gate}</g>`;
}

/** The splash drawing for a done set, showing `step`. */
export function render(data, done, { step, id = 'jzr' } = {}) {
  done = asSet(done);
  const sid = typeof step === 'string' ? step : step?.id;
  const L = layout(data, sid);
  const s = L.step;
  const clips = L.tiles.map((t) => `<clipPath id="${id}-${s.id}-${t.it.id}"><rect width="${T}" height="${T}" rx="5"/></clipPath>`).join('');
  const tiles = L.tiles.map((t) => tile(data.track, s.id, t, done.has(`${s.id}.${t.it.id}`), id)).join('');
  const n = s.items.filter((it) => done.has(`${s.id}.${it.id}`)).length;
  const head = `<text class="rp-step" x="${W / 2}" y="34">${s.n}  ${s.name.toUpperCase()}</text>`
    + `<text class="rp-count" x="${W / 2}" y="56">${n} of ${s.items.length} restored</text>`;
  const board = data.steps.map((st, r) => st.items.map((it, c) => {
    const on = done.has(`${st.id}.${it.id}`);
    const here = st.id === s.id ? ' here' : '';
    return `<rect class="rp-cell${on ? ' on' : ''}${here}" data-key="${st.id}.${it.id}" x="${f(L.bx + c * (CELL + CGAP))}" y="${f(L.by + r * (CELL + CGAP))}" width="${CELL}" height="${CELL}" rx="2"/>`;
  }).join('')).join('');
  const total = data.steps.reduce((a, st) => a + st.items.filter((it) => done.has(`${st.id}.${it.id}`)).length, 0);
  const of = data.steps.reduce((a, st) => a + st.items.length, 0);
  const foot = `<text class="rp-count" x="${W / 2}" y="${f(L.H - 8)}">${total} / ${of} across the track</text>`;
  return `<div class="jz jz-repair"><svg viewBox="0 0 ${W} ${f(L.H)}" xmlns="http://www.w3.org/2000/svg" role="img" `
    + `aria-label="${s.name}: ${n} of ${s.items.length} restored"><defs>${clips}</defs>${head}${tiles}<g class="rp-board">${board}</g>${foot}</svg></div>`;
}

/** The header glyph: the whole track as a small board, one row per step. */
export function mini(host, data, doneKeys) {
  const done = asSet(doneKeys);
  const c = 4, g = 1.4;
  const maxN = Math.max(...data.steps.map((s) => s.items.length));
  const w = maxN * c + (maxN - 1) * g, h = data.steps.length * c + (data.steps.length - 1) * g;
  const cells = data.steps.map((s, r) => s.items.map((it, k) => `<rect class="rp-cell${done.has(`${s.id}.${it.id}`) ? ' on' : ''}" x="${f(k * (c + g))}" y="${f(r * (c + g))}" width="${c}" height="${c}" rx="0.6"/>`).join('')).join('');
  host.innerHTML = `<div class="jz jz-mini jz-repair"><svg viewBox="-1 -1 ${f(w + 2)} ${f(h + 2)}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="The repair board">${cells}</svg></div>`;
}

export async function play(stage, { data, before, after, step, item, reduced }) {
  const [sid, iid, key] = keyFor(step, item);
  const opts = { step: sid };
  if (reduced) return fadeIn(stage, render(data, after, opts));
  stage.innerHTML = render(data, before, opts);
  const svg = stage.querySelector('svg');
  const t = svg?.querySelector(`.rp-tile[data-key="${key}"]`);
  if (!t || t.classList.contains('done')) { stage.innerHTML = render(data, after, opts); return; }
  const at = t.getAttribute('transform');
  const pieces = [...t.querySelectorAll('.rp-pc')];
  const grime = [...t.querySelectorAll('.rp-gm')];
  const cell = svg.querySelector(`.rp-cell[data-key="${key}"]`);

  // what the motion adds on top: a hint around the tile, the rune drawing in, the glint
  const fx = el('g', { class: 'jz-fx', transform: at }, svg);
  const hint = el('rect', { class: 'rp-hint', x: -5, y: -5, width: T + 10, height: T + 10, rx: 8 }, fx);
  const clip = el('clipPath', { id: 'jzr-glint' }, el('defs', {}, fx));
  el('rect', { width: T, height: T, rx: 5 }, clip);
  const face = el('rect', { class: 'rp-face', width: T, height: T, rx: 5, opacity: 0 }, fx);
  const mark = el('path', { class: 'rp-rune', d: rune(data.track, sid, iid) }, fx);
  const len = mark.getTotalLength ? mark.getTotalLength() : 160;
  mark.style.strokeDasharray = `${len}`; mark.style.strokeDashoffset = `${len}`;
  const grad = el('linearGradient', { id: 'jzr-glint-g', x1: 0, x2: 1, y1: 0, y2: 0 }, clip.parentNode);
  el('stop', { offset: '0', class: 'rp-g0' }, grad); el('stop', { offset: '0.5', class: 'rp-g1' }, grad); el('stop', { offset: '1', class: 'rp-g0' }, grad);
  const glint = el('g', { 'clip-path': 'url(#jzr-glint)' }, fx);
  const band = el('polygon', { points: '-40,-20 0,-20 -60,120 -100,120', fill: 'url(#jzr-glint-g)', opacity: 0 }, glint);
  const spark = el('path', { class: 'rp-spark', d: 'M0 -9 L2 -2 L9 0 L2 2 L0 9 L-2 2 L-9 0 L-2 -2 Z', transform: `translate(${T - 6} 6) scale(0)` }, fx);

  await tween(160, (e) => { hint.style.opacity = String(e); });
  const motion = [
    // the grime lifts away, each speck on its own
    ...grime.map((g, i) => {
      const t0 = g.getAttribute('transform') || '', o = Number(g.style.opacity || 0.5);
      return tween(520, (e) => {
        g.setAttribute('transform', `translate(${((i % 2 ? 1 : -1) * 5 * e).toFixed(2)} ${(-26 * e).toFixed(2)}) ${t0}`);
        g.style.opacity = String(o * (1 - e));
      }, { delay: i * 18 });
    }),
    // the pieces snap home, the lost one last
    ...pieces.map((p, i) => {
      const dx = +p.dataset.dx, dy = +p.dataset.dy, a = +p.dataset.a, cx = p.dataset.cx, cy = p.dataset.cy;
      return tween(420, (e) => {
        const k = 1 - e;
        p.setAttribute('transform', `translate(${(dx * k).toFixed(2)} ${(dy * k).toFixed(2)}) rotate(${(a * k).toFixed(2)} ${cx} ${cy})`);
      }, { delay: 360 + (p.classList.contains('lost') ? 170 : i * 45), easing: ease.back });
    }),
    // a thump as it comes together, the face goes pale, the rune draws in
    tween(240, (_, t2) => {
      const s = 1 + 0.06 * bump(t2);
      t.setAttribute('transform', `${at} translate(50 50) scale(${s.toFixed(4)}) translate(-50 -50)`);
      fx.setAttribute('transform', `${at} translate(50 50) scale(${s.toFixed(4)}) translate(-50 -50)`);
    }, { delay: 820, easing: ease.linear }),
    tween(260, (e) => { face.setAttribute('opacity', e.toFixed(3)); }, { delay: 860 }),
    tween(380, (e) => { mark.style.strokeDashoffset = `${len * (1 - e)}`; }, { delay: 980 }),
    tween(300, (_, t2) => { hint.style.opacity = String(1 - t2); }, { delay: 900 }),
    // the gold glint crosses it, and a spark at the corner
    tween(520, (e, t2) => {
      band.setAttribute('transform', `translate(${lerp(0, 230, e).toFixed(1)} 0)`);
      band.setAttribute('opacity', bump(t2).toFixed(3));
    }, { delay: 1060, easing: ease.inOut }),
    tween(420, (_, t2) => { spark.setAttribute('transform', `translate(${T - 6} 6) scale(${(1.3 * bump(t2)).toFixed(3)}) rotate(${(t2 * 90).toFixed(1)})`); }, { delay: 1240, easing: ease.linear }),
    // its cell on the board fills
    cell ? tween(320, (_, t2) => { cell.classList.add('on', 'jz-flash'); cell.style.opacity = String(0.4 + 0.6 * t2); }, { delay: 1100 }) : null,
  ];
  // the commit restored the whole step: a gold wave runs across its tiles, in the path's order
  const all = (set) => (data.steps.find((x) => x.id === sid)?.items ?? []).every((it) => asSet(set).has(`${sid}.${it.id}`));
  if (all(after) && !all(before)) {
    const tiles = [...svg.querySelectorAll('.rp-tile')];
    motion.push(...tiles.map((tl, i) => {
      const glow = el('rect', { class: 'rp-wave', width: T, height: T, rx: 5, transform: tl.getAttribute('transform').split(' translate(50')[0], opacity: 0 }, svg);
      return tween(380, (_, t2) => { glow.setAttribute('opacity', (0.85 * bump(t2)).toFixed(3)); }, { delay: 1150 + i * 45, easing: ease.linear });
    }));
  }
  await Promise.all(motion);
  await wait(60);
  stage.innerHTML = render(data, after, opts);
}
