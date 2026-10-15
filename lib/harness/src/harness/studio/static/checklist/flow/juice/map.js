// The map as a juice object: a fog-of-war map of the track, like Metroid's. Each step is a region of rooms, one room
// per item, joined in the path's order; the regions snake down the map joined by corridors; around the walls lies
// The Wasteland, never revealed here. A cleared item's room is revealed (floor, walls, a lit door to each cleared
// neighbour, a gold notch on each door to a room not yet entered); the rooms next to what you've seen show as dotted
// outlines through the fog. A step cleared opens its whole region, lights the corridor onward and opens a gate in
// the outer wall into The Wasteland. Drawn from the done set alone: the same set always draws the same map.
//
// On a commit: the fog peels back from the room, its walls draw in, its doors light; if that cleared the step, the
// region opens out, its name comes up, the corridor clears and the gate to The Wasteland glows.
import { hash, rng } from '../../concepts/model.js';
import { asSet, bump, ease, el, f, fadeIn, keyFor, lerp, tween, wait } from './fx.js';

export const label = 'Map';

const U = 20;                 // one cell
const M = 2;                  // the Wasteland's band, in cells
const SLOT_W = 5, SLOT_H = 2, GAP = 2;
const COLS = 16, ROWS = 18;   // M + 5 + 2 + 5 + M across; M + 4 rows of regions with gaps + M down
const W = COLS * U, H = ROWS * U;

/** Every region's slot and every room's cell, in cells. */
function layout(data) {
  return data.steps.map((step, s) => {
    const row = Math.floor(s / 2), col = row % 2 ? 1 - (s % 2) : s % 2;
    const n = step.items.length, cols = Math.ceil(n / 2);
    const sx = M + col * (SLOT_W + GAP), sy = M + row * (SLOT_H + GAP);
    const ox = sx + (SLOT_W - cols) / 2;
    const rooms = step.items.map((it, k) => {
      const top = k < cols;
      const c = top ? k : 2 * cols - 1 - k;
      return { it, k, cx: ox + c, cy: sy + (top ? 0 : 1) };
    });
    return { step, s, row, col, sx, sy, x0: ox, x1: ox + cols, rooms };
  });
}

const room = (r) => ({ x: r.cx * U + 2, y: r.cy * U + 2, w: U - 4, h: U - 4 });
const hole = (r) => ({ x: r.cx * U, y: r.cy * U, w: U, h: U });
const rect = (b, cls, extra = '') => `<rect class="${cls}" x="${f(b.x)}" y="${f(b.y)}" width="${f(b.w)}" height="${f(b.h)}"${extra}/>`;

/** The door between two rooms next to each other on the path. */
function door(a, b) {
  if (a.cy === b.cy) {
    const x = Math.max(a.cx, b.cx) * U;
    return { x: x - 3, y: a.cy * U + U / 2 - 2, w: 6, h: 4 };
  }
  const y = Math.max(a.cy, b.cy) * U;
  return { x: a.cx * U + U / 2 - 2, y: y - 3, w: 4, h: 6 };
}

/** The region's bounds (with a margin) and its corridor to the next one. */
const area = (g) => ({ x: g.x0 * U - 6, y: g.sy * U - 6, w: (g.x1 - g.x0) * U + 12, h: SLOT_H * U + 12 });
function corridor(g, next) {
  if (!next) return null;
  if (g.row === next.row) {                                         // side by side
    const y = (g.sy + 1) * U - 3;
    const [l, r] = g.col < next.col ? [g, next] : [next, g];
    return { x: l.x1 * U + 6, y, w: r.x0 * U - 6 - (l.x1 * U + 6), h: 6 };
  }
  const x = (g.sx + SLOT_W / 2) * U - 3;                            // one above the other
  return { x, y: (g.sy + SLOT_H) * U + 6, w: 6, h: (next.sy - g.sy - SLOT_H) * U - 12 };
}
/** The gate in the outer wall beside a region, and the trail out from it. */
function gate(g) {
  const y = (g.sy + 1) * U;
  const left = g.col === 0;
  const x = left ? M * U - 7 : (COLS - M) * U + 7;
  return { x, y, left };
}

/** The splash drawing for a done set. `id` keeps the mask's name apart when two maps share a page. */
export function render(data, done, { id = 'jzm' } = {}) {
  done = asSet(done);
  const L = layout(data);
  const isOn = (g, r) => done.has(`${g.step.id}.${r.it.id}`);
  const cleared = (g) => g.rooms.every((r) => isOn(g, r));

  const holes = [], floors = [], walls = [], doors = [], seen = [], labels = [], ways = [], gates = [];
  L.forEach((g, i) => {
    const next = L[i + 1], prevClear = i === 0 || cleared(L[i - 1]);
    if (cleared(g)) {
      const a = area(g);
      holes.push(rect(a, '', ' rx="6"'));
      floors.push(rect(a, 'mp-region', ' rx="6"'));
      labels.push(`<text class="mp-label" x="${f(a.x + a.w / 2)}" y="${f(a.y - 5)}">${g.step.n} ${g.step.name.toUpperCase()}</text>`);
      const c = corridor(g, next);
      if (c) { holes.push(rect(c, '')); ways.push(rect(c, 'mp-way')); }
      const gt = gate(g);
      gates.push(`<g class="mp-gate" data-step="${g.step.id}"><rect x="${f(gt.x - 2)}" y="${f(gt.y - 9)}" width="4" height="18" rx="1"/>`
        + `<path class="mp-trail" d="M${f(gt.x)} ${f(gt.y)} h${gt.left ? -(M * U - 14) : M * U - 14}"/></g>`);
    }
    g.rooms.forEach((r, k) => {
      const on = isOn(g, r);
      if (on) {
        holes.push(rect(hole(r), ''));
        walls.push(`<g class="mp-room" data-key="${g.step.id}.${r.it.id}">${rect(room(r), 'mp-floor')}${r.it.gate ? `<path class="mp-dp" d="M${f(r.cx * U + 10)} ${f(r.cy * U + 6)} l4 4 -4 4 -4 -4 Z"/>` : ''}</g>`);
      }
      const nb = [g.rooms[k - 1], g.rooms[k + 1]].filter(Boolean);
      for (const o of nb) {
        if (o.k < r.k) continue;                                  // each door once
        const a = on, b = isOn(g, o);
        if (a && b) doors.push(rect(door(r, o), 'mp-door', ` data-a="${g.step.id}.${r.it.id}" data-b="${g.step.id}.${o.it.id}"`));
        else if (a || b) doors.push(rect(door(r, o), 'mp-door frontier', ` data-a="${g.step.id}.${r.it.id}" data-b="${g.step.id}.${o.it.id}"`));
      }
      const near = nb.some((o) => isOn(g, o)) || (k === 0 && prevClear);
      if (!on && near) seen.push(rect(room(r), 'mp-seen', ` data-key="${g.step.id}.${r.it.id}"`));
    });
  });

  // the fog: dots on a dark ground, the same everywhere for the track
  const r = rng(hash(`${data.track}|fog`));
  const dots = Array.from({ length: 7 }, () => `<circle cx="${f(r() * 14)}" cy="${f(r() * 14)}" r="${f(0.5 + r() * 0.7)}"/>`).join('');
  const dense = Array.from({ length: 12 }, () => `<circle cx="${f(r() * 10)}" cy="${f(r() * 10)}" r="${f(0.4 + r() * 0.6)}"/>`).join('');
  const inner = { x: M * U, y: M * U, w: (COLS - 2 * M) * U, h: (ROWS - 2 * M) * U };
  const defs = `<pattern id="${id}-dots" width="14" height="14" patternUnits="userSpaceOnUse"><g class="mp-dots">${dots}</g></pattern>`
    + `<pattern id="${id}-dense" width="10" height="10" patternUnits="userSpaceOnUse"><g class="mp-dots dense">${dense}</g></pattern>`
    + `<mask id="${id}-fog" maskUnits="userSpaceOnUse" x="0" y="0" width="${W}" height="${H}"><rect x="0" y="0" width="${W}" height="${H}" fill="#fff"/>`
    + `<g class="mp-holes" fill="#000">${holes.join('')}</g></mask>`;
  const n = L.reduce((a, g) => a + g.rooms.filter((rr) => isOn(g, rr)).length, 0);
  const of = L.reduce((a, g) => a + g.rooms.length, 0);
  return `<div class="jz jz-map"><svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="The map: ${n} of ${of} rooms revealed">`
    + `<defs>${defs}</defs>`
    + `<rect class="mp-ground" x="0" y="0" width="${W}" height="${H}" rx="10"/>`
    + `<rect class="mp-waste" x="0" y="0" width="${W}" height="${H}" rx="10" fill="url(#${id}-dense)"/>`
    + `<text class="mp-waste-label" x="${W / 2}" y="${H - 13}">THE WASTELAND</text>`
    + `<g class="mp-under">${floors.join('')}${ways.join('')}${walls.join('')}</g>`
    + `<g class="mp-fog" mask="url(#${id}-fog)">${rect(inner, 'mp-fog-ground')}${rect(inner, 'mp-fog-dots', ` fill="url(#${id}-dots)"`)}</g>`
    + `<g class="mp-over">${seen.join('')}${doors.join('')}${labels.join('')}</g>`
    + `${rect({ x: inner.x - 4, y: inner.y - 4, w: inner.w + 8, h: inner.h + 8 }, 'mp-wall', ' rx="4"')}`
    + `<g class="mp-gates">${gates.join('')}</g></svg></div>`;
}

/** The header glyph: the regions' rooms, the revealed ones solid. No fog, so it reads on any header. */
export function mini(host, data, doneKeys) {
  const done = asSet(doneKeys);
  const cells = layout(data).flatMap((g) => g.rooms.map((r) => {
    const on = done.has(`${g.step.id}.${r.it.id}`);
    return `<rect class="mp-mcell${on ? ' on' : ''}" x="${f(r.cx * U + 2)}" y="${f(r.cy * U + 2)}" width="${U - 4}" height="${U - 4}" rx="2"/>`;
  })).join('');
  host.innerHTML = `<div class="jz jz-mini jz-map"><svg viewBox="${M * U - 4} ${M * U - 4} ${(COLS - 2 * M) * U + 8} ${(ROWS - 2 * M) * U + 8}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="The map">${cells}</svg></div>`;
}

export async function play(stage, { data, before, after, step, item, reduced }) {
  const [sid, iid, key] = keyFor(step, item);
  if (reduced) return fadeIn(stage, render(data, after));
  before = asSet(before); after = asSet(after);
  stage.innerHTML = render(data, before);
  const svg = stage.querySelector('svg');
  const L = layout(data);
  const g = L.find((x) => x.step.id === sid);
  const r = g?.rooms.find((x) => x.it.id === iid);
  if (!svg || !r) { stage.innerHTML = render(data, after); return; }
  const mask = svg.querySelector('.mp-holes');
  const over = svg.querySelector('.mp-over'), under = svg.querySelector('.mp-under');
  const fx = el('g', { class: 'jz-fx' }, over);
  const stepClears = g.rooms.every((x) => after.has(`${sid}.${x.it.id}`)) && !g.rooms.every((x) => before.has(`${sid}.${x.it.id}`));

  // 1. the fog peels back from the room, a gold scan line at its edge
  const hb = hole(r), cx = hb.x + U / 2, cy = hb.y + U / 2;
  const peel = el('rect', { x: cx, y: cy, width: 0, height: 0 }, mask);
  const scan = el('rect', { class: 'mp-scan', x: cx, y: cy, width: 0, height: 0 }, fx);
  const dotted = svg.querySelector(`.mp-seen[data-key="${key}"]`);
  const fl = el('rect', { class: 'mp-floor', ...room(r), opacity: 0 }, under);
  const rb = room(r);
  const wall = el('rect', { class: 'mp-draw', x: rb.x, y: rb.y, width: rb.w, height: rb.h }, fx);
  const per = 2 * (rb.w + rb.h);
  wall.style.strokeDasharray = `${per}`; wall.style.strokeDashoffset = `${per}`;
  const sizeTo = (node, b, e, pad = 0) => {
    const w = lerp(0, b.w + pad * 2, e), h = lerp(0, b.h + pad * 2, e);
    node.setAttribute('x', f(cx - w / 2)); node.setAttribute('y', f(cy - h / 2));
    node.setAttribute('width', f(w)); node.setAttribute('height', f(h));
  };

  // the doors to its neighbours, lit when the neighbour is cleared, a gold notch where it isn't
  const nb = [g.rooms[r.k - 1], g.rooms[r.k + 1]].filter(Boolean);
  const doors = nb.map((o) => {
    const lit = after.has(`${sid}.${o.it.id}`);
    const old = svg.querySelector(`.mp-door[data-a="${sid}.${(o.k < r.k ? o : r).it.id}"][data-b="${sid}.${(o.k < r.k ? r : o).it.id}"]`);
    old?.remove();
    const d = el('rect', { class: `mp-door ${lit ? 'jz-lit' : 'frontier'}`, ...door(r, o), opacity: 0 }, fx);
    return d;
  });

  const motion = [
    tween(460, (e) => { sizeTo(peel, hb, e, 0.5); sizeTo(scan, hb, e, 0.5); scan.style.opacity = String(1 - e * 0.6); }),
    dotted ? tween(260, (_, t) => { dotted.style.opacity = String(1 - t); }) : null,
    tween(360, (e) => { fl.setAttribute('opacity', e.toFixed(3)); }, { delay: 250 }),
    tween(460, (e) => { wall.style.strokeDashoffset = `${per * (1 - e)}`; }, { delay: 260, easing: ease.inOut }),
    tween(240, (_, t) => { scan.style.opacity = String(0.4 * (1 - t)); }, { delay: 520 }),
    ...doors.map((d, i) => tween(420, (_, t) => {
      d.setAttribute('opacity', Math.min(1, t * 2.5).toFixed(3));
      d.style.transformBox = 'fill-box'; d.style.transformOrigin = 'center';
      d.style.transform = `scale(${(1 + 1.4 * bump(t)).toFixed(3)})`;
      if (d.classList.contains('jz-lit')) d.classList.toggle('hot', t < 0.8);
    }, { delay: 640 + i * 90, easing: ease.linear })),
  ];

  if (stepClears) {
    // 2. the whole region opens: the fog rolls back from the room to the region's walls
    const a = area(g);
    const open = el('rect', { x: cx, y: cy, width: 0, height: 0, rx: 6 }, mask);
    const frame = el('rect', { class: 'mp-draw region', x: a.x, y: a.y, width: a.w, height: a.h, rx: 6 }, fx);
    const fper = 2 * (a.w + a.h);
    frame.style.strokeDasharray = `${fper}`; frame.style.strokeDashoffset = `${fper}`;
    const floor = el('rect', { class: 'mp-region', x: a.x, y: a.y, width: a.w, height: a.h, rx: 6, opacity: 0 }, under);
    const name = el('text', { class: 'mp-label', x: f(a.x + a.w / 2), y: f(a.y - 5), opacity: 0 }, fx);
    name.textContent = `${g.step.n} ${g.step.name.toUpperCase()}`;
    const c = corridor(g, L[g.s + 1]);
    const cw = c && el('rect', { x: c.x, y: c.y, width: 0, height: 0 }, mask);
    const cwv = c && el('rect', { class: 'mp-way', x: c.x, y: c.y, width: 0, height: 0 }, under);
    const gt = gate(g);
    const gg = el('g', { class: 'mp-gate jz-glow', opacity: 0 }, fx);
    el('rect', { x: gt.x - 2, y: gt.y - 9, width: 4, height: 18, rx: 1 }, gg);
    const trail = el('path', { class: 'mp-trail', d: `M${gt.x} ${gt.y} h${gt.left ? -(M * U - 14) : M * U - 14}` }, gg);
    const halo = el('circle', { class: 'mp-halo', cx: gt.x, cy: gt.y, r: 0 }, fx);
    motion.push(
      tween(640, (e) => {
        const x = lerp(cx, a.x, e), y = lerp(cy, a.y, e);
        open.setAttribute('x', f(x)); open.setAttribute('y', f(y));
        open.setAttribute('width', f(lerp(0, a.w, e))); open.setAttribute('height', f(lerp(0, a.h, e)));
        floor.setAttribute('opacity', e.toFixed(3));
      }, { delay: 900, easing: ease.inOut }),
      tween(620, (e) => { frame.style.strokeDashoffset = `${fper * (1 - e)}`; }, { delay: 960, easing: ease.inOut }),
      tween(300, (e) => { name.setAttribute('opacity', e.toFixed(3)); }, { delay: 1300 }),
      c ? tween(380, (e) => {
        const w = c.w > c.h ? c.w * e : c.w, h = c.w > c.h ? c.h : c.h * e;
        for (const n of [cw, cwv]) { n.setAttribute('width', f(w)); n.setAttribute('height', f(h)); }
      }, { delay: 1340 }) : null,
      tween(560, (_, t) => {
        gg.setAttribute('opacity', Math.min(1, t * 3).toFixed(3));
        halo.setAttribute('r', f(lerp(2, 30, t))); halo.style.opacity = String(1 - t);
        trail.style.strokeDashoffset = `${-24 * t}`;
      }, { delay: 1420, easing: ease.linear }),
    );
  }
  await Promise.all(motion);
  await wait(60);
  stage.innerHTML = render(data, after);
}
