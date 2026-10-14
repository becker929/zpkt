// The A/B, Anthony's format: one track that switches between two versions every 1 or 2 bars, on the grid, level
// matched by the meter so the louder one does not win by being louder.
//
//   A  your mix: the phone's sketch with every move you made
//   B  one of: the set's render (Live's own mix of these 24 bars, engine.stems.useMix), the set's knobs (the same
//      sketch with every control back at the set's value, so only your moves differ), or the last point (the mix
//      before the last joint climb)
//
// The side of bar n is decided when bar n-1 is scheduled (the engine plays a bar ~120 ms ahead), so a switch lands
// on the downbeat. Level match: the worklet's 100 ms K-weighted blocks are sorted into A and B by the bar they fall
// in (the first 60 ms of a bar are skipped), and B gets the gain that matches its loudness to A's, on B's bars only.
// Tap A or B to hold one; tap the centre to switch.

import { h, haptic, toast } from '../ui.js';
import { setNorm } from '../params.js';
import { fmt } from './util.js';

const MODES = [
  { id: 'render', label: 'Set render', b: 'The set\'s render' },
  { id: 'knobs', label: 'Set knobs', b: 'The set\'s knobs' },
  { id: 'last', label: 'Last point', b: 'Before the climb' },
];

export function abSwitch(rt) {
  const { ctx, loop } = rt;
  const { engine, store } = ctx;
  const st = {
    run: 'off',             // off | alt | A | B
    mode: 'render', period: 1, match: true,
    plan: new Map(),        // bar -> {side, when, g}
    timers: new Set(),
    gB: 1,                  // B's matching gain (linear)
    pA: 0, pB: 0, nA: 0, nB: 0,
    snapA: null, snapB: null, side: 'A', prevUseMix: false, swapping: false,
  };

  // --- the view ----------------------------------------------------------------------------------------------
  const tile = (side, what) => h('button', { type: 'button', class: `mx-ab-tile is-${side.toLowerCase()}`, 'aria-label': `Hold ${side}` },
    h('b', { text: side }), h('span', { class: 'mx-ab-what' }, h('span', { class: 'mx-ab-name', text: what }), h('em', { text: '' }), h('small', { text: '' })));
  const tA = tile('A', 'Your mix'), tB = tile('B', '');
  const readA = tA.querySelector('em'), readB = tB.querySelector('em'), matchB = tB.querySelector('small');
  const ring = h('i', { class: 'mx-ab-ring' });
  const centreText = h('span', { class: 'mx-ab-state', text: 'A/B' });
  const centreSub = h('span', { class: 'mx-ab-sub' });
  const centre = h('button', { type: 'button', class: 'mx-ab-go', 'aria-label': 'Switch between A and B on the grid' }, ring, centreText, centreSub);
  const chip = (text, onclick) => h('button', { type: 'button', class: 'mx-chip', text, onclick });
  const modeChips = MODES.map((m) => chip(m.label, () => setMode(m.id)));
  const perChips = [1, 2].map((n) => chip(n === 1 ? '1 bar' : '2 bars', () => { st.period = n; haptic(); render(); }));
  const matchChip = chip('Match', () => { st.match = !st.match; haptic(); render(); });
  const el = h('section', { class: 'mx-ab', 'aria-label': 'A/B', dataset: { side: 'A' } },
    h('div', { class: 'mx-ab-row' }, tA, centre, tB),
    h('div', { class: 'mx-ab-opts' }, h('div', { class: 'mx-seg' }, ...modeChips), h('div', { class: 'mx-seg' }, ...perChips), matchChip));

  const render = () => {
    tB.querySelector('.mx-ab-name').textContent = MODES.find((m) => m.id === st.mode).b;
    modeChips.forEach((c, i) => { c.classList.toggle('is-on', MODES[i].id === st.mode); c.disabled = MODES[i].id === 'last' && !rt.lastClimb; });
    perChips.forEach((c, i) => c.classList.toggle('is-on', st.period === i + 1));
    matchChip.classList.toggle('is-on', st.match);
    tA.classList.toggle('is-held', st.run === 'A');
    tB.classList.toggle('is-held', st.run === 'B');
    centre.classList.toggle('is-on', st.run === 'alt');
    el.classList.toggle('is-running', st.run !== 'off');
    const every = `every ${st.period === 1 ? 'bar' : '2 bars'}`;
    centreText.textContent = st.run === 'alt' ? 'Stop' : 'A/B';
    centreSub.textContent = st.run === 'A' || st.run === 'B' ? `holding ${st.run}` : every;
  };
  rt.renderAB = render;

  // --- switching ---------------------------------------------------------------------------------------------
  const skip = (id) => /^mix\.(mute|solo)/.test(id);
  const knobIds = () => {
    if (st.mode === 'knobs') return ctx.params.list.filter((p) => !skip(p.id) && !store.isSet(p.id)).map((p) => p.id);
    if (st.mode === 'last' && rt.lastClimb) return Object.keys(rt.lastClimb).filter((id) => !skip(id) && Math.abs(rt.lastClimb[id] - store.get(id)) > 1e-6);
    return [];
  };

  const write = (snap) => {
    st.swapping = true;
    try { for (const [id, v] of Object.entries(snap)) store.set(id, v, { source: 'ab', record: false }); } finally { st.swapping = false; }
  };
  const swapTo = (side) => {
    if (!st.snapA || st.side === side) return;
    st.side = side;
    write(side === 'B' ? st.snapB : st.snapA);
  };

  const plan = (bar, when) => {
    const side = st.run === 'alt' ? (Math.floor(bar / st.period) % 2 ? 'B' : 'A') : st.run;
    const g = side === 'B' && st.match ? st.gB : 1;
    const gain = engine.master.out.gain;
    gain.cancelScheduledValues(when);
    gain.setValueAtTime(g, when);
    st.plan.set(bar, { side, when, g });
    for (const k of st.plan.keys()) if (k < bar - 4) st.plan.delete(k);
    if (st.mode === 'render') engine.stems.useMix = side === 'B';
    else {
      const timer = setTimeout(() => { st.timers.delete(timer); if (st.run !== 'off') swapTo(side); },
        Math.max(0, (when - engine.ctx.currentTime) * 1000 - 4));
      st.timers.add(timer);
    }
  };

  ctx.own(engine.onBar((bar, when) => { if (st.run !== 'off') plan(bar + 1, when + engine.barSeconds); }));
  ctx.own(engine.onStop(() => stop()));

  const start = async (run) => {
    if (!engine.ctx) { toast('Start the engine first'); return; }
    const fresh = st.run === 'off';
    if (fresh) {
      if (st.mode !== 'render') {
        const ids = knobIds();
        if (!ids.length) { toast(st.mode === 'knobs' ? 'Nothing has moved from the set yet' : 'No joint climb to compare yet'); return; }
        st.snapA = store.snapshot(ids);
        st.snapB = st.mode === 'knobs'
          ? Object.fromEntries(ids.map((id) => [id, setNorm(ctx.params.get(id))]))
          : Object.fromEntries(ids.map((id) => [id, rt.lastClimb[id]]));
        st.side = 'A';
      } else st.prevUseMix = engine.stems.useMix;
    }
    st.run = run;
    if (!engine.playing) await engine.start();
    if (fresh) {
      // bars already scheduled keep what they play; the first free bar is planned now, the rest by onBar
      const bs = engine.barSeconds, pos = engine.position();
      const first = Math.ceil(engine.nextStep / 16);
      const now = st.mode === 'render' ? (engine.stems.useMix ? 'B' : 'A') : st.side;
      for (let b = pos.bar; b < first; b++) st.plan.set(b, { side: now, when: engine.t0 + b * bs, g: 1 });
      plan(first, engine.t0 + first * bs);
    } else {
      // a new hold or a restart of the switching: re-plan the first free bar
      const first = Math.ceil(engine.nextStep / 16);
      plan(first, engine.t0 + first * engine.barSeconds);
    }
    render();
  };

  const stop = (keepId) => {
    if (st.run === 'off') return;
    st.run = 'off';
    for (const t of st.timers) clearTimeout(t);
    st.timers.clear();
    if (engine.ctx) {
      const gain = engine.master.out.gain, now = engine.ctx.currentTime;
      gain.cancelScheduledValues(now);
      gain.setTargetAtTime(1, now, 0.02);
    }
    if (st.mode === 'render') engine.stems.useMix = st.prevUseMix;
    else if (st.snapA && st.side === 'B') {
      const back = { ...st.snapA };
      if (keepId) delete back[keepId];
      write(back);
    }
    st.side = 'A';
    st.snapA = st.snapB = null;
    st.plan.clear();
    render();
  };

  const setMode = (id) => {
    if (id === 'last' && !rt.lastClimb) return;
    const was = st.run;
    stop();
    st.mode = id; st.pA = st.pB = st.nA = st.nB = 0; st.gB = 1;
    readA.textContent = readB.textContent = matchB.textContent = '';
    haptic(); render();
    if (was !== 'off') start(was);
  };

  // a hand on a control the A/B is switching ends the A/B, and keeps that hand's value
  ctx.own(store.onAny((id, _v, source) => {
    if (st.run === 'off' || st.swapping || st.mode === 'render' || source === 'ab') return;
    if (st.snapA && id in st.snapA) { stop(id); toast('A/B stopped: you moved a control it was switching'); }
  }));

  const press = (run) => {
    haptic(true);
    if (st.run === run) { stop(); return; }
    start(run);
  };
  centre.addEventListener('click', () => press('alt'));
  tA.addEventListener('click', () => press('A'));
  tB.addEventListener('click', () => press('B'));

  // --- level match -------------------------------------------------------------------------------------------
  rt.meterFns.add((msg) => {
    if (st.run === 'off' || !engine.playing || !(msg.ms > 1e-9)) return;
    const bs = engine.barSeconds;
    const t1 = msg.t, t0 = t1 - 0.1;
    const bar = Math.floor((t0 - engine.t0) / bs);
    if (Math.floor((t1 - engine.t0) / bs) !== bar || t0 - (engine.t0 + bar * bs) < 0.06) return;
    const p = st.plan.get(bar);
    if (!p) return;
    const raw = msg.ms / (p.g * p.g);
    const a = 0.05;
    if (p.side === 'A') { st.pA = st.nA ? st.pA + (raw - st.pA) * a : raw; st.nA++; }
    else { st.pB = st.nB ? st.pB + (raw - st.pB) * a : raw; st.nB++; }
    if (st.nA > 6 && st.nB > 6) {
      const want = Math.min(4, Math.max(0.25, Math.sqrt(st.pA / st.pB)));
      st.gB += (want - st.gB) * 0.25;
    }
    const L = (pw, n) => (n ? `${fmt(-0.691 + 10 * Math.log10(pw))} LUFS` : '');
    const off = 20 * Math.log10(st.gB);
    readA.textContent = L(st.pA, st.nA);
    readB.textContent = L(st.pB, st.nB);
    matchB.textContent = st.match && st.nA > 6 && st.nB > 6 ? `played ${fmt(off, 1, true)} dB` : st.match ? 'matching…' : 'not matched';
  });
  rt.abState = st;

  // --- the lights --------------------------------------------------------------------------------------------
  loop.add({
    el,
    draw() {
      const pos = engine.position();
      const p = st.run !== 'off' ? st.plan.get(pos.bar) : null;
      const side = p?.side ?? (engine.stems.useMix ? 'B' : 'A');
      if (el.dataset.side !== side) el.dataset.side = side;
      const frac = st.run === 'alt' ? ((pos.bar % st.period) + pos.phase) / st.period : pos.phase;
      ring.style.setProperty('--p', `${(frac * 360).toFixed(1)}deg`);
    },
  });

  render();
  return { el, stop, render };
}
