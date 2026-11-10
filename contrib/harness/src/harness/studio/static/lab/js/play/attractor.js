// Lorenz: a strange attractor drawing itself, slowly moving three knobs with its three coordinates.
//
// Chaos is the attractor's rho. Below 24.7 the path spirals into one of two still points and the knobs come to
// rest there (calm); just above, it circles one wing for a while and flips to the other at moments nobody can
// predict (the edge); higher, it flips all the time (wild). Speed sets how fast it runs (at 35 % one loop is about
// two bars). Tap the screen to kick the path: two nearly equal paths soon part completely, which is the point.
// X swings the first knob both ways, Y the second, Z (the height of the butterfly) raises the third.

import { haptic, toast } from '../ui.js';
import { C, canvas2d, chips, clamp, pointers, rgba, shell, MONO } from './room.js';
import { camera, mul, rx, ry, tf } from './proj.js';

const SIGMA = 10, BETA = 8 / 3, N = 1600;
const TAU = Math.PI * 2;

export function attractor(room) {
  const m = shell(room, {
    key: 'lorenz', title: 'Lorenz', sub: 'a strange attractor on three knobs', power: true,
    note: 'Chaos below 25 %: it settles and the knobs come to rest. Around 55 %: it circles one wing and flips without warning. Tap the screen to kick it.',
  });
  const picks = chips(room, m, [
    { role: 'X', hint: 'left and right wings', def: 'kick.colourFreq' },
    { role: 'Y', hint: 'front and back', def: 'kick.sub30' },
    { role: 'Z', hint: 'the butterfly\'s height', def: 'mix.spaceMix' },
  ]);
  m.el.insertBefore(picks.el, m.tools);
  m.output = room.out('lorenz');
  const S = canvas2d(room, m.view);
  m.tools.append(
    room.knob('play.chaos', { size: 64, label: 'Chaos' }),
    room.knob('play.attSpeed', { size: 64, label: 'Speed' }),
    room.knob('play.attDepth', { size: 64, label: 'Depth' }));

  let s = [1.2, 1.1, 20];
  const trail = new Float32Array(N * 3);
  let head = 0, count = 0, kick = 0, view = 0;
  const rho = () => 12 + 30 * (room.real('play.chaos', 55) / 100);
  const deriv = ([x, y, z], r) => [SIGMA * (y - x), x * (r - z) - y, x * y - BETA * z];
  const step = (h, r) => {                                  // one RK4 step
    const k1 = deriv(s, r);
    const k2 = deriv(s.map((v, i) => v + k1[i] * h / 2), r);
    const k3 = deriv(s.map((v, i) => v + k2[i] * h / 2), r);
    const k4 = deriv(s.map((v, i) => v + k3[i] * h), r);
    s = s.map((v, i) => v + (h / 6) * (k1[i] + 2 * k2[i] + 2 * k3[i] + k4[i]));
    if (!s.every(Number.isFinite)) s = [1, 1, 20];
  };
  const push = () => { trail[head * 3] = s[0]; trail[head * 3 + 1] = s[1]; trail[head * 3 + 2] = s[2]; head = (head + 1) % N; count = Math.min(N, count + 1); };
  // warm up so the screen starts with a butterfly
  for (let i = 0; i < 1400; i++) { step(0.01, 28); push(); }

  pointers(S.cv, {
    up(p) {
      if (p.moved) return;
      s = [s[0] + (Math.random() - 0.5) * 6, s[1] + (Math.random() - 0.5) * 6, s[2] + (Math.random() - 0.5) * 4];
      kick = 1;
      haptic(true);
      if (!m.on) toast('Kicked: switch it on to hear the path');
    },
  });

  m.sim = (dt) => {
    const speed = 0.05 + 1.4 * Math.pow(room.real('play.attSpeed', 35) / 100, 1.5);
    const r = rho();
    // in Lorenz time, one loop is ~0.75; at speed 35 % that is two bars (3 s)
    const T = dt * speed * 1.2;
    const n = Math.max(1, Math.ceil(T / 0.008));
    for (let i = 0; i < n; i++) { step(T / n, r); }
    push();
    kick = Math.max(0, kick - dt * 2);
    view += dt * 0.12;
    if (m.on) {
      const depth = room.real('play.attDepth', 30) / 100;
      const [X, Y, Z] = picks.ids;
      m.output.frame([[X, clamp(s[0] / 20, -1, 1) * depth], [Y, clamp(s[1] / 27, -1, 1) * depth], [Z, clamp(s[2] / 45) * depth]]);
    }
  };

  m.draw = () => {
    const { g, w: W, h: H } = S.fit();
    const a = room.audio();
    g.clearRect(0, 0, W, H);
    const bg = g.createRadialGradient(W / 2, H * 0.55, 10, W / 2, H / 2, Math.max(W, H) * 0.75);
    bg.addColorStop(0, '#0d0a14'); bg.addColorStop(1, '#030305');
    g.fillStyle = bg; g.fillRect(0, 0, W, H);
    const M = mul(rx(-0.35), ry(view));
    const F = Math.min(W, H) / 62;
    const cam = camera(W / 2, H * 0.53, F, 160);
    const P = (i) => { const k = ((head - count + i) % N + N) % N; return cam.p(tf(M, [trail[k * 3], trail[k * 3 + 2] - 25, trail[k * 3 + 1]])); };
    const r = rho();
    // the two still points the path falls into when calm
    if (r > 1) {
      const q = Math.sqrt(BETA * (r - 1));
      for (const sgn of [-1, 1]) {
        const c = cam.p(tf(M, [sgn * q, r - 1 - 25, sgn * q]));
        g.strokeStyle = r < 24.74 ? rgba(C.acid, 0.8) : 'rgba(255,255,255,0.18)';
        g.lineWidth = 1; g.beginPath(); g.arc(c.x, c.y, 5, 0, TAU); g.stroke();
        g.beginPath(); g.moveTo(c.x - 8, c.y); g.lineTo(c.x + 8, c.y); g.moveTo(c.x, c.y - 8); g.lineTo(c.x, c.y + 8); g.stroke();
      }
    }
    // the trail, in 20 runs, fading
    g.globalCompositeOperation = 'lighter';
    g.lineJoin = 'round'; g.lineCap = 'round';
    const runs = 20, per = Math.ceil(count / runs);
    for (let rI = 0; rI < runs; rI++) {
      const i0 = rI * per, i1 = Math.min(count - 1, i0 + per);
      if (i1 <= i0) continue;
      const f = (rI + 1) / runs;
      g.strokeStyle = f > 0.85 ? rgba(C.cold, 0.25 + 0.6 * f) : rgba(C.magenta, 0.08 + 0.45 * f * f);
      g.lineWidth = 0.8 + 1.4 * f;
      g.beginPath();
      let p0 = P(i0); g.moveTo(p0.x, p0.y);
      for (let i = i0 + 1; i <= i1; i++) { p0 = P(i); g.lineTo(p0.x, p0.y); }
      g.stroke();
    }
    const hd = P(count - 1);
    const gr = g.createRadialGradient(hd.x, hd.y, 0, hd.x, hd.y, 18 + 14 * a.pulse + 20 * kick);
    gr.addColorStop(0, 'rgba(255,255,255,0.95)'); gr.addColorStop(0.25, rgba(C.cold, 0.7)); gr.addColorStop(1, 'rgba(89,199,255,0)');
    g.fillStyle = gr; g.beginPath(); g.arc(hd.x, hd.y, 40, 0, TAU); g.fill();
    g.globalCompositeOperation = 'source-over';
    // readouts: rho and the mood, three meters
    g.font = `700 10px ${MONO}`; g.textAlign = 'left'; g.fillStyle = C.text3;
    g.fillText(`RHO ${r.toFixed(1)}`, 12, 18);
    g.fillStyle = r < 24.74 ? C.acid : r < 30 ? C.lcd : C.alarm;
    g.fillText(r < 24.74 ? 'CALM: IT SETTLES' : r < 30 ? 'THE EDGE' : 'WILD', 12, 32);
    const vals = [clamp(s[0] / 20, -1, 1), clamp(s[1] / 27, -1, 1), clamp(s[2] / 45)];
    ['X', 'Y', 'Z'].forEach((t, i) => {
      const x = W - 70, y = 14 + i * 13, w = 52;
      g.fillStyle = C.text3; g.textAlign = 'right'; g.fillText(t, x - 6, y + 7);
      g.fillStyle = '#15191d'; g.fillRect(x, y, w, 8);
      g.fillStyle = m.on ? C.cold : C.steel4;
      if (i < 2) { const v = vals[i]; g.fillRect(x + w / 2 + Math.min(0, v) * w / 2, y, Math.abs(v) * w / 2, 8); g.fillStyle = C.text3; g.fillRect(x + w / 2, y - 1, 1, 10); }
      else g.fillRect(x, y, vals[i] * w, 8);
    });
  };
  return room.add(m);
}
