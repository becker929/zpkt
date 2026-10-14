// The repair board: the whole track on one screen, each item a tile. A cleared item is restored (solid ink); an open
// one is decayed, under grime that is the same every time for that item. Scrubbing a tile clean restores it. Opening
// an item again cracks the cleared items after it in its step (they were built on it); scrubbing along a crack heals
// it in gold, and the seam stays, so the board keeps the history of what was redone. Nothing is locked: the board is
// what would go out the door if the track were released now.
import {
  TRACK, extra, haptic, hash, isDone, keyOf, loadTrack, onChange, onTap, rng, roles, setDone, setExtra, stateOf,
  studioHref, totals,
} from './model.js';

const CLEAN_AT = 0.85;      // the share of the surface scrubbed that counts as restored
const GRID = 40;            // coverage cells per side
const BRUSH = 0.085;        // the brush's radius, as a share of the surface's side
const NEAR_CRACK = 0.07;    // how close to a crack a cell must be for the crack to need scrubbing there
const REOPEN_MS = 650;
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const dpr = () => Math.min(3, devicePixelRatio || 1);
const $ = (id) => document.getElementById(id);

let data;
const crackKey = (step, it) => `${keyOf(step, it)}!crack`;
const goldKey = (step, it) => `${keyOf(step, it)}!gold`;
const cracked = (step, it) => isDone(step, it) && !!extra(crackKey(step, it));
const golds = (step, it) => Number(extra(goldKey(step, it))) || 0;

// --- the palette, from the stylesheet's tokens (so dark mode is one place) ---
let pal;
function palette() {
  const cs = getComputedStyle(document.documentElement);
  const v = (n) => cs.getPropertyValue(n).trim();
  pal = { ink: v('--ink'), paper: v('--tile-paper'), gold: v('--gold'), seam: v('--bg'), goldHi: v('--gold-hi'),
    grime: [v('--grime-1'), v('--grime-2'), v('--grime-3')] };    // "r,g,b"
}
const rgba = (t, a) => `rgba(${t},${a.toFixed(3)})`;

// --- deterministic drawing, in a unit square scaled to the canvas ---
/** Grime for an item: a mottled wash, drips and specks, the same for the same item every time. `amount` thins it. */
function grime(ctx, s, key, amount = 1) {
  const r = rng(hash(`${TRACK}:${key}#grime`));
  ctx.fillStyle = rgba(pal.paper, amount); ctx.fillRect(0, 0, s, s);
  for (let i = 0; i < 22; i++) {
    const x = r() * s, y = r() * s, rad = (0.1 + r() * 0.38) * s, t = pal.grime[Math.floor(r() * 3)];
    const g = ctx.createRadialGradient(x, y, 0, x, y, rad);
    const a = (0.16 + r() * 0.32) * amount;
    g.addColorStop(0, rgba(t, a)); g.addColorStop(0.6, rgba(t, a * 0.45)); g.addColorStop(1, rgba(t, 0));
    ctx.fillStyle = g; ctx.fillRect(0, 0, s, s);
  }
  ctx.lineCap = 'round';
  for (let i = 0; i < 6; i++) {                          // drips, from the top edge down
    let x = r() * s, y = -2;
    const len = (0.25 + r() * 0.6) * s;
    ctx.strokeStyle = rgba(pal.grime[2], (0.10 + r() * 0.14) * amount);
    ctx.lineWidth = (0.006 + r() * 0.02) * s;
    ctx.beginPath(); ctx.moveTo(x, y);
    while (y < len) { y += s * 0.05; x += (r() - 0.5) * s * 0.02; ctx.lineTo(x, y); }
    ctx.stroke();
  }
  for (let i = 0; i < 900; i++) {                        // grit: fine, uneven, mostly tiny
    const t = pal.grime[Math.floor(r() * 3)];
    ctx.fillStyle = rgba(t, (0.12 + r() * 0.4) * amount);
    const w = (0.0015 + r() ** 4 * 0.011) * s, h = w * (0.5 + r());
    ctx.save(); ctx.translate(r() * s, r() * s); ctx.rotate(r() * Math.PI);
    ctx.beginPath(); ctx.ellipse(0, 0, w, h, 0, 0, Math.PI * 2); ctx.fill(); ctx.restore();
  }
  const v = ctx.createRadialGradient(s / 2, s / 2, s * 0.3, s / 2, s / 2, s * 0.75);   // darker at the edges
  v.addColorStop(0, rgba(pal.grime[2], 0)); v.addColorStop(1, rgba(pal.grime[2], 0.28 * amount));
  ctx.fillStyle = v; ctx.fillRect(0, 0, s, s);
}

/** The n-th crack through an item (1, 2, …): a jagged line from one edge across the tile, with a branch or two.
 * The n-th crack, once healed, is the n-th gold seam, so the seam is exactly the crack that was scrubbed. */
function crack(key, n) {
  const r = rng(hash(`${TRACK}:${key}#crack${n}`));
  const edge = (e, t) => [[t, 0], [1, t], [t, 1], [0, t]][e];
  const e0 = Math.floor(r() * 4), e1 = (e0 + 1 + Math.floor(r() * 3)) % 4;
  const a = edge(e0, 0.15 + r() * 0.7), b = edge(e1, 0.15 + r() * 0.7);
  const steps = 7 + Math.floor(r() * 4), main = [a];
  for (let i = 1; i < steps; i++) {
    const t = i / steps;
    main.push([a[0] + (b[0] - a[0]) * t + (r() - 0.5) * 0.14, a[1] + (b[1] - a[1]) * t + (r() - 0.5) * 0.14]);
  }
  main.push(b);
  const lines = [main];
  for (let k = 0, nb = 1 + Math.floor(r() * 2); k < nb; k++) {
    const from = main[2 + Math.floor(r() * (main.length - 4))];
    const ang = r() * Math.PI * 2, line = [from];
    let [x, y] = from;
    for (let i = 0; i < 3; i++) { x += Math.cos(ang + (r() - 0.5)) * 0.08; y += Math.sin(ang + (r() - 0.5)) * 0.08; line.push([x, y]); }
    lines.push(line);
  }
  return lines;
}

/** Lines in a unit square, `width` a share of the side but never under about a pixel. */
function strokeLines(ctx, s, lines, color, width) {
  ctx.strokeStyle = color; ctx.lineJoin = 'round'; ctx.lineCap = 'round';
  const px = 1.1 * dpr();
  for (const [i, line] of lines.entries()) {
    ctx.lineWidth = Math.max(px, (i === 0 ? width : width * 0.6) * s);
    ctx.beginPath();
    line.forEach(([x, y], j) => (j ? ctx.lineTo(x * s, y * s) : ctx.moveTo(x * s, y * s)));
    ctx.stroke();
  }
}

/** The restored tile: ink, with a gold seam for every crack it has healed (a seam is gold with a paler line along
 * it, so it reads as metal, not paint). Seams are finer on a large surface than on a small tile. */
const seamWidth = (s) => (s > 300 ? 0.016 : 0.03);
function restored(ctx, s, key, seams) {
  ctx.fillStyle = pal.ink; ctx.fillRect(0, 0, s, s);
  for (let n = 1; n <= seams; n++) {
    strokeLines(ctx, s, crack(key, n), pal.gold, seamWidth(s));
    if (s > 300) strokeLines(ctx, s, crack(key, n), pal.goldHi, seamWidth(s) * 0.3);
  }
}

function sized(canvas) {
  const w = canvas.getBoundingClientRect().width;
  const s = Math.max(1, Math.round(w * dpr()));
  if (canvas.width !== s) { canvas.width = s; canvas.height = s; }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, s, s);
  ctx.globalCompositeOperation = 'source-over';
  return [ctx, s];
}

// --- the board ---
const tiles = new Map();    // key -> {btn, canvas, step, it}

function build() {
  $('track').textContent = data.track;
  document.title = `${data.track} Repair Board`;
  const board = $('board');
  board.replaceChildren();
  for (const step of data.steps) {
    const count = document.createElement('span');
    count.className = 'block-count';
    const head = document.createElement('div');
    head.className = 'block-head';
    head.innerHTML = `<span class="block-n"></span><span class="block-name"></span>`;
    head.children[0].textContent = step.n; head.children[1].textContent = step.name;
    head.append(count);
    const row = document.createElement('div');
    row.className = 'tiles';
    step.items.forEach((it, i) => {
      const btn = document.createElement('button');
      btn.type = 'button'; btn.className = 'tile'; btn.dataset.key = keyOf(step, it);
      btn.setAttribute('aria-label', `${step.n}.${i + 1} ${it.title}`);
      if (it.gate) btn.classList.add('gate');
      const canvas = document.createElement('canvas');
      btn.append(canvas);
      onTap(btn, () => open(step, it));
      row.append(btn);
      tiles.set(keyOf(step, it), { btn, canvas, step, it });
    });
    const block = document.createElement('section');
    block.className = 'block'; block.dataset.step = step.id;
    block.append(head, row);
    block.count = count;
    board.append(block);
  }
}

function paintBoard() {
  for (const block of $('board').children) {
    const step = data.steps.find((s) => s.id === block.dataset.step);
    const done = step.items.filter((it) => isDone(step, it)).length;
    block.count.textContent = `${done}/${step.items.length}`;
    block.classList.toggle('clear', done === step.items.length);
    const r = roles(step);
    step.items.forEach((it, i) => paintTile(tiles.get(keyOf(step, it)), r[i]));
  }
  const [n, of] = totals(data);
  const cracks = [...tiles.values()].filter((t) => cracked(t.step, t.it)).length;
  $('tally').innerHTML = `<b>${n}</b><span>/${of}</span>${cracks ? `<em>${cracks} cracked</em>` : ''}`;
}

function paintTile(t, role) {
  const { btn, canvas, step, it } = t;
  const key = keyOf(step, it);
  const state = !isDone(step, it) ? 'decayed' : cracked(step, it) ? 'cracked' : 'restored';
  btn.dataset.state = state; btn.dataset.role = role;
  btn.dataset.gold = String(golds(step, it));
  const [ctx, s] = sized(canvas);
  if (state === 'decayed') grime(ctx, s, key);
  else {
    restored(ctx, s, key, golds(step, it));
    if (state === 'cracked') strokeLines(ctx, s, crack(key, golds(step, it) + 1), pal.seam, 0.05);
  }
}

// --- the sheet: one item, large, with the surface to scrub ---
let sheet = null;     // {step, it, cells, cleared, total, done}

function open(step, it) {
  haptic();
  sheet = { step, it };
  $('sheet').classList.add('open'); $('sheet').setAttribute('aria-hidden', 'false');
  $('scrim').classList.add('show');
  fillSheet();
}
function close() {
  if (!sheet) return;
  sheet = null;
  $('sheet').classList.remove('open'); $('sheet').setAttribute('aria-hidden', 'true');
  $('scrim').classList.remove('show');
}

const PLACE = {
  you: 'Your move',
  ready: 'Ready: the agent cleared the way, and it waits on your move above (mocked)',
  clearing: 'The agent is clearing here (mocked)',
  ahead: 'Further along the path',
};
const times = (n) => (n === 1 ? 'once' : n === 2 ? 'twice' : `${n} times`);

function fillSheet() {
  const { step, it } = sheet;
  const i = step.items.indexOf(it);
  const role = roles(step)[i];
  const state = !isDone(step, it) ? 'decayed' : cracked(step, it) ? 'cracked' : 'restored';
  const g = golds(step, it);
  $('sheet').dataset.state = state;
  $('sheet-crumb').textContent = `${step.n} ${step.name} · ${i + 1} of ${step.items.length}`;
  $('sheet-title').textContent = it.title;
  let place = state === 'cracked' ? 'Cracked: something before it was opened again. Scrub along the crack to re-check it'
    : state === 'restored' ? `Restored${g ? `, healed in gold ${times(g)}` : ''}` : PLACE[role];
  if (it.gate) place += ' · a decision point, not a lock';
  $('sheet-place').textContent = place;
  $('sheet-why').textContent = state === 'decayed' && (role === 'you' || role === 'clearing') ? (it.why ?? '') : '';
  $('sheet-studio').href = studioHref(step, it);
  $('reopen').hidden = state === 'decayed';

  const surface = $('surface');
  surface.classList.remove('finishing', 'finished');
  const base = $('base'), top = $('grime');
  const [bctx, s] = sized(base);
  restored(bctx, s, keyOf(step, it), g + (state === 'cracked' ? 1 : 0));   // under a crack lies its gold seam
  const [ctx] = sized(top);
  top.style.opacity = '';
  const key = keyOf(step, it);
  // which cells must be scrubbed: all of a decayed tile, the cells along a crack
  const lines = state === 'cracked' ? crack(key, g + 1) : null;
  const cells = [];
  for (let y = 0; y < GRID; y++) {
    for (let x = 0; x < GRID; x++) {
      const p = [(x + 0.5) / GRID, (y + 0.5) / GRID];
      if (!lines || lines.some((l) => nearLine(p, l) < NEAR_CRACK)) cells.push(p);
    }
  }
  if (state === 'decayed') grime(ctx, s, key);
  else if (state === 'cracked') {
    grime(ctx, s, `${key}#dust${g + 1}`, 0.75);     // dust along the crack, kept only near it
    ctx.save();
    ctx.globalCompositeOperation = 'destination-in';
    ctx.beginPath();
    for (const l of lines) l.forEach(([x, y], j) => (j ? ctx.lineTo(x * s, y * s) : ctx.moveTo(x * s, y * s)));
    ctx.lineWidth = NEAR_CRACK * 1.4 * s; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.strokeStyle = 'rgba(0,0,0,1)';
    ctx.stroke();
    ctx.restore();
    strokeLines(ctx, s, lines, pal.seam, 0.03);      // and the crack itself, a line of paper through the ink
  }
  sheet.cells = cells; sheet.cleared = new Uint8Array(cells.length); sheet.total = 0; sheet.done = state === 'restored';
  surface.dataset.clean = state === 'restored' ? '100' : '0';
  surface.classList.toggle('idle', state === 'restored');
  meter(state === 'restored' ? 1 : 0);
}

function nearLine([px, py], line) {
  let best = Infinity;
  for (let i = 1; i < line.length; i++) best = Math.min(best, segDist(px, py, line[i - 1], line[i]));
  return best;
}
function segDist(px, py, [ax, ay], [bx, by]) {
  const dx = bx - ax, dy = by - ay, l = dx * dx + dy * dy;
  const t = l ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / l)) : 0;
  return Math.hypot(px - ax - t * dx, py - ay - t * dy);
}

function meter(p) {
  $('meter-fill').style.transform = `scaleX(${Math.min(1, p / CLEAN_AT)})`;
  $('meter-n').textContent = p >= 1 ? 'Restored' : `${Math.round(p * 100)} % clean`;
  $('meter').classList.toggle('near', p >= CLEAN_AT * 0.8 && p < 1);
}

// scrubbing: the finger erases the grime where it goes and clears the coverage cells under the brush
function scrubber() {
  const surface = $('surface'), top = $('grime');
  let last = null;
  const at = (e) => {
    const r = top.getBoundingClientRect();
    return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height];
  };
  const stroke = (a, b) => {
    const ctx = top.getContext('2d'), s = top.width;
    ctx.globalCompositeOperation = 'destination-out';
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.strokeStyle = 'rgba(0,0,0,0.35)'; ctx.lineWidth = BRUSH * 2.7 * s;
    ctx.beginPath(); ctx.moveTo(a[0] * s, a[1] * s); ctx.lineTo(b[0] * s, b[1] * s); ctx.stroke();
    ctx.strokeStyle = 'rgba(0,0,0,1)'; ctx.lineWidth = BRUSH * 2 * s;
    ctx.beginPath(); ctx.moveTo(a[0] * s, a[1] * s); ctx.lineTo(b[0] * s, b[1] * s); ctx.stroke();
    const before = sheet.total;
    sheet.cells.forEach((p, i) => {
      if (!sheet.cleared[i] && segDist(p[0], p[1], a, b) <= BRUSH) { sheet.cleared[i] = 1; sheet.total++; }
    });
    const p = sheet.total / sheet.cells.length;
    if (Math.floor(p * 10) > Math.floor((before / sheet.cells.length) * 10)) haptic();
    surface.dataset.clean = String(Math.round(p * 100));
    meter(p);
    if (p >= CLEAN_AT) finish();
  };
  surface.addEventListener('pointerdown', (e) => {
    if (!sheet || sheet.done) return;
    e.preventDefault();
    try { surface.setPointerCapture(e.pointerId); } catch { /* a pointer the browser no longer tracks */ }
    last = at(e);
    stroke(last, last);
  });
  surface.addEventListener('pointermove', (e) => {
    if (!last || !sheet || sheet.done) return;
    const evs = e.getCoalescedEvents?.() ?? [];
    for (const ev of evs.length ? evs : [e]) { const p = at(ev); stroke(last, p); last = p; if (sheet.done) break; }
  });
  const up = () => { last = null; };
  surface.addEventListener('pointerup', up);
  surface.addEventListener('pointercancel', up);
}

// restored: what grime is left fades, a line of light crosses the tile, and the item is cleared
function finish() {
  const { step, it } = sheet;
  sheet.done = true;
  haptic(true);
  const surface = $('surface');
  surface.classList.add('finishing');
  meter(1);
  surface.dataset.clean = '100';
  setTimeout(() => {
    if (cracked(step, it)) {
      setExtra(goldKey(step, it), golds(step, it) + 1);       // the crack becomes the next seam
      setExtra(crackKey(step, it), undefined);
    } else {
      setDone(step, it, true);
    }
    surface.classList.add('finished');
  }, reduced ? 0 : 260);
}

// opening an item again: a hold, so it is never by accident; the cleared items after it in its step crack
function reopener() {
  const btn = $('reopen');
  let timer = 0;
  const cancel = () => { clearTimeout(timer); btn.classList.remove('holding'); };
  const go = () => {
    cancel();
    if (!sheet) return;
    const { step, it } = sheet;
    haptic(true);
    setExtra(crackKey(step, it), undefined);
    setDone(step, it, false);
    for (const later of step.items.slice(step.items.indexOf(it) + 1)) {
      if (isDone(step, later)) setExtra(crackKey(step, later), 1);
    }
    for (const later of step.items.slice(step.items.indexOf(it) + 1)) {
      const b = tiles.get(keyOf(step, later))?.btn;
      if (b?.dataset.state === 'cracked') { b.classList.remove('jolt'); void b.offsetWidth; b.classList.add('jolt'); }
    }
  };
  btn.addEventListener('pointerdown', (e) => {
    if (e.button > 0) return;
    btn.classList.add('holding'); haptic();
    timer = setTimeout(go, REOPEN_MS);
  });
  for (const t of ['pointerup', 'pointerleave', 'pointercancel']) btn.addEventListener(t, cancel);
  btn.addEventListener('contextmenu', (e) => e.preventDefault());
  btn.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
}

function repaint() {
  palette();
  paintBoard();
  if (sheet) {
    const justRestored = $('surface').classList.contains('finishing');
    fillSheet();
    $('surface').classList.toggle('finished', justRestored);     // keep the line of light running
  }
  document.querySelector('meta[name=theme-color]').content = getComputedStyle(document.body).backgroundColor;
}

let queued = false;
const later = () => { if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; repaint(); }); } };

onTap($('sheet-close'), close);
onTap($('scrim'), close);
addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
onTap($('sheet-studio'), () => { location.href = $('sheet-studio').href; });
scrubber();
reopener();
onChange(later);
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', later);
addEventListener('resize', later);
loadTrack()
  .then((d) => { data = d; palette(); build(); repaint(); document.body.dataset.ready = 'true'; })
  .catch((err) => { $('board').textContent = String(err.message || err); });
