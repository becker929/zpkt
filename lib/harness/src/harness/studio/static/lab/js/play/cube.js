// Snapshot cube: a steel die you spin with a thumb, over a neon floor that scrolls on the beat.
//
// Faces: the snapshot slots A, B, C, D (the transport's), the set, and a dice roll. Tap a face to recall it (an empty
// slot saves the knobs into it, as the transport does); long press a slot face to save over it.
// Rotation: the cube's turn about each axis moves a knob (modulation: the knob itself stays). Facing A, nothing
// moves; half a turn about an axis moves its knob by the depth. Flick it and it spins down like a slowing LFO.
// Lock: a flick keeps spinning at the nearest tempo (a quarter, a half, one or two turns a bar), on the beat.
// Up/down flicks turn X, sideways flicks Y, a two-finger twist Z.

import { h, haptic, toast } from '../ui.js';
import { C, btn, canvas2d, chips, clamp, pointers, rgba, shell, MONO } from './room.js';
import { add, camera, euler, inside, mul, rx, ry, scale, tf } from './proj.js';

const TAU = Math.PI * 2;
const FACES = [
  { key: 'A', slot: 0, n: [0, 0, 1], u: [1, 0, 0], v: [0, 1, 0] },
  { key: 'B', slot: 1, n: [1, 0, 0], u: [0, 0, -1], v: [0, 1, 0] },
  { key: 'C', slot: 2, n: [0, 0, -1], u: [-1, 0, 0], v: [0, 1, 0] },
  { key: 'D', slot: 3, n: [-1, 0, 0], u: [0, 0, 1], v: [0, 1, 0] },
  { key: 'SET', n: [0, 1, 0], u: [1, 0, 0], v: [0, 0, -1] },
  { key: 'DICE', n: [0, -1, 0], u: [1, 0, 0], v: [0, 0, 1] },
];
const RATES = [0.25, 0.5, 1, 2];          // turns per bar a locked spin snaps to

export function cube(room) {
  const { store, engine } = room;
  const m = shell(room, {
    key: 'cube', title: 'Cube', sub: 'snapshots on a spinning die', power: true,
    note: 'Tap a face: A to D recall a snapshot (an empty one saves), SET goes back to the set, the dice nudges this cube\'s three knobs. Flick it: each axis moves a knob. Lock keeps a flick spinning in tempo.',
  });
  const picks = chips(room, m, [
    { role: 'X', hint: 'flick up and down', def: 'kick.colourFreq' },
    { role: 'Y', hint: 'flick sideways', def: 'kick.drive' },
    { role: 'Z', hint: 'twist two fingers', def: 'mix.spaceMix' },
  ]);
  m.el.insertBefore(picks.el, m.tools);
  m.output = room.out('cube');
  const S = canvas2d(room, m.view);

  const ang = [0, 0, 0], w = [0, 0, 0], lock = [null, null, null];   // lock[i] = {rate, phi, slew}
  let locking = false, held = false, homing = false, flashFace = null, flashT = 0, lastTick = [0, 0, 0];
  let faces2d = [];

  const lockBtn = btn('Lock', (_e, b) => {
    locking = !locking;
    b.setAttribute('aria-pressed', String(locking));
    if (!locking) for (let i = 0; i < 3; i++) if (lock[i]) { w[i] = TAU * lock[i].rate / engine.barSeconds; lock[i] = null; }
    toast(locking ? 'Lock: a flick spins in tempo' : 'Lock off: spins slow down');
  }, { pressed: false, label: 'Lock spins to the tempo' });
  const homeBtn = btn('Home', () => goHome(), { label: 'Turn back to face A' });
  m.tools.append(room.knob('play.cubeDepth', { size: 64, label: 'Depth' }), lockBtn, homeBtn);

  const goHome = () => {
    homing = true;
    for (let i = 0; i < 3; i++) { w[i] = 0; lock[i] = null; }
  };
  m.onPower = (on) => { if (!on) goHome(); };

  // --- touches ----------------------------------------------------------------------------------------------------
  let twist0 = null, longTimer = 0, downFace = null;
  const K = 0.011;                                       // radians per px
  const faceAt = (x, y) => faces2d.find((f) => inside(f.pts, x, y)) ?? null;
  pointers(S.cv, {
    down(p, all) {
      held = true; homing = false;
      for (let i = 0; i < 3; i++) { if (lock[i]) { lock[i] = null; } w[i] = 0; }
      if (all.size === 2) {
        const [a, b] = [...all.values()];
        twist0 = Math.atan2(b.y - a.y, b.x - a.x);
        clearTimeout(longTimer);
        return;
      }
      downFace = faceAt(p.x, p.y);
      clearTimeout(longTimer);
      if (downFace && downFace.slot != null) {
        longTimer = setTimeout(() => {
          if (p.moved || !all.has(p.id)) return;
          store.saveSlot(downFace.slot);
          haptic(true);
          flashFace = downFace.key; flashT = 1;
          toast(`Saved to ${downFace.key}`);
          downFace = null;
        }, 520);
      }
    },
    move(p, all) {
      if (all.size >= 2) {
        const [a, b] = [...all.values()];
        const t = Math.atan2(b.y - a.y, b.x - a.x);
        if (twist0 != null) { let d = t - twist0; if (d > Math.PI) d -= TAU; if (d < -Math.PI) d += TAU; ang[2] -= d; w[2] = -d * 60; }
        twist0 = t;
        if (!m.on) m.setOn(true);
        return;
      }
      if (!p.moved) return;
      clearTimeout(longTimer);
      ang[1] += (p.x - p.px) * K;
      ang[0] += (p.y - p.py) * K;
      w[1] = p.vx * K; w[0] = p.vy * K;
      if (!m.on) m.setOn(true);
    },
    up(p, all) {
      clearTimeout(longTimer);
      if (all.size) { twist0 = null; return; }
      held = false; twist0 = null;
      if (!p.moved && performance.now() - p.t0 < 400 && downFace) { tapFace(downFace); downFace = null; return; }
      downFace = null;
      for (let i = 0; i < 2; i++) w[i] = clamp(i === 0 ? p.vy * K : p.vx * K, -30, 30);
      if (locking) {
        const c = room.clock();
        for (let i = 0; i < 3; i++) {
          const turnsPerBar = (w[i] * engine.barSeconds) / TAU;
          if (Math.abs(turnsPerBar) < 0.12) continue;
          const r = RATES.reduce((best, x) => (Math.abs(Math.log(Math.abs(turnsPerBar) / x)) < Math.abs(Math.log(Math.abs(turnsPerBar) / best)) ? x : best), 1);
          const rate = Math.sign(turnsPerBar) * r;
          const base = TAU * rate * c.t;
          const phi = Math.round((ang[i] - base) / (Math.PI / 2)) * (Math.PI / 2);
          lock[i] = { rate, phi, slew: ang[i] - (phi + base) };
          haptic(true);
        }
      }
    },
  });

  const tapFace = (f) => {
    flashFace = f.key; flashT = 1;
    if (f.slot != null) {
      if (store.slots[f.slot]) { store.recallSlot(f.slot); haptic(); toast(`${f.key} recalled`); }
      else { store.saveSlot(f.slot); haptic(true); toast(`Saved to ${f.key}`); }
    } else if (f.key === 'SET') {
      store.resetAll(); haptic(true); toast('Every knob at the set\'s value (undo: the menu)');
    } else {
      store.randomize(picks.ids, 0.12); haptic(true); toast('Rolled: this cube\'s three knobs nudged');
    }
  };

  // --- the spin -----------------------------------------------------------------------------------------------------
  m.sim = (dt) => {
    const c = room.clock();
    for (let i = 0; i < 3; i++) {
      if (homing) {
        const home = Math.round(ang[i] / TAU) * TAU;
        ang[i] += (home - ang[i]) * (1 - Math.exp(-dt * 6));
        if (Math.abs(home - ang[i]) < 0.002) ang[i] = home;
        continue;
      }
      if (held) continue;
      if (lock[i]) {
        lock[i].slew *= Math.exp(-dt * 5);
        ang[i] = lock[i].phi + TAU * lock[i].rate * c.t + lock[i].slew;
      } else if (w[i]) {
        ang[i] += w[i] * dt;
        w[i] *= Math.exp(-dt * 0.8);
        if (Math.abs(w[i]) < 0.03) w[i] = 0;
      }
      // a tick each time a face comes round
      const q = Math.round(ang[i] / (Math.PI / 2));
      if (q !== lastTick[i]) { lastTick[i] = q; if (m.on && room.ratio(m) > 0) haptic(); }
    }
    if (homing && ang.every((a) => Math.abs(a - Math.round(a / TAU) * TAU) < 0.002)) homing = false;
    if (m.on) {
      const depth = room.real('play.cubeDepth', 40) / 100;
      m.output.frame(picks.ids.map((id, i) => [id, ((1 - Math.cos(ang[i])) / 2) * depth]));
    }
  };

  // --- drawing ----------------------------------------------------------------------------------------------------
  m.draw = (dt) => {
    const { g, w: W, h: H } = S.fit();
    const a = room.audio(), c = room.clock();
    flashT = Math.max(0, flashT - dt * 2.5);
    g.clearRect(0, 0, W, H);
    const bg = g.createLinearGradient(0, 0, 0, H);
    bg.addColorStop(0, '#07060a'); bg.addColorStop(0.55, '#120412'); bg.addColorStop(1, '#050406');
    g.fillStyle = bg; g.fillRect(0, 0, W, H);
    floor(g, W, H, c, a);

    const cx = W / 2, cy = H * 0.46;
    const F = Math.min(W, H) * 0.165 * (1 + 0.07 * a.pulse);
    const cam = camera(cx, cy, F, 5.2);
    const t = performance.now() / 1000;
    const view = mul(rx(0.42 + Math.sin(t * 0.7) * 0.04), ry(-0.62 + Math.sin(t * 0.45) * 0.06));
    const M = mul(view, euler(ang[0], ang[1], ang[2]));
    const drawn = [];
    for (const f of FACES) {
      const n = tf(M, f.n);
      if (!cam.facing(n, n)) continue;
      const u = tf(M, f.u), v = tf(M, f.v);
      const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([s, t]) => cam.p(add(add(n, scale(u, s)), scale(v, t))));
      drawn.push({ f, n, u, v, pts: corners, z: n[2] });
    }
    drawn.sort((p, q) => p.z - q.z);
    faces2d = drawn.slice().reverse().map((d) => ({ ...d.f, pts: d.pts }));
    const L = [-0.45, 0.6, 0.66];
    // the cube's shadow on the floor
    g.fillStyle = 'rgba(255,61,242,0.08)';
    g.beginPath(); g.ellipse(cx, H * 0.83, F * 1.5, F * 0.28, 0, 0, TAU); g.fill();
    for (const d of drawn) {
      const lit = 0.25 + 0.75 * Math.max(0, d.n[0] * L[0] + d.n[1] * L[1] + d.n[2] * L[2]);
      const [p0, p1, p2, p3] = d.pts;
      const full = d.f.slot != null && !!store.slots[d.f.slot];
      const gr = g.createLinearGradient(p3.x, p3.y, p1.x, p1.y);
      const s0 = Math.round(48 * lit + 10), s1 = Math.round(22 * lit + 6);
      gr.addColorStop(0, `rgb(${s0 + 6},${s0 + 4},${s0 + 12})`);
      gr.addColorStop(1, `rgb(${s1},${s1},${s1 + 4})`);
      g.beginPath(); g.moveTo(p0.x, p0.y); g.lineTo(p1.x, p1.y); g.lineTo(p2.x, p2.y); g.lineTo(p3.x, p3.y); g.closePath();
      g.fillStyle = gr; g.fill();
      if (full) { g.fillStyle = rgba(C.magenta, 0.1 + 0.12 * lit); g.fill(); }
      if (flashFace === d.f.key && flashT > 0) { g.fillStyle = rgba(C.acid, 0.35 * flashT); g.fill(); }
      g.lineJoin = 'round';
      g.strokeStyle = rgba(C.magenta, 0.45 + 0.5 * a.pulse); g.lineWidth = 1.6; g.stroke();
      // the face's label, drawn in the face's own plane
      const o = cam.p(d.n), ue = cam.p(add(d.n, d.u)), ve = cam.p(add(d.n, d.v));
      const U = [(ue.x - o.x) / 100, (ue.y - o.y) / 100], V = [(ve.x - o.x) / 100, (ve.y - o.y) / 100];
      g.save();
      g.setTransform(U[0] * S.dpr, U[1] * S.dpr, -V[0] * S.dpr, -V[1] * S.dpr, o.x * S.dpr, o.y * S.dpr);
      faceLabel(g, d.f, full, lit);
      g.restore();
    }
    // the axes' modulation, as three LED ladders
    const depth = room.real('play.cubeDepth', 40) / 100;
    ['X', 'Y', 'Z'].forEach((t, i) => {
      const x = 14 + i * 22, y0 = H - 14;
      const amt = m.on ? (1 - Math.cos(ang[i])) / 2 : 0;
      g.fillStyle = C.text3; g.font = `700 9px ${MONO}`; g.textAlign = 'center';
      g.fillText(t, x + 4, y0 + 2);
      for (let k = 0; k < 8; k++) {
        const on = depth !== 0 && amt * 8 > k + 0.5;
        g.fillStyle = on ? C.cold : '#14222b';
        g.fillRect(x, y0 - 12 - k * 7, 9, 5);
      }
    });
    g.textAlign = 'right'; g.font = `600 10px ${MONO}`; g.fillStyle = locking ? C.magenta : C.text3;
    g.fillText(locking ? (lock.some(Boolean) ? `LOCKED ${lock.filter(Boolean).map((l) => `${Math.abs(l.rate)}`).join(' / ')} TURN/BAR` : 'LOCK: FLICK IT') : '', W - 12, 18);
  };

  return room.add(m);
}

function faceLabel(g, f, full, lit) {
  g.textAlign = 'center'; g.textBaseline = 'middle';
  if (f.slot != null) {
    g.font = 'italic 900 112px -apple-system, "Helvetica Neue", Arial, sans-serif';
    if (full) {
      g.shadowColor = C.lcd; g.shadowBlur = 16;
      g.fillStyle = C.lcd; g.fillText(f.key, 0, -8);
      g.shadowBlur = 0;
    } else {
      g.lineWidth = 3; g.strokeStyle = `rgba(233,231,226,${0.18 + 0.2 * lit})`; g.strokeText(f.key, 0, -8);
    }
    g.font = `700 15px ${MONO}`;
    g.fillStyle = full ? 'rgba(255,181,71,0.75)' : 'rgba(233,231,226,0.4)';
    g.fillText(full ? 'RECALL' : 'TAP: SAVE', 0, 68);
  } else if (f.key === 'SET') {
    g.font = 'italic 900 64px -apple-system, "Helvetica Neue", Arial, sans-serif';
    g.shadowColor = C.acid; g.shadowBlur = 12; g.fillStyle = C.acid; g.fillText('SET', 0, -6); g.shadowBlur = 0;
    g.font = `700 14px ${MONO}`; g.fillStyle = 'rgba(198,255,61,0.6)'; g.fillText('BACK TO THE SET', 0, 52);
  } else {
    g.fillStyle = C.magenta; g.shadowColor = C.magenta; g.shadowBlur = 10;
    for (const [x, y] of [[-48, -48], [48, -48], [0, 0], [-48, 48], [48, 48]]) { g.beginPath(); g.arc(x, y, 13, 0, Math.PI * 2); g.fill(); }
    g.shadowBlur = 0;
  }
}

/** A neon floor in perspective, its lines rushing toward you one per beat. */
function floor(g, W, H, c, a) {
  const hy = H * 0.62, vx = W / 2;
  const glow = g.createLinearGradient(0, hy - 30, 0, hy + 10);
  glow.addColorStop(0, 'rgba(255,61,242,0)'); glow.addColorStop(1, `rgba(255,61,242,${0.18 + 0.25 * a.pulse})`);
  g.fillStyle = glow; g.fillRect(0, hy - 30, W, 40);
  g.strokeStyle = `rgba(255,61,242,${0.5 + 0.4 * a.pulse})`; g.lineWidth = 1.2;
  g.beginPath(); g.moveTo(0, hy); g.lineTo(W, hy); g.stroke();
  g.save();
  g.beginPath(); g.rect(0, hy, W, H - hy); g.clip();
  g.strokeStyle = 'rgba(255,61,242,0.28)'; g.lineWidth = 1;
  for (let i = -12; i <= 12; i++) { g.beginPath(); g.moveTo(vx + i * 6, hy); g.lineTo(vx + i * W * 0.22, H); g.stroke(); }
  const ph = c.beatPhase;
  for (let k = 0; k < 9; k++) {
    const z = (k + 1 - ph) / 9;                       // 1 far .. 0 near
    const y = hy + (H - hy) * Math.pow(1 - z, 2.6);
    g.globalAlpha = 0.15 + 0.6 * (1 - z);
    g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke();
  }
  g.restore();
  g.globalAlpha = 1;
}
