// The kHs Transient Shaper on Clubby 052, as a picture: the body's level over time before (dashed) and after (filled)
// the shaper, and the shaper's own gain (cold). Three zones you drag up or down: ATTACK (the first few ms), PUMP
// (the swell through the body), SUSTAIN (what follows). Time runs on a square-root scale so the attack has room.

import { h } from '../ui.js';
import { toNorm } from '../params.js';
import { knob } from '../widgets/knob.js';
import { ampBase, g2db, shaperGain } from './dsp.js';
import { drawNodes } from './env.js';
import { nodeCanvas } from './nodes.js';
import { C, MONO, panel, rgba } from './util.js';

const T_MAX = 420;   // ms

export function transient(ctx, rig, painter) {
  const { store, params } = ctx;
  const v = new Proxy({}, { get: (_t, id) => store.real(id) });
  const M = { L: 8, R: 8, T: 16, B: 18 };
  const X = (t, W) => M.L + Math.sqrt(Math.max(0, t) / T_MAX) * (W - M.L - M.R);
  const Y = (a, H) => M.T + (1 - a / 2.2) * (H - M.T - M.B);
  const setReal = (w, id, real) => w(id).set(toNorm(params.get(id), real));
  const zone = (id, t, span) => ({
    key: id, ids: [id], label: params.get(id).label,
    pos: (W, H) => { const p = params.get(id); const n = (v[id] - p.min) / (p.max - p.min); return [X(t, W), M.T + (1 - n) * (H - M.T - M.B)]; },
    move: (_dx, dy, { H, w }) => { const p = params.get(id); setReal(w, id, v[id] - (dy / (H - M.T - M.B)) * (p.max - p.min)); },
    span,
  });
  const nodes = [zone('kick.attack', 5, [0, 22]), zone('kick.pump', 60, [22, 125]), zone('kick.sustain', 240, [125, T_MAX])];
  const nc = nodeCanvas(ctx, { cls: 'kx-shape', label: 'Transient shaper', nodes });
  const draw = () => {
    const { g, k, w: W, h: H } = nc.cv.fit();
    g.scale(k, k);
    g.fillStyle = '#060707'; g.fillRect(0, 0, W, H);
    // zones
    const names = ['ATTACK', 'PUMP', 'SUSTAIN'];
    nodes.forEach((n, i) => {
      const x0 = X(n.span[0], W), x1 = X(n.span[1], W);
      g.fillStyle = nc.state.selected === n.key ? rgba(C.hazard, 0.07) : i % 2 ? 'rgba(255,255,255,0.02)' : 'rgba(255,255,255,0.0)';
      g.fillRect(x0, M.T, x1 - x0, H - M.T - M.B);
      g.fillStyle = 'rgba(255,255,255,0.08)'; g.fillRect(x1, M.T, 1, H - M.T - M.B);
      g.font = `700 9px ${MONO}`; g.textAlign = 'center'; g.fillStyle = C.text2;
      g.fillText(names[i], (x0 + x1) / 2, M.T - 4);
    });
    g.font = `600 8.5px ${MONO}`; g.fillStyle = C.text3;
    for (const t of [5, 25, 60, 125, 250, 400]) g.fillText(String(t), X(t, W), H - 5);
    // the body without the shaper, and with it
    const line = (fn, color, width, dash) => {
      g.beginPath();
      for (let i = 0; i <= 240; i++) { const t = (i / 240) ** 2 * T_MAX; const y = Y(fn(t / 1000), H); if (i === 0) g.moveTo(X(t, W), y); else g.lineTo(X(t, W), y); }
      g.setLineDash(dash ? [4, 3] : []); g.strokeStyle = color; g.lineWidth = width; g.stroke(); g.setLineDash([]);
    };
    g.beginPath(); g.moveTo(X(0, W), Y(0, H));
    for (let i = 0; i <= 240; i++) { const t = (i / 240) ** 2 * T_MAX; g.lineTo(X(t, W), Y(Math.min(2.2, ampBase(v, t / 1000) * shaperGain(v, t / 1000)), H)); }
    g.lineTo(X(T_MAX, W), Y(0, H)); g.closePath();
    const grd = g.createLinearGradient(0, M.T, 0, H); grd.addColorStop(0, rgba(C.hazard, 0.5)); grd.addColorStop(1, rgba(C.hazard, 0.05));
    g.fillStyle = grd; g.fill();
    line((t) => ampBase(v, t), rgba(C.text, 0.5), 1.2, true);
    g.shadowColor = C.hazard; g.shadowBlur = 8;
    line((t) => Math.min(2.2, ampBase(v, t) * shaperGain(v, t)), C.hazard, 2, false);
    g.shadowBlur = 0;
    // the shaper's gain in dB (0 dB at the middle line)
    line((t) => 1.1 + g2db(shaperGain(v, t)) / 24, rgba(C.cold, 0.85), 1.4, false);
    g.fillStyle = rgba(C.cold, 0.9); g.textAlign = 'right'; g.font = `600 8.5px ${MONO}`;
    g.fillText('SHAPER GAIN', W - M.R - 2, Y(1.1, H) - 4);
    drawNodes(g, nc, W, H);
  };
  const mark = painter.add(nc.el, draw);
  nc.setRedraw(mark);
  for (const id of ['kick.attack', 'kick.pump', 'kick.sustain', 'ks.ampHold', 'ks.ampDecay', 'ks.ampCurve']) ctx.own(store.on(id, mark, { now: false }));
  const knobs = ['kick.attack', 'kick.pump', 'kick.sustain', 'kick.verb'].map((id) => knob(ctx, id, { size: 64 }));
  return panel('Transient', { sub: 'kHs Transient Shaper on Clubby 052, FlexVerb', cls: 'kx-shaperack' },
    nc.el,
    h('div', { class: 'rack-body kx-knobrow' }, ...knobs),
    h('p', { class: 'rack-note', text: 'On a reference kick, attack 50-90% moved the crest from 8.8 to 15.5 dB and thinned the sub. HW002\'s peaks are already less dense than the references\'.' }));
}
