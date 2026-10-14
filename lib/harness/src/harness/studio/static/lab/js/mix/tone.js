// Tone: where the mix's colour stands against the references, and the EQ curves that move it.
//
// The analyser is a 1/3-octave RTA of the master, measured the way the references were (each band relative to the
// total, both channels' power averaged, ~3 s average), drawn over the references' range (blue boxes) and HW002's
// own measurement (acid ticks). The three gap zones (deep sub, mids, air) carry their gap now; tap one and its EQ
// node lights up below. The EQ editors: one per bus, nodes you drag (up/down: gain; sideways: frequency where the
// set's band can move), the set's curve dashed, the bus's own spectrum behind.

import { doubleTap, drag, h, haptic, inspect, longPress, toast } from '../ui.js';
import { knob } from '../widgets/knob.js';
import { writer } from '../widgets/core.js';
import { format, toNorm, toReal } from '../params.js';
import { CAL, THIRDS, ZONES } from './refs.js';
import { biquadCoefs, canvas, fit, fmt, magDb, rgba, scrollable } from './util.js';

const F0 = 20, F1 = 20000;
const BUSES = [
  {
    id: 'kick', label: 'Kick bus', stem: 'kick', live: 'kick group: EQ Eight x2',
    nodes: [
      { gain: 'kick.sub30', type: 'lowshelf', f: 30, label: '30' },
      { gain: 'kick.sub35', type: 'lowshelf', f: 35, label: '35' },
      { gain: 'kick.body', type: 'peaking', f: 62.5, q: 0.82, label: '62' },
      { gain: 'kick.push', type: 'peaking', f: 330, q: 1.0, label: '330' },
      { gain: 'kick.colour', freq: 'kick.colourFreq', type: 'peaking', q: 1.2, label: 'Colour' },
      { gain: 'kick.air', type: 'highshelf', f: 5000, label: '5k' },
    ],
    more: ['kick.drive', 'kick.thresh', 'kick.cmix'],
  },
  {
    id: 'rumble', label: 'Rumble', stem: 'kick', live: 'rumble: EQ Eight (inside the kick group)',
    nodes: [
      { gain: 'rumble.sub', type: 'lowshelf', f: 31, label: '31' },
      { gain: 'rumble.air', type: 'highshelf', f: 5000, label: '5k' },
    ],
    more: ['rumble.drive', 'rumble.level', 'rumble.width'],
  },
  {
    id: 'perc', label: 'Perc 2', stem: 'perc', live: 'perc 2: EQ Eight',
    nodes: [
      { gain: 'mix.hatsBell', type: 'peaking', f: 1000, q: 1, label: '1k' },
      { gain: 'mix.hatsAir', type: 'highshelf', f: 5000, label: '5k' },
    ],
    more: ['mix.hatsDrive', 'mix.perc1Drive', 'mix.layerB'],
  },
  {
    id: 'sfx', label: 'SFX bus', stem: 'sfx', live: 'SFX group: EQ Eight',
    nodes: [{ freq: 'mix.sfxLowCut', type: 'highpass', q: 0.71, label: 'Low cut' }],
    more: ['mix.sfxThresh', 'mix.sfxDecay', 'mix.sfxVerb'],
  },
];
// which node closes which gap
const FIX = { sub: ['kick', 'kick.sub30'], mids: ['kick', 'kick.colour'], air: ['kick', 'kick.air'] };

export function tone(rt) {
  const { ctx, C, loop } = rt;
  const { store, engine, params } = ctx;
  const fx = (f, L, W) => L + (Math.log10(f) - Math.log10(F0)) / (Math.log10(F1) - Math.log10(F0)) * W;

  // =================================================================================================================
  // the RTA
  // =================================================================================================================
  const rta = canvas('mx-rta', loop);
  const bands = THIRDS.map(([c, lo, mean, hi, set], i) => ({ c, lo, mean, hi, set, cal: CAL[i] ?? 0, a: c / Math.pow(10, 0.05), b: c * Math.pow(10, 0.05), slow: 0, fast: 0, rel: null, relFast: null }));
  const zoneCards = ZONES.map((z) => {
    const now = h('b', { text: '—' });
    const setGap = mean(z.bands.map((c) => { const b = bands.find((q) => q.c === c); return b.set - b.mean; }));
    const needle = h('i', { class: 'mx-zone-needle' });
    const setTick = h('i', { class: 'mx-zone-set', style: { left: gaugePos(setGap) } });
    const el = h('button', { type: 'button', class: 'mx-zone', dataset: { zone: z.id }, onclick: () => { haptic(); selectNode(...FIX[z.id]); toast(`${z.label}: ${z.say}`); } },
      h('span', { class: 'mx-zone-name', text: z.label }),
      h('span', { class: 'mx-zone-hz', text: z.id === 'sub' ? '25-40 Hz' : z.id === 'mids' ? '1-3.2 kHz' : '8-12.5 kHz' }),
      now,
      h('div', { class: 'mx-zone-gauge' }, h('i', { class: 'mx-zone-ok' }), setTick, needle),
      h('span', { class: 'mx-zone-legend', text: `set ${fmt(setGap, 1, true)} · refs ±3` }));
    return { z, el, now, needle, setGap, gap: null };
  });
  function gaugePos(db) { return `${(Math.max(-12, Math.min(12, db)) + 12) / 24 * 100}%`; }

  // analyser state
  let binHz = 0, nBins = 0, specBuf = null, specBufR = null, fastBins = null;
  let lastT = 0, have = false;
  const measure = (now) => {
    const t = rt.taps;
    if (!t || !engine.playing) return;
    if (now - lastT < 66) return;
    const dt = lastT ? Math.min(0.5, (now - lastT) / 1000) : 0.066;
    lastT = now;
    if (!specBuf) {
      nBins = t.specL.frequencyBinCount;
      binHz = engine.ctx.sampleRate / t.specL.fftSize;
      specBuf = new Float32Array(nBins); specBufR = new Float32Array(nBins); fastBins = new Float32Array(nBins);
      for (const b of bands) { b.i0 = Math.max(1, Math.ceil(b.a / binHz)); b.i1 = Math.min(nBins, Math.ceil(b.b / binHz)); }
    }
    t.specL.getFloatFrequencyData(specBuf);
    t.specR.getFloatFrequencyData(specBufR);
    const aSlow = 1 - Math.exp(-dt / 3), aFast = 1 - Math.exp(-dt / 0.35), aBin = 1 - Math.exp(-dt / 0.2);
    for (let i = 0; i < nBins; i++) {
      const p = specBuf[i] = (Math.pow(10, specBuf[i] / 10) + Math.pow(10, specBufR[i] / 10)) * 0.5;   // now power
      fastBins[i] += (p - fastBins[i]) * aBin;
    }
    let totS = 0, totF = 0;
    for (const b of bands) {
      let p = 0;
      for (let i = b.i0; i < b.i1; i++) p += specBuf[i];
      b.slow = have ? b.slow + (p - b.slow) * aSlow : p;
      b.fast = have ? b.fast + (p - b.fast) * aFast : p;
      totS += b.slow; totF += b.fast;
    }
    have = true;
    if (totS <= 0) return;
    for (const b of bands) { b.rel = 10 * Math.log10(b.slow / totS + 1e-12) + b.cal; b.relFast = 10 * Math.log10(b.fast / totF + 1e-12) + b.cal; }
    rta.totF = totF;
    for (const zc of zoneCards) {
      const g = mean(zc.z.bands.map((c) => { const b = bands.find((q) => q.c === c); return b.rel - b.mean; }));
      zc.gap = g;
    }
  };

  let zonesT = 0;
  const drawRTA = (now) => {
    measure(now);
    const { g, w, h: hh } = fit(loop, rta);
    if (!w) return;
    const L = 26, R = 6, T = 16, B = 16, W = w - L - R, H = hh - T - B;
    const Y0 = -48, Y1 = 0;
    const y = (db) => T + (1 - (Math.max(Y0, Math.min(Y1, db)) - Y0) / (Y1 - Y0)) * H;
    const x = (f) => fx(f, L, W);
    g.clearRect(0, 0, w, hh);
    // grid
    g.font = '600 8px ui-monospace, Menlo, monospace';
    g.textBaseline = 'middle';
    for (let db = Y0; db <= Y1; db += 12) {
      g.fillStyle = 'rgba(255,255,255,0.06)'; g.fillRect(L, y(db), W, 1);
      g.fillStyle = C.text3; g.textAlign = 'right'; g.fillText(String(db), L - 4, y(db));
    }
    g.textAlign = 'center'; g.textBaseline = 'alphabetic';
    for (const [f, t] of [[50, '50'], [100, '100'], [200, '200'], [500, '500'], [1000, '1k'], [2000, '2k'], [5000, '5k'], [10000, '10k']]) {
      g.fillStyle = 'rgba(255,255,255,0.05)'; g.fillRect(x(f), T, 1, H);
      g.fillStyle = C.text3; g.fillText(t, x(f), hh - 4);
    }
    // gap zones
    for (const zc of zoneCards) {
      const z = zc.z, xa = x(z.lo), xb = x(z.hi);
      const gap = zc.gap ?? zc.setGap;
      const ok = Math.abs(gap) <= 3;
      g.fillStyle = ok ? rgba(C.cold, 0.08) : rgba(C.hazard, 0.08);
      g.fillRect(xa, T, xb - xa, H);
      g.save(); g.beginPath(); g.rect(xa, T, xb - xa, H); g.clip();
      g.strokeStyle = ok ? rgba(C.cold, 0.12) : rgba(C.hazard, 0.12); g.lineWidth = 1;
      for (let k = -H; k < xb - xa; k += 7) { g.beginPath(); g.moveTo(xa + k, T + H); g.lineTo(xa + k + H, T); g.stroke(); }
      g.restore();
      g.fillStyle = ok ? C.cold : C.hazard;
      g.font = '700 8px ui-monospace, Menlo, monospace'; g.textAlign = 'center';
      g.fillText(`${z.label.toUpperCase()} ${fmt(gap, 1, true)}`, (xa + xb) / 2, T - 5);
    }
    // bands: the refs' range (box), the set (acid tick), now (amber LED bar)
    for (let i = 0; i < bands.length; i++) {
      const b = bands[i];
      const xa = x(b.a), xb = x(b.b), bw = Math.max(3, (xb - xa) * 0.72), xc = (xa + xb) / 2;
      g.fillStyle = rgba(C.cold, 0.2); g.fillRect(xc - bw / 2 - 1, y(b.hi), bw + 2, Math.max(2, y(b.lo) - y(b.hi)));
      g.fillStyle = rgba(C.cold, 0.85); g.fillRect(xc - bw / 2 - 1, y(b.mean) - 0.75, bw + 2, 1.5);
      if (b.rel != null) {
        // an LED column: a dim body, a bright cap at the level now (amber inside the refs' +-3 dB, hazard outside)
        const top = y(b.rel), seg = 3, off = b.rel - b.mean;
        const col = Math.abs(off) <= 3 ? C.lcd : C.hazard;
        for (let yy = T + H - seg; yy >= top; yy -= seg + 1) {
          const cap = yy - top < 8;
          g.fillStyle = rgba(col, cap ? 0.95 : 0.2);
          g.fillRect(xc - bw / 2 + 1, yy, bw - 2, seg);
        }
      }
      g.fillStyle = C.acid; g.fillRect(xc - bw / 2 - 2, y(b.set) - 1, bw + 4, 2);
    }
    // the fine line (per-bin, as a 1/3-octave-equivalent level)
    if (fastBins && rta.totF > 0) {
      g.beginPath();
      let started = false;
      for (let px = 0; px <= W; px += 2) {
        const f = Math.pow(10, Math.log10(F0) + px / W * (Math.log10(F1) - Math.log10(F0)));
        const fi = f / binHz, i0 = Math.floor(fi), fr = fi - i0;
        if (i0 < 1 || i0 + 1 >= nBins) continue;
        const p = fastBins[i0] * (1 - fr) + fastBins[i0 + 1] * fr;
        const db = 10 * Math.log10(p * (0.2316 * f / binHz) / rta.totF + 1e-12);
        if (!started) { g.moveTo(L + px, y(db)); started = true; } else g.lineTo(L + px, y(db));
      }
      g.strokeStyle = 'rgba(233,231,226,0.3)'; g.lineWidth = 1; g.stroke();
    }
    if (!engine.playing) {
      g.fillStyle = C.text3; g.font = '600 10px ui-monospace, Menlo, monospace'; g.textAlign = 'center';
      g.fillText('PLAY TO MEASURE', L + W / 2, T + H / 2);
    }
    g.textAlign = 'left';
    // zone cards, 10 times a second
    if (now - zonesT > 100) {
      zonesT = now;
      for (const zc of zoneCards) {
        if (zc.gap == null) continue;
        zc.now.textContent = `${fmt(zc.gap, 1, true)} dB`;
        zc.needle.style.left = gaugePos(zc.gap);
        zc.el.dataset.ok = String(Math.abs(zc.gap) <= 3);
      }
    }
  };
  loop.add({ el: rta, draw: drawRTA });

  // =================================================================================================================
  // the EQ editor
  // =================================================================================================================
  const eqcv = canvas('mx-eq', loop);
  let bus = BUSES[0], selNode = null;
  const busChips = BUSES.map((b) => h('button', { type: 'button', class: 'mx-chip', text: b.label, onclick: () => { haptic(); selectBus(b.id); } }));
  const nodeRead = h('div', { class: 'mx-eq-read' });
  const liveName = h('span', { class: 'mx-eq-live' });
  const moreSets = new Map(BUSES.map((b) => [b.id, h('div', { class: 'mx-eq-more', hidden: true }, ...b.more.map((pid) => knob(ctx, pid, { size: 54 })))]));

  const nodeVals = (n) => {
    const gp = n.gain ? params.get(n.gain) : null, fp = n.freq ? params.get(n.freq) : null;
    return {
      gain: gp ? toReal(gp, store.get(n.gain)) : 0,
      f: fp ? toReal(fp, store.get(n.freq)) : n.f,
      setGain: gp ? gp.set : 0,
      setF: fp ? fp.set : n.f,
      gp, fp,
    };
  };
  const curve = (b, which) => {
    const cos = b.nodes.map((n) => {
      const v = nodeVals(n);
      const gain = which === 'set' ? v.setGain : v.gain, f = which === 'set' ? v.setF : v.f;
      return biquadCoefs(n.type, f, n.q ?? 0.71, gain);
    });
    return (f) => cos.reduce((s, co) => s + magDb(co, f), 0);
  };

  const showRead = () => {
    const n = selNode;
    if (!n) { nodeRead.replaceChildren(h('span', { text: 'Drag a node: up and down for gain, sideways for frequency where it can move.' })); return; }
    const v = nodeVals(n);
    const parts = [h('b', { text: n.label })];
    if (v.fp) parts.push(h('span', { class: `lcd-s${store.isSet(n.freq) ? ' is-acid' : ''}`, text: format(v.fp, v.f) }));
    if (v.gp) parts.push(h('span', { class: `lcd-s${store.isSet(n.gain) ? ' is-acid' : ''}`, text: format(v.gp, v.gain) }));
    const p = v.gp ?? v.fp;
    parts.push(h('i', { text: p.tried ? `tried ${format(p, p.tried[0])} to ${format(p, p.tried[1])}` : p.label }));
    nodeRead.replaceChildren(...parts);
  };

  const selectBus = (id) => {
    bus = BUSES.find((b) => b.id === id) ?? BUSES[0];
    busChips.forEach((c, i) => c.classList.toggle('is-on', BUSES[i] === bus));
    liveName.textContent = `Live: ${bus.live}`;
    selNode = null;
    for (const [id2, box] of moreSets) box.hidden = id2 !== bus.id;
    rt.taps?.eqSource(bus.stem);
    showRead();
  };
  const selectNode = (busId, gainId) => {
    selectBus(busId);
    selNode = bus.nodes.find((n) => n.gain === gainId || n.freq === gainId) ?? null;
    showRead();
    el.querySelector('.mx-eq-box')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  // geometry of the EQ plot
  const EQ = { L: 8, R: 8, T: 12, B: 16, D: 24 };
  let eqW = 0, eqH = 0;
  const ex = (f) => fx(f, EQ.L, eqW - EQ.L - EQ.R);
  const ey = (db) => EQ.T + (1 - (Math.max(-EQ.D, Math.min(EQ.D, db)) + EQ.D) / (2 * EQ.D)) * (eqH - EQ.T - EQ.B);
  const nodeXY = (n) => { const v = nodeVals(n); return [ex(v.f), ey(n.gain ? v.gain : 0)]; };

  const pick = (e, radius = 40) => {
    const r = eqcv.getBoundingClientRect();
    const px = e.clientX - r.left, py = e.clientY - r.top;
    let best = null, bd = Infinity;
    for (const n of bus.nodes) { const [x, y] = nodeXY(n); const d = Math.hypot(px - x, (py - y) * 0.8); if (d < bd) { bd = d; best = n; } }
    return bd < radius ? best : null;
  };

  let ws = null;
  drag(eqcv, {
    onStart: (e) => {
      const n = pick(e, 60);
      if (!n) { ws = null; return; }
      selNode = n;
      ws = { n, g: n.gain ? writer(ctx, n.gain, 'eq') : null, f: n.freq ? writer(ctx, n.freq, 'eq') : null };
      ws.g?.begin(); ws.f?.begin();
      showRead();
    },
    onMove: (dx, dy) => {
      if (!ws) return;
      const plotH = eqH - EQ.T - EQ.B, plotW = eqW - EQ.L - EQ.R;
      if (ws.g) {
        const p = ws.g.p;
        const dDb = -dy / plotH * (2 * EQ.D);
        ws.g.add(dDb / (p.max - p.min));
      }
      if (ws.f) {
        const p = ws.f.p;
        const v = toReal(p, store.get(ws.n.freq));
        const f2 = v * Math.pow(10, dx / plotW * (Math.log10(F1) - Math.log10(F0)));
        ws.f.set(toNorm(p, f2));
      }
      showRead();
    },
    onEnd: () => { if (ws) { ws.g?.end(); ws.f?.end(); } ws = null; },
    onTap: (e) => { const n = pick(e); selNode = n; showRead(); },
  });
  doubleTap(eqcv, (e) => {
    const n = pick(e);
    if (!n) return;
    store.begin();
    if (n.gain) store.reset(n.gain, { source: 'doubletap' });
    if (n.freq) store.reset(n.freq, { source: 'doubletap' });
    store.end();
    haptic(true);
    toast(`${n.label}: the set's value`);
  });
  longPress(eqcv, (e) => { const n = pick(e); if (n) inspect(n.gain ?? n.freq); });
  scrollable(eqcv, (e) => !!pick(e, 48));

  const eqBuf = { data: null };
  const drawEQ = () => {
    const { g, w, h: hh } = fit(loop, eqcv);
    if (!w) return;
    eqW = w; eqH = hh;
    const plotW = w - EQ.L - EQ.R;
    g.clearRect(0, 0, w, hh);
    // grid
    g.font = '600 8px ui-monospace, Menlo, monospace';
    for (const db of [-18, -12, -6, 0, 6, 12, 18]) {
      g.fillStyle = db === 0 ? 'rgba(255,255,255,0.14)' : 'rgba(255,255,255,0.05)';
      g.fillRect(EQ.L, ey(db), plotW, 1);
      if (db % 12 === 0) { g.fillStyle = C.text3; g.textAlign = 'right'; g.textBaseline = 'bottom'; g.fillText(`${db > 0 ? '+' : ''}${db}`, EQ.L + plotW - 2, ey(db) - 1); }
    }
    g.textAlign = 'center'; g.textBaseline = 'alphabetic';
    for (const [f, t] of [[30, '30'], [100, '100'], [300, '300'], [1000, '1k'], [3000, '3k'], [10000, '10k']]) {
      g.fillStyle = 'rgba(255,255,255,0.05)'; g.fillRect(ex(f), EQ.T, 1, hh - EQ.T - EQ.B);
      g.fillStyle = C.text3; g.fillText(t, ex(f), hh - 4);
    }
    // the gap zones, faint
    for (const zc of zoneCards) {
      g.fillStyle = (zc.gap ?? zc.setGap) && Math.abs(zc.gap ?? zc.setGap) <= 3 ? rgba(C.cold, 0.05) : rgba(C.hazard, 0.06);
      g.fillRect(ex(zc.z.lo), EQ.T, ex(zc.z.hi) - ex(zc.z.lo), hh - EQ.T - EQ.B);
    }
    // the bus's spectrum
    const t = rt.taps;
    if (t && engine.playing) {
      if (!eqBuf.data || eqBuf.data.length !== t.eq.frequencyBinCount) eqBuf.data = new Float32Array(t.eq.frequencyBinCount);
      t.eq.smoothingTimeConstant = 0.82;
      t.eq.getFloatFrequencyData(eqBuf.data);
      const bin = engine.ctx.sampleRate / t.eq.fftSize, d = eqBuf.data;
      g.beginPath(); g.moveTo(EQ.L, hh - EQ.B);
      for (let px = 0; px <= plotW; px += 2) {
        const f = Math.pow(10, Math.log10(F0) + px / plotW * 3);
        const i = Math.min(d.length - 1, Math.max(1, Math.round(f / bin)));
        const db = d[i] + 10 * Math.log10(f / 1000) * 0.5;      // a +1.5 dB/oct tilt so the highs read
        const yy = EQ.T + (1 - (Math.max(-100, Math.min(-10, db)) + 100) / 90) * (hh - EQ.T - EQ.B);
        g.lineTo(EQ.L + px, yy);
      }
      g.lineTo(EQ.L + plotW, hh - EQ.B); g.closePath();
      const gr = g.createLinearGradient(0, EQ.T, 0, hh - EQ.B);
      gr.addColorStop(0, 'rgba(233,231,226,0.16)'); gr.addColorStop(1, 'rgba(233,231,226,0.02)');
      g.fillStyle = gr; g.fill();
    }
    // the set's curve and the curve now
    const cs = curve(bus, 'set'), cn = curve(bus, 'now');
    const path = (fn) => { g.beginPath(); for (let px = 0; px <= plotW; px += 2) { const f = Math.pow(10, Math.log10(F0) + px / plotW * 3); const yy = ey(fn(f)); if (px) g.lineTo(EQ.L + px, yy); else g.moveTo(EQ.L + px, yy); } };
    path(cn);
    g.lineTo(EQ.L + plotW, ey(0)); g.lineTo(EQ.L, ey(0)); g.closePath();
    g.fillStyle = rgba(C.hazard, 0.12); g.fill();
    path(cs); g.setLineDash([4, 3]); g.strokeStyle = rgba(C.acid, 0.8); g.lineWidth = 1.4; g.stroke(); g.setLineDash([]);
    path(cn); g.strokeStyle = C.hazard; g.lineWidth = 2.2; g.shadowColor = C.hazard; g.shadowBlur = 6; g.stroke(); g.shadowBlur = 0;
    // nodes
    for (const n of bus.nodes) {
      const v = nodeVals(n);
      const [x, yy] = nodeXY(n);
      // the tried range as a pale track
      const p = v.gp ?? v.fp;
      if (p?.tried) {
        g.strokeStyle = 'rgba(198,255,61,0.28)'; g.lineWidth = 6; g.lineCap = 'round';
        g.beginPath();
        if (v.gp && v.fp?.tried) { g.moveTo(ex(v.fp.tried[0]), ey(v.gp.tried?.[0] ?? v.gain)); g.lineTo(ex(v.fp.tried[1]), ey(v.gp.tried?.[1] ?? v.gain)); }
        else if (v.gp) { g.moveTo(x, ey(v.gp.tried[0])); g.lineTo(x, ey(v.gp.tried[1])); }
        else { g.moveTo(ex(v.fp.tried[0]), yy); g.lineTo(ex(v.fp.tried[1]), yy); }
        g.stroke(); g.lineCap = 'butt';
      }
      // the set's position
      g.fillStyle = C.acid;
      g.beginPath(); g.arc(ex(v.setF), ey(n.gain ? v.setGain : 0), 2.5, 0, Math.PI * 2); g.fill();
      const on = n === selNode;
      g.beginPath(); g.arc(x, yy, on ? 11 : 8.5, 0, Math.PI * 2);
      g.fillStyle = on ? '#3a3e45' : '#25282d'; g.fill();
      g.strokeStyle = on ? C.lcd : C.hazard; g.lineWidth = on ? 2.5 : 1.8; g.stroke();
      g.font = '700 8.5px ui-monospace, Menlo, monospace'; g.textAlign = 'center';
      g.fillStyle = on ? C.lcd : C.text2;
      g.fillText(n.label.toUpperCase(), x, yy < 30 ? yy + 22 : yy - 14);
    }
    g.textAlign = 'left';
  };
  loop.add({ el: eqcv, draw: drawEQ });

  // re-read when any EQ param changes (the curve is drawn every frame while visible; this keeps the readout honest)
  const eqIds = new Set(BUSES.flatMap((b) => b.nodes.flatMap((n) => [n.gain, n.freq].filter(Boolean))));
  ctx.own(store.onAny((id) => { if (eqIds.has(id)) showRead(); }));

  // =================================================================================================================
  const el = h('section', { class: 'rack mx-tone' },
    h('div', { class: 'rack-head' }, h('span', { class: 'rack-title', text: 'Tone' }), h('span', { class: 'rack-sub', text: 'the master against the four references' })),
    h('div', { class: 'mx-rta-box' }, rta),
    h('div', { class: 'mx-legend' },
      h('span', { class: 'is-cold', text: 'refs range' }), h('span', { class: 'is-acid', text: 'the set, measured' }), h('span', { class: 'is-lcd', text: 'now, here' })),
    h('div', { class: 'mx-zones' }, ...zoneCards.map((z) => z.el)),
    h('div', { class: 'mx-eq-head' }, h('div', { class: 'mx-seg mx-eq-buses' }, ...busChips), liveName),
    h('div', { class: 'mx-eq-box' }, eqcv),
    nodeRead,
    ...moreSets.values(),
    h('p', { class: 'rack-note', text: 'Bands are relative to the whole (the 29 bands sum to 0 dB), so loudness cancels and only the shape counts. Tap a gap to find the knob that closes it. Double tap a node: the set. Long press: the inspector.' }));

  selectBus('kick');
  return {
    el,
    select: (id) => selectBus(id),
    attach: () => rt.taps?.eqSource(bus.stem),
  };
}

function mean(a) { return a.reduce((s, v) => s + v, 0) / Math.max(1, a.length); }
