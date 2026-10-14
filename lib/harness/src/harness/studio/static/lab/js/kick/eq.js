// The kick group's two EQ Eights as one curve you drag. Before COLDFIRE: the 30 Hz shelf, the 62 Hz body, the
// 330 Hz push. After it: the 35 Hz shelf, the colour bell (frequency and boost: drag it anywhere) and the 5 kHz
// shelf. The colour climb's move (484 Hz +5.8 dB to 2.2 kHz +7.6 dB) is a ghost path; the 2 kHz gap is marked.
// Chips pick a node when two sit close (30 and 35 Hz); a drag far from every node moves the picked one.

import { h, haptic } from '../ui.js';
import { toNorm } from '../params.js';
import { knob } from '../widgets/knob.js';
import { biquadDb, kickEqBands } from './dsp.js';
import { drawNodes } from './env.js';
import { nodeCanvas } from './nodes.js';
import { C, MONO, logAxis, panel, rgba } from './util.js';

const AX = logAxis(20, 16000);
const DB = 18;

export function eqCurve(ctx, rig, painter) {
  const { store, params } = ctx;
  const v = new Proxy({}, { get: (_t, id) => store.real(id) });
  const M = { L: 6, R: 6, T: 10, B: 16 };
  const X = (f, W) => M.L + AX.x(f, W - M.L - M.R);
  const Y = (db, H) => M.T + (0.5 - db / (2 * DB)) * (H - M.T - M.B);
  const setReal = (w, id, real) => w(id).set(toNorm(params.get(id), real));
  const bands = () => kickEqBands(v);
  const nodes = bands().map((b) => ({
    key: b.id, ids: b.freqId ? [b.id, b.freqId] : [b.id], label: params.get(b.id).label,
    pos: (W, H) => { const bb = bands().find((x) => x.id === b.id); return [X(bb.f, W), Y(Math.max(-DB, Math.min(DB, bb.gain)), H)]; },
    move: (dx, dy, { W, H, w }) => {
      if (dy) setReal(w, b.id, v[b.id] - (dy / (H - M.T - M.B)) * 2 * DB);
      if (b.freqId && dx) setReal(w, b.freqId, v[b.freqId] * Math.exp((dx / (W - M.L - M.R)) * Math.log(16000 / 20)));
    },
  }));
  const nc = nodeCanvas(ctx, { cls: 'kx-eq', label: 'Kick bus EQ', nodes, sticky: true });
  const chips = nodes.map((n) => {
    const b = h('button', { type: 'button', class: 'kx-chipbtn', dataset: { key: n.key }, text: bands().find((x) => x.id === n.key).label });
    b.addEventListener('click', () => { nc.select(n.key); haptic(); renderChips(); });
    return b;
  });
  const renderChips = () => chips.forEach((c) => c.classList.toggle('is-on', c.dataset.key === nc.state.selected));
  const read = h('div', { class: 'kx-env-read' });

  const draw = () => {
    const { g, k, w: W, h: H } = nc.cv.fit();
    g.scale(k, k);
    g.fillStyle = '#060707'; g.fillRect(0, 0, W, H);
    // grid
    g.font = `600 8.5px ${MONO}`; g.textAlign = 'center';
    for (const f of [20, 30, 50, 100, 200, 500, 1000, 2000, 5000, 10000]) {
      const x = X(f, W);
      g.fillStyle = 'rgba(255,255,255,0.05)'; g.fillRect(x, M.T, 1, H - M.T - M.B);
      g.fillStyle = C.text3; g.fillText(f >= 1000 ? `${f / 1000}k` : String(f), x, H - 4);
    }
    for (const db of [-12, -6, 0, 6, 12]) {
      g.fillStyle = db === 0 ? 'rgba(255,255,255,0.14)' : 'rgba(255,255,255,0.05)';
      g.fillRect(M.L, Y(db, H), W - M.L - M.R, 1);
    }
    g.textAlign = 'right'; g.fillStyle = C.text3;
    g.fillText('+12', W - M.R - 2, Y(12, H) - 2); g.fillText('-12', W - M.R - 2, Y(-12, H) - 2);
    // the 2 kHz gap (the drop sits 6.1 dB under the references there)
    g.fillStyle = rgba(C.cold, 0.08);
    g.fillRect(X(1000, W), M.T, X(3200, W) - X(1000, W), H - M.T - M.B);
    g.fillStyle = rgba(C.cold, 0.8); g.textAlign = 'center';
    g.fillText('MIDS GAP 1-3.2k', X(1800, W), H - M.B - 4);
    // the colour climb, as a ghost path
    const p0 = [X(484, W), Y(5.83, H)], p1 = [X(2184, W), Y(7.58, H)];
    g.setLineDash([4, 4]); g.strokeStyle = rgba(C.acid, 0.6); g.lineWidth = 1.5;
    g.beginPath(); g.moveTo(...p0); g.quadraticCurveTo((p0[0] + p1[0]) / 2, Y(10.5, H), ...p1); g.stroke(); g.setLineDash([]);
    g.fillStyle = rgba(C.acid, 0.7);
    g.beginPath(); g.arc(...p0, 3, 0, Math.PI * 2); g.fill();
    g.beginPath(); g.moveTo(p1[0] + 6, p1[1]); g.lineTo(p1[0] - 4, p1[1] - 5); g.lineTo(p1[0] - 3, p1[1] + 5); g.closePath(); g.fill();
    g.font = `600 8px ${MONO}`; g.fillText('COLOUR CLIMB', (p0[0] + p1[0]) / 2, Y(10.5, H) - 2);
    // the curves: before COLDFIRE, after it, and both
    const bs = bands();
    const resp = (f, which) => bs.filter((b) => which == null || b.pre === which).reduce((s, b) => s + biquadDb(b.type, b.f, b.gain, b.q, f), 0);
    const path = (which, color, width, fill) => {
      g.beginPath();
      for (let i = 0; i <= 220; i++) {
        const f = AX.f(i / 220, 1);
        const x = X(f, W), y = Y(Math.max(-DB, Math.min(DB, resp(f, which))), H);
        if (i === 0) g.moveTo(x, y); else g.lineTo(x, y);
      }
      if (fill) {
        g.save(); g.lineTo(W - M.R, Y(0, H)); g.lineTo(M.L, Y(0, H)); g.closePath();
        g.fillStyle = fill; g.fill(); g.restore();
        g.beginPath();
        for (let i = 0; i <= 220; i++) {
          const f = AX.f(i / 220, 1);
          const x = X(f, W), y = Y(Math.max(-DB, Math.min(DB, resp(f, which))), H);
          if (i === 0) g.moveTo(x, y); else g.lineTo(x, y);
        }
      }
      g.strokeStyle = color; g.lineWidth = width; g.stroke();
    };
    path(true, rgba(C.hazard, 0.45), 1, null);
    path(false, rgba(C.cold, 0.5), 1, null);
    g.shadowColor = C.hazard; g.shadowBlur = 6;
    path(null, C.text, 2, rgba(C.hazard, 0.16));
    g.shadowBlur = 0;
    // nodes: before COLDFIRE ringed in hazard, after in cold
    drawNodes(g, nc, W, H);
    g.font = `600 8.5px ${MONO}`; g.textAlign = 'center';
    for (const b of bs) {
      const [x, y] = nodes.find((n) => n.key === b.id).pos(W, H);
      g.fillStyle = b.pre ? C.hazard : C.cold;
      g.fillText(b.label, x + (b.id === 'kick.sub30' ? -10 : b.id === 'kick.sub35' ? 12 : 0), y + (b.gain < -6 ? 22 : -13));
    }
    g.textAlign = 'left'; g.fillStyle = C.hazard; g.fillText('● BEFORE COLDFIRE', M.L + 4, M.T + 9);
    g.fillStyle = C.cold; g.fillText('● AFTER', M.L + 104, M.T + 9);
    const sel = nc.selected();
    if (sel) {
      const p = params.get(sel.key), b = bs.find((x) => x.id === sel.key);
      read.textContent = `${p.label}: ${b.gain > 0 ? '+' : ''}${b.gain.toFixed(1)} dB${b.freqId ? ` at ${Math.round(b.f)} Hz` : ''}`;
    }
    renderChips();
  };
  const mark = painter.add(nc.el, draw);
  nc.setRedraw(mark);
  for (const b of bands()) { ctx.own(store.on(b.id, mark, { now: false })); if (b.freqId) ctx.own(store.on(b.freqId, mark, { now: false })); }

  const knobs = ['kick.sub30', 'kick.sub35', 'kick.body', 'kick.push', 'kick.colour', 'kick.colourFreq', 'kick.air']
    .map((id) => knob(ctx, id, { size: 64 }));
  return panel('Kick bus EQ', { sub: 'two EQ Eights, around COLDFIRE', cls: 'kx-eqrack' },
    h('div', { class: 'kx-env-head' }, h('b', { text: 'CURVE' }), read),
    nc.el,
    h('div', { class: 'kx-chips' }, ...chips),
    h('div', { class: 'rack-body is-row kx-knobrow' }, ...knobs),
    h('p', { class: 'rack-note', text: 'Deep sub: the references sit 7-9 dB above HW002 at 25-40 Hz; the deep-sub climb took the 30 Hz shelf from -14.8 to +4.8 dB. The 330 Hz push feeds COLDFIRE: an untested lever for bite.' }));
}
