// The aspects: the six things the experiments climbed, as a spider with six axes. On each axis 0 is the set and 1
// is the climb's best (the values below, from the brief, params.json's tried ranges and the climbs' best.json).
// Drag a vertex along its axis and that aspect's knobs morph between the two, all of them at once, one undo step
// a drag. Tap a vertex: that aspect on or off. Long press: the inspector for its first knob. Several aspects live
// on the kick stage; their knobs are shared, so the kick surface moves with this one.
//
// Joint climb: every knob of every aspect nudged at random inside its own set-to-best range, on the next downbeat,
// so the A/B can compare it with the point before ("Last point"). Back: return to that point.

import { drag, h, haptic, inspect, longPress, toast } from '../ui.js';
import { format, setNorm, toNorm, toReal } from '../params.js';
import { canvas, fit, rgba, scrollable } from './util.js';

// names that say whose knob it is where the param's own label does not
const NAMES = {
  'kick.air': 'Kick bus high shelf (5 kHz)', 'kick.colour': 'Kick bus colour boost', 'kick.colourFreq': 'Kick bus colour frequency',
  'kick.thresh': 'Kick bus compressor threshold', 'kick.ratio': 'Kick bus compressor ratio', 'kick.cattack': 'Kick bus compressor attack',
  'kick.release': 'Kick bus compressor release', 'kick.cmix': 'Kick bus compressor dry/wet', 'kick.sub35': 'Kick bus 35 Hz shelf (second EQ)',
};

export const ASPECTS = [
  {
    id: 'colour', label: 'Colour', b6: true,
    params: [['kick.colourFreq', 2184], ['kick.colour', 7.58], ['kick.air', -11.57], ['mix.hatsBell', 4.01], ['rumble.air', -6.82], ['mix.hatsAir', -2.34]],
    note: 'Colour climb (batch 6): the kick bus bell from 484 Hz to 2.2 kHz and +5.8 to +7.6 dB, its 5 kHz shelf to -11.6 dB, perc 2 +4 dB at 1 kHz, the rumble -6.8 dB at 5 kHz. The mids sit 6-8 dB under the references; "colour should bring it forward".',
  },
  {
    id: 'space', label: 'Space', b6: true,
    params: [['mix.spaceMix', 42.7], ['mix.spaceFeedback', 83.5], ['mix.spaceDelay', 36.5], ['mix.spaceDensity', 98.4], ['mix.spaceHighCut', 64.9]],
    note: 'Space climb (batch 6): Supermassive on perc 2, mix 28 to 43%, feedback 0 to 84%, delay 7 to 37%, density 91 to 98%, high cut 43 to 65%. The aspect Anthony preferred.',
  },
  {
    id: 'mono', label: 'Mono low', b6: true,
    params: [['mix.bassMono', 1, 0.02], ['mix.monoFreq', 169.3], ['rumble.mono', 1, 0.02]],
    note: 'Mono-low climb (batch 6): the Main\'s bass mono on, below 169 Hz, and the rumble\'s bass mono on. Below 120 Hz the references correlate 0.99-1.00; HW002 0.88.',
  },
  {
    id: 'drop', label: 'Drop power',
    params: [['mix.clipDrive', 8.9], ['kick.cmix', 36], ['kick.thresh', -15.47], ['kick.ratio', 2], ['kick.cattack', 0.5], ['kick.release', 40]],
    note: 'Offline (batch 5) on the drum bus: 8.9 dB of soft clip, then 36% of a 2:1 compressor at -10 dB, 0.5 ms attack, 40 ms release. Here: the master clipper and the kick group\'s compressor. Block crest: refs 4.4-6.6 dB, the set 8.7.',
  },
  {
    id: 'dist', label: 'Kick dist', zone: { id: 'kick.drive', lo: 37, hi: 50 },
    params: [['kick.drive', 50], ['rumble.drive', 50]],
    note: 'Batch 7.1: COLDFIRE on the kick bus and the Decapitator on the rumble, moved together. 37% and 50% were best, 77% and 100% worse: the target is 37-50%. Offline the win was mid only, clean below 60 Hz.',
  },
  {
    id: 'sub', label: 'Deep sub', b6: true,
    params: [['kick.sub30', 4.75], ['rumble.sub', 2.98], ['kick.sub35', 0.21]],
    note: 'Deep-sub climb (batch 6): the kick bus 30 Hz shelf -14.75 to +4.75 dB, the rumble\'s 31 Hz shelf -14.3 to +3.0 dB. At 25-40 Hz the references sit 7-9 dB above HW002.',
  },
];

export function aspects(rt) {
  const { ctx, C, loop } = rt;
  const { store, params, engine } = ctx;
  // each knob: [id, best, toggle threshold] -> {p, id, a (set, norm), b (best, norm), at}
  const A = ASPECTS.map((x) => ({
    ...x,
    knobs: x.params.map(([id, best, at]) => {
      const p = params.get(id);
      return { id, p, a: setNorm(p), b: toNorm(p, best), toggle: p.scale === 'toggle' || p.scale === 'enum', at: at ?? 0.5, best };
    }),
    t: 0, last: 1,
  }));
  for (const x of A) if (x.zone) { const k = x.knobs.find((q) => q.id === x.zone.id); x.zoneT = [(toNorm(k.p, x.zone.lo) - k.a) / (k.b - k.a), 1]; }
  const allIds = A.flatMap((x) => x.knobs.map((k) => k.id));

  /** Where the store puts an aspect: the mean position of its continuous knobs between set and best. */
  const measure = (x) => {
    const cont = x.knobs.filter((k) => !k.toggle);
    const ts = cont.map((k) => (Math.abs(k.b - k.a) < 1e-6 ? 0 : (store.get(k.id) - k.a) / (k.b - k.a)));
    const t = ts.reduce((s, v) => s + v, 0) / Math.max(1, ts.length);
    const spread = Math.max(...ts) - Math.min(...ts);
    const togglesOk = x.knobs.filter((k) => k.toggle).every((k) => (store.get(k.id) > 0.5) === (Math.max(0, t) >= k.at));
    return { t, spread, partial: spread > 0.08 || !togglesOk };
  };
  const remeasure = () => { for (const x of A) if (x !== active) Object.assign(x, measure(x)); };

  /** Put an aspect at t: every knob a fraction t of the way from the set to the best. */
  const place = (x, t) => {
    x.t = t;
    for (const k of x.knobs) {
      const v = k.toggle ? (t >= k.at ? k.b : k.a) : k.a + (k.b - k.a) * t;
      store.set(k.id, v, { source: 'aspect' });
    }
    x.partial = false; x.spread = 0;
  };

  // --- view ------------------------------------------------------------------------------------------------------
  const cv = canvas('mx-radar', loop);
  const title = h('b', { class: 'mx-asp-name' });
  const pct = h('span', { class: 'mx-asp-pct lcd-s' });
  const list = h('div', { class: 'mx-asp-knobs' });
  const note = h('p', { class: 'mx-asp-note' });
  const card = h('div', { class: 'mx-asp-card' }, h('div', { class: 'mx-asp-top' }, title, pct), list, note);
  const btn = (text, fn, cls = '') => h('button', { type: 'button', class: `mx-chip ${cls}`, text, onclick: () => { haptic(true); fn(); } });
  const backBtn = btn('Back', () => back());
  const tiltBtn = h('button', { type: 'button', class: 'mx-chip mx-tilt', 'aria-pressed': 'false', onclick: () => { haptic(true); toggleTilt(); } },
    h('i'), 'Tilt');
  const acts = h('div', { class: 'mx-asp-acts' },
    btn('The set', () => all(() => 0, 'Every aspect: the set')),
    btn('Batch 6: all four', () => all((x) => (x.b6 ? 1 : x.t), 'Deep sub, mono low, colour, space: the batch 6 best')),
    btn('Joint climb', () => climb(), 'is-hot'),
    backBtn, tiltBtn);
  const el = h('section', { class: 'rack mx-aspects' },
    h('div', { class: 'rack-head' }, h('span', { class: 'rack-title', text: 'The aspects' }), h('span', { class: 'rack-sub', text: '0 = the set, 1 = the climb\'s best' })),
    h('div', { class: 'mx-radar-box' }, cv),
    card, acts,
    h('p', { class: 'rack-note mx-honest', text: 'By ear (batch 6), all four together beat the set and no single one did on its own. Measured, the gains do not stack: each climb moved its own meter, and together they do not add up. Trust the A/B.' }));

  let sel = A[0], active = null;
  const showCard = () => {
    title.textContent = sel.label;
    pct.textContent = `${Math.round(Math.max(0, sel.tiltT ?? sel.t) * 100)}%`;
    list.replaceChildren(...sel.knobs.map((k) => {
      const now = toReal(k.p, store.live(k.id));
      return h('div', { class: `mx-asp-knob${store.isSet(k.id) ? ' is-set' : ''}` },
        h('span', { text: NAMES[k.id] ?? k.p.label }), h('b', { text: format(k.p, now) }),
        h('i', { text: `best ${format(k.p, k.best)}` }));
    }));
    note.textContent = sel.note;
  };

  // geometry
  let G = null;
  const geo = (w, hh) => {
    const cx = w / 2, cy = hh / 2 + 2, R = Math.min(w / 2 - 54, hh / 2 - 46), r0 = Math.max(30, R * 0.26);
    return { cx, cy, R, r0, axes: A.map((x, i) => { const ang = -Math.PI / 2 + i * Math.PI / 3; return { x, ux: Math.cos(ang), uy: Math.sin(ang) }; }) };
  };
  const at = (ax, t) => [G.cx + ax.ux * (G.r0 + (G.R - G.r0) * t), G.cy + ax.uy * (G.r0 + (G.R - G.r0) * t)];

  // --- touch ---------------------------------------------------------------------------------------------------
  const nearest = (e) => {
    if (!G) return null;
    const r = cv.getBoundingClientRect();
    const px = e.clientX - r.left, py = e.clientY - r.top;
    let best = null, bd = Infinity;
    for (const ax of G.axes) {
      const [vx, vy] = at(ax, Math.max(0, Math.min(1, ax.x.t)));
      const d = Math.hypot(px - vx, py - vy);
      if (d < bd) { bd = d; best = ax; }
    }
    if (bd < 46) return best;
    // otherwise the axis whose direction points at the finger
    const dx = px - G.cx, dy = py - G.cy, len = Math.hypot(dx, dy);
    if (len < G.r0 || len > G.R + 40) return null;
    let ba = null, bc = -2;
    for (const ax of G.axes) { const c = (dx * ax.ux + dy * ax.uy) / len; if (c > bc) { bc = c; ba = ax; } }
    return bc > 0.9 ? ba : null;
  };
  let dragAx = null, tDrag = 0;
  const marks = (x) => [0, 0.5, 1, ...(x.zoneT ?? [])];
  drag(cv, {
    onStart: (e) => {
      dragAx = nearest(e);
      if (!dragAx) return;
      active = dragAx.x; sel = active; tDrag = Math.max(0, Math.min(1, active.t));
      store.begin();
      showCard();
    },
    onMove: (dx, dy) => {
      if (!dragAx) return;
      const x = dragAx.x;
      const was = tDrag;
      tDrag = Math.max(0, Math.min(1, tDrag + (dx * dragAx.ux + dy * dragAx.uy) / (G.R - G.r0)));
      if (marks(x).some((m) => (was - m) * (tDrag - m) < 0 || (tDrag === m && was !== m))) haptic();
      place(x, tDrag);
      showCard();
    },
    onEnd: (_e, moved) => {
      if (!dragAx) return;
      if (moved && tDrag > 0.02) dragAx.x.last = tDrag;
      store.end();
      active = null; dragAx = null;
    },
    onTap: (e) => {
      const ax = nearest(e);
      if (!ax) return;
      const x = ax.x;
      sel = x;
      store.begin();
      place(x, x.t > 0.02 ? 0 : (x.last || 1));
      store.end();
      haptic(true);
      showCard();
    },
  });
  longPress(cv, (e) => { const ax = nearest(e); if (ax) inspect(ax.x.knobs[0].id); });
  scrollable(cv, (e) => !!nearest(e));

  const all = (fn, msg) => {
    store.begin();
    for (const x of A) place(x, Math.max(0, Math.min(1, fn(x))));
    store.end();
    toast(msg);
    showCard();
  };

  // --- the joint climb ---------------------------------------------------------------------------------------------
  const trail = [];
  let pending = null;
  const climb = () => {
    const before = store.snapshot(allIds);
    const next = {};
    for (const x of A) {
      const cont = x.knobs.filter((k) => !k.toggle);
      let sum = 0;
      for (const k of cont) {
        const u = Math.abs(k.b - k.a) < 1e-6 ? 0 : (store.get(k.id) - k.a) / (k.b - k.a);
        const u2 = Math.max(0, Math.min(1, Math.max(0, Math.min(1, u)) + (Math.random() * 2 - 1) * 0.35));
        next[k.id] = k.a + (k.b - k.a) * u2;
        sum += u2;
      }
      const t = sum / Math.max(1, cont.length);
      for (const k of x.knobs.filter((q) => q.toggle)) next[k.id] = t >= k.at ? k.b : k.a;
    }
    const go = () => {
      pending = null;
      trail.push(A.map((x) => Math.max(0, Math.min(1, x.t))));
      if (trail.length > 6) trail.shift();
      store.apply(next, { source: 'climb' });
      rt.lastClimb = before;
      rt.renderAB?.();
      remeasure(); showCard();
      backBtn.disabled = false;
      toast('Joint climb: a new point. A/B it against "Last point"');
    };
    if (engine.playing && engine.ctx) { pending = go; toast('Joint climb: on the next downbeat'); } else go();
  };
  ctx.own(engine.onBar((_bar, when) => {
    if (!pending) return;
    const fn = pending; pending = null;
    setTimeout(fn, Math.max(0, (when - engine.ctx.currentTime) * 1000));
  }));
  const back = () => {
    if (!rt.lastClimb) { toast('No climb to go back from'); return; }
    rt.stopAB?.();
    store.apply(rt.lastClimb, { source: 'climb' });
    rt.lastClimb = null;
    trail.pop();
    rt.renderAB?.();
    backBtn.disabled = true;
    remeasure(); showCard();
    toast('Back to the point before the climb');
  };
  backBtn.disabled = true;

  // --- tilt: the phone as a joystick over colour (roll right) and space (tip the top away) --------------------------
  // Live while on, as modulation over the knobs (nothing saved); turning it off keeps where you are as one undo step.
  const tilt = { on: false, b0: null, g0: null, base: {}, heard: false, timer: 0 };
  const TILT = { colour: A.find((x) => x.id === 'colour'), space: A.find((x) => x.id === 'space') };
  const tiltIds = [...TILT.colour.knobs, ...TILT.space.knobs].map((k) => k.id);
  const onOrient = (e) => {
    if (!tilt.on || e.beta == null || e.gamma == null) return;
    tilt.heard = true;
    if (tilt.b0 == null) { tilt.b0 = e.beta; tilt.g0 = e.gamma; }
    const tc = Math.max(0, Math.min(1, tilt.base.colour + (e.gamma - tilt.g0) / 30));
    const tsp = Math.max(0, Math.min(1, tilt.base.space + (tilt.b0 - e.beta) / 30));
    for (const [x, t] of [[TILT.colour, tc], [TILT.space, tsp]]) {
      x.tiltT = t;
      for (const k of x.knobs) store.modulate(k.id, (k.toggle ? (t >= k.at ? k.b : k.a) : k.a + (k.b - k.a) * t) - store.get(k.id), 'tilt');
    }
    const now = performance.now();
    if (now - (tilt.shown ?? 0) > 120) { tilt.shown = now; if (sel === TILT.colour || sel === TILT.space) showCard(); }
  };
  const tiltOff = (keep) => {
    if (!tilt.on) return;
    tilt.on = false;
    clearTimeout(tilt.timer);
    window.removeEventListener('deviceorientation', onOrient);
    if (keep && tilt.heard) {
      store.begin();
      for (const id of tiltIds) store.set(id, store.live(id), { source: 'tilt' });
      store.end();
    }
    for (const id of tiltIds) store.modulate(id, 0, 'tilt');
    TILT.colour.tiltT = TILT.space.tiltT = undefined;
    tiltBtn.classList.remove('is-on'); tiltBtn.setAttribute('aria-pressed', 'false');
    remeasure(); showCard();
  };
  const toggleTilt = async () => {
    if (tilt.on) { tiltOff(true); toast('Tilt off: kept where you were'); return; }
    const DOE = window.DeviceOrientationEvent;
    if (!DOE) { toast('No tilt sensor here'); return; }
    if (typeof DOE.requestPermission === 'function') {
      try { if ((await DOE.requestPermission()) !== 'granted') { toast('Tilt needs motion access'); return; } } catch { toast('Tilt needs motion access'); return; }
    }
    Object.assign(tilt, { on: true, b0: null, g0: null, heard: false, base: { colour: Math.max(0, Math.min(1, TILT.colour.t)), space: Math.max(0, Math.min(1, TILT.space.t)) } });
    window.addEventListener('deviceorientation', onOrient);
    tiltBtn.classList.add('is-on'); tiltBtn.setAttribute('aria-pressed', 'true');
    toast('Tilt right: more colour. Tip the top away: more space');
    tilt.timer = setTimeout(() => { if (tilt.on && !tilt.heard) { tiltOff(false); toast('No tilt sensor answered'); } }, 2500);
  };
  ctx.own(() => tiltOff(false));

  // follow the store: any of these knobs moved elsewhere re-measures its aspect
  const watched = new Set(allIds);
  ctx.own(store.onAny((id, _v, source) => { if (watched.has(id) && source !== 'aspect' && source !== 'tilt') { remeasure(); if (!active) showCard(); } }));
  remeasure();
  showCard();

  // --- draw ----------------------------------------------------------------------------------------------------------
  loop.add({
    el: cv,
    draw() {
      const { g, w, h: hh } = fit(loop, cv);
      if (!w) return;
      G = geo(w, hh);
      const pos = engine.position();
      const beat = pos.playing ? (pos.phase * 4) % 1 : 1;
      const pulse = Math.pow(1 - beat, 3);
      g.clearRect(0, 0, w, hh);
      // rings
      g.lineWidth = 1;
      for (const t of [0, 0.25, 0.5, 0.75, 1]) {
        g.beginPath();
        G.axes.forEach((ax, i) => { const [x, y] = at(ax, t); if (i) g.lineTo(x, y); else g.moveTo(x, y); });
        g.closePath();
        g.strokeStyle = t === 1 ? rgba(C.text, 0.32) : t === 0 ? rgba(C.acid, 0.85) : 'rgba(255,255,255,0.07)';
        g.setLineDash(t === 1 ? [4, 4] : []);
        g.lineWidth = t === 0 ? 1.5 : 1;
        g.stroke();
      }
      g.setLineDash([]);
      // axes and target zones
      for (const ax of G.axes) {
        const [x0, y0] = at(ax, 0), [x1, y1] = at(ax, 1);
        g.strokeStyle = 'rgba(255,255,255,0.12)'; g.lineWidth = 1;
        g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.stroke();
        if (ax.x.zoneT) {
          const [za, zb] = ax.x.zoneT;
          const [xa, ya] = at(ax, za), [xb, yb] = at(ax, zb);
          g.strokeStyle = rgba(C.cold, 0.55); g.lineWidth = 7; g.lineCap = 'round';
          g.beginPath(); g.moveTo(xa, ya); g.lineTo(xb, yb); g.stroke();
          g.lineCap = 'butt';
        }
      }
      // the trail of earlier climb points
      trail.forEach((pt, j) => {
        g.beginPath();
        G.axes.forEach((ax, i) => { const [x, y] = at(ax, pt[i]); if (i) g.lineTo(x, y); else g.moveTo(x, y); });
        g.closePath();
        g.strokeStyle = rgba(C.cold, 0.12 + 0.08 * (j / Math.max(1, trail.length)));
        g.lineWidth = 1; g.stroke();
      });
      // the shape now
      const ts = G.axes.map((ax) => Math.max(0, Math.min(1, ax.x === active ? tDrag : ax.x.tiltT ?? ax.x.t)));
      g.beginPath();
      G.axes.forEach((ax, i) => { const [x, y] = at(ax, ts[i]); if (i) g.lineTo(x, y); else g.moveTo(x, y); });
      g.closePath();
      const grad = g.createRadialGradient(G.cx, G.cy, G.r0, G.cx, G.cy, G.R);
      grad.addColorStop(0, rgba(C.hazard, 0.05));
      grad.addColorStop(1, rgba(C.hazard, 0.22 + 0.16 * pulse));
      g.fillStyle = grad; g.fill();
      g.strokeStyle = C.hazard; g.lineWidth = 2; g.shadowColor = C.hazard; g.shadowBlur = 8 + 6 * pulse; g.stroke();
      g.shadowBlur = 0;
      // vertices and labels
      g.textBaseline = 'middle';
      G.axes.forEach((ax, i) => {
        const x = ax.x, t = ts[i];
        const [vx, vy] = at(ax, t);
        const on = x === active || x === sel;
        g.beginPath(); g.arc(vx, vy, on ? 11 : 9, 0, Math.PI * 2);
        g.fillStyle = x.partial ? '#111214' : '#2a2d33'; g.fill();
        g.lineWidth = on ? 3 : 2; g.strokeStyle = x.partial ? rgba(C.hazard, 0.7) : C.hazard; g.stroke();
        if (!x.partial) { g.beginPath(); g.arc(vx, vy, 3, 0, Math.PI * 2); g.fillStyle = on ? C.lcd : C.hazard; g.fill(); }
        // label and value beyond the best ring, clear of the handle
        const top = ax.uy < -0.9, bottom = ax.uy > 0.9, right = ax.ux > 0.2;
        let lx, ly1, ly2;
        if (top) { lx = G.cx; ly1 = G.cy - G.R - 31; ly2 = G.cy - G.R - 18; g.textAlign = 'center'; }
        else if (bottom) { lx = G.cx; ly1 = G.cy + G.R + 22; ly2 = G.cy + G.R + 35; g.textAlign = 'center'; }
        else { lx = G.cx + ax.ux * (G.R + 17); ly1 = G.cy + ax.uy * G.R - 7; ly2 = ly1 + 13; g.textAlign = right ? 'left' : 'right'; }
        const label = x.label.toUpperCase();
        g.font = '700 10px ui-monospace, Menlo, monospace';
        g.fillStyle = on ? C.text : C.text2;
        g.fillText(label, lx, ly1);
        if (x.b6) {
          const lw = g.measureText(label).width;
          const bx = g.textAlign === 'center' ? lx + lw / 2 + 4 : right ? lx + lw + 4 : lx - lw - 4;
          const al = g.textAlign;
          g.textAlign = right || al === 'center' ? 'left' : 'right';
          g.font = '700 7.5px ui-monospace, Menlo, monospace'; g.fillStyle = rgba(C.cold, 0.85);
          g.fillText('B6', bx, ly1);
          g.textAlign = al;
        }
        g.font = '600 11px ui-monospace, Menlo, monospace';
        g.fillStyle = t < 0.005 ? C.acid : C.lcd;
        g.fillText(t < 0.005 ? 'SET' : `${Math.round(t * 100)}%`, lx, ly2);
      });
      g.textAlign = 'left';
    },
  });
  return { el };
}
