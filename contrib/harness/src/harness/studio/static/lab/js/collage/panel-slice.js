// SLICE: the tape cut into 16 slices from its cue (drag the strip to slide the region along the tape), played on
// 4x4 pads (pad 1 bottom left, like an MPC; hit the middle for loud, the edge for soft) or by a 16-step pattern on
// the engine's 16ths. STEPS turns the same grid into the pattern (step 1 top left, reading like a bar): tap a step to
// give it the last pad you hit, drag it up or down to change its slice, sideways for its velocity, hold to empty it. The LED row above
// always shows the pattern and where it is. REC writes your pad hits into the pattern as it plays. DICE re-cuts.

import { h, haptic, drag, longPress, toast } from '../ui.js';
import { knob } from '../widgets/knob.js';
import { toggle } from '../widgets/fader.js';
import { saveState, state } from './state.js';
import { bufferNow, drawWave, peakIn, peaksNow } from './sources.js';
import { cutsOf, dice, playSlice, recordHit, regionOf, sliceOf, straight } from './slicer.js';
import { fit, latch, push } from './bits.js';
import { clock } from './meta.js';

export default function slicePanel(C) {
  const { store, engine } = C;
  const region = h('canvas', { class: 'cs-region', 'aria-label': 'The region: drag to slide it along the tape' });
  const rlcd = h('div', { class: 'cs-rlcd' });
  const seqBtn = latch('Play', {
    icon: 'play', on: state.seq, title: 'Play the 16-step pattern',
    onChange: async (on) => {
      state.seq = on;
      if (on && !engine.playing) { try { await engine.start(); } catch { /* no sound */ } }
      C.ev.emit('seq');
    },
  });
  const recBtn = latch('Rec', { icon: 'rec', on: state.rec, cls: 'is-rec', title: 'Write pad hits into the pattern', onChange: (on) => { state.rec = on; if (on && !state.seq) seqBtn.click(); } });
  const diceBtn = push('Dice', () => { dice(C); toast('Re-cut and re-dealt'); }, { icon: 'dice', title: 'New cuts, new pattern' });
  const viewBtn = latch('Steps', { title: 'Edit the pattern on the grid', onChange: (on) => setView(on ? 'steps' : 'pads') });
  const orderBtn = push('In order', () => { straight(C); toast('Slices in order: the region as it was'); }, { icon: 'scissors', title: 'Pattern back to 1-16' });

  // --- the LED row: the pattern, always in view -------------------------------------------------------------------
  const leds = Array.from({ length: 16 }, (_, i) => h('i', { class: `cs-led${i % 4 === 0 ? ' is-beat' : ''}` }));
  const ledRow = h('div', { class: 'cs-leds', 'aria-hidden': 'true' }, ...leds);

  // --- steps (step 1 top left) --------------------------------------------------------------------------------------
  const steps = Array.from({ length: 16 }, (_, i) => {
    const b = h('button', { type: 'button', class: `cs-cell cs-step${i % 4 === 0 ? ' is-beat' : ''}`, 'aria-label': `Step ${i + 1}` },
      h('span', { class: 'cs-cell-n', text: String(i + 1) }), h('b', { class: 'cs-step-s' }), h('i', { class: 'cs-step-vel' }));
    let held = false, acc = 0, axis = null;
    drag(b, {
      onStart: () => { held = false; acc = 0; axis = null; },
      onMove: (dx, dy) => {
        axis ??= Math.abs(dx) > Math.abs(dy) ? 'x' : 'y';
        if (axis === 'x') {                         // sideways: the step's velocity
          if (state.pattern[i] < 0) return;
          const v0 = state.vel[i] ?? 0.9, v = Math.max(0.15, Math.min(1, v0 + dx / 140));
          if ((v0 < 1 && v >= 1) || (v0 > 0.15 && v <= 0.15)) haptic();
          state.vel[i] = v;
          renderSteps();
          return;
        }
        acc -= dy / 18;
        while (Math.abs(acc) >= 1) {
          const d = Math.sign(acc);
          acc -= d;
          const cur = state.pattern[i] < 0 ? (d > 0 ? -1 : 16) : state.pattern[i];
          state.pattern[i] = Math.max(0, Math.min(15, cur + d));
          haptic();
          renderSteps();
        }
      },
      onTap: () => {
        if (held) return;
        state.pattern[i] = state.pattern[i] === state.lastPad ? -1 : state.lastPad;
        state.vel[i] = state.vel[i] || 0.9;
        haptic();
        renderSteps();
      },
      onEnd: () => saveState(),
    });
    longPress(b, () => { held = true; state.pattern[i] = -1; renderSteps(); saveState(); });
    return b;
  });
  const renderSteps = () => {
    steps.forEach((b, i) => {
      const s = state.pattern[i];
      b.querySelector('.cs-step-s').textContent = s >= 0 ? String(s + 1) : '·';
      b.classList.toggle('is-on', s >= 0);
      b.style.setProperty('--vel', String(state.vel[i] ?? 0.9));
      leds[i].classList.toggle('is-on', s >= 0);
    });
  };

  // --- pads (pad 1 bottom left) -------------------------------------------------------------------------------------
  const pads = Array.from({ length: 16 }, (_, i) => {
    const cv = h('canvas', { class: 'cs-pad-wave' });
    const b = h('button', { type: 'button', class: 'cs-cell cs-pad', 'aria-label': `Slice ${i + 1}`, dataset: { i } }, cv, h('span', { class: 'cs-cell-n', text: String(i + 1) }));
    b.style.order = String((3 - Math.floor(i / 4)) * 4 + (i % 4));
    b.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      if (!C.ready) { toast('Start the engine first'); return; }
      if (!bufferNow(engine, state.sel)) { toast('This tape is still loading'); return; }
      const r = b.getBoundingClientRect();
      const dx = (e.clientX - r.left - r.width / 2) / (r.width / 2), dy = (e.clientY - r.top - r.height / 2) / (r.height / 2);
      const vel = Math.max(0.3, 1 - 0.65 * Math.min(1, Math.hypot(dx, dy) / 1.25));
      playSlice(C, i, engine.ctx.currentTime + 0.004, vel);
      haptic();
      state.lastPad = i;
      if (recordHit(C, i, vel) >= 0) renderSteps();
      const sl = sliceOf(C, i);
      const st = store.real('col.slice.pitch');
      const rate = Math.pow(2, (st + C.G.pitchOf(state.sel)) / 12);
      C.setLoaded({ src: state.sel, off: sl.a, len: Math.max(1, Math.round((sl.b - sl.a) / rate / engine.stepSeconds)), st, rev: store.real('col.slice.rev') === 1 });
      b.style.setProperty('--vel', vel.toFixed(2));
      b.classList.add('is-down');
    });
    const up = () => b.classList.remove('is-down');
    b.addEventListener('pointerup', up);
    b.addEventListener('pointercancel', up);
    b.addEventListener('contextmenu', (e) => e.preventDefault());
    return { b, cv };
  });
  const padGrid = h('div', { class: 'cs-grid is-pads' }, ...pads.map((p) => p.b));
  const stepGrid = h('div', { class: 'cs-grid is-steps', hidden: true }, ...steps);
  padGrid.style.touchAction = 'none';
  const setView = (v) => {
    padGrid.hidden = v !== 'pads';
    stepGrid.hidden = v !== 'steps';
    viewBtn.set(v === 'steps');
    if (v === 'pads') padsDirty = true;
  };

  const flash = (i, vel) => {
    const p = pads[i]?.b;
    if (!p) return;
    p.style.setProperty('--flash', (0.35 + 0.65 * vel).toFixed(2));
    p.classList.remove('is-flash'); void p.offsetWidth; p.classList.add('is-flash');
  };
  const timers = new Set();
  const at = (when, fn) => {
    const ms = Math.max(0, (when - engine.ctx.currentTime) * 1000);
    const t = setTimeout(() => { timers.delete(t); fn(); }, ms);
    timers.add(t);
  };
  C.own(() => { for (const t of timers) clearTimeout(t); });
  let curStep = -1;
  const clearNow = () => { if (curStep >= 0) { steps[curStep].classList.remove('is-now'); leds[curStep].classList.remove('is-now'); } curStep = -1; };
  C.own(C.ev.on('pad', (i, when, vel) => { if (!el.hidden) at(when, () => flash(i, vel)); }));
  C.own(C.ev.on('step', (i, when) => {
    if (el.hidden) return;
    at(when, () => { clearNow(); curStep = i; steps[i].classList.add('is-now'); leds[i].classList.add('is-now'); });
  }));
  C.own(C.ev.on('seq', () => { seqBtn.set(state.seq); if (!state.seq) clearNow(); }));
  C.own(C.ev.on('pattern', renderSteps));

  // --- the region strip ---------------------------------------------------------------------------------------------
  drag(region, {
    onMove: (dx) => {
      if (!C.ready) return;
      const r = regionOf(C);
      const w = region.getBoundingClientRect().width;
      C.setCue(state.sel, Math.max(0, Math.min(r.dur - r.len, r.start - (dx / w) * r.len)));
    },
    onEnd: () => { haptic(); padsDirty = true; },
  });

  const knobs = h('div', { class: 'cl-knobrow' },
    knob(C.ctx, 'col.slice.pitch', { size: 64 }), knob(C.ctx, 'col.slice.decay', { size: 64 }),
    knob(C.ctx, 'col.slice.swing', { size: 64 }),
    h('div', { class: 'cl-tcol' }, toggle(C.ctx, 'col.slice.bars', { label: 'Region' }), toggle(C.ctx, 'col.slice.mode', { label: 'Cut' })),
    h('div', { class: 'cl-tcol' }, toggle(C.ctx, 'col.slice.choke', { label: 'Choke' }), toggle(C.ctx, 'col.slice.rev', { label: 'Back' })),
    h('div', { class: 'cl-tcol' }, orderBtn));

  const el = h('section', { class: 'cl-panel cs', 'aria-label': 'Slice' },
    h('div', { class: 'cs-region-box' }, region, h('i', { class: 'cl-crt' }), rlcd),
    h('div', { class: 'cl-btnrow' }, seqBtn, recBtn, diceBtn, viewBtn),
    h('div', { class: 'cs-deck' }, ledRow, padGrid, stepGrid),
    knobs);

  // --- drawing -----------------------------------------------------------------------------------------------------
  let padsDirty = true, regionKey = '';
  const R = fit(region, () => { regionKey = ''; });
  const drawPads = () => {
    const buf = bufferNow(engine, state.sel);
    const dpr = Math.min(3, devicePixelRatio || 1);
    const r = C.ready ? regionOf(C) : null;
    const gain = buf && r && peaksNow(buf) ? Math.min(12, 0.9 * (peaksNow(buf).peak / peakIn(buf, r.start, r.start + r.len))) : 0.9;
    for (let i = 0; i < 16; i++) {
      const cv = pads[i].cv;
      const rr = cv.getBoundingClientRect();
      cv.width = Math.max(1, Math.round(rr.width * dpr)); cv.height = Math.max(1, Math.round(rr.height * dpr));
      const g = cv.getContext('2d');
      g.clearRect(0, 0, cv.width, cv.height);
      if (!buf || !C.ready) continue;
      const { a, b } = sliceOf(C, i);
      drawWave(g, buf, a, b, 0, cv.height * 0.18, cv.width, cv.height * 0.64, { color: C.src()?.color ?? '#e0b7ff', gain, alpha: 0.6 });
    }
    padsDirty = false;
  };
  for (const id of ['col.slice.bars', 'col.slice.mode']) C.own(store.on(id, () => { padsDirty = true; regionKey = ''; }, { now: false }));
  C.own(C.ev.on('slices', () => { padsDirty = true; regionKey = ''; }));
  C.own(C.ev.on('select', () => { padsDirty = true; regionKey = ''; }));
  C.own(C.ev.on('buffer', (id) => { if (id === state.sel) { padsDirty = true; regionKey = ''; } }));
  let cueT = 0;
  C.own(C.ev.on('cue', () => { regionKey = ''; clearTimeout(cueT); cueT = setTimeout(() => { padsDirty = true; }, 120); }));
  C.own(() => clearTimeout(cueT));
  renderSteps();

  const layer = document.createElement('canvas');
  return {
    el,
    show() { padsDirty = true; regionKey = ''; R.measure(); renderSteps(); },
    draw() {
      if (padsDirty && !padGrid.hidden) drawPads();
      const buf = bufferNow(engine, state.sel);
      const W = region.width, H = region.height, dpr = R.dpr;
      const r = C.ready ? regionOf(C) : { start: 0, len: 1.5, dur: 1.5 };
      const key = `${state.sel}|${r.start.toFixed(4)}|${r.len}|${C.dice}|${store.real('col.slice.mode')}|${W}x${H}|${!!buf}`;
      if (key !== regionKey) {
        regionKey = key;
        layer.width = W; layer.height = H;
        const g = layer.getContext('2d');
        g.fillStyle = '#08070b'; g.fillRect(0, 0, W, H);
        if (buf && C.ready) {
          drawWave(g, buf, r.start, r.start + r.len, 0, H * 0.2, W, H * 0.66, { color: C.src()?.color ?? '#e0b7ff', gain: 0.95, local: true });
          const cuts = cutsOf(C);
          g.font = `600 ${9 * dpr}px ui-monospace, monospace`;
          let lastLabel = -1e9;
          cuts.forEach((c, i) => {
            const x = ((c - r.start) / r.len) * W;
            g.fillStyle = i ? 'rgba(255,255,255,0.5)' : '#e0b7ff';
            g.fillRect(x, 0, dpr, H);
            if (x - lastLabel > 14 * dpr) { g.fillStyle = 'rgba(233,231,226,0.75)'; g.fillText(String(i + 1), x + 2 * dpr, 10 * dpr); lastLabel = x; }
          });
          // where the region sits in the whole tape
          g.fillStyle = 'rgba(255,255,255,0.08)'; g.fillRect(0, H - 4 * dpr, W, 4 * dpr);
          g.fillStyle = '#e0b7ff'; g.fillRect((r.start / r.dur) * W, H - 4 * dpr, Math.max(2 * dpr, (r.len / r.dur) * W), 4 * dpr);
        }
        rlcd.textContent = C.ready ? `${clock(r.start, 2)} > ${clock(r.start + r.len, 2)}  ${['EQUAL', 'ONSETS'][store.real('col.slice.mode')]}` : 'START THE ENGINE';
      }
      const g = R.g;
      g.drawImage(layer, 0, 0);
      if (C.ready) {
        g.fillStyle = '#fff';
        for (const hd of C.players.heads(state.sel)) {
          const x = ((hd.pos - r.start) / r.len) * W;
          if (x >= 0 && x <= W) g.fillRect(x, 0, 1.5 * dpr, H);
        }
      }
    },
  };
}

