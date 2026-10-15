// The Wasteland, walked (release 1 of the overworld): a wanderer you steer around a 1-bit world. Drag anywhere to
// walk (a stick appears under the finger; further is faster), or tap a spot to walk there; on a keyboard, the
// arrows or WASD. The camp, the museum and the seven sites name themselves as you come near. Where you stood is kept
// in this browser. The thumbs on the edges tell the artist what landed (../map/feedback.js).
// The map (release 3, chart.js) is its own screen, from the header or M; a waypoint set there puts a gold arrow on
// the screen's edge and a pillar of light over the place.
//
// The world is drawn at one art pixel per pixel into a small canvas the size of the view, then scaled up by a whole
// number of device pixels, so every pixel stays square.
import { TRACK, haptic } from '../concepts/model.js';
import { mountFeedback } from '../map/feedback.js';
import { CHUNK, H, W, chunk, land, solidAt } from './land.js';
import { HERO_H, Scarf, frames } from './hero.js';
import { Seen, openChart } from './chart.js';

const L = land();
const cv = document.getElementById('game');
const ctx = cv.getContext('2d');
const low = document.createElement('canvas');
const lc = low.getContext('2d');
const labelsEl = document.getElementById('labels');
const ring = document.getElementById('ring');
const hint = document.getElementById('hint');
const wayEl = document.getElementById('way');
const chartEl = document.getElementById('chart');

const MAXV = 78;                    // px a second, at full stick
const SAVE = 'wasteland:hero';

let dpr = 1, S = 9, VW = 131, VH = 284;
function resize() {
  dpr = Math.min(3, devicePixelRatio || 1);
  cv.width = Math.round(innerWidth * dpr); cv.height = Math.round(innerHeight * dpr);
  // about 34,000 art px on screen whatever the device: ~131 x 284 on an iPhone, wider on a desk
  S = Math.max(2, Math.round(Math.sqrt((cv.width * cv.height) / 34000)));
  VW = Math.ceil(cv.width / S); VH = Math.ceil(cv.height / S);
  low.width = VW; low.height = VH;
  ctx.imageSmoothingEnabled = false;
}
addEventListener('resize', resize);
resize();

// --- the wanderer ---
const saved = (() => { try { return JSON.parse(localStorage.getItem(SAVE)); } catch { return null; } })();
const hero = { x: L.start.x, y: L.start.y, vx: 0, vy: 0, face: 'down', flip: false, walk: 0, idle: 0, travelled: 0 };
if (saved && Number.isFinite(saved.x) && !blocked(saved.x, saved.y)) Object.assign(hero, { x: saved.x, y: saved.y, face: saved.face || 'down' });
const scarf = new Scarf(hero.x, hero.y - 9);
const cam = { x: hero.x, y: hero.y };
const seen = new Seen(W, H);
let waypoint = (() => { try { return JSON.parse(localStorage.getItem('wasteland:waypoint')); } catch { return null; } })();
function setWaypoint(w) {
  waypoint = w;
  try { localStorage.setItem('wasteland:waypoint', JSON.stringify(w)); } catch { /* this visit only */ }
}
function persist() {
  try { localStorage.setItem(SAVE, JSON.stringify({ x: Math.round(hero.x), y: Math.round(hero.y), face: hero.face })); } catch { /* this visit only */ }
  seen.save();
}
setInterval(persist, 2000);
addEventListener('pagehide', persist);

// the feet are a 7 x 3 box: what can't be walked through is checked at its corners and middle
function blocked(x, y) {
  for (const dx of [-3, 0, 3]) for (const dy of [-2, 0]) if (solidAt(x + dx, y + dy)) return true;
  return false;
}

// --- input: a floating stick, a tap to walk somewhere, the keyboard ---
const keys = new Set();
const joy = { id: null, ox: 0, oy: 0, x: 0, y: 0, on: false, t0: 0 };
let target = null;
const R = 46;                       // the stick's reach, CSS px
cv.addEventListener('pointerdown', (e) => {
  if (joy.id !== null) return;
  try { cv.setPointerCapture(e.pointerId); } catch { /* a synthetic pointer: the moves still come */ }
  Object.assign(joy, { id: e.pointerId, ox: e.clientX, oy: e.clientY, x: 0, y: 0, on: false, t0: performance.now() });
});
cv.addEventListener('pointermove', (e) => {
  if (e.pointerId !== joy.id) return;
  let dx = e.clientX - joy.ox, dy = e.clientY - joy.oy;
  const d = Math.hypot(dx, dy);
  if (!joy.on && d > 10) { joy.on = true; target = null; ring.classList.add('on'); }
  if (!joy.on) return;
  if (d > R) {                      // the stick follows a finger that runs past its reach
    joy.ox += (dx / d) * (d - R); joy.oy += (dy / d) * (d - R);
    dx = e.clientX - joy.ox; dy = e.clientY - joy.oy;
  }
  joy.x = dx / R; joy.y = dy / R;
  ring.style.transform = `translate(${joy.ox}px, ${joy.oy}px)`;
  ring.style.setProperty('--kx', `${dx}px`); ring.style.setProperty('--ky', `${dy}px`);
});
function release(e) {
  if (e.pointerId !== joy.id) return;
  if (!joy.on && performance.now() - joy.t0 < 400) {
    // a tap: walk to the spot
    target = { x: view.x + (e.clientX * dpr) / S, y: view.y + (e.clientY * dpr) / S, t: 0, stuck: 0 };
    haptic();
  }
  joy.id = null; joy.on = false; joy.x = 0; joy.y = 0;
  ring.classList.remove('on');
}
cv.addEventListener('pointerup', release);
cv.addEventListener('pointercancel', release);
const KEYMAP = { ArrowUp: 'u', KeyW: 'u', ArrowDown: 'd', KeyS: 'd', ArrowLeft: 'l', KeyA: 'l', ArrowRight: 'r', KeyD: 'r' };
addEventListener('keydown', (e) => {
  if (e.code === 'KeyM' || (e.code === 'Escape' && chart)) { toggleChart(); return; }
  if (KEYMAP[e.code]) { keys.add(KEYMAP[e.code]); target = null; e.preventDefault(); }
  if (e.key === 'Shift') keys.add('slow');
});
addEventListener('keyup', (e) => { if (KEYMAP[e.code]) keys.delete(KEYMAP[e.code]); if (e.key === 'Shift') keys.delete('slow'); });
addEventListener('blur', () => keys.clear());

let chart = null;                  // the map screen, while it's open
function intent() {
  if (chart) return [0, 0, 0];
  let x = (keys.has('r') ? 1 : 0) - (keys.has('l') ? 1 : 0), y = (keys.has('d') ? 1 : 0) - (keys.has('u') ? 1 : 0);
  if (x || y) { const d = Math.hypot(x, y); return [x / d, y / d, keys.has('slow') ? 0.45 : 1]; }
  if (joy.on) {
    const d = Math.hypot(joy.x, joy.y);
    if (d < 0.14) return [0, 0, 0];
    return [joy.x / d, joy.y / d, Math.min(1, (d - 0.14) / 0.7)];
  }
  if (target) {
    const dx = target.x - hero.x, dy = target.y - hero.y, d = Math.hypot(dx, dy);
    if (d < 1.5) { target = null; return [0, 0, 0]; }
    return [dx / d, dy / d, Math.min(1, d / 14 + 0.25)];
  }
  return [0, 0, 0];
}

// --- the world's small lives: footprints, dust, the wind, fire, lamps ---
const prints = [];
const puffs = [];
const motes = Array.from({ length: 26 }, (_, i) => ({ x: cam.x + ((i * 53) % 140) - 70, y: cam.y + ((i * 97) % 300) - 150, s: 0.5 + ((i * 37) % 10) / 10 }));
const sparks = [];
let footSide = 1, arrived = -9;

function update(dt, t) {
  const [ix, iy, mag] = intent();
  const want = [ix * mag * MAXV, iy * mag * MAXV];
  const k = 1 - Math.exp(-dt * (mag > 0 ? 12 : 16));
  hero.vx += (want[0] - hero.vx) * k; hero.vy += (want[1] - hero.vy) * k;
  if (Math.abs(hero.vx) < 0.5 && mag === 0) hero.vx = 0;
  if (Math.abs(hero.vy) < 0.5 && mag === 0) hero.vy = 0;

  const x0 = hero.x, y0 = hero.y;
  // move on each axis apart, so a wall is slid along; at a corner, nudge round it
  let nx = hero.x + hero.vx * dt;
  if (!blocked(nx, hero.y)) hero.x = nx;
  else {
    const nudge = [1, -1, 2, -2, 3, -3].find((o) => Math.sign(o) === Math.sign(iy || o) && !blocked(nx, hero.y + o));
    if (nudge !== undefined && Math.abs(hero.vx) > Math.abs(hero.vy)) hero.y += Math.sign(nudge) * Math.min(1, dt * 60); else hero.vx = 0;
  }
  let ny = hero.y + hero.vy * dt;
  if (!blocked(hero.x, ny)) hero.y = ny;
  else {
    const nudge = [1, -1, 2, -2, 3, -3].find((o) => Math.sign(o) === Math.sign(ix || o) && !blocked(hero.x + o, ny));
    if (nudge !== undefined && Math.abs(hero.vy) > Math.abs(hero.vx)) hero.x += Math.sign(nudge) * Math.min(1, dt * 60); else hero.vy = 0;
  }
  const moved = Math.hypot(hero.x - x0, hero.y - y0);
  const speed = moved / Math.max(dt, 1e-3);
  if (target) {
    target.t += dt;
    target.stuck = moved < 0.2 * dt * 60 ? target.stuck + dt : 0;
    if (target.stuck > 0.25 || target.t > 30) target = null;
  }

  // the facing and the walk
  if (speed > 4) {
    if (Math.abs(hero.vx) > Math.abs(hero.vy) * 0.85) { hero.face = 'side'; hero.flip = hero.vx < 0; }
    else hero.face = hero.vy < 0 ? 'up' : 'down';
    const before = Math.floor(hero.walk);
    hero.walk += moved / 6.5;
    hero.idle = 0;
    hero.travelled += moved;
    if (Math.floor(hero.walk) !== before && Math.floor(hero.walk) % 2 === 1) {
      // a planted foot: a print, and dust when running
      const side = (footSide = -footSide);
      const px = hero.face === 'side' ? 0 : side * 2, py = hero.face === 'side' ? side : 0;
      prints.push({ x: Math.round(hero.x + px), y: Math.round(hero.y + py), t });
      if (prints.length > 90) prints.shift();
      if (speed > 55) puffs.push({ x: hero.x - Math.sign(hero.vx) * 3, y: hero.y, t, s: Math.random() });
    }
    if (hero.travelled > 40) hint.classList.add('gone');
  } else {
    hero.idle += dt;
  }
  seen.walk(hero.x, hero.y);
  if (waypoint && Math.hypot(hero.x - waypoint.x, hero.y - waypoint.y) < 40) { setWaypoint(null); haptic(true); arrived = t; }
  scarf.update(hero.x + (hero.face === 'side' ? (hero.flip ? 2 : -2) : 0), hero.y - 9, hero.vx, hero.vy, dt);

  // the camera leads a little where you're going
  const lead = 18;
  const tx = hero.x + (hero.vx / MAXV) * lead, ty = hero.y - 8 + (hero.vy / MAXV) * lead;
  const c = 1 - Math.exp(-dt * 5);
  cam.x += (tx - cam.x) * c; cam.y += (ty - cam.y) * c;

  for (const m of motes) {
    m.x += (14 + 10 * m.s) * dt; m.y += (5 + 4 * Math.sin(t * 0.6 + m.s * 9)) * dt;
    if (m.x > view.x + VW + 4) { m.x = view.x - 4; m.y = view.y + Math.random() * VH; }
    if (m.y > view.y + VH + 4) m.y = view.y - 4;
    if (m.x < view.x - 8) m.x = view.x + VW;
    if (m.y < view.y - 8) m.y = view.y + VH;
  }
  if (Math.random() < dt * 0.8) for (const l of L.lights) if (l.kind === 'spark') {
    for (let i = 0; i < 5; i++) sparks.push({ x: l.x, y: l.y + 18, vx: (Math.random() - 0.5) * 60, vy: -20 - Math.random() * 40, t });
  }
  for (const s of sparks) { s.vy += 120 * dt; s.x += s.vx * dt; s.y += s.vy * dt; }
  while (sparks.length && t - sparks[0].t > 0.6) sparks.shift();
}

// --- drawing ---
const view = { x: 0, y: 0 };
const px = (x, y, color) => { lc.fillStyle = color; lc.fillRect(Math.round(x - view.x), Math.round(y - view.y), 1, 1); };
const INK = '#fff', GOLD = '#f1b64a', DIM = '#787878';

function draw(t) {
  view.x = Math.round(Math.max(0, Math.min(W - VW, cam.x - VW / 2)));
  view.y = Math.round(Math.max(0, Math.min(H - VH, cam.y - VH / 2)));
  lc.fillStyle = '#000';
  lc.fillRect(0, 0, VW, VH);
  for (let j = Math.floor(view.y / CHUNK); j <= Math.floor((view.y + VH) / CHUNK); j++) {
    for (let i = Math.floor(view.x / CHUNK); i <= Math.floor((view.x + VW) / CHUNK); i++) {
      if (i * CHUNK >= W || j * CHUNK >= H) continue;
      lc.drawImage(chunk(i, j), i * CHUNK - view.x, j * CHUNK - view.y);
    }
  }
  // footprints fade over eight seconds
  for (const p of prints) {
    const age = t - p.t;
    if (age > 8) continue;
    lc.globalAlpha = 1 - age / 8;
    px(p.x, p.y, INK); px(p.x + 1, p.y, INK);
  }
  lc.globalAlpha = 1;
  // firelight on the ground
  glow(L.fire.x, L.fire.y + 3, 24, t);
  for (const l of L.lights) if (l.kind === 'fire') glow(l.x, l.y + 4, 22, t);

  // the things standing, back to front, with the wanderer among them
  const near = L.near(view.x - 64, view.y - 24, view.x + VW + 64, view.y + VH + 100);
  const heroItem = { y: hero.y, hero: true };
  const list = [...near, heroItem].sort((a, b) => a.y - b.y);
  const n = hero.idle > 0 ? (Math.floor(hero.idle / 1.6) % 2 ? -1 : 0) : 1 + (Math.floor(hero.walk) % 4);
  const heroImg = frames(hero.face, n, hero.flip);
  const hx = Math.round(hero.x) - 5 - view.x, hy = Math.round(hero.y) - (HERO_H - 1) - view.y;
  let covered = false;
  for (const p of list) {
    if (p.hero) {
      if (hero.face !== 'up') drawScarf();
      lc.drawImage(heroImg, hx, hy);
      if (hero.face === 'up') drawScarf();
      continue;
    }
    const sx = p.x - p.a.ax - view.x, sy = p.y - p.a.ay - view.y;
    lc.drawImage(p.a.img, sx, sy);
    if (p.y > hero.y && sx < hx + 10 && sx + p.a.img.width > hx && sy < hy + 14 && sy + p.a.img.height > hy + 2) covered = true;
  }
  if (covered) lc.drawImage(frames(hero.face, n, hero.flip, true), hx, hy);

  // fire, lamps, the beacon, sparks
  flame(L.fire.x, L.fire.y, t);
  for (const l of L.lights) {
    if (l.kind === 'fire') flame(l.x, l.y, t + 3);
    if (l.kind === 'lamp') { const on = Math.sin(t * 2.2) > -0.3; lc.fillStyle = on ? GOLD : DIM; lc.fillRect(l.x - 1 - view.x, l.y - view.y, 3, 2); }
    if (l.kind === 'beacon' && t % 1.6 < 0.18) { lc.fillStyle = GOLD; lc.fillRect(l.x - 1 - view.x, l.y - 1 - view.y, 3, 3); }
  }
  for (const s of sparks) px(s.x, s.y, GOLD);

  // the wires between the pylons pass overhead
  lc.fillStyle = DIM;
  for (const w of L.wires) {
    if (Math.max(w.x0, w.x1) < view.x || Math.min(w.x0, w.x1) > view.x + VW || Math.max(w.y0, w.y1) + w.sag < view.y || Math.min(w.y0, w.y1) > view.y + VH) continue;
    const len = Math.ceil(Math.abs(w.x1 - w.x0));
    for (let k = 0; k <= len; k++) {
      const u = k / len;
      lc.fillRect(Math.round(w.x0 + (w.x1 - w.x0) * u - view.x), Math.round(w.y0 + (w.y1 - w.y0) * u + w.sag * 4 * u * (1 - u) - view.y), 1, 1);
    }
  }
  if (waypoint) pillar(waypoint.x, waypoint.y, t);
  // dust kicked up, and the wind's motes
  for (const p of puffs) {
    const age = t - p.t;
    if (age > 0.45) continue;
    const r = 1 + age * 9;
    lc.globalAlpha = 1 - age / 0.45;
    for (let a = 0; a < 6; a++) px(p.x + Math.cos(a + p.s * 6) * r, p.y - 1 + Math.sin(a + p.s * 6) * r * 0.5, INK);
  }
  lc.globalAlpha = 1;
  while (puffs.length && t - puffs[0].t > 0.5) puffs.shift();
  for (const m of motes) { lc.globalAlpha = 0.35 + m.s * 0.4; px(m.x, m.y, INK); }
  lc.globalAlpha = 1;
  if (target) { const on = Math.floor(t * 4) % 2; lc.fillStyle = on ? INK : DIM; for (const [a, b] of [[-1, -1], [1, 1], [1, -1], [-1, 1], [0, 0]]) lc.fillRect(Math.round(target.x + a - view.x), Math.round(target.y + b - view.y), 1, 1); }

  ctx.drawImage(low, 0, 0, VW, VH, 0, 0, VW * S, VH * S);
  labels();
}

function pillar(x, y, t) {
  // the waypoint: a column of gold light standing over the place, and a ring on the ground
  if (x < view.x - 20 || x > view.x + VW + 20 || y < view.y - 10 || y > view.y + VH + 140) return;
  const B = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];
  lc.fillStyle = GOLD;
  for (let j = 0; j < 130; j++) {
    const Y = Math.round(y - j), w = 2 + Math.round(Math.sin(t * 3 + j * 0.15));
    for (let i = -w; i <= w; i++) {
      const X = Math.round(x + i), tone = (1 - j / 130) * (1 - Math.abs(i) / (w + 1)) * 12;
      if (B[((Y + Math.floor(t * 20)) & 3) * 4 + (X & 3)] < tone) lc.fillRect(X - view.x, Y - view.y, 1, 1);
    }
  }
  for (let a = 0; a < 28; a++) {
    const u = (a / 28) * Math.PI * 2 + t * 0.8;
    if (a % 2) px(x + Math.cos(u) * 12, y + Math.sin(u) * 5, GOLD);
  }
}
function drawScarf() {
  // the tail, joined up, two pixels deep near the neck
  const p = scarf.p.map(([x, y]) => [Math.round(x), Math.round(y)]);
  for (let i = 1; i < p.length; i++) {
    let [x0, y0] = p[i - 1];
    const [x1, y1] = p[i];
    for (let k = 0; k < 4 && (x0 !== x1 || y0 !== y1); k++) {
      x0 += Math.sign(x1 - x0); y0 += Math.sign(y1 - y0);
      px(x0, y0, GOLD);
      if (i < 3) px(x0, y0 + 1, GOLD);
    }
  }
}
function flame(x, y, t) {
  const f = Math.floor(t * 12);
  for (let i = -2; i <= 2; i++) {
    const h = Math.max(0, 5 - Math.abs(i) * 2 + ((f * 7 + i * 13) % 3));
    for (let k = 0; k < h; k++) px(x + i, y - k, k < h - 2 && Math.abs(i) < 2 ? INK : GOLD);
  }
}
function glow(x, y, r, t) {
  // a dithered warm pool, breathing with the flame
  const rr = r + Math.sin(t * 7) * 0.8;
  lc.fillStyle = GOLD;
  const B = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];
  for (let j = -r; j <= r; j++) for (let i = -r; i <= r; i++) {
    const d = Math.hypot(i, j * 1.6) / rr;
    if (d > 1) continue;
    const X = Math.round(x + i), Y = Math.round(y + j);
    if (B[(Y & 3) * 4 + (X & 3)] < (1 - d) * 3.2) lc.fillRect(X - view.x, Y - view.y, 1, 1);
  }
}

// --- the names of places, as you come near ---
const labelEls = new Map();
let nearest = null;
function labels() {
  let best = null;
  for (const lm of L.landmarks) {
    const d = Math.hypot(hero.x - lm.x, hero.y - (lm.y + 40));
    let el = labelEls.get(lm.id);
    const show = d < lm.r;
    if (show && (!best || d < best.d)) best = { lm, d };
    if (!el && !show) continue;
    if (!el) {
      el = document.createElement('div');
      el.className = 'lm';
      el.innerHTML = `<b></b><span></span>`;
      el.querySelector('b').textContent = lm.name;
      el.querySelector('span').textContent = lm.sub;
      labelsEl.append(el);
      labelEls.set(lm.id, el);
    }
    el.classList.toggle('on', show);
    const x = ((lm.x - view.x) * S) / dpr, y = ((lm.y - view.y) * S) / dpr;
    el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
  }
  if ((best?.lm.id ?? null) !== nearest) {
    nearest = best?.lm.id ?? null;
    if (nearest) { haptic(); seen.reached(nearest); }
  }
  arrow();
}

// the waypoint's arrow, on the screen's edge when the place is off it
function arrow() {
  if (!waypoint) { wayEl.classList.remove('on'); return; }
  const cw = innerWidth, chh = innerHeight;
  const sx = ((waypoint.x - view.x) * S) / dpr, sy = ((waypoint.y - 40 - view.y) * S) / dpr;
  const top = 78, side = 30, bottom = 54;
  if (sx > side && sx < cw - side && sy > top && sy < chh - bottom) { wayEl.classList.remove('on'); return; }
  const cx = cw / 2, cy = chh / 2, dx = sx - cx, dy = sy - cy;
  const k = Math.min(Math.abs((dx > 0 ? cw - side - cx : side - cx) / (dx || 1e-6)), Math.abs((dy > 0 ? chh - bottom - cy : top - cy) / (dy || 1e-6)));
  const ax = cx + dx * k, ay = cy + dy * k;
  wayEl.classList.add('on');
  wayEl.classList.toggle('r', ax > cw - 90); wayEl.classList.toggle('l', ax < 90); wayEl.classList.toggle('b', ay > chh - 90);
  wayEl.style.transform = `translate(${ax.toFixed(1)}px, ${ay.toFixed(1)}px)`;
  wayEl.style.setProperty('--a', `${Math.atan2(dy, dx)}rad`);
  wayEl.querySelector('span').textContent = `${waypoint.name} · ${Math.round(Math.hypot(waypoint.x - hero.x, waypoint.y - hero.y) / 8)} m`;
}

function toggleChart() {
  if (chart) { chart.close(); return; }
  keys.clear(); target = null; joy.on = false; joy.id = null; ring.classList.remove('on');
  persist();
  chart = openChart(chartEl, {
    L, hero, seen, waypoint,
    onPick: (w) => setWaypoint(w),
    onClose: () => { chart = null; },
  });
}
document.getElementById('mapbtn').addEventListener('click', toggleChart);

// --- the loop ---
let last = performance.now(), frameCount = 0;
function frame(now) {
  const dt = Math.min(0.05, (now - last) / 1000);
  last = now;
  const t = now / 1000;
  update(dt, t);
  draw(t);
  frameCount++;
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

// warm the rest of the ground in the background, nearest first
(() => {
  const todo = [];
  for (let j = 0; j * CHUNK < H; j++) for (let i = 0; i * CHUNK < W; i++) todo.push([i, j]);
  todo.sort((a, b) => Math.hypot(a[0] * CHUNK - hero.x, a[1] * CHUNK - hero.y) - Math.hypot(b[0] * CHUNK - hero.x, b[1] * CHUNK - hero.y));
  const next = () => { const c = todo.shift(); if (!c) return; chunk(...c); setTimeout(next, 30); };
  setTimeout(next, 600);
})();

mountFeedback({
  context: () => ({
    view: chart ? 'map' : 'overworld', track: TRACK, x: Math.round(hero.x), y: Math.round(hero.y), near: nearest,
    moving: Math.hypot(hero.vx, hero.vy) > 4, waypoint: waypoint?.id ?? null, walked: Math.round(seen.fraction * 1000) / 10,
  }),
});
setTimeout(() => document.getElementById('title').classList.add('gone'), 2600);

// for the tests: where the wanderer is, and what the world holds
window.__wasteland = {
  hero, land: L, solidAt, blocked, view, seen, scale: () => ({ S, dpr, VW, VH }), frames: () => frameCount, near: () => nearest,
  waypoint: () => waypoint, chartOpen: () => !!chart,
};
