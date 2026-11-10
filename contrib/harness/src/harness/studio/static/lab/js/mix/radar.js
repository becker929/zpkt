// Loudness: the full meter, as a radar. One turn is one pass of the 24 bars the lab loops, so each bar of the
// Short keeps its place on the dial: the radius is the short-term loudness (3 s) there, the ring of dots the
// momentary (400 ms). The master target (-14 to -11 LUFS) and the references (-7.2 to -4.3 integrated) are rings.
// In the middle: integrated loudness since the last reset. BS.1770-4 throughout (js/mix/loudness-worklet.js).

import { h, haptic, toast } from '../ui.js';
import { REF, TRACKS } from './refs.js';
import { canvas, fit, fmt, rgba } from './util.js';

const N = 240, LO = -36, HI = 0;

export function loudness(rt) {
  const { ctx, C, loop } = rt;
  const { engine } = ctx;
  const cv = canvas('mx-loud', loop);
  const S = new Float32Array(N).fill(NaN), M = new Float32Array(N).fill(NaN);
  const loopBars = () => engine.stems.sequence?.length || 24;      // one turn: one pass of what the stems loop
  const cell = (label) => { const b = h('b', { text: '—' }); return { el: h('div', { class: 'mx-lcell' }, h('span', { text: label }), b), b }; };
  const cells = { m: cell('Momentary'), s: cell('Short-term'), i: cell('Integrated'), lra: cell('LRA'), tp: cell('True peak max'), plr: cell('PLR'), psr: cell('PSR'), sp: cell('Sample peak') };

  rt.meterFns.add((msg) => {
    if (engine.playing) {
      const B = loopBars();
      const pos = (((msg.t - 0.05 - engine.t0) / engine.barSeconds) % B + B) % B;
      const k = Math.floor(pos / B * N) % N;
      if (msg.s > -70) S[k] = msg.s;
      if (msg.m > -70) M[k] = msg.m;
    }
    const put = (c, v, unit = '', d = 1) => { c.b.textContent = v == null || v <= -70 ? '—' : `${fmt(v, d)}${unit}`; };
    put(cells.m, msg.m); put(cells.s, msg.s); put(cells.i, msg.i);
    cells.lra.b.textContent = msg.lra > 0 ? `${fmt(msg.lra)} LU` : '—';
    put(cells.tp, msg.tpMax > -100 ? msg.tpMax : null, ' dBTP');
    put(cells.plr, msg.plr, ' LU'); put(cells.psr, msg.psr, ' LU'); put(cells.sp, msg.sp > -100 ? msg.sp : null, ' dB');
    cells.tp.el.dataset.state = msg.tpMax > REF.master.tp ? 'over' : '';
    cells.i.el.dataset.state = msg.i > -70 && msg.i >= REF.master.min && msg.i <= REF.master.max ? 'ok' : '';
  });

  const draw = () => {
    const { g, w, h: hh } = fit(loop, cv);
    if (!w) return;
    const cx = w / 2, cy = hh / 2, R = Math.min(w, hh) / 2 - 18, r0 = R * 0.34;
    const r = (db) => r0 + (Math.max(LO, Math.min(HI, db)) - LO) / (HI - LO) * (R - r0);
    const ang = (k) => -Math.PI / 2 + k / N * Math.PI * 2;
    g.clearRect(0, 0, w, hh);
    // the dial
    g.fillStyle = '#060607'; g.beginPath(); g.arc(cx, cy, R + 4, 0, Math.PI * 2); g.fill();
    const ring = (a, b, col) => { g.beginPath(); g.arc(cx, cy, r(b), 0, Math.PI * 2); g.arc(cx, cy, r(a), 0, Math.PI * 2, true); g.fillStyle = col; g.fill(); };
    ring(REF.master.min, REF.master.max, 'rgba(233,231,226,0.08)');
    ring(REF.refsLufs.min, REF.refsLufs.max, rgba(C.cold, 0.16));
    g.strokeStyle = 'rgba(255,255,255,0.07)'; g.lineWidth = 1;
    for (let db = LO; db <= HI; db += 6) { g.beginPath(); g.arc(cx, cy, r(db), 0, Math.PI * 2); g.stroke(); }
    // bar ticks
    const BARS = loopBars();
    g.font = '600 8px ui-monospace, Menlo, monospace'; g.textAlign = 'center'; g.textBaseline = 'middle';
    for (let b = 0; b < BARS; b++) {
      const a = -Math.PI / 2 + b / BARS * Math.PI * 2;
      const long = b % 4 === 0;
      g.strokeStyle = long ? 'rgba(255,255,255,0.3)' : 'rgba(255,255,255,0.12)';
      g.beginPath(); g.moveTo(cx + Math.cos(a) * (R + 1), cy + Math.sin(a) * (R + 1)); g.lineTo(cx + Math.cos(a) * (R + (long ? 7 : 4)), cy + Math.sin(a) * (R + (long ? 7 : 4))); g.stroke();
      if (long && BARS > 1) { g.fillStyle = C.text3; g.fillText(String(b + 1), cx + Math.cos(a) * (R + 13), cy + Math.sin(a) * (R + 13)); }
    }
    // the sweep
    const pos = engine.position();
    const k0 = pos.playing ? ((pos.t % BARS) / BARS) * N : -1;
    // history: short-term wedges, momentary dots; older sectors fade with distance behind the sweep
    for (let k = 0; k < N; k++) {
      if (Number.isNaN(S[k])) continue;
      const behind = k0 < 0 ? 0.5 : ((k0 - k + N) % N) / N;
      const a0 = ang(k), a1 = ang(k + 1) + 0.004;
      const s = S[k];
      const col = s > REF.master.max ? C.lcd : s >= REF.master.min ? C.acid : rgba(C.acid, 0.7);
      g.beginPath(); g.arc(cx, cy, r(s), a0, a1); g.arc(cx, cy, r0, a1, a0, true); g.closePath();
      g.globalAlpha = 0.25 + 0.65 * (1 - behind);
      g.fillStyle = s > -6 ? C.alarm : col;
      g.fill();
      if (!Number.isNaN(M[k])) {
        const am = (a0 + a1) / 2;
        g.fillStyle = C.text;
        g.fillRect(cx + Math.cos(am) * r(M[k]) - 0.8, cy + Math.sin(am) * r(M[k]) - 0.8, 1.6, 1.6);
      }
    }
    g.globalAlpha = 1;
    if (k0 >= 0) {
      const a = ang(k0);
      if (g.createConicGradient) {
        const cg = g.createConicGradient(a - Math.PI * 0.5, cx, cy);
        cg.addColorStop(0, 'rgba(255,181,71,0)'); cg.addColorStop(0.25, 'rgba(255,181,71,0.16)'); cg.addColorStop(0.2501, 'rgba(0,0,0,0)');
        g.fillStyle = cg;
        g.beginPath(); g.arc(cx, cy, R, 0, Math.PI * 2); g.arc(cx, cy, r0, 0, Math.PI * 2, true); g.fill();
      }
      g.strokeStyle = C.lcd; g.lineWidth = 1.5; g.shadowColor = C.lcd; g.shadowBlur = 8;
      g.beginPath(); g.moveTo(cx + Math.cos(a) * r0, cy + Math.sin(a) * r0); g.lineTo(cx + Math.cos(a) * R, cy + Math.sin(a) * R); g.stroke();
      g.shadowBlur = 0;
    }
    // the hub
    g.fillStyle = '#0d0e10'; g.beginPath(); g.arc(cx, cy, r0 - 4, 0, Math.PI * 2); g.fill();
    g.strokeStyle = 'rgba(255,255,255,0.1)'; g.stroke();
    const m = rt.meter;
    const I = m && m.i > -70 ? m.i : null;
    g.fillStyle = I == null ? C.text3 : I >= REF.master.min && I <= REF.master.max ? C.cold : C.lcd;
    g.font = '600 24px ui-monospace, Menlo, monospace';
    g.shadowColor = g.fillStyle; g.shadowBlur = 10;
    g.fillText(I == null ? '—' : I.toFixed(1), cx, cy - 3);
    g.shadowBlur = 0;
    g.font = '700 8px ui-monospace, Menlo, monospace'; g.fillStyle = C.text3;
    g.fillText('LUFS INTEGRATED', cx, cy + 17);
    // ring labels
    g.textAlign = 'left'; g.font = '700 7.5px ui-monospace, Menlo, monospace';
    g.fillStyle = 'rgba(233,231,226,0.7)'; g.fillText('TARGET', cx + 4, cy - r((REF.master.min + REF.master.max) / 2));
    g.fillStyle = C.cold; g.fillText('REFS', cx + 4, cy - r((REF.refsLufs.min + REF.refsLufs.max) / 2));
  };
  loop.add({ el: cv, draw });

  const reset = () => {
    rt.taps?.reset(); S.fill(NaN); M.fill(NaN); haptic(true); toast('Integrated, LRA and peaks: from now');
  };
  const el = h('section', { class: 'rack mx-loudness' },
    h('div', { class: 'rack-head' }, h('span', { class: 'rack-title', text: 'Loudness' }), h('span', { class: 'rack-sub', text: 'one turn: one pass of the loop' })),
    h('div', { class: 'mx-loud-box' }, cv),
    h('div', { class: 'mx-lcells' }, ...Object.values(cells).map((c) => c.el)),
    h('div', { class: 'mx-asp-acts' }, h('button', { type: 'button', class: 'mx-chip', text: 'Reset integrated', onclick: reset })),
    h('div', { class: 'mx-refs' },
      ...TRACKS.map((t) => h('div', {}, h('span', { text: t.name }), h('b', { text: `${fmt(t.lufs)} LUFS` }), h('i', { text: `PLR ${fmt(t.plr)}` }))),
      h('div', { class: 'is-set' }, h('span', { text: 'HW002, unmastered' }), h('b', { text: `${fmt(REF.setLufs)} LUFS` }), h('i', { text: 'PLR 14.1' })),
      h('div', { class: 'is-target' }, h('span', { text: 'Master target' }), h('b', { text: '-14 to -11' }), h('i', { text: '≤ -1.5 dBTP' }))),
    h('p', { class: 'rack-note', text: 'On a Short a louder master does not play louder: YouTube turns everything to about -14 LUFS, so the references lose 7-10 dB. Density and tone carry the impact; loudness is a decision for the master.' }));
  return { el };
}
