// The kick's first screen: what the kick is doing now (a live trace of the kick buses on the beat, beat LEDs, gain
// reduction, the state in words) and the four most-played things in thumb reach: the source switch, the heat fader
// (COLDFIRE and the Decapitator together), the A/B/C tapper (37 / 43.5 / 50 %, a bar each), and the scoop.

import { clamp, drag, h, haptic, inspect, longPress, standard, toast } from '../ui.js';
import { follow, writer } from '../widgets/core.js';
import { format, toNorm, toReal } from '../params.js';
import { C, MONO, canvas, logAxis, rgba } from './util.js';
import { BEAT, BW8_QDB, biquadDb } from './dsp.js';
import { HEAT, MODE } from './rig.js';

// ---- the header ------------------------------------------------------------------------------------------------
export function header(ctx, rig, painter) {
  const { engine, store } = ctx;
  const cv = canvas('kx-head-cv');
  const leds = [0, 1, 2, 3].map((i) => h('i', { class: `kx-led${i === 0 ? ' is-one' : ''}` }));
  const gr = h('b', { class: 'kx-gr-v', text: '0.0' });
  const grBar = h('i', { class: 'kx-gr-bar' });
  const src = h('span', { class: 'kx-chip kx-chip-src', text: 'STEM' });
  const heat = h('span', { class: 'kx-chip kx-chip-heat', text: 'HEAT' });
  const scoop = h('span', { class: 'kx-chip kx-chip-scoop', text: 'SCOOP' });
  const el = h('div', { class: 'kx-head' },
    h('div', { class: 'kx-head-scope' }, cv, h('span', { class: 'kx-head-tag', text: 'KICK BUS · LAST BEAT' })),
    h('div', { class: 'kx-head-side' },
      h('div', { class: 'kx-leds', 'aria-hidden': 'true' }, ...leds),
      h('div', { class: 'kx-gr', title: 'Gain reduction of the kick group compressor' },
        h('span', { text: 'GR' }), gr, h('span', { class: 'kx-gr-u', text: 'dB' }), h('div', { class: 'kx-gr-track' }, grBar))),
    h('div', { class: 'kx-head-status' }, src, heat, scoop));

  const names = ['STEM', 'SYNTH', 'BOTH'];
  const status = () => {
    const sel = rig.sel;
    src.textContent = sel === MODE.AB ? `A/B · ${rig.playing === MODE.STEM ? 'A STEM' : 'B SYNTH'}` : names[rig.playing] ?? 'STEM';
    src.classList.toggle('is-synth', rig.playing !== MODE.STEM);
    const d1 = store.real('kick.drive'), d2 = store.real('rumble.drive');
    heat.textContent = `HEAT ${Math.round(d1)}/${Math.round(d2)}%`;
    heat.classList.toggle('is-zone', d1 >= HEAT.zone[0] - 0.5 && d1 <= HEAT.zone[1] + 0.5 && d2 >= HEAT.zone[0] - 0.5 && d2 <= HEAT.zone[1] + 0.5);
    const on = rig.scoopOn();
    scoop.textContent = on ? `SCOOP ${Math.round(store.real('kick.scoopFreq'))} Hz` : rig.scoop.armed ? 'SCOOP ARMED' : rig.scoop.latch ? 'SCOOP NEXT BAR' : 'SCOOP OFF';
    scoop.classList.toggle('is-on', on);
  };
  for (const id of ['kick.drive', 'rumble.drive', 'kick.scoopFreq']) ctx.own(store.on(id, status));
  ctx.own(rig.on(status));

  // the trace: the current beat drawn as it plays over the last one, from the kick buses' tap
  let cur = null, prev = null, curStart = -1, buf = null;
  const COLS = 160;
  const columns = (data, fs, now, t0, t1) => {
    const out = new Float32Array(COLS * 2).fill(0);
    const N = data.length;
    for (let c = 0; c < COLS; c++) {
      const ta = t0 + (c / COLS) * BEAT, tb = t0 + ((c + 1) / COLS) * BEAT;
      if (ta > t1) { out[c * 2] = NaN; continue; }
      let i0 = Math.round(N - 1 - (now - ta) * fs), i1 = Math.round(N - 1 - (now - Math.min(tb, t1)) * fs);
      i0 = Math.max(0, i0); i1 = Math.min(N - 1, i1);
      let lo = 0, hi = 0;
      for (let i = i0; i <= i1; i++) { const x = data[i]; if (x < lo) lo = x; if (x > hi) hi = x; }
      out[c * 2] = lo; out[c * 2 + 1] = hi;
    }
    return out;
  };
  painter.add(el, () => {
    const pos = engine.position();
    leds.forEach((l, i) => l.classList.toggle('is-lit', pos.playing && pos.beat === i));
    const r = rig.reduction();
    gr.textContent = r < -0.05 ? r.toFixed(1) : '0.0';
    gr.classList.toggle('is-idle', r > -0.05);
    grBar.style.width = `${clamp(-r / 12) * 100}%`;
    const { g, W, H, k } = cv.fit();
    g.fillStyle = '#050606'; g.fillRect(0, 0, W, H);
    // grid: the 16ths of one beat
    g.fillStyle = 'rgba(255,255,255,0.05)';
    for (let i = 1; i < 4; i++) g.fillRect((i / 4) * W, 0, k, H);
    g.fillRect(0, H / 2, W, k);
    if (rig.tap && engine.playing) {
      const ac = rig.ac, fs = ac.sampleRate, now = ac.currentTime;
      buf ??= new Float32Array(rig.tap.fftSize);
      rig.tap.getFloatTimeDomainData(buf);
      const kb = Math.floor((now - engine.t0) / BEAT);
      const start = engine.t0 + kb * BEAT;
      if (start !== curStart) { if (cur) prev = cur; curStart = start; }
      cur = columns(buf, fs, now, start, now);
    }
    const trace = (cols, color, alpha) => {
      if (!cols) return;
      g.fillStyle = rgba(color, alpha);
      const cw = W / COLS;
      for (let c = 0; c < COLS; c++) {
        const lo = cols[c * 2], hi = cols[c * 2 + 1];
        if (Number.isNaN(lo)) break;
        const y0 = H / 2 - hi * H * 0.48, y1 = H / 2 - lo * H * 0.48;
        g.fillRect(c * cw, y0, Math.max(k, cw - k * 0.5), Math.max(k, y1 - y0));
      }
    };
    trace(prev, C.text3, 0.45);
    g.shadowColor = C.hazard; g.shadowBlur = 8 * k;
    trace(cur, rig.playing === MODE.STEM ? C.lcd : C.hazard, 0.95);
    g.shadowBlur = 0;
    // scanlines
    g.fillStyle = 'rgba(0,0,0,0.22)';
    for (let y = 0; y < H; y += 3 * k) g.fillRect(0, y, W, k);
    if (!engine.playing) {
      g.fillStyle = C.text3; g.font = `${10 * k}px ${MONO}`; g.textAlign = 'center';
      g.fillText('PRESS PLAY: THE TRACE FOLLOWS THE BEAT', W / 2, H / 2 - 6 * k);
    }
  }, { always: true });
  status();
  return el;
}

// ---- the source switch -----------------------------------------------------------------------------------------
export function sourceSwitch(ctx, rig) {
  const { store, params } = ctx;
  const p = params.get('ks.source');
  const w = writer(ctx, 'ks.source', 'source');
  const labels = [['STEM', 'the set'], ['SYNTH', 'phone'], ['BOTH', 'layered'], ['A/B', 'a bar each']];
  const btns = labels.map(([big, small], i) => {
    const b = h('button', { type: 'button', class: 'kx-src', dataset: { i: String(i) } },
      h('i', { class: 'kx-src-led' }), h('b', { text: big }), h('span', { text: small }));
    b.addEventListener('click', () => {
      w.begin(); w.set(toNorm(p, i)); w.end();
      haptic(true);
      if (i !== MODE.STEM && !ctx.engine.playing) toast('Press play: the synth plays on the beat');
    });
    longPress(b, () => inspect('ks.source'));
    return b;
  });
  const sample = h('button', { type: 'button', class: 'kx-src kx-src-sample', 'aria-pressed': 'false' },
    h('i', { class: 'kx-src-led' }), h('b', { text: '+SMP' }), h('span', { text: 'hit layer' }));
  const ws = writer(ctx, 'ks.sample', 'source');
  sample.addEventListener('click', () => { ws.begin(); ws.set(store.get('ks.sample') >= 0.5 ? 0 : 1); ws.end(); haptic(); });
  longPress(sample, () => inspect('ks.sample'));
  follow(ctx, 'ks.sample', (_v, real) => { sample.classList.toggle('is-on', real === 1); sample.setAttribute('aria-pressed', String(real === 1)); });
  const render = () => {
    btns.forEach((b, i) => {
      b.classList.toggle('is-on', rig.sel === i);
      b.setAttribute('aria-pressed', String(rig.sel === i));
      b.classList.toggle('is-sounding', rig.sel === MODE.AB && ((i === MODE.STEM && rig.playing === MODE.STEM) || (i === MODE.SYNTH && rig.playing === MODE.SYNTH)));
    });
  };
  ctx.own(rig.on((type) => { if (type === 'source' || type === 'playing' || type === 'ready') render(); }));
  ctx.own(store.on('ks.source', render));                   // the rig sets rig.sel first (it listens first)
  return h('div', { class: 'kx-srcs', role: 'group', 'aria-label': 'Kick source' }, ...btns, sample);
}

// ---- heat: one fader for both drives ---------------------------------------------------------------------------
export function heatFader(ctx, rig, painter) {
  const { store, params } = ctx;
  const [A, B] = HEAT.ids.map((id) => params.get(id));
  const wa = writer(ctx, A.id, 'heat'), wb = writer(ctx, B.id, 'heat');
  const cv = canvas('kx-heat-cv');
  const cap = h('i', { class: 'kx-heat-cap' }, h('span', { class: 'kx-heat-grip' }));
  const needleA = h('i', { class: 'kx-heat-needle is-a' });
  const needleB = h('i', { class: 'kx-heat-needle is-b' });
  const read = h('b', { class: 'kx-heat-v lcd' });
  const sub = h('span', { class: 'kx-heat-sub' });
  const track = h('div', { class: 'kx-heat-track', role: 'slider', tabindex: '0', 'aria-label': 'Heat: COLDFIRE and Decapitator drive together' },
    cv, needleA, needleB, cap);
  const el = h('div', { class: 'kx-heat' },
    h('div', { class: 'kx-heat-top' }, h('span', { class: 'kx-heat-t', text: 'HEAT' }), h('span', { class: 'kx-heat-what', text: 'COLDFIRE + DECAPITATOR' }), read),
    track, sub);
  const pct = (id) => store.live(id) * 100;
  const redraw = painter.add(track, () => {
    const { g, W, H, k } = cv.fit();
    const x = (v) => (v / 100) * W;
    g.clearRect(0, 0, W, H);
    // the groove
    const gy = H * 0.5;
    g.fillStyle = '#030303'; g.fillRect(0, gy - 3 * k, W, 6 * k);
    // fill: the heat so far
    const hv = (pct(A.id) + pct(B.id)) / 2;
    const grad = g.createLinearGradient(0, 0, W, 0);
    grad.addColorStop(0, '#3a2a14'); grad.addColorStop(0.37, C.lcd); grad.addColorStop(0.5, C.hazard); grad.addColorStop(0.8, C.alarm);
    g.fillStyle = grad; g.shadowColor = C.hazard; g.shadowBlur = 10 * k;
    g.fillRect(0, gy - 2 * k, x(hv), 4 * k);
    g.shadowBlur = 0;
    // the 8.1 target zone, hazard-striped
    const z0 = x(HEAT.zone[0]), z1 = x(HEAT.zone[1]);
    g.save();
    g.beginPath(); g.rect(z0, 4 * k, z1 - z0, H - 8 * k); g.clip();
    g.fillStyle = rgba(C.hazard, 0.1); g.fillRect(z0, 0, z1 - z0, H);
    g.strokeStyle = rgba(C.hazard, 0.32); g.lineWidth = 3 * k;
    for (let s = z0 - H; s < z1 + H; s += 9 * k) { g.beginPath(); g.moveTo(s, H); g.lineTo(s + H, 0); g.stroke(); }
    g.restore();
    g.strokeStyle = rgba(C.hazard, 0.7); g.lineWidth = k;
    g.strokeRect(z0 + k / 2, 4 * k, z1 - z0 - k, H - 8 * k);
    // ticks every 10 %, labels
    g.font = `600 ${9 * k}px ${MONO}`; g.textAlign = 'center';
    for (let v = 0; v <= 100; v += 5) {
      const big = v % 10 === 0;
      g.fillStyle = big ? C.steel4 : C.steel3;
      g.fillRect(x(v) - k / 2, H - (big ? 12 : 8) * k, k, (big ? 8 : 4) * k);
    }
    // A B C
    HEAT.abc.forEach((v, i) => {
      g.fillStyle = rgba(C.text, 0.75);
      g.fillText('ABC'[i], x(v), 13 * k);
    });
    // the set's marks
    g.fillStyle = C.acid;
    for (const p of [A, B]) g.fillRect(x(p.set) - k, H - 14 * k, 2 * k, 6 * k);
    g.fillStyle = C.text3; g.textAlign = 'left'; g.fillText('0', 3 * k, H - 15 * k);
    g.textAlign = 'right'; g.fillText('100', W - 3 * k, H - 15 * k);
  });
  const render = () => {
    const a = pct(A.id), b = pct(B.id), hv = (a + b) / 2;
    cap.style.left = `${hv}%`;
    needleA.style.left = `${a}%`;
    needleB.style.left = `${b}%`;
    read.textContent = `${hv.toFixed(1)}%`;
    const inZone = (v) => v >= HEAT.zone[0] - 0.25 && v <= HEAT.zone[1] + 0.25;
    sub.replaceChildren(
      h('span', { class: `kx-heat-k${inZone(a) ? ' is-zone' : ''}` }, h('i', { class: 'is-a' }), `COLDFIRE ${format(A, toReal(A, store.live(A.id)))}`),
      h('span', { class: `kx-heat-k${inZone(b) ? ' is-zone' : ''}` }, h('i', { class: 'is-b' }), `DECAP ${format(B, toReal(B, store.live(B.id)))}`),
      h('span', { class: 'kx-heat-zone', text: 'TARGET 37-50 % (8.1)' }));
    el.style.setProperty('--heat', String(clamp(hv / 100)));
    el.classList.toggle('is-zone', inZone(a) && inZone(b));
    redraw();
  };
  ctx.own(store.on(A.id, render)); ctx.own(store.on(B.id, render));

  // relative drag: both move by the finger's travel and are pulled together as you push, so they meet
  let wasZone = false;
  drag(track, {
    onStart: () => {
      if (rig.heat.cycling) { rig.heatCycle(false); toast('Cycle stopped: the fader has it'); }
      wa.begin(); wb.begin(); el.classList.add('is-touched');
      wasZone = el.classList.contains('is-zone');
    },
    onMove: (dx) => {
      const W = track.getBoundingClientRect().width || 300;
      const d = dx / W;
      const a = store.get(A.id), b = store.get(B.id);
      const mid = clamp((a + b) / 2 + d);
      const pull = Math.min(1, 8 * Math.abs(d));
      wa.set(a + d + (mid - a - d) * pull);
      wb.set(b + d + (mid - b - d) * pull);
      const z = el.classList.contains('is-zone');
      if (z !== wasZone) { haptic(true); wasZone = z; }
    },
    onEnd: () => { wa.end(); wb.end(); el.classList.remove('is-touched'); },
  });
  standardBoth(track, ctx, HEAT.ids, 'Heat');
  track.addEventListener('keydown', (e) => {
    const d = { ArrowRight: 0.01, ArrowUp: 0.01, ArrowLeft: -0.01, ArrowDown: -0.01 }[e.key];
    if (!d) return;
    ctx.store.begin(); for (const id of HEAT.ids) ctx.store.nudge(id, d); ctx.store.end(); e.preventDefault();
  });
  return el;
}

/** Double tap: every id back to the set (one undo step). Long press: the first id's inspector. */
function standardBoth(el, ctx, ids, name) {
  let last = -Infinity, x0 = 0, y0 = 0;
  el.addEventListener('pointerdown', (e) => { x0 = e.clientX; y0 = e.clientY; });
  el.addEventListener('pointerup', (e) => {
    if (Math.hypot(e.clientX - x0, e.clientY - y0) > 10) { last = -Infinity; return; }
    const now = performance.now();
    if (now - last < 300) { last = -Infinity; ctx.store.resetAll(ids); haptic(true); toast(`${name}: the set's values`); } else last = now;
  });
  longPress(el, () => inspect(ids[0]));
}

// ---- A / B / C ---------------------------------------------------------------------------------------------------
export function abcTapper(ctx, rig, painter) {
  const { store, params } = ctx;
  const [A, B] = HEAT.ids.map((id) => params.get(id));
  const pads = HEAT.abc.map((v, i) => {
    const b = h('button', { type: 'button', class: `kx-abc-pad is-${'abc'[i]}`, dataset: { i: String(i) } },
      h('i', { class: 'kx-abc-led' }), h('b', { text: 'ABC'[i] }), h('span', { text: `${v}%` }), h('em', { class: 'kx-abc-lu' }));
    b.addEventListener('click', () => {
      if (rig.heat.cycling) rig.heatCycle(false);
      store.begin();
      store.set(A.id, toNorm(A, v), { source: 'abc' });
      store.set(B.id, toNorm(B, v), { source: 'abc' });
      store.end();
      haptic(true);
    });
    longPress(b, () => inspect(A.id));
    return b;
  });
  const cycleState = h('span', { class: 'kx-cycle-s', text: 'OFF' });
  const icon = h('span', { class: 'kx-cycle-i', 'aria-hidden': 'true' });
  icon.innerHTML = '<svg viewBox="0 0 24 24"><path d="M4 12a8 8 0 0 1 13.7-5.6L20 8.5M20 4v4.5h-4.5M20 12a8 8 0 0 1-13.7 5.6L4 15.5M4 20v-4.5h4.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const cycle = h('button', { type: 'button', class: 'kx-cycle', 'aria-pressed': 'false' }, icon, h('b', { text: 'CYCLE' }), cycleState);
  cycle.addEventListener('click', () => {
    const H = rig.heat;
    if (!H.cycling) rig.heatCycle(true, 1);
    else if (H.per === 1) rig.heatCycle(true, 2);
    else rig.heatCycle(false);
    haptic(true);
    if (rig.heat.cycling && !ctx.engine.playing) toast('Press play: A, B and C take turns on the bar');
    render();
  });
  const render = () => {
    const H = rig.heat;
    const comps = [0, 1, 2].map((i) => rig.matchComp(`h${i}`));
    pads.forEach((p, i) => {
      const c = comps[i];
      p.querySelector('.kx-abc-lu').textContent = H.cycling ? (c == null ? 'LU ...' : Math.abs(c) < 0.05 ? '0.0 dB' : `${c > 0 ? '+' : ''}${c.toFixed(1)} dB`) : '';
    });
    const matched = H.cycling && comps.filter((c) => c != null).length >= 2;
    cycleState.textContent = !H.cycling ? 'OFF' : `${H.per === 1 ? 'EVERY BAR' : 'EVERY 2 BARS'}${matched ? ' · LU' : ''}`;
    cycle.classList.toggle('is-on', H.cycling);
    cycle.setAttribute('aria-pressed', String(H.cycling));
  };
  ctx.own(rig.on((type) => { if (type === 'heat' || type === 'match') render(); }));
  // pads light: the one the drives are at (while cycling, the one sounding); the next one in the cycle blinks
  const tick = () => {
    const H = rig.heat;
    const a = store.live(A.id) * 100, b = store.live(B.id) * 100;
    pads.forEach((p, i) => {
      const v = HEAT.abc[i];
      const at = Math.abs(a - v) < 0.3 && Math.abs(b - v) < 0.3;
      p.classList.toggle('is-on', at);
      p.classList.toggle('is-next', H.cycling && H.idx >= 0 && ((H.idx + 1) % 3) === i);
    });
  };
  ctx.own(store.on(A.id, tick)); ctx.own(store.on(B.id, tick));
  ctx.own(rig.on((type) => { if (type === 'heat') tick(); }));
  render();
  return h('div', { class: 'kx-abc' }, ...pads, cycle);
}

// ---- the scoop -------------------------------------------------------------------------------------------------
export function scoopBlock(ctx, rig, painter) {
  const { store, params, engine } = ctx;
  const P = params.get('kick.scoopFreq');
  const wf = writer(ctx, P.id, 'scoop');
  const cv = canvas('kx-scoop-cv');
  const hz = h('b', { class: 'kx-scoop-hz' });
  const state = h('span', { class: 'kx-scoop-state', text: 'HOLD TO SCOOP' });
  const pad = h('div', { class: 'kx-scoop-pad', role: 'button', tabindex: '0', 'aria-label': 'Hold to scoop the kick: a 48 dB per octave low cut' },
    cv,
    h('div', { class: 'kx-scoop-label' }, state, h('span', { class: 'kx-scoop-sub' }, hz, ' · 48 dB/oct low cut'),
      h('span', { class: 'kx-scoop-hint', text: 'slide while holding: the frequency' })));

  // hold: any finger down scoops; a held finger sliding up or down moves the frequency
  const fingers = new Map();
  let moved = false;
  pad.style.touchAction = 'none';
  pad.addEventListener('pointerdown', (e) => {
    try { pad.setPointerCapture(e.pointerId); } catch { /* synthetic */ }
    fingers.set(e.pointerId, e.clientY);
    if (fingers.size === 1) { moved = false; wf.begin(); rig.scoopHold(true); haptic(true); pad.classList.add('is-held'); }
    e.preventDefault();
  });
  pad.addEventListener('pointermove', (e) => {
    if (!fingers.has(e.pointerId)) return;
    const y0 = fingers.get(e.pointerId);
    const dy = e.clientY - y0;
    if (!moved && Math.abs(dy) < 6) return;
    moved = true;
    fingers.set(e.pointerId, e.clientY);
    wf.add(-dy / 260 * (fingers.size > 1 ? 0.25 : 1));
  });
  const up = (e) => {
    if (!fingers.delete(e.pointerId)) return;
    if (fingers.size) return;
    rig.scoopHold(false);
    wf.end();
    haptic();
    pad.classList.remove('is-held');
  };
  pad.addEventListener('pointerup', up);
  pad.addEventListener('pointercancel', up);
  pad.addEventListener('contextmenu', (e) => e.preventDefault());
  pad.addEventListener('keydown', (e) => { if (e.key === ' ' || e.key === 'Enter') { rig.scoopHold(true); pad.classList.add('is-held'); e.preventDefault(); } });
  pad.addEventListener('keyup', (e) => { if (e.key === ' ' || e.key === 'Enter') { rig.scoopHold(false); pad.classList.remove('is-held'); } });

  // the latch: the next 4 bars, from the bar line
  const latchLeds = [0, 1, 2, 3].map(() => h('i', { class: 'kx-latch-led' }));
  const latchText = h('span', { class: 'kx-latch-s', text: 'NEXT 4 BARS' });
  const latch = h('button', { type: 'button', class: 'kx-latch', 'aria-pressed': 'false' },
    h('b', { text: 'LATCH' }), latchText, h('span', { class: 'kx-latch-leds' }, ...latchLeds));
  latch.addEventListener('click', () => {
    const on = rig.scoopLatch();
    haptic(true);
    if (on && !engine.playing) toast('Armed: it scoops from the first bar when you press play');
  });

  // the frequency strip: 20-400 Hz, the set's 126 Hz in acid, under 70 Hz the scoop becomes a sub cut
  const strip = frequencyStrip(ctx, P, painter);

  const ax = logAxis(20, 600);
  let spec = null;
  const redraw = painter.add(pad, () => {
    const { g, W, H, k } = cv.fit();
    const held = rig.scoopOn();
    g.clearRect(0, 0, W, H);
    // the live low end of the kick buses
    if (rig.spec && engine.playing) {
      spec ??= new Float32Array(rig.spec.frequencyBinCount);
      rig.spec.getFloatFrequencyData(spec);
      const fs = rig.ac.sampleRate, df = fs / rig.spec.fftSize;
      g.beginPath(); g.moveTo(0, H);
      for (let x = 0; x <= W; x += 2 * k) {
        const f = ax.f(x, W);
        const fi = Math.max(1, f / df), i0 = Math.floor(fi), u = fi - i0;
        const m = (spec[i0] ?? -200) * (1 - u) + (spec[i0 + 1] ?? -200) * u;
        const y = H - clamp((m + 90) / 75) * H * 0.9;
        g.lineTo(x, y);
      }
      g.lineTo(W, H); g.closePath();
      const grd = g.createLinearGradient(0, 0, 0, H);
      grd.addColorStop(0, rgba(held ? C.hazard : C.lcd, 0.55)); grd.addColorStop(1, rgba(held ? C.hazard : C.lcd, 0.04));
      g.fillStyle = grd; g.fill();
    }
    // the cut: 4 cascaded Butterworth biquads at the scoop frequency
    const F = store.real(P.id);
    g.beginPath();
    for (let x = 0; x <= W; x += 2 * k) {
      const f = ax.f(x, W);
      let db = 0;
      for (const q of BW8_QDB) db += biquadDb('highpass', F, 0, q, f);
      const y = clamp(-db / 60) * H * 0.92 + H * 0.06;
      if (x === 0) g.moveTo(x, y); else g.lineTo(x, y);
    }
    g.strokeStyle = held ? C.hazard : rgba(C.text, 0.35); g.lineWidth = (held ? 2.5 : 1.5) * k;
    g.setLineDash(held ? [] : [5 * k, 4 * k]);
    g.shadowColor = C.hazard; g.shadowBlur = held ? 12 * k : 0;
    g.stroke(); g.setLineDash([]); g.shadowBlur = 0;
    const xf = ax.x(F, W);
    g.fillStyle = rgba(held ? C.hazard : C.text3, held ? 0.2 : 0.08);
    g.fillRect(0, 0, xf, H);
    // frequency marks
    g.font = `600 ${9 * k}px ${MONO}`; g.fillStyle = C.text3; g.textAlign = 'center';
    for (const f of [30, 60, 120, 250, 500]) { const x = ax.x(f, W); g.fillRect(x, H - 6 * k, k, 6 * k); g.fillText(String(f), x, H - 8 * k); }
  }, { always: true });
  const render = () => {
    const on = rig.scoopOn();
    hz.textContent = format(P, store.real(P.id));
    state.textContent = on ? 'SCOOPED' : rig.scoop.armed ? 'ARMED: NEXT BAR' : 'HOLD TO SCOOP';
    pad.classList.toggle('is-on', on);
    const S = rig.scoop;
    latch.classList.toggle('is-armed', S.armed);
    latch.classList.toggle('is-on', !!S.latch);
    latch.setAttribute('aria-pressed', String(S.armed || !!S.latch));
    latchText.textContent = S.armed ? 'ARMED' : S.latch ? 'SCOOPING' : 'NEXT 4 BARS';
    redraw();
  };
  // the latch's LEDs follow the bars it covers
  painter.add(latch, () => {
    const S = rig.scoop, now = rig.ac?.currentTime ?? 0;
    const n = S.latch ? Math.floor((now - S.latch.start) / engine.barSeconds) : -1;
    latchLeds.forEach((l, i) => { l.classList.toggle('is-done', S.latch && i < n); l.classList.toggle('is-lit', S.latch && i === n); });
    pad.classList.toggle('is-on', rig.scoopOn());
    const on = rig.scoopOn();
    if (on !== render.on) { render.on = on; render(); }
  }, { always: true });
  ctx.own(store.on(P.id, render));
  ctx.own(rig.on((type) => { if (type === 'scoop' || type === 'ready') render(); }));
  render();
  return h('div', { class: 'kx-scoop' }, pad, h('div', { class: 'kx-scoop-side' }, latch, strip));
}

/** A vertical log-frequency strip for the scoop's cutoff: relative drag, the set's value, the sub-cut zone. */
function frequencyStrip(ctx, P, painter) {
  const { store } = ctx;
  const w = writer(ctx, P.id, 'strip');
  const cv = canvas('kx-fstrip-cv');
  const read = h('b', { class: 'kx-fstrip-v' });
  const el = h('div', { class: 'kx-fstrip', role: 'slider', tabindex: '0', 'aria-label': P.label },
    h('div', { class: 'kx-fstrip-track' }, cv), read);
  const track = el.querySelector('.kx-fstrip-track');
  const redraw = painter.add(el, () => {
    const { g, W, H, k } = cv.fit();
    const pad = 8 * k;
    const y = (f) => pad + (1 - Math.log(f / P.min) / Math.log(P.max / P.min)) * (H - 2 * pad);
    g.clearRect(0, 0, W, H);
    const gx = W * 0.62;                                   // the groove, right of the labels
    g.fillStyle = '#040404'; g.fillRect(gx - 3 * k, pad, 6 * k, H - 2 * pad);
    // under 70 Hz: the scoop eats the sub (57 Hz was the deep-sub climb's value)
    const yz = y(70);
    g.save(); g.beginPath(); g.rect(0, yz, W, H - yz); g.clip();
    g.fillStyle = rgba(C.alarm, 0.12); g.fillRect(0, yz, W, H - yz);
    g.strokeStyle = rgba(C.alarm, 0.35); g.lineWidth = k;
    for (let s0 = yz - W; s0 < H + W; s0 += 7 * k) { g.beginPath(); g.moveTo(0, s0 + W * 0.6); g.lineTo(W, s0); g.stroke(); }
    g.restore();
    g.font = `600 ${8 * k}px ${MONO}`; g.textAlign = 'right';
    let lastY = Infinity;
    for (const f of [20, 30, 50, 70, 100, 150, 200, 300, 400]) {
      const yy = y(f);
      g.fillStyle = f === 70 ? C.alarm : C.steel4;
      g.fillRect(gx - 9 * k, yy, 5 * k, k); g.fillRect(gx + 4 * k, yy, 5 * k, k);
      if ([20, 50, 100, 200, 400].includes(f) && lastY - yy > 11 * k) {
        g.fillStyle = C.text3; g.fillText(String(f), gx - 12 * k, yy + 3 * k); lastY = yy;
      }
    }
    g.save(); g.translate(W - 4 * k, (yz + H) / 2); g.rotate(-Math.PI / 2);
    g.textAlign = 'center'; g.fillStyle = rgba(C.alarm, 0.85); g.font = `700 ${7.5 * k}px ${MONO}`;
    g.fillText('SUB CUT', 0, 0); g.restore();
    // the set's 126 Hz
    g.fillStyle = C.acid; g.fillRect(gx - 10 * k, y(P.set) - k, 20 * k, 2 * k);
    // the cap
    const v = store.real(P.id), yc = y(v);
    const cw = 26 * k, ch = 16 * k;
    const grd = g.createLinearGradient(0, yc - ch / 2, 0, yc + ch / 2);
    grd.addColorStop(0, '#5b616b'); grd.addColorStop(0.45, '#2d3137'); grd.addColorStop(0.55, '#1d2024'); grd.addColorStop(1, '#3a3f46');
    g.shadowColor = '#000'; g.shadowBlur = 6 * k; g.shadowOffsetY = 3 * k;
    g.fillStyle = grd; g.fillRect(gx - cw / 2, yc - ch / 2, cw, ch);
    g.shadowBlur = 0; g.shadowOffsetY = 0;
    g.fillStyle = v < 70 ? C.alarm : C.hazard; g.fillRect(gx - cw / 2 + 3 * k, yc - k, cw - 6 * k, 2 * k);
  });
  let crossed = false;
  follow(ctx, P.id, (_n, real, text) => {
    read.textContent = text;
    el.classList.toggle('is-set', store.isSet(P.id));
    el.classList.toggle('is-sub', real < 70);
    if (real < 70 && !crossed) { crossed = true; } else if (real >= 70) crossed = false;
    redraw();
  });
  let warned = false;
  drag(track, {
    onStart: () => { w.begin(); el.classList.add('is-touched'); },
    onMove: (_dx, dy) => {
      const before = store.real(P.id);
      w.add(-dy / Math.max(120, track.getBoundingClientRect().height * 1.4));
      const after = store.real(P.id);
      if ((before - 70) * (after - 70) < 0) { haptic(true); if (after < 70 && !warned) { warned = true; toast('Under 70 Hz the scoop cuts the sub, not the kick'); } }
    },
    onEnd: () => { w.end(); el.classList.remove('is-touched'); },
  });
  standard(track, store, P.id);
  return el;
}

