// Gyro: three nested gimbal rings, each a slow wave locked to the bar clock (a quarter bar up to eight bars a turn).
// Each ring's turn moves a knob: facing you, the knob as it is; half a turn round, the depth; back again by the
// end of its cycle, on the bar line. Three rings at different lengths make a figure that repeats only when they all
// meet again, like layered automation.
//
// Tap a ring: its next length. Drag along a ring: slide its phase (when in the cycle it peaks).

import { haptic, toast } from '../ui.js';
import { C, canvas2d, chips, load, pointers, rgba, save, shell, shortOf, MONO } from './room.js';
import { camera, mul, rx, ry, tf } from './proj.js';

const RATES = [0.25, 0.5, 1, 2, 4, 8];      // bars per turn
const TAU = Math.PI * 2;
const label = (r) => (r < 1 ? `1/${1 / r} BAR` : `${r} BAR${r > 1 ? 'S' : ''}`);

export function gyro(room) {
  const { params } = room;
  const m = shell(room, {
    key: 'gyro', title: 'Gyro', sub: 'three rings locked to the bars', power: true,
    note: 'Each ring turns once per its length and moves a knob as it turns. Tap a ring for its next length; drag along it to move its peak.',
  });
  const picks = chips(room, m, [
    { role: 'Out', hint: 'the outer ring', def: 'kick.colour' },
    { role: 'Mid', hint: 'the middle ring', def: 'mix.spaceMix' },
    { role: 'In', hint: 'the inner ring', def: 'kick.sub30' },
  ]);
  m.el.insertBefore(picks.el, m.tools);
  m.output = room.out('gyro');
  const S = canvas2d(room, m.view);
  m.tools.append(room.knob('play.gyroDepth', { size: 64, label: 'Depth' }));

  const rates = load('gyro.rates', [4, 2, 1]).map((r) => (RATES.includes(r) ? r : 1));
  const phase = load('gyro.phase', [0, 0, 0]);
  const flash = [0, 0, 0];
  let rings2d = [], dragRing = null;
  const theta = (k, t) => TAU * (t / rates[k]) + phase[k];

  pointers(S.cv, {
    down(p) {
      let best = null, bd = 26;
      rings2d.forEach((pts, k) => { for (const q of pts) { const d = Math.hypot(q.x - p.x, q.y - p.y); if (d < bd) { bd = d; best = k; } } });
      dragRing = best;
    },
    move(p) {
      if (dragRing == null || !p.moved) return;
      phase[dragRing] = (phase[dragRing] + (p.x - p.px) * 0.015) % TAU;
    },
    up(p) {
      if (dragRing == null) return;
      const k = dragRing;
      dragRing = null;
      if (!p.moved) {
        rates[k] = RATES[(RATES.indexOf(rates[k]) + 1) % RATES.length];
        save('gyro.rates', rates);
        flash[k] = 1;
        haptic(true);
        toast(`${['Outer', 'Middle', 'Inner'][k]} ring: one turn every ${label(rates[k]).toLowerCase()}`);
      } else save('gyro.phase', phase);
    },
  });

  m.sim = (dt) => {
    for (let k = 0; k < 3; k++) flash[k] = Math.max(0, flash[k] - dt * 2);
    if (!m.on) return;
    const t = room.clock().t, depth = room.real('play.gyroDepth', 35) / 100;
    m.output.frame(picks.ids.map((id, k) => [id, ((1 - Math.cos(theta(k, t))) / 2) * depth]));
  };

  m.draw = () => {
    const { g, w: W, h: H } = S.fit();
    const a = room.audio(), c = room.clock();
    g.clearRect(0, 0, W, H);
    const bg = g.createRadialGradient(W / 2, H / 2, 5, W / 2, H / 2, Math.max(W, H) * 0.7);
    bg.addColorStop(0, '#0f1014'); bg.addColorStop(1, '#040405');
    g.fillStyle = bg; g.fillRect(0, 0, W, H);
    const s = Math.min(W, H);
    const cam = camera(W / 2, H / 2, 1, 900);
    const view = rx(0.38);
    const O = [];
    const th = [0, 1, 2].map((k) => theta(k, c.t));
    O[0] = mul(view, ry(th[0]));
    O[1] = mul(O[0], rx(th[1]));
    O[2] = mul(O[1], ry(th[2]));
    const radii = [s * 0.43, s * 0.33, s * 0.23];
    rings2d = [];
    const segs = 72;
    // the stand
    g.strokeStyle = 'rgba(255,255,255,0.08)'; g.lineWidth = 2;
    g.beginPath(); g.moveTo(W / 2, H / 2 + radii[0] * 0.95); g.lineTo(W / 2, H - 6); g.stroke();
    for (let k = 0; k < 3; k++) {
      const p = params.get(picks.ids[k]);
      const col = C[p.stage] ?? C.magenta;
      const pts = [];
      for (let i = 0; i <= segs; i++) {
        const an = (i / segs) * TAU;
        pts.push(cam.p(tf(O[k], [radii[k] * Math.cos(an), radii[k] * Math.sin(an), 0])));
      }
      rings2d.push(pts.filter((_, i) => i % 3 === 0));
      const amt = (1 - Math.cos(th[k])) / 2;
      for (let i = 0; i < segs; i++) {
        const p0 = pts[i], p1 = pts[i + 1];
        const zf = (p0.z / radii[k] + 1) / 2;          // 0 back .. 1 front
        g.strokeStyle = '#000'; g.lineWidth = 9; g.globalAlpha = 0.5 + 0.5 * zf;
        g.beginPath(); g.moveTo(p0.x, p0.y); g.lineTo(p1.x, p1.y); g.stroke();
        const shade = Math.round(40 + 120 * zf);
        g.strokeStyle = `rgb(${shade},${shade},${shade + 8})`; g.lineWidth = 6;
        g.beginPath(); g.moveTo(p0.x, p0.y); g.lineTo(p1.x, p1.y); g.stroke();
        g.strokeStyle = rgba(col, (0.25 + 0.75 * zf) * (m.on ? 0.5 + 0.5 * amt : 0.35) + flash[k] * 0.5);
        g.lineWidth = 2;
        g.beginPath(); g.moveTo(p0.x, p0.y); g.lineTo(p1.x, p1.y); g.stroke();
      }
      g.globalAlpha = 1;
      // the pivots this ring turns on
      const frame = [view, O[0], O[1]][k], r = radii[k];
      for (const v of k === 1 ? [[r, 0, 0], [-r, 0, 0]] : [[0, r, 0], [0, -r, 0]]) {
        const q = cam.p(tf(frame, v));
        g.fillStyle = '#6a707a'; g.strokeStyle = '#000'; g.lineWidth = 1.5;
        g.beginPath(); g.arc(q.x, q.y, 4.5, 0, TAU); g.fill(); g.stroke();
      }
      // the ring's marker: where "the knob as it is" sits on it, and its label
      const mk = pts[0];
      g.fillStyle = col; g.shadowColor = col; g.shadowBlur = 10;
      g.beginPath(); g.arc(mk.x, mk.y, 5 + 3 * flash[k], 0, TAU); g.fill(); g.shadowBlur = 0;
      const ly = 16 + k * 30;
      g.textAlign = 'left'; g.font = `800 10px ${MONO}`; g.fillStyle = col;
      g.fillText(`${['OUT', 'MID', 'IN'][k]} ${shortOf(p).toUpperCase()}`, 10, ly);
      g.font = `600 10px ${MONO}`; g.fillStyle = C.text2;
      g.fillText(label(rates[k]), 10, ly + 12);
      g.fillStyle = '#15191d'; g.fillRect(W - 66, ly - 8, 54, 7);
      g.fillStyle = m.on ? C.cold : C.steel4; g.fillRect(W - 66, ly - 8, 54 * amt, 7);
    }
    // the core
    const cr = s * 0.07 * (1 + 0.25 * a.pulse);
    const cg = g.createRadialGradient(W / 2 - cr * 0.3, H / 2 - cr * 0.3, 1, W / 2, H / 2, cr);
    cg.addColorStop(0, '#fff'); cg.addColorStop(0.4, C.magenta); cg.addColorStop(1, 'rgba(255,61,242,0)');
    g.fillStyle = cg; g.beginPath(); g.arc(W / 2, H / 2, cr * 1.6, 0, TAU); g.fill();
    g.textAlign = 'right'; g.font = `600 9.5px ${MONO}`; g.fillStyle = C.text3;
    g.fillText('TAP A RING: LENGTH  ·  DRAG: PHASE', W - 10, H - 10);
  };
  return room.add(m);
}
