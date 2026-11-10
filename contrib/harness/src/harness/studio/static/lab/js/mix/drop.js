// Drop power: how dense the peak is. The references' 400 ms blocks have a crest (peak over RMS) of 4.4-6.6 dB,
// the set's 8.7: their density comes before the limiter, from clipping, saturation and a fuller drum bus.
//
//   the clipper's transfer curve: input level across, output up; the ball is the level going into it now
//   the crest meter: the median block crest of the last 30 s against the references
//   the Main's glue rack (off in the set), its threshold and ratio, and its gain reduction
//   the phone's master clipper and ceiling (data/extras-mix.json), and batch 5's offline finding as a preset

import { h, haptic, toast } from '../ui.js';
import { knob } from '../widgets/knob.js';
import { toggle } from '../widgets/fader.js';
import { toNorm } from '../params.js';
import { REF } from './refs.js';
import { levelOf } from './taps.js';
import { canvas, fit, fmt, rgba } from './util.js';

const PRESET = { 'mix.clipDrive': 8.9, 'kick.cmix': 36, 'kick.thresh': -15.47, 'kick.ratio': 2, 'kick.cattack': 0.5, 'kick.release': 40 };
const KNEE = 0.92;                     // the engine's soft clip starts here
const shape = (x) => { const a = Math.min(1, Math.abs(x)); return a < KNEE ? a : KNEE + (1 - KNEE) * Math.tanh((a - KNEE) / (1 - KNEE)); };

export function dropPower(rt) {
  const { ctx, C, loop } = rt;
  const { store, engine, params } = ctx;
  const curveCv = canvas('mx-xfer', loop);
  const crestCv = canvas('mx-crest', loop);
  const grCv = canvas('mx-gr', loop);
  const buf = new Float32Array(2048);
  const trail = [];
  let inPk = -60;
  const shown = { med: null, now: null };

  const drawCurve = (now) => {
    const { g, w, h: hh } = fit(loop, curveCv);
    if (!w) return;
    const drive = store.real('mix.clipDrive'), ceil = store.real('mix.ceiling');
    const pre = Math.pow(10, drive / 20), post = Math.pow(10, -drive / 40);
    const LO = -30, HI = 6, P = 20;
    const W = w - P - 6, H = hh - 6 - P;
    const x = (db) => P + (Math.max(LO, Math.min(HI, db)) - LO) / (HI - LO) * W;
    const y = (db) => 6 + (1 - (Math.max(LO, Math.min(HI, db)) - LO) / (HI - LO)) * H;
    const out = (db) => Math.min(ceil, 20 * Math.log10(post * shape(pre * Math.pow(10, db / 20)) + 1e-9));
    g.clearRect(0, 0, w, hh);
    g.fillStyle = '#050505'; g.fillRect(P, 6, W, H);
    g.font = '600 7.5px ui-monospace, Menlo, monospace';
    for (let db = LO; db <= HI; db += 6) {
      g.fillStyle = 'rgba(255,255,255,0.06)'; g.fillRect(x(db), 6, 1, H); g.fillRect(P, y(db), W, 1);
      g.fillStyle = C.text3; g.textAlign = 'right'; g.fillText(String(db), P - 3, y(db) + 3);
    }
    g.textAlign = 'center'; g.fillText('IN dBFS', P + W / 2, hh - 4);
    // unity and the ceiling
    g.strokeStyle = 'rgba(255,255,255,0.18)'; g.setLineDash([3, 3]); g.lineWidth = 1;
    g.beginPath(); g.moveTo(x(LO), y(LO)); g.lineTo(x(HI), y(HI)); g.stroke();
    g.strokeStyle = rgba(C.alarm, 0.8); g.beginPath(); g.moveTo(P, y(ceil)); g.lineTo(P + W, y(ceil)); g.stroke();
    g.setLineDash([]);
    g.fillStyle = C.alarm; g.textAlign = 'left'; g.fillText(`CEILING ${fmt(ceil)}`, P + 4, y(ceil) - 4);
    // the knee: where clipping starts
    const kneeIn = 20 * Math.log10(KNEE / pre);
    g.fillStyle = rgba(C.hazard, 0.08); g.fillRect(x(kneeIn), 6, P + W - x(kneeIn), H);
    // the curve
    g.beginPath();
    for (let px = 0; px <= W; px += 1.5) { const db = LO + px / W * (HI - LO); const yy = y(out(db)); if (px) g.lineTo(P + px, yy); else g.moveTo(P + px, yy); }
    g.strokeStyle = C.hazard; g.lineWidth = 2.4; g.shadowColor = C.hazard; g.shadowBlur = 8; g.stroke(); g.shadowBlur = 0;
    // the level going in now, with a trail
    const t = rt.taps;
    if (t && engine.playing) {
      const lv = levelOf(t.glue, buf);
      inPk = lv.peak > inPk ? lv.peak : inPk - 0.6;
      trail.push([lv.peak, now]);
    }
    while (trail.length && now - trail[0][1] > 900) trail.shift();
    for (const [db, ts] of trail) {
      const a = 1 - (now - ts) / 900;
      g.fillStyle = rgba(db > kneeIn ? C.alarm : C.lcd, 0.35 * a);
      g.beginPath(); g.arc(x(db), y(out(db)), 2.2, 0, Math.PI * 2); g.fill();
    }
    if (engine.playing && inPk > LO) {
      const into = inPk - kneeIn;
      g.beginPath(); g.arc(x(inPk), y(out(inPk)), 6, 0, Math.PI * 2);
      g.fillStyle = into > 0 ? C.alarm : C.lcd; g.shadowColor = g.fillStyle; g.shadowBlur = 12; g.fill(); g.shadowBlur = 0;
      g.fillStyle = into > 0 ? C.alarm : C.text2; g.textAlign = 'right'; g.font = '700 9px ui-monospace, Menlo, monospace';
      g.fillText(into > 0 ? `${fmt(into)} dB INTO THE CLIP` : 'CLEAN', P + W - 4, 18);
    }
    g.textAlign = 'left';
  };

  const drawCrest = () => {
    const { g, w, h: hh } = fit(loop, crestCv);
    if (!w) return;
    const m = rt.meter;
    if (m && engine.playing) {
      if (m.crestMed != null) shown.med = shown.med == null ? m.crestMed : shown.med + (m.crestMed - shown.med) * 0.2;
      if (m.crest != null) shown.now = shown.now == null ? m.crest : shown.now + (m.crest - shown.now) * 0.3;
    }
    const LO = 2, HI = 14, T = 16, B = 18, H = hh - T - B;
    const y = (db) => T + (1 - (Math.max(LO, Math.min(HI, db)) - LO) / (HI - LO)) * H;
    g.clearRect(0, 0, w, hh);
    const bx = 18, bw = 16;
    g.fillStyle = '#050505'; g.fillRect(bx, T, bw, H);
    g.fillStyle = rgba(C.cold, 0.35); g.fillRect(bx, y(REF.crest.max), bw, y(REF.crest.min) - y(REF.crest.max));
    if (shown.med != null) {
      const yy = y(shown.med);
      g.fillStyle = shown.med <= REF.crest.max ? C.cold : C.lcd;
      g.fillRect(bx + 3, yy, bw - 6, T + H - yy);
    }
    if (shown.now != null) { g.fillStyle = C.text; g.fillRect(bx - 3, y(shown.now) - 1, bw + 6, 2); }
    g.fillStyle = C.acid; g.fillRect(bx - 6, y(REF.crest.set) - 1, bw + 12, 2);
    g.font = '600 7.5px ui-monospace, Menlo, monospace'; g.textAlign = 'right';
    for (const db of [4, 6, 8, 10, 12, 14]) { g.fillStyle = C.text3; g.fillText(String(db), bx - 4, y(db) + 3); }
    g.textAlign = 'left';
    g.fillStyle = C.acid; g.fillText('SET', bx + bw + 4, y(REF.crest.set) + 3);
    g.fillStyle = C.cold; g.fillText('REFS', bx + bw + 4, y((REF.crest.min + REF.crest.max) / 2) + 3);
    g.textAlign = 'center'; g.font = '700 8px ui-monospace, Menlo, monospace'; g.fillStyle = C.text2;
    g.fillText('CREST', w / 2, 9);
    g.font = '600 12px ui-monospace, Menlo, monospace'; g.fillStyle = shown.med == null ? C.text3 : shown.med <= REF.crest.max ? C.cold : C.lcd;
    g.fillText(shown.med == null ? '—' : shown.med.toFixed(1), w / 2, hh - 4);
  };

  const gr = { glue: 0, lim: 0 };
  const drawGR = () => {
    const { g, w, h: hh } = fit(loop, grCv);
    if (!w) return;
    const m = engine.master;
    const gl = m ? m.glue.reduction : 0, li = m ? m.limiter.reduction : 0;
    const val = (v) => (typeof v === 'number' ? v : v?.value ?? 0);
    gr.glue = Math.min(gr.glue * 0.85 + val(gl) * 0.15, 0);
    gr.lim = Math.min(gr.lim * 0.85 + val(li) * 0.15, 0);
    g.clearRect(0, 0, w, hh);
    const row = (yy, label, v) => {
      const L = 46, W = w - L - 34, x = (db) => L + W - Math.min(1, -db / 12) * W;
      g.font = '700 8px ui-monospace, Menlo, monospace'; g.fillStyle = C.text2; g.textAlign = 'left';
      g.fillText(label, 0, yy + 8);
      g.fillStyle = '#050505'; g.fillRect(L, yy, W, 10);
      for (let db = 0; db >= -12; db -= 1) {
        const xx = x(db - 0.5);
        g.fillStyle = v <= db - 0.5 ? (db <= -6 ? C.alarm : C.lcd) : 'rgba(255,255,255,0.05)';
        g.fillRect(xx + 1, yy + 2, W / 12 - 2, 6);
      }
      g.textAlign = 'right'; g.fillStyle = C.lcd; g.font = '600 10px ui-monospace, Menlo, monospace';
      g.fillText(fmt(v), w, yy + 9);
    };
    row(2, 'GLUE GR', gr.glue);
    row(20, 'LIMIT GR', gr.lim);
  };

  loop.add({ el: curveCv, draw: drawCurve });
  loop.add({ el: crestCv, draw: drawCrest });
  loop.add({ el: grCv, draw: drawGR });

  const preset = h('button', {
    type: 'button', class: 'mx-preset',
    onclick: () => {
      store.begin();
      for (const [id, v] of Object.entries(PRESET)) store.set(id, toNorm(params.get(id), v), { source: 'preset' });
      store.end();
      haptic(true);
      toast('Batch 5: 8.9 dB soft clip + 36% parallel compression');
    },
  }, h('b', { text: 'Batch 5' }), h('span', { text: '8.9 dB clip + 36% parallel' }));
  const off = h('button', {
    type: 'button', class: 'mx-chip',
    text: 'Back to the set',
    onclick: () => { store.resetAll(Object.keys(PRESET)); haptic(); toast('Clip and parallel compression: the set'); },
  });

  const el = h('section', { class: 'rack mx-drop' },
    h('div', { class: 'rack-head' }, h('span', { class: 'rack-title', text: 'Drop power' }), h('span', { class: 'rack-sub', text: 'a denser peak, before the limiter' })),
    h('div', { class: 'mx-drop-row' }, h('div', { class: 'mx-xfer-box' }, curveCv), crestCv),
    grCv,
    h('div', { class: 'mx-drop-knobs' },
      knob(ctx, 'mix.clipDrive', { size: 64, label: 'Clip drive' }),
      knob(ctx, 'mix.ceiling', { size: 64, label: 'Ceiling' }),
      h('div', { class: 'mx-drop-acts' }, preset, off)),
    h('div', { class: 'mx-drop-knobs mx-glue' },
      toggle(ctx, 'mix.mainRack', { label: 'Glue rack' }),
      knob(ctx, 'mix.glueThresh', { size: 56, label: 'Glue' }),
      toggle(ctx, 'mix.glueRatio', { label: 'Ratio' })),
    h('p', { class: 'rack-note', text: 'Offline (batch 5) the win was on the drum bus: 8.9 dB of soft clip, then 36% of a 2:1 compressor at -10 dB (0.5 ms attack, 40 ms release). The preset puts the clip on the master and the parallel compression on the kick group. The Main\'s glue rack is off in the set.' }));
  return { el };
}
