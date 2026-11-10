// The rumble as its own rack: the Shifter's pitch, the 31 Hz sub shelf, the 5 kHz shelf, bass mono, width, level;
// the synth's own tail and low-pass; LFOTool's duck drawn over one beat (drag it down for a deeper dip), with the
// beat's playhead; and the low end's correlation, live, against the references (HW002 0.88, theirs 0.99-1.00).

import { h, haptic, toast } from '../ui.js';
import { toNorm } from '../params.js';
import { knob } from '../widgets/knob.js';
import { toggle } from '../widgets/fader.js';
import { BEAT, duckShape } from './dsp.js';
import { drawNodes } from './env.js';
import { nodeCanvas } from './nodes.js';
import { C, MONO, canvas, panel, rgba } from './util.js';

export function rumbleRack(ctx, rig, painter) {
  const { store, params, engine } = ctx;
  const M = { L: 8, R: 8, T: 14, B: 16 };
  const X = (u, W) => M.L + u * (W - M.L - M.R);
  const Y = (g, H) => M.T + (1 - g) * (H - M.T - M.B);
  const nc = nodeCanvas(ctx, {
    cls: 'kx-duck', label: 'Rumble duck',
    nodes: [{
      key: 'duck', ids: ['ks.duck'], label: 'Rumble duck',
      pos: (W, H) => [X(0.06, W), Y(1 - store.real('ks.duck') / 100, H)],
      move: (_dx, dy, { H, w }) => w('ks.duck').set(toNorm(params.get('ks.duck'), store.real('ks.duck') + (dy / (H - M.T - M.B)) * 100)),
    }],
  });
  const draw = () => {
    const { g, k, w: W, h: H } = nc.cv.fit();
    g.scale(k, k);
    g.fillStyle = '#060707'; g.fillRect(0, 0, W, H);
    g.font = `600 8.5px ${MONO}`; g.textAlign = 'center';
    for (const [u, t] of [[0, 'KICK'], [0.25, ''], [0.5, 'OFF'], [0.75, ''], [1, 'KICK']]) {
      g.fillStyle = 'rgba(255,255,255,0.06)'; g.fillRect(X(u, W), M.T, 1, H - M.T - M.B);
      g.fillStyle = C.text3; g.fillText(t, Math.min(W - 16, Math.max(16, X(u, W))), H - 4);
    }
    const shape = duckShape(store.real('ks.duck') / 100, 128);
    g.beginPath(); g.moveTo(X(0, W), Y(0, H));
    shape.forEach((v, i) => g.lineTo(X(i / 127, W), Y(v, H)));
    g.lineTo(X(1, W), Y(0, H)); g.closePath();
    const grd = g.createLinearGradient(0, M.T, 0, H); grd.addColorStop(0, rgba(C.cold, 0.45)); grd.addColorStop(1, rgba(C.cold, 0.03));
    g.fillStyle = grd; g.fill();
    g.beginPath(); shape.forEach((v, i) => (i ? g.lineTo(X(i / 127, W), Y(v, H)) : g.moveTo(X(0, W), Y(v, H))));
    g.strokeStyle = C.cold; g.lineWidth = 2; g.shadowColor = C.cold; g.shadowBlur = 6; g.stroke(); g.shadowBlur = 0;
    const since = rig.sinceKick();
    if (engine.playing && Number.isFinite(since)) {
      const u = (since % BEAT) / BEAT;
      g.fillStyle = rgba(C.text, 0.7); g.fillRect(X(u, W), M.T, 1.2, H - M.T - M.B);
    }
    g.fillStyle = C.cold; g.textAlign = 'right'; g.fillText(`LFOTOOL · DUCK ${Math.round(store.real('ks.duck'))}%`, W - M.R, M.T - 3);
    drawNodes(g, nc, W, H);
  };
  const mark = painter.add(nc.el, draw, { always: true });
  nc.setRedraw(mark);

  // correlation under 120 Hz
  const cv = canvas('kx-corr-cv');
  const corrRead = h('b', { class: 'kx-corr-v', text: '--' });
  let smooth = null;
  painter.add(cv, () => {
    const { g, k, w: W, h: H } = cv.fit();
    g.scale(k, k);
    g.clearRect(0, 0, W, H);
    const lo = 0.6, x = (c) => ((Math.max(lo, Math.min(1, c)) - lo) / (1 - lo)) * W;
    g.fillStyle = '#040404'; g.fillRect(0, H / 2 - 5, W, 10);
    g.fillStyle = rgba(C.acid, 0.25); g.fillRect(x(0.99), 2, x(1) - x(0.99), H - 4);
    g.fillStyle = C.acid; g.font = `600 8px ${MONO}`; g.textAlign = 'right'; g.fillText('REFS', W - 2, 9);
    g.fillStyle = C.alarm; g.fillRect(x(0.88) - 1, 2, 2, H - 4);
    g.textAlign = 'center'; g.fillText('HW002 0.88', x(0.88), H - 1);
    for (const c of [0.6, 0.7, 0.8, 0.9, 1]) { g.fillStyle = C.steel4; g.fillRect(x(c), H / 2 - 7, 1, 3); }
    const c = rig.lowCorrelation();
    if (c != null && engine.playing) smooth = smooth == null ? c : smooth + (c - smooth) * 0.08;
    if (smooth != null) {
      g.fillStyle = smooth > 0.985 ? C.acid : C.lcd; g.shadowColor = g.fillStyle; g.shadowBlur = 8;
      g.fillRect(x(smooth) - 2, H / 2 - 8, 4, 16); g.shadowBlur = 0;
      corrRead.textContent = smooth.toFixed(3);
    }
  }, { always: true });

  // hold to hear the rumble alone: its knobs are quiet under the kick
  const solo = h('div', { class: 'kx-solo', role: 'button', tabindex: '0', 'aria-label': 'Hold to hear the rumble alone' },
    h('i', { class: 'kx-src-led' }), h('b', { text: 'HOLD · RUMBLE ALONE' }), h('span', { text: 'the kick and the stem drop out while you hold' }));
  solo.style.touchAction = 'none';
  let sid = null;
  solo.addEventListener('pointerdown', (e) => {
    sid = e.pointerId;
    try { solo.setPointerCapture(e.pointerId); } catch { /* synthetic */ }
    if (!engine.playing) toast('Press play: the rumble plays on the beat');
    rig.soloRumble(true); solo.classList.add('is-on'); haptic(true);
  });
  const off = (e) => { if (e.pointerId !== sid) return; sid = null; rig.soloRumble(false); solo.classList.remove('is-on'); };
  solo.addEventListener('pointerup', off);
  solo.addEventListener('pointercancel', off);
  solo.addEventListener('contextmenu', (e) => e.preventDefault());
  ctx.own(() => { if (sid != null) rig.soloRumble?.(false); });

  const kn = (id, opts = {}) => knob(ctx, id, { size: 64, ...opts });
  return panel('Rumble', { sub: 'Shifter, Decapitator, EQ, LFOTool, Utility', cls: 'kx-rumble' },
    nc.el,
    solo,
    h('div', { class: 'rack-body is-row kx-knobrow' },
      kn('rumble.level'), kn('rumble.sub'), kn('rumble.pitch'), kn('rumble.width'), kn('rumble.air'), kn('ks.tail'), kn('ks.rumbleTone')),
    h('div', { class: 'kx-corr' },
      h('div', { class: 'kx-corr-head' }, h('b', { text: 'LOW END MONO · UNDER 120 Hz' }), corrRead),
      cv,
      toggle(ctx, 'rumble.mono', { label: 'Bass mono', wide: true })),
    h('p', { class: 'rack-note', text: 'The synth\'s rumble is its kick\'s tail through a dark room, low-passed, saturated by the Decapitator, ducked under each kick. Below 120 Hz HW002 is not mono (0.88; side 12 dB under mid, the references 22-45 dB): bass mono on, and watch the needle.' }));
}
