// The kick group's compressor as its transfer curve: input level across, output up. Drag the threshold node along
// the curve, the ratio node (the curve's right end) up or down. The live dot is the kick going in now (its peak)
// and coming out (less the gain reduction the compressor reports). At the set it is idle: the bus sits under the
// threshold, so the dot stays on the straight line.

import { h } from '../ui.js';
import { toNorm } from '../params.js';
import { knob } from '../widgets/knob.js';
import { drawNodes } from './env.js';
import { nodeCanvas } from './nodes.js';
import { MODE } from './rig.js';
import { C, MONO, numbox, panel, rgba } from './util.js';

const LO = -30, KNEE = 6;

/** Output level (dB) for an input level, Compressor2-style with a 6 dB soft knee. */
export function transfer(x, T, R) {
  const d = x - T;
  if (2 * d < -KNEE) return x;
  if (2 * d > KNEE) return T + d / R;
  return x + ((1 / R - 1) * (d + KNEE / 2) ** 2) / (2 * KNEE);
}

export function compressor(ctx, rig, painter) {
  const { store, params } = ctx;
  const v = new Proxy({}, { get: (_t, id) => store.real(id) });
  const M = { L: 30, R: 10, T: 10, B: 20 };
  const X = (db, W) => M.L + ((db - LO) / -LO) * (W - M.L - M.R);
  const Y = (db, H) => M.T + (1 - (db - LO) / -LO) * (H - M.T - M.B);
  const setReal = (w, id, real) => w(id).set(toNorm(params.get(id), real));
  const nc = nodeCanvas(ctx, {
    cls: 'kx-comp', label: 'Compressor transfer curve',
    nodes: [
      {
        key: 'thr', ids: ['kick.thresh'], label: 'Threshold',
        pos: (W, H) => [X(v['kick.thresh'], W), Y(transfer(v['kick.thresh'], v['kick.thresh'], v['kick.ratio']), H)],
        move: (dx, dy, { W, w }) => setReal(w, 'kick.thresh', v['kick.thresh'] + ((dx - dy) / 2 / (W - M.L - M.R)) * -LO),
      },
      {
        key: 'ratio', ids: ['kick.ratio'], label: 'Ratio',
        pos: (W, H) => [X(0, W), Y(transfer(0, v['kick.thresh'], v['kick.ratio']), H)],
        move: (_dx, dy, { H, w }) => setReal(w, 'kick.ratio', Math.max(1, Math.min(20, v['kick.ratio'] * Math.exp((dy / (H - M.T - M.B)) * 4)))),
      },
    ],
  });
  const grRead = h('b', { class: 'kx-comp-gr' });
  const idle = h('span', { class: 'kx-comp-idle' });
  let inPk = -90, inHold = -90, trail = [];
  const draw = () => {
    const { g, k, w: W, h: H } = nc.cv.fit();
    g.scale(k, k);
    g.fillStyle = '#060707'; g.fillRect(0, 0, W, H);
    g.font = `600 8.5px ${MONO}`;
    for (let db = LO + 6; db <= 0; db += 6) {
      g.fillStyle = 'rgba(255,255,255,0.05)';
      g.fillRect(X(db, W), M.T, 1, H - M.T - M.B); g.fillRect(M.L, Y(db, H), W - M.L - M.R, 1);
      g.fillStyle = C.text3; g.textAlign = 'center'; if (db < 0) g.fillText(String(db), X(db, W), H - 6);
      g.textAlign = 'right'; if (db < 0) g.fillText(String(db), M.L - 4, Y(db, H) + 3);
    }
    // unity
    g.setLineDash([2, 4]); g.strokeStyle = 'rgba(255,255,255,0.18)'; g.lineWidth = 1;
    g.beginPath(); g.moveTo(X(LO, W), Y(LO, H)); g.lineTo(X(0, W), Y(0, H)); g.stroke();
    // the bus's level in the set: RMS -9.3 dB, under the threshold
    g.strokeStyle = rgba(C.acid, 0.55); g.beginPath(); g.moveTo(X(-9.3, W), M.T); g.lineTo(X(-9.3, W), H - M.B); g.stroke();
    g.setLineDash([]);
    g.fillStyle = C.acid; g.textAlign = 'right'; g.fillText('BUS RMS -9.3', X(-9.3, W) - 3, M.T + 10);
    // the curve
    const T = v['kick.thresh'], R = v['kick.ratio'];
    g.beginPath();
    for (let i = 0; i <= 160; i++) { const x = LO + (i / 160) * -LO; const y = transfer(x, T, R); if (i === 0) g.moveTo(X(x, W), Y(y, H)); else g.lineTo(X(x, W), Y(y, H)); }
    g.shadowColor = C.hazard; g.shadowBlur = 8; g.strokeStyle = C.hazard; g.lineWidth = 2.4; g.stroke(); g.shadowBlur = 0;
    // the region over the threshold
    g.fillStyle = rgba(C.hazard, 0.07); g.fillRect(X(T, W), M.T, X(0, W) - X(T, W), H - M.T - M.B);
    // the live dot
    const live = rig.ac && ctx.engine.playing;
    if (live) {
      const pk = rig.compInput();
      inPk = pk > inPk ? pk : inPk + (pk - inPk) * 0.08;
      inHold = Math.max(pk, inHold - 0.25);
      const gr = rig.reduction();
      const x = Math.max(LO, Math.min(0, inHold)), y = Math.max(LO, Math.min(0, inHold + gr));
      trail.push([x, y]); if (trail.length > 24) trail.shift();
      trail.forEach(([tx, ty], i) => { g.fillStyle = rgba(C.lcd, (i / trail.length) * 0.35); g.beginPath(); g.arc(X(tx, W), Y(ty, H), 3, 0, Math.PI * 2); g.fill(); });
      g.fillStyle = C.lcd; g.shadowColor = C.lcd; g.shadowBlur = 14;
      g.beginPath(); g.arc(X(x, W), Y(y, H), 6, 0, Math.PI * 2); g.fill(); g.shadowBlur = 0;
      grRead.textContent = gr < -0.05 ? `${gr.toFixed(1)} dB` : '0.0 dB';
      const isIdle = gr > -0.1;
      idle.textContent = isIdle ? 'IDLE: THE KICK SITS UNDER THE THRESHOLD' : 'COMPRESSING';
      nc.el.parentNode?.classList.toggle('is-biting', !isIdle);
    } else {
      grRead.textContent = '-- dB';
      idle.textContent = 'IN THE SET IT IS IDLE: PRESS PLAY TO SEE THE KICK';
    }
    drawNodes(g, nc, W, H);
    g.fillStyle = C.text3; g.textAlign = 'left'; g.fillText('OUT dB', M.L + 6, M.T + 24);
    g.textAlign = 'right'; g.fillText('IN dB', W - M.R - 4, H - M.B - 6);
    const src = rig.playing === MODE.STEM ? 'THE STEM\'S BUS (THE CHANGE ONLY)' : 'THE SYNTH';
    g.textAlign = 'left'; g.fillStyle = C.text2; g.fillText(src, M.L + 6, M.T + 10);
  };
  const mark = painter.add(nc.el, draw, { always: true });
  nc.setRedraw(mark);
  const knobs = ['kick.cattack', 'kick.release', 'kick.cmix'].map((id) => knob(ctx, id, { size: 64 }));
  return panel('Compressor', { sub: 'the kick group\'s Compressor2', cls: 'kx-comprack' },
    h('div', { class: 'kx-env-head' }, h('b', { text: 'GR' }), grRead, idle),
    nc.el,
    h('div', { class: 'kx-nums' }, numbox(ctx, 'kick.thresh', { label: 'Thresh' }), numbox(ctx, 'kick.ratio', { label: 'Ratio' })),
    h('div', { class: 'rack-body kx-knobrow' }, ...knobs),
    h('p', { class: 'rack-note', text: 'Idle as set: the bus RMS (-9.3 dB) sits under the -5.5 dB threshold. The threshold is the one live knob: 11 dB of crest span. Offline, 36% parallel (dry/wet) won the drop.' }));
}
