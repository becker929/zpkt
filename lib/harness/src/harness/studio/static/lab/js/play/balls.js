// Kick box: steel balls in a box, one per knob. Every kick slams the floor and throws the balls that are resting on
// it; how high a ball flies is how far its knob moves (modulation: on the floor, the knob as it is; at the top of
// the box, the depth). So the knobs pump with the kick, and bounce, collide and settle in their own time.
//
// Grab a ball and throw it. Drag the empty box to shake it. With Tilt on, the balls roll the way the phone leans.
// Each hit on a wall or another ball is a tick under your thumb.

import { haptic } from '../ui.js';
import { C, canvas2d, chips, clamp, pointers, rgba, shell, shortOf, MONO } from './room.js';

const G = 2400;           // px/s^2
const TAU = Math.PI * 2;

export function balls(room) {
  const { params } = room;
  const m = shell(room, {
    key: 'balls', title: 'Kick box', sub: 'the kick throws the knobs', power: true,
    note: 'On every kick the floor throws the resting balls up: height is how far each knob moves. Throw a ball, shake the box, or tilt the phone (with Tilt on).',
  });
  const picks = chips(room, m, [
    { role: '1', hint: 'ball one', def: 'kick.drive' },
    { role: '2', hint: 'ball two', def: 'rumble.drive' },
    { role: '3', hint: 'ball three', def: 'kick.colour' },
    { role: '4', hint: 'ball four', def: 'mix.spaceMix' },
  ]);
  m.el.insertBefore(picks.el, m.tools);
  m.output = room.out('balls');
  const S = canvas2d(room, m.view);
  m.tools.append(room.knob('play.kickForce', { size: 64, label: 'Kick' }), room.knob('play.ballsDepth', { size: 64, label: 'Depth' }));

  const R = 23;
  const B = picks.ids.map((_, i) => ({ x: 60 + i * 80, y: 60, vx: (i - 1.5) * 40, vy: 0, held: null, flash: 0, trail: [] }));
  const sparks = [];
  let box = { x0: 8, y0: 8, x1: 300, y1: 300 }, lastBeat = null, floorFlash = 0, grab = null, shaking = null;

  const ballAt = (x, y) => B.findIndex((b) => Math.hypot(b.x - x, b.y - y) < R + 12);
  pointers(S.cv, {
    down(p) {
      const i = ballAt(p.x, p.y);
      if (i >= 0) { grab = { i, id: p.id }; B[i].held = p.id; B[i].vx = 0; B[i].vy = 0; if (!m.on) m.setOn(true); haptic(); }
      else shaking = p.id;
    },
    move(p) {
      if (grab && grab.id === p.id) {
        const b = B[grab.i];
        b.x = clamp(p.x, box.x0 + R, box.x1 - R); b.y = clamp(p.y, box.y0 + R, box.y1 - R);
        b.vx = p.vx; b.vy = p.vy;
      } else if (shaking === p.id && p.moved) {
        for (const b of B) { if (b.held != null) continue; b.vx += (p.x - p.px) * 9; b.vy += (p.y - p.py) * 9; }
      }
    },
    up(p) {
      if (grab && grab.id === p.id) {
        const b = B[grab.i];
        b.held = null; b.vx = clamp(b.vx, -2600, 2600); b.vy = clamp(b.vy, -2600, 2600);
        grab = null;
      }
      if (shaking === p.id) shaking = null;
    },
  });

  const hit = (x, y, speed, color) => {
    if (speed < 260) return;
    if (room.ratio(m) > 0) haptic(speed > 1200);
    for (let k = 0; k < Math.min(10, speed / 160); k++) {
      const an = Math.random() * TAU, v = 60 + Math.random() * speed * 0.25;
      sparks.push({ x, y, vx: Math.cos(an) * v, vy: Math.sin(an) * v, life: 0.35 + Math.random() * 0.3, color });
    }
  };

  m.sim = (dt) => {
    const c = room.clock(), a = room.audio();
    // the kick: on every beat while the engine plays
    const beat = Math.floor(c.beats);
    if (c.playing && lastBeat != null && beat !== lastBeat) {
      floorFlash = 1;
      const force = room.real('play.kickForce', 55) / 100;
      const hgt = force * (box.y1 - box.y0 - 2 * R) * (0.65 + 0.5 * Math.min(1, a.low));
      for (const b of B) {
        if (b.held != null || b.y < box.y1 - R * 2.2) continue;
        b.vy = -Math.sqrt(2 * G * Math.max(0, hgt)) * (0.85 + Math.random() * 0.3);
        b.vx += (Math.random() - 0.5) * 220;
        b.flash = 1;
      }
    }
    lastBeat = c.playing ? beat : null;
    // gravity, from the tilt when Tilt is on
    let gx = 0, gy = G;
    const t = room.sensors.tilt;
    if (t) { const vx = -t.x * 1.3, vy = 1 + t.y; const l = Math.max(0.25, Math.hypot(vx, vy)); gx = (vx / l) * G; gy = (vy / l) * G; }
    const n = 3, h = dt / n;
    for (let s = 0; s < n; s++) {
      for (const b of B) {
        if (b.held != null) continue;
        b.vx += gx * h; b.vy += gy * h;
        b.vx *= 1 - 0.15 * h; b.vy *= 1 - 0.05 * h;
        b.x += b.vx * h; b.y += b.vy * h;
        if (b.x < box.x0 + R) { hit(box.x0, b.y, Math.abs(b.vx), C.text); b.x = box.x0 + R; b.vx = Math.abs(b.vx) * 0.72; }
        if (b.x > box.x1 - R) { hit(box.x1, b.y, Math.abs(b.vx), C.text); b.x = box.x1 - R; b.vx = -Math.abs(b.vx) * 0.72; }
        if (b.y < box.y0 + R) { hit(b.x, box.y0, Math.abs(b.vy), C.text); b.y = box.y0 + R; b.vy = Math.abs(b.vy) * 0.72; }
        if (b.y > box.y1 - R) {
          if (b.vy > 420) hit(b.x, box.y1, b.vy, C.hazard);
          b.y = box.y1 - R; b.vy = -Math.abs(b.vy) * 0.5; b.vx *= 0.97;
          if (Math.abs(b.vy) < 60) b.vy = 0;
        }
      }
      for (let i = 0; i < B.length; i++) for (let j = i + 1; j < B.length; j++) {
        const p = B[i], q = B[j];
        const dx = q.x - p.x, dy = q.y - p.y, d = Math.hypot(dx, dy);
        if (d >= 2 * R || d < 1e-4) continue;
        const nx = dx / d, ny = dy / d, over = 2 * R - d;
        const pm = p.held != null ? 0 : 1, qm = q.held != null ? 0 : 1;
        if (!pm && !qm) continue;
        p.x -= nx * over * pm / (pm + qm); p.y -= ny * over * pm / (pm + qm);
        q.x += nx * over * qm / (pm + qm); q.y += ny * over * qm / (pm + qm);
        const rel = (q.vx - p.vx) * nx + (q.vy - p.vy) * ny;
        if (rel < 0) {
          const imp = -(1 + 0.85) * rel / (pm + qm);
          if (pm) { p.vx -= imp * nx; p.vy -= imp * ny; }
          if (qm) { q.vx += imp * nx; q.vy += imp * ny; }
          hit((p.x + q.x) / 2, (p.y + q.y) / 2, -rel, C.magenta);
          p.flash = q.flash = Math.max(p.flash, Math.min(1, -rel / 1500));
        }
      }
    }
    for (const b of B) { b.flash = Math.max(0, b.flash - dt * 3); b.trail.push([b.x, b.y]); if (b.trail.length > 8) b.trail.shift(); }
    for (let i = sparks.length - 1; i >= 0; i--) {
      const s = sparks[i]; s.life -= dt; s.x += s.vx * dt; s.y += s.vy * dt; s.vy += G * 0.3 * dt;
      if (s.life <= 0) sparks.splice(i, 1);
    }
    floorFlash = Math.max(0, floorFlash - dt * 4);
    if (m.on) {
      const depth = room.real('play.ballsDepth', 45) / 100, span = box.y1 - box.y0 - 2 * R;
      m.output.frame(picks.ids.map((id, i) => [id, clamp((box.y1 - R - B[i].y) / span) * depth]));
    }
  };

  m.draw = () => {
    const { g, w: W, h: H } = S.fit();
    box = { x0: 10, y0: 10, x1: W - 10, y1: H - 22 };
    g.clearRect(0, 0, W, H);
    g.fillStyle = '#08080a'; g.fillRect(0, 0, W, H);
    // the box: a grid, height marks, the floor's hazard stripe
    g.strokeStyle = 'rgba(255,255,255,0.045)'; g.lineWidth = 1;
    for (let x = box.x0; x <= box.x1; x += 24) { g.beginPath(); g.moveTo(x, box.y0); g.lineTo(x, box.y1); g.stroke(); }
    for (let y = box.y1; y >= box.y0; y -= 24) { g.beginPath(); g.moveTo(box.x0, y); g.lineTo(box.x1, y); g.stroke(); }
    g.font = `600 9px ${MONO}`; g.fillStyle = C.text3; g.textAlign = 'right';
    const span = box.y1 - box.y0 - 2 * R;
    for (const f of [0.25, 0.5, 0.75, 1]) { const y = box.y1 - R - f * span; g.fillText(`${f * 100}%`, box.x1 - 4, y - 3); g.strokeStyle = 'rgba(89,199,255,0.12)'; g.beginPath(); g.moveTo(box.x0, y); g.lineTo(box.x1, y); g.stroke(); }
    g.save();
    g.beginPath(); g.rect(box.x0, box.y1, box.x1 - box.x0, 12); g.clip();
    g.fillStyle = floorFlash > 0 ? `rgb(${Math.round(30 + 225 * floorFlash)},${Math.round(20 + 70 * floorFlash)},${Math.round(10 + 20 * floorFlash)})` : '#1a0d06';
    g.fillRect(box.x0, box.y1, box.x1 - box.x0, 12);
    g.fillStyle = '#060606';
    for (let x = box.x0 - 20; x < box.x1 + 20; x += 18) { g.beginPath(); g.moveTo(x, box.y1 + 12); g.lineTo(x + 8, box.y1 + 12); g.lineTo(x + 16, box.y1); g.lineTo(x + 8, box.y1); g.fill(); }
    g.restore();
    if (floorFlash > 0) { const fg = g.createLinearGradient(0, box.y1 - 60, 0, box.y1); fg.addColorStop(0, 'rgba(255,90,31,0)'); fg.addColorStop(1, rgba(C.hazard, 0.25 * floorFlash)); g.fillStyle = fg; g.fillRect(box.x0, box.y1 - 60, box.x1 - box.x0, 60); }
    g.strokeStyle = C.steel4; g.lineWidth = 2; g.strokeRect(box.x0, box.y0, box.x1 - box.x0, box.y1 - box.y0 + 12);
    // sparks
    for (const s of sparks) { g.fillStyle = rgba(s.color, Math.min(1, s.life * 3)); g.fillRect(s.x - 1.5, s.y - 1.5, 3, 3); }
    // balls
    B.forEach((b, i) => {
      const p = params.get(picks.ids[i]);
      const col = C[p.stage] ?? C.magenta;
      const amt = clamp((box.y1 - R - b.y) / span);
      if (m.on && amt > 0.01) { g.strokeStyle = rgba(C.cold, 0.5); g.lineWidth = 2; g.beginPath(); g.moveTo(b.x, b.y + R); g.lineTo(b.x, box.y1); g.stroke(); }
      b.trail.forEach(([x, y], k) => { g.fillStyle = rgba(col, 0.03 * k); g.beginPath(); g.arc(x, y, R, 0, TAU); g.fill(); });
      const gr = g.createRadialGradient(b.x - R * 0.35, b.y - R * 0.45, 2, b.x, b.y, R);
      gr.addColorStop(0, '#ffffff'); gr.addColorStop(0.25, '#c9ccd3'); gr.addColorStop(0.62, '#3b3f47'); gr.addColorStop(1, '#0d0e10');
      g.beginPath(); g.arc(b.x, b.y, R, 0, TAU); g.fillStyle = gr; g.fill();
      g.lineWidth = 2.5; g.strokeStyle = b.held != null ? '#fff' : rgba(col, 0.6 + 0.4 * b.flash); g.stroke();
      if (b.flash > 0) { g.shadowColor = col; g.shadowBlur = 20 * b.flash; g.stroke(); g.shadowBlur = 0; }
      g.textAlign = 'center'; g.textBaseline = 'middle';
      g.fillStyle = '#0a0a0a'; g.font = `900 15px ${MONO}`; g.fillText(String(i + 1), b.x + 1, b.y + 1);
      g.fillStyle = col; g.fillText(String(i + 1), b.x, b.y);
      const label = shortOf(p).toUpperCase();
      g.font = `700 9px ${MONO}`; g.fillStyle = rgba(col, 0.9);
      g.fillText(label.length > 10 ? label.slice(0, 10) : label, b.x, Math.max(box.y0 + 8, b.y - R - 8));
    });
    g.textBaseline = 'alphabetic';
  };
  return room.add(m);
}
