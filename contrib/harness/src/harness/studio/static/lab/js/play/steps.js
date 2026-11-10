// Steps: a Max-style multislider, two lanes of sixteen 16ths, each moving a knob step by step on the bar clock
// (modulation on top of the knob). Draw the bars with a finger across a lane. Glide slides the steps into each
// other; depth is how far a full bar moves the knob. The shapes: on the kick, between the kicks, a ramp over the
// bar, a random one, and off. They go to the lane you touched last.

import { haptic, toast } from '../ui.js';
import { C, btn, canvas2d, chips, clamp, load, pointers, rgba, save, shell, shortOf, MONO } from './room.js';

const N = 16;
const SHAPES = {
  Kick: () => Array.from({ length: N }, (_, i) => (i % 4 === 0 ? 1 : 0)),
  Offbeat: () => Array.from({ length: N }, (_, i) => (i % 4 === 2 ? 1 : i % 4 === 3 ? 0.35 : 0)),
  Ramp: () => Array.from({ length: N }, (_, i) => i / (N - 1)),
  Random: () => Array.from({ length: N }, () => Math.round(Math.random() * 8) / 8),
  Off: () => new Array(N).fill(0),
};

export function steps(room) {
  const { params } = room;
  const m = shell(room, {
    key: 'steps', title: 'Steps', sub: 'a multislider of 16ths', power: true,
    note: 'Draw across a lane: each 16th moves its knob by that much. Glide smooths it. Shapes go to the lane you touched last.',
  });
  const picks = chips(room, m, [
    { role: 'A', hint: 'the top lane', def: 'kick.drive' },
    { role: 'B', hint: 'the bottom lane', def: 'kick.colourFreq' },
  ]);
  m.el.insertBefore(picks.el, m.tools);
  m.output = room.out('steps');
  const S = canvas2d(room, m.view);

  const lanes = load('steps.lanes', null) ?? [SHAPES.Offbeat(), SHAPES.Ramp().map((v) => Math.round(v * 8) / 8)];
  let focus = 0, cur = [0, 0], playing = -1;
  const shapeRow = Object.keys(SHAPES).map((k) => btn(k, () => {
    lanes[focus] = SHAPES[k](); save('steps.lanes', lanes);
    toast(`Lane ${'AB'[focus]}: ${k.toLowerCase()}`);
  }, { cls: 'is-small' }));
  m.tools.append(room.knob('play.stepsDepth', { size: 60, label: 'Depth' }), room.knob('play.stepsGlide', { size: 60, label: 'Glide' }));
  const row = document.createElement('div');
  row.className = 'pl-row';
  row.append(...shapeRow);
  m.tools.append(row);

  // geometry
  const geo = () => { const pad = 8, gap = 12, lh = (S.h - pad * 2 - gap) / 2; return { pad, gap, lh, cw: (S.w - pad * 2) / N }; };
  let last = null;
  const paint = (p) => {
    const { pad, gap, lh, cw } = geo();
    const lane = p.y < pad + lh + gap / 2 ? 0 : 1;
    if (last?.lane != null && last.lane !== lane) return;
    const y0 = pad + lane * (lh + gap);
    const i = clamp(Math.floor((p.x - pad) / cw), 0, N - 1);
    const v = Math.round(clamp(1 - (p.y - y0) / lh) * 16) / 16;
    const from = last ? last.i : i, fv = last ? last.v : v;
    const lo = Math.min(from, i), hi = Math.max(from, i);
    for (let k = lo; k <= hi; k++) {
      const t = hi === lo ? 1 : (k - from) / (i - from);
      lanes[lane][k] = Math.round((fv + (v - fv) * clamp(t)) * 16) / 16;
    }
    if (!last || last.i !== i) haptic();
    last = { lane, i, v };
    focus = lane;
  };
  pointers(S.cv, {
    down(p) { last = null; paint(p); if (!m.on) m.setOn(true); },
    move(p) { if (last) paint(p); },
    up() { last = null; save('steps.lanes', lanes); },
  });

  m.sim = (dt) => {
    const c = room.clock();
    const step = Math.floor((((c.tRaw % 1) + 1) % 1) * N);
    if (step !== playing) playing = step;
    const glide = room.real('play.stepsGlide', 15) / 100;
    const tau = glide * 0.18;                                   // s: up to about two 16ths
    for (let l = 0; l < 2; l++) {
      const target = lanes[l][playing] ?? 0;
      cur[l] = tau < 0.004 ? target : cur[l] + (target - cur[l]) * (1 - Math.exp(-dt / tau));
    }
    if (!m.on) return;
    const depth = room.real('play.stepsDepth', 45) / 100;
    m.output.frame(picks.ids.map((id, l) => [id, cur[l] * depth]));
  };

  m.draw = () => {
    const { g, w: W, h: H } = S.fit();
    const c = room.clock();
    const heard = Math.floor((((c.t % 1) + 1) % 1) * N);
    const { pad, gap, lh, cw } = geo();
    g.clearRect(0, 0, W, H);
    g.fillStyle = '#060607'; g.fillRect(0, 0, W, H);
    for (let l = 0; l < 2; l++) {
      const y0 = pad + l * (lh + gap);
      const p = params.get(picks.ids[l]);
      const col = C[p.stage] ?? C.magenta;
      for (let i = 0; i < N; i++) {
        const x = pad + i * cw;
        g.fillStyle = Math.floor(i / 4) % 2 ? '#0e0f12' : '#131418';
        g.fillRect(x + 1, y0, cw - 2, lh);
        const v = lanes[l][i];
        const on = i === heard && c.playing;
        const bh = v * lh;
        if (bh > 0) {
          const gr = g.createLinearGradient(0, y0 + lh - bh, 0, y0 + lh);
          gr.addColorStop(0, on ? '#ffffff' : rgba(C.magenta, 0.95)); gr.addColorStop(1, on ? C.cold : rgba(C.magenta, 0.35));
          g.fillStyle = gr; g.fillRect(x + 3, y0 + lh - bh, cw - 6, bh);
          g.fillStyle = on ? '#fff' : C.magenta; g.fillRect(x + 3, y0 + lh - bh, cw - 6, 2);
        }
        if (on) { g.strokeStyle = m.on ? C.cold : C.text3; g.lineWidth = 1.5; g.strokeRect(x + 1.5, y0 + 0.5, cw - 3, lh - 1); }
      }
      g.strokeStyle = focus === l ? rgba(C.magenta, 0.7) : 'rgba(255,255,255,0.08)'; g.lineWidth = 1;
      g.strokeRect(pad + 0.5, y0 + 0.5, cw * N - 1, lh - 1);
      g.font = `800 10px ${MONO}`; g.textAlign = 'left';
      const tag = `${'AB'[l]} ${shortOf(p).toUpperCase()}`;
      g.fillStyle = 'rgba(0,0,0,0.75)'; g.fillRect(pad + 2, y0 + 3, g.measureText(tag).width + 8, 15);
      g.fillStyle = col; g.fillText(tag, pad + 6, y0 + 13);
      // what the knob gets now
      const gx = W - pad - 46;
      g.fillStyle = '#15191d'; g.fillRect(gx, y0 + 5, 40, 6);
      g.fillStyle = m.on ? C.cold : C.steel4; g.fillRect(gx, y0 + 5, 40 * cur[l], 6);
    }
    g.font = `600 9px ${MONO}`; g.fillStyle = C.text3; g.textAlign = 'center';
    for (let b = 0; b < 4; b++) g.fillText(String(b + 1), pad + (b * 4 + 0.5) * cw, pad + lh + gap / 2 + 3);
  };
  return room.add(m);
}
