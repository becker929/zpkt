// The synth's two envelopes as curves you drag with a thumb.
//
// Pitch: where the body starts (drag the left node up or down) and where it lands and how fast (the right node:
// across is the fall time, up and down the end note). HW002's own kick, measured, is drawn as acid dots.
// Level: the body's hold (drag the top node across), its decay (the bottom node across), the decay's curve (the
// middle node up or down) and the click (the spike at the start, up or down). The transient shaper's attack, pump
// and sustain shape the filled area; the offbeat and the next kick are marked.

import { h } from '../ui.js';
import { toNorm } from '../params.js';
import { BEAT, LAYER, SET_PITCH, ampBase, ampExp, noteName, pitchAt, shaperGain } from './dsp.js';
import { nodeCanvas } from './nodes.js';
import { C, MONO, numbox, panel, rgba } from './util.js';

const vals = (ctx) => new Proxy({}, { get: (_t, id) => ctx.store.real(id) });

function setReal(ctx, w, id, real) { w(id).set(toNorm(ctx.params.get(id), real)); }

export function envelopes(ctx, rig, painter) {
  const v = vals(ctx);
  const playhead = () => rig.sinceKick();

  // ---- pitch ----
  const P = { L: 34, R: 10, T: 10, B: 18, tMax: 300, f0: 25, f1: 1300 };
  const px = (t, W) => P.L + (t / P.tMax) * (W - P.L - P.R);
  const py = (f, H) => P.T + (1 - Math.log(f / P.f0) / Math.log(P.f1 / P.f0)) * (H - P.T - P.B);
  const logSpan = Math.log(P.f1 / P.f0);
  const pitch = nodeCanvas(ctx, {
    cls: 'kx-env is-pitch',
    label: 'Pitch envelope',
    nodes: [
      {
        key: 'start', ids: ['ks.pitchStart'], label: 'Pitch start',
        pos: (W, H) => [px(0, W), py(v['ks.pitchStart'], H)],
        move: (dx, dy, { H, w }) => setReal(ctx, w, 'ks.pitchStart', v['ks.pitchStart'] * Math.exp((-dy / (H - P.T - P.B)) * logSpan * 0.5)),
      },
      {
        key: 'end', ids: ['ks.pitchDecay', 'ks.pitchEnd'], label: 'Pitch fall and end',
        pos: (W, H) => [Math.min(W - P.R, px(3 * v['ks.pitchDecay'], W)), py(v['ks.pitchEnd'], H)],
        move: (dx, dy, { W, H, w }) => {
          if (dx) setReal(ctx, w, 'ks.pitchDecay', Math.max(1, v['ks.pitchDecay'] + (dx / (W - P.L - P.R)) * P.tMax / 3));
          if (dy) setReal(ctx, w, 'ks.pitchEnd', v['ks.pitchEnd'] * Math.exp((-dy / (H - P.T - P.B)) * logSpan * 0.4));
        },
      },
    ],
  });
  const pitchRead = h('div', { class: 'kx-env-read' });
  const drawPitch = () => {
    const { g, k, w: Wc, h: Hc } = pitch.cv.fit();
    g.scale(k, k);
    g.fillStyle = '#060707'; g.fillRect(0, 0, Wc, Hc);
    grid(g, Wc, Hc, P, px, (t) => (t === 250 ? '250 ms' : `${t}`), [0, 50, 100, 150, 200, 250]);
    g.font = `600 8.5px ${MONO}`; g.textAlign = 'right';
    for (const f of [30, 50, 100, 200, 500, 1000]) {
      const y = py(f, Hc);
      g.fillStyle = 'rgba(255,255,255,0.05)'; g.fillRect(P.L, y, Wc - P.L - P.R, 1);
      g.fillStyle = C.text3; g.fillText(f >= 1000 ? '1k' : String(f), P.L - 4, y + 3);
    }
    // the set's kick, measured
    g.fillStyle = C.acid;
    for (const [t, f] of SET_PITCH) { g.beginPath(); g.arc(px(t, Wc), py(f, Hc), 2.4, 0, Math.PI * 2); g.fill(); }
    // the 060 knock, faint
    curve(g, (t) => [px(t, Wc), py(pitchAt(v, t / 1000, LAYER.l060), Hc)], P.tMax, rgba(C.cold, 0.45), 1);
    // the drawn body
    g.shadowColor = C.hazard; g.shadowBlur = 8;
    curve(g, (t) => [px(t, Wc), py(pitchAt(v, t / 1000), Hc)], P.tMax, C.hazard, 2.2);
    g.shadowBlur = 0;
    const end = v['ks.pitchEnd'];
    g.setLineDash([3, 3]); g.strokeStyle = rgba(C.lcd, 0.5); g.lineWidth = 1;
    g.beginPath(); g.moveTo(P.L, py(end, Hc)); g.lineTo(Wc - P.R, py(end, Hc)); g.stroke(); g.setLineDash([]);
    playheadLine(g, playhead(), (t) => px(t, Wc), P, Hc);
    drawNodes(g, pitch, Wc, Hc);
    g.fillStyle = C.text3; g.font = `600 8.5px ${MONO}`; g.textAlign = 'left';
    g.fillText('Hz', 4, P.T + 6);
    g.fillStyle = C.acid; g.textAlign = 'left'; g.fillText('● HW002 KICK, MEASURED', P.L + 6, P.T + 9);
    pitchRead.textContent = `${Math.round(v['ks.pitchStart'])} Hz  →  ${Math.round(end)} Hz ${noteName(end)}   ·   falls in ${Math.round(v['ks.pitchDecay'])} ms`;
  };
  const markPitch = painter.add(pitch.el, drawPitch, { always: true });
  pitch.setRedraw(markPitch);

  // ---- level ----
  const A = { L: 40, R: 10, T: 14, B: 18, tMax: 600, yMax: 1.25 };
  const ax = (t, W) => A.L + (t / A.tMax) * (W - A.L - A.R);
  const ay = (a, H) => A.T + (1 - a / A.yMax) * (H - A.T - A.B);
  const clickA = () => Math.max(0, Math.min(1.2, (v['ks.click'] + 48) / 54 * 1.2));
  const CLX = 16;                                         // the click's own lane, left of the time axis
  const amp = nodeCanvas(ctx, {
    cls: 'kx-env is-amp',
    label: 'Level envelope',
    nodes: [
      {
        key: 'click', ids: ['ks.click'], label: 'Click level',
        pos: (_W, H) => [CLX, ay(clickA(), H)],
        move: (_dx, dy, { H, w }) => setReal(ctx, w, 'ks.click', v['ks.click'] - (dy / (H - A.T - A.B)) * A.yMax * (54 / 1.2)),
      },
      {
        key: 'hold', ids: ['ks.ampHold'], label: 'Body hold',
        pos: (W, H) => [ax(v['ks.ampHold'], W), ay(1, H)],
        move: (dx, _dy, { W, w }) => setReal(ctx, w, 'ks.ampHold', v['ks.ampHold'] + (dx / (W - A.L - A.R)) * A.tMax),
      },
      {
        key: 'curve', ids: ['ks.ampCurve'], label: 'Decay curve',
        pos: (W, H) => { const t = v['ks.ampHold'] + v['ks.ampDecay'] / 2; return [ax(Math.min(t, A.tMax), W), ay(Math.pow(0.5, ampExp(v)), H)]; },
        move: (_dx, dy, { H, w }) => setReal(ctx, w, 'ks.ampCurve', v['ks.ampCurve'] + (dy / (H - A.T - A.B)) * 140),
      },
      {
        key: 'decay', ids: ['ks.ampDecay'], label: 'Body decay',
        pos: (W, H) => [Math.min(W - A.R, ax(v['ks.ampHold'] + v['ks.ampDecay'], W)), ay(0, H)],
        move: (dx, _dy, { W, w }) => setReal(ctx, w, 'ks.ampDecay', Math.max(10, v['ks.ampDecay'] + (dx / (W - A.L - A.R)) * A.tMax)),
      },
    ],
  });
  const ampRead = h('div', { class: 'kx-env-read' });
  const drawAmp = () => {
    const { g, k, w: Wc, h: Hc } = amp.cv.fit();
    g.scale(k, k);
    g.fillStyle = '#060707'; g.fillRect(0, 0, Wc, Hc);
    grid(g, Wc, Hc, A, ax, (t) => `${t}`, [0, 100, 200, 300, 400, 500]);
    // the offbeat and the next kick
    const mark = (t, text, color) => {
      const x = ax(t, Wc);
      g.fillStyle = rgba(color, 0.5); g.fillRect(x, A.T, 1, Hc - A.T - A.B);
      g.font = `600 8px ${MONO}`; g.fillStyle = color; g.textAlign = 'center'; g.fillText(text, x, A.T - 3);
    };
    mark(BEAT * 500, 'OFF', C.text3);
    mark(BEAT * 1000, 'NEXT KICK', C.text2);
    g.fillStyle = 'rgba(255,255,255,0.06)'; g.fillRect(A.L, ay(1, Hc), Wc - A.L - A.R, 1);
    // the offbeat pad's knock, when it plays
    if (v['ks.offbeatOn'] > 0.5) {
      area(g, (t) => [ax(BEAT * 500 + t, Wc), ay(ampBase(v, t / 1000, LAYER.off) * 0.55, Hc)], 160, rgba(C.cold, 0.25), rgba(C.cold, 0.6), ay(0, Hc));
    }
    // shaped (with the transient shaper) as a filled area, the drawn envelope as a line
    area(g, (t) => [ax(t, Wc), ay(Math.min(A.yMax, ampBase(v, t / 1000) * shaperGain(v, t / 1000)), Hc)], A.tMax, rgba(C.hazard, 0.28), null, ay(0, Hc));
    g.shadowColor = C.hazard; g.shadowBlur = 8;
    curve(g, (t) => [ax(t, Wc), ay(ampBase(v, t / 1000), Hc)], A.tMax, C.hazard, 2.2);
    g.shadowBlur = 0;
    // the click, in its own lane
    g.fillStyle = 'rgba(255,255,255,0.03)'; g.fillRect(4, A.T, CLX * 2 - 8, Hc - A.T - A.B);
    g.strokeStyle = C.lcd; g.lineWidth = 3; g.shadowColor = C.lcd; g.shadowBlur = 6;
    g.beginPath(); g.moveTo(CLX, ay(0, Hc)); g.lineTo(CLX, ay(clickA(), Hc)); g.stroke(); g.shadowBlur = 0;
    g.font = `600 8px ${MONO}`; g.fillStyle = C.lcd; g.textAlign = 'center'; g.fillText('CLK', CLX, Hc - 5);
    playheadLine(g, playhead(), (t) => ax(t, Wc), A, Hc);
    drawNodes(g, amp, Wc, Hc);
    ampRead.textContent = `hold ${Math.round(v['ks.ampHold'])} ms · decay ${Math.round(v['ks.ampDecay'])} ms · curve ${Math.round(v['ks.ampCurve'])}%`;
  };
  const markAmp = painter.add(amp.el, drawAmp, { always: true });
  amp.setRedraw(markAmp);

  const n = (id, label) => numbox(ctx, id, { label });
  return panel('Envelopes', { sub: 'the synth\'s body: drag the curves', cls: 'kx-envs' },
    h('div', { class: 'kx-env-head' }, h('b', { text: 'PITCH' }), pitchRead),
    pitch.el,
    h('div', { class: 'kx-nums' }, n('ks.pitchStart', 'Start'), n('ks.pitchEnd', 'End'), n('ks.pitchDecay', 'Fall')),
    h('div', { class: 'kx-env-head' }, h('b', { text: 'LEVEL' }), ampRead),
    amp.el,
    h('div', { class: 'kx-nums' }, n('ks.ampHold', 'Hold'), n('ks.ampDecay', 'Decay'), n('ks.ampCurve', 'Curve'), n('ks.click', 'Click'), n('ks.clickTone', 'Click Hz')),
    h('p', { class: 'rack-note', text: 'The synth plays these on every beat when the source is Synth or Both; tap a layer pad to hear one now. Acid dots: HW002\'s own kick, measured from the stem.' }));
}

// ---- drawing helpers ----------------------------------------------------------------------------------------------
function grid(g, W, H, P, x, label, ticks) {
  g.font = `600 8.5px ${MONO}`; g.textAlign = 'center';
  for (const t of ticks) {
    const xx = x(t, W);
    g.fillStyle = 'rgba(255,255,255,0.05)'; g.fillRect(xx, P.T, 1, H - P.T - P.B);
    g.fillStyle = C.text3; g.fillText(label(t), xx, H - 5);
  }
}

function curve(g, at, tMax, color, width) {
  g.beginPath();
  for (let i = 0; i <= 200; i++) { const [x, y] = at((i / 200) * tMax); if (i === 0) g.moveTo(x, y); else g.lineTo(x, y); }
  g.strokeStyle = color; g.lineWidth = width; g.lineJoin = 'round'; g.stroke();
}

function area(g, at, tMax, fill, stroke, baseY) {
  g.beginPath();
  const [x0] = at(0);
  let lastX = x0;
  g.moveTo(x0, baseY);
  for (let i = 0; i <= 200; i++) { const [x, y] = at((i / 200) * tMax); g.lineTo(x, Math.min(baseY, y)); lastX = x; }
  g.lineTo(lastX, baseY);
  g.closePath();
  g.fillStyle = fill; g.fill();
  if (stroke) { g.strokeStyle = stroke; g.lineWidth = 1; g.stroke(); }
}

function playheadLine(g, since, x, P, H) {
  if (!Number.isFinite(since) || since > 0.62) return;
  const xx = x(since * 1000);
  g.fillStyle = rgba(C.text, 0.6);
  g.fillRect(xx, P.T, 1.2, H - P.T - P.B);
}

export function drawNodes(g, nc, W, H) {
  for (const n of nc.nodes) {
    if (n.hidden?.()) continue;
    const [x, y] = n.pos(W, H);
    const active = nc.state.active?.key === n.key, sel = nc.state.selected === n.key;
    g.beginPath(); g.arc(x, y, active ? 11 : 8, 0, Math.PI * 2);
    g.fillStyle = active ? C.hazard : '#1b1d21';
    g.fill();
    g.lineWidth = 2; g.strokeStyle = active || sel ? C.hazard : C.text2; g.stroke();
    g.beginPath(); g.arc(x, y, 2.5, 0, Math.PI * 2); g.fillStyle = active ? '#120400' : C.text; g.fill();
  }
}
