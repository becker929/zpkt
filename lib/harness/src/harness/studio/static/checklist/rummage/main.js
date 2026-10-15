// The Rummage (docs/rummage.md): a region you play to finish a short, SH001. A junk market on layered paper with
// three machines standing in it (The Wireless, the bed; The Clatter, the drums; The Bellows, the low end) and the
// Gramophone at its heart. Walk up to a machine and operate it (machine.js fills the screen); commit, and the choice
// falls into your hands as an artifact; carry it to the Gramophone and set it on its plinth. With all three on, the
// Gramophone plays the short as made, a plate is hung in the museum and the sleeve is yours. Nothing is locked.
//
// Walking is the Wasteland's: drag anywhere for a stick (further is faster), tap a spot to go there (tap a machine to
// go up to it), or the arrow keys and WASD; Enter acts. The camera follows on a critically damped spring with an
// eased look-ahead, and leads by the spring's own lag, so the look-ahead is really ahead. The scene is drawn to the
// device pixel (scene.js). Where you stand is kept in this browser; the region's state through the harness
// (flow.js). The artist's thumbs are on the edges (../map/feedback.js).
import { haptic, onTap } from '../concepts/model.js';
import { mountFeedback } from '../map/feedback.js';
import * as sounds from '../map/sounds.js';
import { loadArt } from './art.js';
import { createFlow, hangPlate, hangWaiting } from './flow.js';
import { openGramophone, picture } from './gram.js';
import { Hero } from './hero.js';
import { HERO_R, MACHINES, PARTS, region } from './region.js';
import { createScene } from './scene.js';
import { openStubMachine } from './stub.js';

const AUDIO_BASE = '/studio/regions/rummage/audio/';
const MAXV = 190;                   // world units a second, at full stick: 4-8 s from a machine to the Gramophone
const SAVE = 'rummage:hero';
const STUB = new URLSearchParams(location.search).has('stub');
const $ = (id) => document.getElementById(id);
const cv = $('game'), labelsEl = $('labels'), ring = $('ring'), hint = $('hint'), wayEl = $('way'), actEl = $('act');

// --- what the page is made of: the art, the music's manifest, the region's state ---
const FALLBACK_AUDIO = {
  track: 'sh001', bpm: 120, bars: 32, seconds: 64, combos: {},
  parts: Object.fromEntries(PARTS.map((p) => [p, [1, 2, 3].map((id) => ({ id, name: `${MACHINES[p].name}, ${['one', 'two', 'three'][id - 1]}`, about: 'Not rendered yet' }))])),
};
async function loadAudio() {
  try {
    const r = await fetch('audio.json', { cache: 'no-cache' });
    if (r.ok) { const a = await r.json(); if (a?.parts) return a; }
  } catch { /* the music isn't rendered yet */ }
  return null;
}
const [art, audio, flow] = await Promise.all([loadArt('art/'), loadAudio(), createFlow()]);
const music = audio ?? FALLBACK_AUDIO;              // the options' names and the tempo, rendered or not
const R = region(art);
const scene = createScene(cv, { R, art });
art.onImage((a) => scene.refresh(a));
addEventListener('resize', () => scene.resize());
hangWaiting();

const optionOf = (part, id) => music.parts?.[part]?.find((o) => o.id === id) ?? { id, name: `Option ${id}`, about: '' };
const nameOf = (key) => { const [part, id] = key.split('-'); return optionOf(part, Number(id)).name; };
const isFinished = (combo) => flow.state.completions.some((c) => c.combo === combo);

// the machine (machine.js, or the stand-in in stub.js if it won't load) and the player (player.js), which there is
// only once the music has renders: until then the machines and the Gramophone work and say the sound is coming
let openMachine = openStubMachine, player = null;
const modules = (async () => {
  if (!STUB) {
    try { const m = await import('./machine.js'); if (typeof m.openMachine === 'function') openMachine = m.openMachine; } catch { /* the stand-in */ }
  }
  if (!Object.keys(audio?.combos ?? {}).length) return;
  try { player = await (await import('./player.js')).createPlayer({ audio, base: AUDIO_BASE }); } catch { player = null; }
})();

// --- the wanderer ---
const saved = (() => { try { return JSON.parse(localStorage.getItem(SAVE)); } catch { return null; } })();
const hero = new Hero(art, R.start.x, R.start.y);
if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y) && !R.blocked(saved.x, saved.y)) Object.assign(hero, { x: saved.x, y: saved.y, face: saved.face || 'front', flip: !!saved.flip });
hero.carry = flow.state.carrying;
const cam = { x: hero.x, y: hero.y - 60, vx: 0, vy: 0, lx: 0, ly: 0, lvx: 0, lvy: 0 };
function persist() {
  try { localStorage.setItem(SAVE, JSON.stringify({ x: Math.round(hero.x), y: Math.round(hero.y), face: hero.face, flip: hero.flip })); } catch { /* this visit only */ }
}
setInterval(persist, 2000);
addEventListener('pagehide', persist);

/** Unity's SmoothDamp (Game Programming Gems 4, 1.10): a critically damped spring from cur towards target that never
 * overshoots; `smooth` is roughly the time to get there. Returns [value, velocity]. */
function smoothDamp(cur, target, vel, smooth, dt, maxSpeed = Infinity) {
  const omega = 2 / Math.max(1e-4, smooth), x = omega * dt, e = 1 / (1 + x + 0.48 * x * x + 0.235 * x * x * x);
  const max = maxSpeed * smooth, change = Math.max(-max, Math.min(max, cur - target)), to = cur - change;
  const temp = (vel + omega * change) * dt;
  let v = (vel - omega * temp) * e, out = to + (change + temp) * e;
  if (target - cur > 0 === out > target) { out = target; v = 0; }
  return [out, v];
}

// --- input: a floating stick, a tap to walk somewhere, the keyboard ---
const keys = new Set();
const joy = { id: null, ox: 0, oy: 0, x: 0, y: 0, on: false, t0: 0 };
let target = null, machine = null, gram = null;
const busy = () => !!(machine || gram);
const REACH = 46;                   // the stick's reach, CSS px
cv.addEventListener('pointerdown', (e) => {
  sounds.wake();
  if (joy.id !== null || busy()) return;
  try { cv.setPointerCapture(e.pointerId); } catch { /* a synthetic pointer: the moves still come */ }
  Object.assign(joy, { id: e.pointerId, ox: e.clientX, oy: e.clientY, x: 0, y: 0, on: false, t0: performance.now() });
});
cv.addEventListener('pointermove', (e) => {
  if (e.pointerId !== joy.id) return;
  let dx = e.clientX - joy.ox, dy = e.clientY - joy.oy;
  const d = Math.hypot(dx, dy);
  if (!joy.on && d > 10) { joy.on = true; target = null; ring.classList.add('on'); }
  if (!joy.on) return;
  if (d > REACH) {                  // the stick follows a finger that runs past its reach
    joy.ox += (dx / d) * (d - REACH); joy.oy += (dy / d) * (d - REACH);
    dx = e.clientX - joy.ox; dy = e.clientY - joy.oy;
  }
  joy.x = dx / REACH; joy.y = dy / REACH;
  ring.style.transform = `translate(${joy.ox}px, ${joy.oy}px)`;
  ring.style.setProperty('--kx', `${dx}px`); ring.style.setProperty('--ky', `${dy}px`);
});
function release(e) {
  if (e.pointerId !== joy.id) return;
  if (!joy.on && performance.now() - joy.t0 < 400 && !busy()) tapAt(e.clientX, e.clientY);
  joy.id = null; joy.on = false; joy.x = 0; joy.y = 0;
  ring.classList.remove('on');
}
cv.addEventListener('pointerup', release);
cv.addEventListener('pointercancel', release);
/** A tap on the ground walks there; a tap on a machine, the Gramophone or the tear walks up to it. */
function tapAt(cx, cy) {
  const [x, y] = scene.toWorld(cx, cy);
  let to = { x, y };
  for (const t of [R.gram, ...PARTS.map((p) => R.machines[p]), R.portal]) {
    const a = t.asset, left = t.x - a.anchor[0] * a.w, top = t.y - a.anchor[1] * a.h;
    if (x > left && x < left + a.w && y > top && y < t.y + 10) { to = { x: t.x, y: t.y + 30, place: t.id }; break; }
  }
  target = { ...to, t: 0, stuck: 0, side: 0 };
  haptic();
}
const KEYMAP = { ArrowUp: 'u', KeyW: 'u', ArrowDown: 'd', KeyS: 'd', ArrowLeft: 'l', KeyA: 'l', ArrowRight: 'r', KeyD: 'r' };
addEventListener('keydown', (e) => {
  if (e.code === 'Escape') { machine?.handle?.close(); gram?.close(); return; }
  if (busy()) return;
  if ((e.code === 'Enter' || e.code === 'Space') && action) { e.preventDefault(); act(); return; }
  if (KEYMAP[e.code]) { keys.add(KEYMAP[e.code]); target = null; e.preventDefault(); }
  if (e.key === 'Shift') keys.add('slow');
});
addEventListener('keyup', (e) => { if (KEYMAP[e.code]) keys.delete(KEYMAP[e.code]); if (e.key === 'Shift') keys.delete('slow'); });
addEventListener('blur', () => keys.clear());
function stopInput() { keys.clear(); target = null; joy.on = false; joy.id = null; ring.classList.remove('on'); }

function intent() {
  if (busy()) return [0, 0, 0];
  let x = (keys.has('r') ? 1 : 0) - (keys.has('l') ? 1 : 0), y = (keys.has('d') ? 1 : 0) - (keys.has('u') ? 1 : 0);
  if (x || y) { const d = Math.hypot(x, y); return [x / d, y / d, keys.has('slow') ? 0.45 : 1]; }
  if (joy.on) {
    const d = Math.hypot(joy.x, joy.y);
    if (d < 0.14) return [0, 0, 0];
    return [joy.x / d, joy.y / d, Math.min(1, (d - 0.14) / 0.7)];
  }
  if (target) {
    const dx = target.x - hero.x, dy = target.y - hero.y, d = Math.hypot(dx, dy);
    if (d < 4) { target = null; return [0, 0, 0]; }
    return [dx / d, dy / d, Math.min(1, d / 60 + 0.3)];
  }
  return [0, 0, 0];
}

// --- the little lives: flights, sparks, paper flecks, rings from the horn ---
const fx = { bounce: new Map(), settle: new Map(), bloom: null, flights: [], bits: [], rings: [], lastBeat: -1 };
const hidden = {};                  // a plinth shows what was on it until the new artifact lands
let now = 0;
/** An artifact flying from a point to a point (or to a moving one), in an arc, growing or shrinking on the way. */
function fly(key, from, to, { dur = 0.55, delay = 0, k0 = 0.5, k1 = 0.5, arc = 90, spin = 0, fade = false, onLand } = {}) {
  fx.flights.push({ key, from, to, t0: now + delay, dur, k0, k1, arc, spin, fade, onLand });
}
function burst(x, y, n = 14, colors = ['#f1b64a', '#fbf6ea', '#e8c26a'], speed = 160, kind = 'star') {
  for (let i = 0; i < n; i++) {
    const a = Math.random() * Math.PI * 2, s = speed * (0.4 + Math.random() * 0.8);
    fx.bits.push({ x, y, vx: Math.cos(a) * s, vy: Math.sin(a) * s * 0.7 - speed * 0.5, t0: now, life: 0.5 + Math.random() * 0.4, c: colors[i % colors.length], r: Math.random() * 6, kind, size: 3 + Math.random() * 4 });
  }
}
function hornAt() {
  const g = R.gram, a = g.asset;
  return [g.x - a.anchor[0] * a.w + a.horn[0] * a.w, g.y - a.anchor[1] * a.h + a.horn[1] * a.h];
}
function drawFx(g, sc, t) {
  // flights
  for (const f of fx.flights) {
    const u = (t - f.t0) / f.dur;
    if (u < 0) continue;
    const it = art.artifacts[f.key], v = Math.min(1, u), e = v < 0.5 ? 2 * v * v : 1 - (-2 * v + 2) ** 2 / 2;
    const [x0, y0] = typeof f.from === 'function' ? f.from() : f.from, [x1, y1] = typeof f.to === 'function' ? f.to() : f.to;
    const x = x0 + (x1 - x0) * e, y = y0 + (y1 - y0) * e - Math.sin(Math.PI * v) * f.arc, k = f.k0 + (f.k1 - f.k0) * e;
    const base = sc.pose(it, { sx: 0.5, sy: 0.5, contact: false, pin: true }, true);
    g.save();
    g.setTransform(1, 0, 0, 1, 0, 0);
    if (f.fade) g.globalAlpha = Math.max(0, 1 - v);
    const X = x * sc.K - sc.view.x, Y = y * sc.K - sc.view.y, s = k / 0.5;
    g.setTransform(s * Math.cos(f.spin * v), s * Math.sin(f.spin * v), -s * Math.sin(f.spin * v), s * Math.cos(f.spin * v), X, Y);
    g.drawImage(base.c, -base.ax, -base.ay);
    g.restore();
    if (u >= 1 && !f.done) { f.done = true; f.onLand?.(); }
  }
  fx.flights = fx.flights.filter((f) => !f.done);
  // sparks and flecks
  for (const b of fx.bits) {
    const age = t - b.t0;
    if (age > b.life) continue;
    const x = b.x + b.vx * age, y = b.y + b.vy * age + 260 * age * age, a = 1 - age / b.life;
    g.globalAlpha = a; g.fillStyle = b.c;
    g.save(); g.translate(x, y); g.rotate(b.r + age * 8);
    if (b.kind === 'star') { g.beginPath(); for (let k = 0; k < 8; k++) { const r = k % 2 ? b.size * 0.35 : b.size; g.lineTo(Math.cos((k * Math.PI) / 4) * r, Math.sin((k * Math.PI) / 4) * r); } g.closePath(); g.fill(); }
    else g.fillRect(-b.size, -b.size * 0.6, b.size * 2, b.size * 1.2);
    g.restore();
  }
  g.globalAlpha = 1;
  fx.bits = fx.bits.filter((b) => t - b.t0 < b.life);
  // rings from the horn: a burst when the short is finished, one a beat while it plays
  const [hx, hy] = hornAt();
  for (const r of fx.rings) {
    const age = t - r.t0, u = age / r.life;
    if (u > 1 || u < 0) continue;
    g.strokeStyle = `rgba(241,182,74,${(1 - u) * r.a})`; g.lineWidth = 4 * (1 - u) + 1;
    g.beginPath(); g.ellipse(hx, hy, 20 + u * r.size, (20 + u * r.size) * 0.62, -0.3, 0, Math.PI * 2); g.stroke();
  }
  fx.rings = fx.rings.filter((r) => t - r.t0 < r.life);
}
function beat(t) {
  if (!player?.playing) return 0;
  const pos = player.position(), b = (pos * (music.bpm || 120)) / 60;
  if (Math.floor(b) !== fx.lastBeat) { fx.lastBeat = Math.floor(b); fx.rings.push({ t0: t, life: 1.1, size: 120, a: 0.55 }); }
  return Math.max(0, 1 - (b % 1) * 3.5);
}

// --- the frame ---
let action = null, nearest = null, frameCount = 0;
function update(dt, t) {
  const [ix, iy, mag] = intent();
  const want = [ix * mag * MAXV, iy * mag * MAXV];
  const k = 1 - Math.exp(-dt * (mag > 0 ? 12 : 16));
  hero.vx += (want[0] - hero.vx) * k; hero.vy += (want[1] - hero.vy) * k;
  if (mag === 0 && Math.hypot(hero.vx, hero.vy) < 3) { hero.vx = 0; hero.vy = 0; }
  const x0 = hero.x, y0 = hero.y;
  let [nx, ny] = R.resolve(hero.x + hero.vx * dt, hero.y + hero.vy * dt);
  const intended = Math.hypot(hero.vx, hero.vy) * dt;
  if (target && intended > 0.2 && Math.hypot(nx - x0, ny - y0) < intended * 0.4) {
    // walking to a tapped spot and something's in the way: try round it, keeping to one side once chosen
    const sides = target.side ? [target.side, -target.side] : [1, -1];
    for (const turn of [0.7, 1.2, 1.6]) {
      let hit = false;
      for (const s of sides) {
        const c = Math.cos(turn * s), sn = Math.sin(turn * s), vx = hero.vx * c - hero.vy * sn, vy = hero.vx * sn + hero.vy * c;
        const [tx, ty] = R.resolve(hero.x + vx * dt, hero.y + vy * dt);
        if (Math.hypot(tx - x0, ty - y0) > intended * 0.6) { nx = tx; ny = ty; target.side = s; hit = true; break; }
      }
      if (hit) break;
    }
  }
  hero.x = nx; hero.y = ny;
  const moved = Math.hypot(hero.x - x0, hero.y - y0);
  if (target) {
    target.t += dt;
    target.stuck = moved < 0.15 * dt * 60 ? target.stuck + dt : 0;
    if (target.stuck > 0.35 || target.t > 30) target = null;
  }
  const mvx = moved > 0.01 ? (hero.x - x0) / Math.max(dt, 1e-3) : 0, mvy = moved > 0.01 ? (hero.y - y0) / Math.max(dt, 1e-3) : 0;
  hero.update(dt, moved, mvx, mvy, t);
  if (moved > 0.5) walked += moved;
  if (walked > 60) hint.classList.add('gone');

  // the camera: it looks ahead where you're going (the look-ahead eases slowly, so a turn doesn't swing it), and
  // follows on a spring with weight; a jump (a reload, a teleport) is cut to, not flown. With the Gramophone open,
  // it frames the Gramophone above the sheet.
  const LEAD = 90;
  [cam.lx, cam.lvx] = smoothDamp(cam.lx, (mvx / MAXV) * LEAD, cam.lvx, 0.7, dt);
  [cam.ly, cam.lvy] = smoothDamp(cam.ly, (mvy / MAXV) * LEAD * 0.8, cam.lvy, 0.7, dt);
  let tx = hero.x + cam.lx + mvx * 0.32, ty = hero.y - 60 + cam.ly + mvy * 0.32;
  if (gram) {
    const a = R.gram.asset, sheet = $('gram').offsetHeight || innerHeight * 0.5;
    tx = R.gram.x; ty = R.gram.y - a.h * 0.56 + (sheet - 60) / (2 * scene.zoom);    // between the header and the sheet
  }
  if (Math.hypot(tx - cam.x, ty - cam.y) > 700) Object.assign(cam, { x: tx, y: ty, vx: 0, vy: 0 });
  [cam.x, cam.vx] = smoothDamp(cam.x, tx, cam.vx, gram ? 0.45 : 0.32, dt, 2400);
  [cam.y, cam.vy] = smoothDamp(cam.y, ty, cam.vy, gram ? 0.45 : 0.32, dt, 2400);
}

function draw(t) {
  scene.look(cam.x, cam.y);
  scene.draw(t, {
    hero, plinths: { ...flow.state.plinths, ...hidden }, bounce: fx.bounce, settle: fx.settle, bloom: fx.bloom,
    beat: player?.playing ? beat : null, after: drawFx,
  });
  labels();
  arrow();
}

// --- the names of places, and what you can do where you stand ---
const labelEls = new Map();
function labels() {
  let best = null;
  for (const p of R.places) {
    const d = Math.hypot(hero.x - p.at[0], hero.y - p.at[1]);
    if (d < p.zone && (!best || d / p.zone < best.d / best.p.zone)) best = { p, d };
    const show = d < p.see && !machine && !gram && !(d < p.zone && p.id === nearest);   // there, the button names it
    let el = labelEls.get(p.id);
    if (!el && !show) continue;
    if (!el) {
      el = document.createElement('div');
      el.className = 'lm'; el.dataset.id = p.id;
      el.innerHTML = '<b></b><span></span>';
      el.querySelector('b').textContent = p.name;
      labelsEl.append(el);
      labelEls.set(p.id, el);
    }
    const committed = MACHINES[p.id] && flow.state.committed[p.id];
    const sub = committed ? `${p.sub} · ${optionOf(p.id, committed).name}` : p.sub;
    if (el.dataset.sub !== sub) { el.dataset.sub = sub; el.querySelector('span').textContent = sub; }
    const [x, y] = scene.toScreen(p.x, p.y);
    const on = show && x > -60 && x < innerWidth + 60;              // a place off the side of the screen isn't named
    el.classList.toggle('on', on);
    el.classList.toggle('here', best?.p === p);
    if (!on) continue;
    const cx = Math.max(80, Math.min(innerWidth - 80, x));          // kept on the screen, and under the header
    el.style.transform = `translate(${cx.toFixed(1)}px, ${Math.max(126, y).toFixed(1)}px)`;
  }
  const id = best?.p.id ?? null;
  if (id !== nearest) {
    nearest = id;
    if (id) { haptic(); fx.bounce.set(id, now); }
  }
  paintAction();
}

/** What the big button does here, if anything. */
function actionHere() {
  if (busy() || !nearest) return null;
  const carry = flow.state.carrying;
  if (MACHINES[nearest]) {
    const part = nearest, m = MACHINES[part], committed = flow.state.committed[part];
    const sub = carry && !carry.startsWith(`${part}-`) ? `you carry ${nameOf(carry)}: a commit here swaps it`
      : committed ? `committed: ${optionOf(part, committed).name}` : `choose ${m.what}`;
    return { kind: 'operate', part, verb: 'Operate', what: m.name, sub };
  }
  if (nearest === 'gram') {
    if (carry) {
      const part = carry.split('-')[0], on = flow.state.plinths[part];
      return { kind: 'place', verb: 'Place', what: nameOf(carry), sub: on && on !== carry ? `replaces ${nameOf(on)}` : `on ${MACHINES[part].name}’s plinth` };
    }
    const combo = flow.combo();
    if (combo) return { kind: 'gram', verb: 'Play the short', what: 'The Gramophone', sub: isFinished(combo) ? 'finished · play it again' : 'all three are on', play: true };
    const n = PARTS.filter((p) => flow.state.plinths[p]).length;
    return { kind: 'gram', verb: 'Look', what: 'The Gramophone', sub: `${n} of 3 plinths filled` };
  }
  if (nearest === 'portal') return { kind: 'leave', verb: 'Back', what: 'to The Wasteland', sub: 'through the tear' };
  return null;
}
let actKey = '';
function paintAction() {
  action = actionHere();
  const key = action ? `${action.verb}|${action.what}|${action.sub}` : '';
  if (key === actKey) return;
  const was = actKey;
  actKey = key;
  actEl.classList.toggle('on', !!action);
  document.body.classList.toggle('acting', !!action);
  actEl.setAttribute('aria-hidden', String(!action));
  actEl.tabIndex = action ? 0 : -1;
  if (!action) { if (walked > 60) hint.classList.add('gone'); return; }
  hint.classList.add('gone');
  actEl.querySelector('b').textContent = action.verb;
  actEl.querySelector('span').textContent = action.what;
  actEl.querySelector('small').textContent = action.sub;
  actEl.classList.toggle('play', !!action.play);
  if (was) { actEl.classList.remove('again'); void actEl.offsetWidth; actEl.classList.add('again'); }
}
onTap(actEl, () => { sounds.wake(); player?.wake?.(); act(); });
function act() {
  if (!action || busy()) return;
  haptic(true);
  if (action.kind === 'operate') operate(action.part);
  else if (action.kind === 'place') place();
  else if (action.kind === 'gram') openGram();
  else if (action.kind === 'leave') { persist(); location.href = '../wasteland/'; }
}

// --- operating a machine, and what it gives you ---
// It opens inside the tap that asks for it (that tap is what lets iOS start the audio), with the machine and the
// player the page loaded at the start.
function operate(part) {
  if (busy()) return;
  stopInput();
  const host = document.createElement('div');
  host.className = 'machine-host';
  document.body.append(host);
  const before = flow.state.carrying;
  let chosen = null;
  const options = [1, 2, 3].map((id) => { const o = optionOf(part, id); return { id, name: o.name, about: o.about ?? '', artifact: art.artifacts[`${part}-${id}`].url }; });
  const onCommit = (id) => {
    if (![1, 2, 3].includes(Number(id))) return;
    chosen = Number(id);
    flow.commit(part, chosen);
    paintGoal();
  };
  const onClose = (result) => {
    if (!machine || machine.host !== host) return;
    machine = null;
    setTimeout(() => host.remove(), 700);
    if (!chosen && result?.committed) onCommit(result.committed);
    if (chosen) arrive(part, `${part}-${chosen}`, before && before !== `${part}-${chosen}` ? before : null);
  };
  machine = { part, host, handle: null, commit: onCommit };
  machine.handle = openMachine(host, {
    part, machine: { name: MACHINES[part].name, panel: art.machines[part].panel }, options, committed: { ...flow.state.committed },
    player, onCommit, onClose, feedback: thumbs, audio,
  });
}
function machineTop(part) { const m = R.machines[part], a = m.asset; return [m.x, m.y - a.h * 0.55]; }
function arrive(part, key, dropped) {
  if (dropped) {
    const dPart = dropped.split('-')[0];
    fly(dropped, hero.back(), machineTop(dPart), { dur: 0.7, k0: 0.4, k1: 0.25, arc: 140, spin: 6, fade: true });
    toast(`${nameOf(dropped)} goes back to ${MACHINES[dPart].name}: you carry one at a time.`);
  }
  hero.carry = null;
  paintCarry();
  fly(key, machineTop(part), () => hero.back(false), {
    dur: 0.62, delay: dropped ? 0.25 : 0.05, k0: 0.9, k1: 46 / art.artifacts[key].h, arc: 120,
    onLand: () => {
      hero.carry = flow.state.carrying;          // the state's, should it have moved on while this flew
      hero.cheer();
      const [x, y] = hero.back(false);
      burst(x, y, 16);
      sounds.land();
      haptic(true);
      paintCarry(true);
      if (!dropped) toast(`${nameOf(key)}: take it to the Gramophone.`);
    },
  });
}

// --- the Gramophone ---
function place() {
  const res = flow.place();
  if (!res) return;
  hidden[res.part] = res.replaced;
  const from = hero.back(false);
  hero.carry = null;
  paintCarry();
  paintGoal();
  fly(res.artifact, from, scene.dish(res.part), {
    dur: 0.5, k0: 46 / art.artifacts[res.artifact].h, k1: (R.gram.asset.h * 0.17) / art.artifacts[res.artifact].h, arc: 110,
    onLand: () => {
      delete hidden[res.part];
      fx.settle.set(res.part, now);
      fx.bounce.set('gram', now + 0.12);
      const [x, y] = scene.dish(res.part);
      burst(x, y - 10, 18, ['#fbf6ea', '#e3dbc5', '#b48b5b', '#f1b64a'], 140, 'fleck');
      if (res.replaced) fly(res.replaced, [x, y], [x + (res.part === 'bass' ? 160 : -160), y + 40], { dur: 0.6, k0: 0.55, k1: 0.3, arc: 120, spin: 5, fade: true });
      sounds.play();
      haptic(true);
      paintPips(res.part);
      const combo = flow.combo();
      toast(res.replaced ? `${nameOf(res.artifact)} replaces ${nameOf(res.replaced)}.` : combo && !isFinished(combo) ? 'All three are on. Play the short.' : `${nameOf(res.artifact)} is on the Gramophone.`);
    },
  });
}
function openGram() {
  if (busy()) return;
  stopInput();
  const combo = flow.combo(), plinths = { ...flow.state.plinths };
  const names = Object.fromEntries(PARTS.map((p) => [p, plinths[p] ? nameOf(plinths[p]) : null]));
  gram = openGramophone($('gram'), {
    plinths, names, art, player, combo, finished: !!combo && isFinished(combo),
    onPlay: (c) => complete(c, names),
    onClose: () => { gram = null; paintGoal(); },
  });
}
function complete(combo, names) {
  const fresh = flow.finish(combo);
  fx.rings.push({ t0: now, life: 1.2, size: 200, a: 0.9 });
  if (!fresh) return false;
  fx.bloom = now;
  for (let i = 1; i < 5; i++) fx.rings.push({ t0: now + i * 0.18, life: 1.3, size: 260, a: 0.8 });
  const [hx, hy] = hornAt();
  burst(hx, hy, 30, ['#f1b64a', '#fbf6ea', '#c4432e', '#33508a', '#3e8580'], 260, 'fleck');
  confetti();
  haptic(true);
  paintGoal();
  plate = hangPlate({ combo, file: audio?.combos?.[combo]?.file ?? null, sleeve: art.sleeve(combo)?.file ?? null, names })
    .then((p) => { if (p?.id) flow.plated(combo, p.id); return p; });
  return true;
}
let plate = null;
const CONFETTI = ['#f1b64a', '#c4432e', '#33508a', '#3e8580', '#fbf6ea', '#d99a2b', '#e3dbc5', '#b48b5b'];
const CLIPS = ['polygon(0 0,100% 10%,90% 100%,5% 85%)', 'polygon(50% 0,100% 100%,0 90%)', 'polygon(0 20%,100% 0,85% 80%,10% 100%)', 'circle(50%)'];
function confetti(n = 90) {
  const box = $('confetti');
  for (let i = 0; i < n; i++) {
    const el = document.createElement('i');
    const s = el.style;
    s.left = `${Math.random() * 100}%`;
    s.setProperty('--c', CONFETTI[i % CONFETTI.length]);
    s.setProperty('--w', `${6 + Math.random() * 10}px`); s.setProperty('--h', `${8 + Math.random() * 12}px`);
    s.setProperty('--clip', CLIPS[i % CLIPS.length]);
    s.setProperty('--dx', `${(Math.random() - 0.5) * 160}px`); s.setProperty('--r', `${(Math.random() - 0.5) * 1440}deg`);
    s.setProperty('--d', `${2.2 + Math.random() * 1.6}s`); s.setProperty('--delay', `${Math.random() * 0.7}s`);
    box.append(el);
  }
  setTimeout(() => box.replaceChildren(), 4800);
}

// --- what is on screen besides the world: what you carry, the plinths, the next thing to do, a note ---
function paintCarry(fresh = false) {
  const el = $('carry'), key = hero.carry;
  el.classList.toggle('on', !!key);
  if (!key) return;
  el.querySelector('figure').replaceChildren(picture(art, key, 40));
  el.querySelector('b').textContent = nameOf(key);
  if (fresh) { el.classList.remove('swap'); void el.offsetWidth; el.classList.add('swap'); }
}
function paintPips(popPart = null) {
  for (const li of $('pips').children) {
    const part = li.dataset.part, on = flow.state.plinths[part];
    li.classList.toggle('full', !!on);
    li.setAttribute('aria-label', `${MACHINES[part].name}: ${on ? nameOf(on) : 'empty'}`);
    if (part === popPart) { li.classList.remove('pop'); void li.offsetWidth; li.classList.add('pop'); }
  }
}
function paintGoal() {
  const s = flow.state, filled = PARTS.filter((p) => s.plinths[p]).length, combo = flow.combo(), carry = s.carrying;
  let text;
  if (carry) text = `Take ${nameOf(carry)} to the Gramophone`;
  else if (combo && !isFinished(combo)) text = 'All three are on: play the short';
  else if (combo) text = 'SH001 is finished · recommit a machine to change it';
  else if (filled) text = `${filled} of 3 on the Gramophone · next, ${MACHINES[PARTS.find((p) => !s.plinths[p])].name}`;
  else text = 'SH001 · find a machine and operate it';
  $('goal').textContent = text;
}
let toastTimer = 0;
function toast(text, ms = 2800) {
  const el = $('toast');
  el.textContent = text;
  el.classList.add('on');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('on'), ms);
}
// the way to the Gramophone, on the screen's edge, while you carry something to it (or it's ready to play)
function arrow() {
  const combo = flow.combo();
  const want = !busy() && (flow.state.carrying || (combo && !isFinished(combo)));
  const [sx, sy] = want ? scene.toScreen(R.gram.x, R.gram.y - R.gram.asset.h * 0.5) : [0, 0];
  const cw = innerWidth, ch = innerHeight, top = 120, side = 30, bottom = 110;
  if (!want || (sx > side && sx < cw - side && sy > top && sy < ch - bottom)) { wayEl.classList.remove('on'); return; }
  const cx = cw / 2, cy = ch / 2, dx = sx - cx, dy = sy - cy;
  const k = Math.min(Math.abs((dx > 0 ? cw - side - cx : side - cx) / (dx || 1e-6)), Math.abs((dy > 0 ? ch - bottom - cy : top - cy) / (dy || 1e-6)));
  const ax = cx + dx * k, ay = cy + dy * k;
  wayEl.classList.add('on');
  wayEl.classList.toggle('r', ax > cw - 90); wayEl.classList.toggle('l', ax < 90); wayEl.classList.toggle('b', ay > ch - 140);
  wayEl.style.transform = `translate(${ax.toFixed(1)}px, ${ay.toFixed(1)}px)`;
  wayEl.style.setProperty('--a', `${Math.atan2(dy, dx)}rad`);
  const text = `The Gramophone · ${Math.round(Math.hypot(R.gram.x - hero.x, R.gram.y - hero.y) / 40)} m`;
  const span = wayEl.querySelector('span');
  if (span.textContent !== text) span.textContent = text;
}

// --- the loop ---
let last = performance.now(), walked = 0;
const perf = { intervals: [], work: [] };
function frame(ts) {
  const t0 = performance.now();
  const dt = Math.min(0.05, (ts - last) / 1000);
  perf.intervals.push(ts - last);
  last = ts;
  now = ts / 1000;
  update(dt, now);
  if (!machine) draw(now);
  else labels();
  perf.work.push(performance.now() - t0);
  if (perf.intervals.length > 600) { perf.intervals.splice(0, 300); perf.work.splice(0, 300); }
  frameCount++;
  requestAnimationFrame(frame);
}
scene.warm(cam.x, cam.y);
paintCarry(); paintPips(); paintGoal();
requestAnimationFrame((ts) => { last = ts; requestAnimationFrame(frame); });

const thumbs = mountFeedback({
  context: () => {
    const where = {
      view: gram ? 'rummage-gramophone' : 'rummage', track: 'sh001', region: 'rummage',
      x: Math.round(hero.x), y: Math.round(hero.y), near: nearest, carrying: flow.state.carrying,
      committed: { ...flow.state.committed }, plinths: { ...flow.state.plinths }, finished: flow.state.completions.length,
      playing: player?.playing ?? null,
    };
    if (!machine) return where;
    let inside = { view: 'rummage-machine', part: machine.part };
    try { inside = { ...inside, ...(machine.handle?.context?.() ?? {}) }; } catch { /* the stand-in has none */ }
    return { ...where, ...inside };
  },
});
if (art.title) {
  const img = document.createElement('img');
  img.src = art.title.url; img.alt = 'The Rummage';
  img.onload = () => $('title').replaceChildren(img, $('title').querySelector('span'));
}
setTimeout(() => $('title').classList.add('gone'), 2800);

// for the tests: where the wanderer is, what the region holds, and the machine's hand
window.__rummage = {
  hero, cam, R, scene, flow, art, audio, music, perf, fx,
  get player() { return player; },
  frames: () => frameCount, near: () => nearest, action: () => action, modules,
  machineOpen: () => !!machine, gramOpen: () => !!gram, plate: () => plate,
  /** Puts the wanderer somewhere (pushed out of anything solid) and cuts the camera to him. */
  teleport(x, y) {
    [hero.x, hero.y] = R.resolve(x, y, HERO_R);
    hero.vx = hero.vy = 0; target = null;
    Object.assign(cam, { x: hero.x, y: hero.y - 60, vx: 0, vy: 0, lx: 0, ly: 0, lvx: 0, lvy: 0 });
    return [hero.x, hero.y];
  },
  /** Turns the open machine's selector to `id` and pulls its lever (the real machine plays its commit through). */
  commit(id) {
    const m = machine;
    if (!m) return false;
    if (m.handle?.select && m.handle?.commit) { m.handle.select(id); m.handle.commit(); return true; }
    m.commit(id); m.handle?.close?.();
    return true;
  },
  get machine() { return machine; },
  act,
};
