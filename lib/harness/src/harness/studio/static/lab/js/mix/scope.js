// Low end: is it mono? A goniometer of the master (mid up, side across; a mono signal is a vertical line) with the
// band below 120 Hz drawn hot over the full band in phosphor, and the meters the references were measured with:
// correlation below 120 Hz (refs 0.99-1.00, HW002 0.88) and side against mid below 120 Hz (refs -22 to -45 dB,
// HW002 -12). The mono controls under it are the set's: the Main's bass mono and its frequency, the rumble's.

import { h } from '../ui.js';
import { fader, toggle } from '../widgets/fader.js';
import { REF } from './refs.js';
import { canvas, fit, rgba } from './util.js';

export function lowEnd(rt) {
  const { ctx, C, loop } = rt;
  const { engine } = ctx;
  const scope = canvas('mx-scope', loop);
  const meters = canvas('mx-corr', loop);
  const bufL = new Float32Array(2048), bufR = new Float32Array(2048);
  const lowL = new Float32Array(4096), lowR = new Float32Array(4096);
  let gainFull = 2, gainLow = 3;
  const shown = { corr: null, corrS: null, sm: null, full: null };

  const drawScope = () => {
    const { g, w, h: hh } = fit(loop, scope);
    if (!w) return;
    const cx = w / 2, cy = hh / 2, R = Math.min(w, hh) / 2 - 8;
    // phosphor: fade what was there
    g.globalCompositeOperation = 'source-over';
    g.fillStyle = 'rgba(6,7,8,0.34)';
    g.fillRect(0, 0, w, hh);
    // graticule
    g.strokeStyle = 'rgba(255,255,255,0.08)'; g.lineWidth = 1;
    g.beginPath(); g.arc(cx, cy, R, 0, Math.PI * 2); g.stroke();
    g.beginPath(); g.arc(cx, cy, R / 2, 0, Math.PI * 2); g.stroke();
    g.beginPath();
    g.moveTo(cx, cy - R); g.lineTo(cx, cy + R); g.moveTo(cx - R, cy); g.lineTo(cx + R, cy);
    const d = R * Math.SQRT1_2;
    g.moveTo(cx - d, cy - d); g.lineTo(cx + d, cy + d); g.moveTo(cx + d, cy - d); g.lineTo(cx - d, cy + d);
    g.stroke();
    g.fillStyle = C.text3; g.font = '700 9px ui-monospace, Menlo, monospace'; g.textAlign = 'center';
    g.fillText('M', cx, cy - R + 10); g.fillText('S', cx - R + 7, cy - 4); g.fillText('S', cx + R - 7, cy - 4);
    g.fillText('L', cx - d + 6, cy - d + 2); g.fillText('R', cx + d - 6, cy - d + 2);
    const t = rt.taps;
    if (!t || !engine.playing) return;
    t.scL.getFloatTimeDomainData(bufL); t.scR.getFloatTimeDomainData(bufR);
    t.lowL.getFloatTimeDomainData(lowL); t.lowR.getFloatTimeDomainData(lowR);
    // auto-gain: the loudest point reaches ~85% of the radius
    let pk = 1e-4, pkL = 1e-4;
    for (let i = 0; i < bufL.length; i++) { const a = Math.abs(bufL[i]) + Math.abs(bufR[i]); if (a > pk) pk = a; }
    for (let i = 0; i < lowL.length; i += 4) { const a = Math.abs(lowL[i]) + Math.abs(lowR[i]); if (a > pkL) pkL = a; }
    gainFull += ((0.85 / (pk * Math.SQRT1_2)) - gainFull) * (0.85 / (pk * Math.SQRT1_2) < gainFull ? 0.5 : 0.04);
    gainLow += ((0.85 / (pkL * Math.SQRT1_2)) - gainLow) * (0.85 / (pkL * Math.SQRT1_2) < gainLow ? 0.5 : 0.04);
    g.globalCompositeOperation = 'lighter';
    const trace = (L, Rr, step, k, col, width, alpha) => {
      g.beginPath();
      for (let i = 0; i < L.length; i += step) {
        const m = (L[i] + Rr[i]) * Math.SQRT1_2 * k, s = (L[i] - Rr[i]) * Math.SQRT1_2 * k;
        const x = cx + s * R, y = cy - m * R;
        if (i) g.lineTo(x, y); else g.moveTo(x, y);
      }
      g.strokeStyle = rgba(col, alpha); g.lineWidth = width; g.stroke();
    };
    trace(bufL, bufR, 1, Math.min(gainFull, 40), C.cold, 1, 0.22);
    trace(lowL, lowR, 4, Math.min(gainLow, 60), C.hazard, 2, 0.5);
    g.globalCompositeOperation = 'source-over';
  };

  const drawMeters = () => {
    const { g, w, h: hh } = fit(loop, meters);
    if (!w) return;
    g.clearRect(0, 0, w, hh);
    const m = rt.meter;
    const lowOk = m && m.lowLevel > -60 && engine.playing;
    const ease = (k, v, a = 0.2) => { if (v == null) return; shown[k] = shown[k] == null ? v : shown[k] + (v - shown[k]) * a; };
    if (lowOk) { ease('corr', m.corrLow, 0.25); ease('corrS', m.corrLowS, 0.15); ease('sm', m.smLow, 0.15); }
    if (m && engine.playing) ease('full', m.corrFull, 0.2);
    const bar = (y, label, val, lo, hi, zone, setV, unit, digits) => {
      const L = 0, W = w;
      const x = (v) => L + (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo) * W;
      g.font = '700 8.5px ui-monospace, Menlo, monospace'; g.textAlign = 'left'; g.textBaseline = 'alphabetic';
      g.fillStyle = C.text2; g.fillText(label, L, y - 4);
      g.textAlign = 'right'; g.font = '600 13px ui-monospace, Menlo, monospace';
      const inRef = val != null && zone && val >= zone[0] && val <= zone[1];
      g.fillStyle = val == null ? C.text3 : inRef ? C.cold : C.lcd;
      g.fillText(val == null ? '—' : `${val.toFixed(digits)}${unit}`, W, y - 3);
      g.fillStyle = '#050505'; g.fillRect(L, y, W, 12);
      if (zone) { g.fillStyle = rgba(C.cold, 0.3); g.fillRect(x(zone[0]), y, Math.max(2, x(zone[1]) - x(zone[0])), 12); }
      if (val != null) {
        const x0 = x(Math.max(lo, Math.min(hi, 0))), xv = x(val);
        g.fillStyle = rgba(C.lcd, 0.8);
        g.fillRect(Math.min(x0, xv), y + 3, Math.abs(xv - x0), 6);
        g.fillStyle = C.text; g.fillRect(xv - 1, y - 1, 2, 14);
      }
      g.font = '600 7.5px ui-monospace, Menlo, monospace'; g.fillStyle = C.text3; g.textAlign = 'left';
      g.fillText(String(lo), L, y + 22); g.textAlign = 'right'; g.fillText(String(hi), W, y + 22);
      if (setV != null) {
        g.fillStyle = C.acid; g.fillRect(x(setV) - 1, y - 3, 2, 18);
        g.textAlign = 'center'; g.fillStyle = rgba(C.acid, 0.9); g.fillText('SET', x(setV), y + 22);
      }
    };
    bar(18, 'CORR <120 Hz', lowOk ? shown.corrS : null, 0.6, 1, [REF.corrLow.min, REF.corrLow.max], REF.corrLow.set, '', 3);
    bar(62, 'SIDE - MID <120', lowOk ? shown.sm : null, -50, 0, [REF.sideMidLow.min, REF.sideMidLow.max], REF.sideMidLow.set, ' dB', 1);
    bar(106, 'CORR ALL BANDS', engine.playing ? shown.full : null, -1, 1, null, null, '', 2);
    g.textAlign = 'left';
  };

  loop.add({ el: scope, draw: drawScope });
  loop.add({ el: meters, draw: drawMeters });

  const el = h('section', { class: 'rack mx-low' },
    h('div', { class: 'rack-head' }, h('span', { class: 'rack-title', text: 'Low end' }), h('span', { class: 'rack-sub', text: 'mono below 120 Hz, like every reference' })),
    h('div', { class: 'mx-low-row' },
      h('div', { class: 'mx-scope-box' }, scope, h('span', { class: 'mx-scope-key' }, h('i', { class: 'is-hot' }), 'below 120 Hz', h('i', { class: 'is-cold' }), 'all')),
      h('div', { class: 'mx-corr-box' }, meters, h('p', { class: 'mx-corr-note', text: 'Blue: the references. Acid: the set, measured. A line straight up is mono.' }))),
    h('div', { class: 'mx-low-controls' },
      toggle(ctx, 'mix.bassMono', { label: 'Main bass mono' }),
      toggle(ctx, 'rumble.mono', { label: 'Rumble mono' })),
    fader(ctx, 'mix.monoFreq', { horizontal: true, length: 300, label: 'Mono below' }),
    h('p', { class: 'rack-note', text: 'The Main\'s bass mono (Utility) folds everything under its frequency to mono; the climb liked 169 Hz. The rumble\'s own bass mono does it before the kick group.' }));
  return { el };
}
