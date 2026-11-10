// The meter bridge, pinned to the top of the mix surface: momentary and short-term loudness as LED ladders against
// the master target (-14 to -11 LUFS) and the references (-7.2 to -4.3), and LCD cells for integrated, true peak,
// PLR, block crest and the low end's correlation. Numbers come from the worklet ten times a second; the ladders
// glide in the frame loop. Tap: the full loudness meter further down.

import { h } from '../ui.js';
import { REF } from './refs.js';
import { canvas, fit, fmt, rgba } from './util.js';

const LO = -36, HI = 0;

export function bridge(rt, { onTap } = {}) {
  const { C, loop } = rt;
  const cv = canvas('mx-bridge-cv', loop);
  const cell = (key, label, unit) => {
    const v = h('b', { text: '—' });
    const el = h('div', { class: 'mx-cell', dataset: { key } }, h('span', { text: label }), v, unit ? h('i', { text: unit }) : null);
    return { el, v };
  };
  const cells = {
    i: cell('i', 'Integ', 'LUFS'),
    tp: cell('tp', 'True pk', 'dBTP'),
    plr: cell('plr', 'PLR', 'LU'),
    crest: cell('crest', 'Crest', 'dB'),
    low: cell('low', 'Low r', '<120'),
  };
  const el = h('div', { class: 'mx-bridge', role: 'button', 'aria-label': 'Loudness meter', onclick: () => onTap?.() },
    cv, h('div', { class: 'mx-cells' }, ...Object.values(cells).map((c) => c.el)));

  const shown = { m: -120, s: -120, mHold: -120, holdT: 0 };
  rt.meterFns.add((msg) => {
    const set = (c, text, state) => { c.v.textContent = text; c.el.dataset.state = state ?? ''; };
    set(cells.i, msg.i > -70 ? fmt(msg.i) : '—', msg.i > -70 ? (msg.i >= REF.master.min && msg.i <= REF.master.max ? 'ok' : '') : '');
    set(cells.tp, msg.tpMax > -100 ? fmt(msg.tpMax) : '—', msg.tpMax > REF.master.tp ? 'over' : 'ok');
    set(cells.plr, msg.plr != null ? fmt(msg.plr) : '—');
    const cr = msg.crestMed;
    set(cells.crest, cr != null ? fmt(cr) : '—', cr == null ? '' : cr <= REF.crest.max + 0.05 ? 'ok' : cr >= REF.crest.set - 0.5 ? 'over' : '');
    const lowOk = msg.lowLevel > -60;
    set(cells.low, lowOk && msg.corrLowS != null ? msg.corrLowS.toFixed(2) : '—', !lowOk || msg.corrLowS == null ? '' : msg.corrLowS >= REF.corrLow.min ? 'ok' : 'over');
  });

  loop.add({
    el,
    always: true,
    draw() {
      const { g, w, h: H } = fit(loop, cv);
      if (!w) return;
      const msg = rt.meter;
      const ease = (a, b, k) => a + (b - a) * k;
      shown.m = ease(shown.m, msg && msg.m > -120 ? msg.m : -120, msg && msg.m > shown.m ? 0.6 : 0.18);
      shown.s = ease(shown.s, msg && msg.s > -120 ? msg.s : -120, 0.25);
      const now = performance.now();
      if (shown.m > shown.mHold || now - shown.holdT > 1500) { shown.mHold = shown.m; shown.holdT = now; }
      const L = 22, R = w - 46;
      const x = (db) => L + (Math.max(LO, Math.min(HI, db)) - LO) / (HI - LO) * (R - L);
      g.clearRect(0, 0, w, H);
      // zones: the master target and the references
      const zone = (a, b, col, y0, y1) => { g.fillStyle = col; g.fillRect(x(a), y0, x(b) - x(a), y1 - y0); };
      zone(REF.master.min, REF.master.max, 'rgba(233,231,226,0.10)', 0, H);
      zone(REF.refsLufs.min, REF.refsLufs.max, rgba(C.cold, 0.16), 0, H);
      g.fillStyle = rgba(C.cold, 0.9);
      g.font = '600 7.5px ui-monospace, Menlo, monospace';
      g.textBaseline = 'top';
      g.fillText('REFS', x(REF.refsLufs.min) + 2, 1);
      g.fillStyle = 'rgba(233,231,226,0.7)';
      g.fillText('TARGET', x(REF.master.min) + 2, 1);
      // the set's integrated (unmastered)
      g.fillStyle = C.acid;
      g.fillRect(x(REF.setLufs) - 0.75, 9, 1.5, H - 9);
      // LED ladders: M (tall), S (short)
      const seg = 3.2, gap = 1.2;
      const ladder = (val, y, hh, hold) => {
        for (let px = L; px < R; px += seg + gap) {
          const db = LO + (px - L) / (R - L) * (HI - LO);
          const lit = db <= val;
          const col = db > -6 ? C.alarm : db > -11 ? C.lcd : C.acid;
          g.fillStyle = lit ? col : 'rgba(255,255,255,0.05)';
          g.globalAlpha = lit ? 0.95 : 1;
          g.fillRect(px, y, seg, hh);
        }
        g.globalAlpha = 1;
        if (hold != null && hold > LO) { g.fillStyle = C.text; g.fillRect(x(hold) - 1, y, 2, hh); }
      };
      ladder(shown.m, 10, 9, shown.mHold);
      ladder(shown.s, 22, 5);
      // labels and numbers
      g.font = '700 9px ui-monospace, Menlo, monospace';
      g.textBaseline = 'middle';
      g.fillStyle = C.text2;
      g.fillText('M', 4, 14.5); g.fillText('S', 4, 24.5);
      g.textAlign = 'right';
      g.fillStyle = C.lcd;
      g.font = '600 12px ui-monospace, Menlo, monospace';
      g.fillText(shown.m > LO - 10 ? shown.m.toFixed(1) : '—', w - 4, 14.5);
      g.font = '600 9.5px ui-monospace, Menlo, monospace';
      g.fillStyle = rgba(C.lcd, 0.75);
      g.fillText(shown.s > LO - 10 ? shown.s.toFixed(1) : '—', w - 4, 25.5);
      g.textAlign = 'left';
    },
  });
  return { el };
}
