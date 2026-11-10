// Space: Valhalla Supermassive on perc 2 as a room you stretch. The hall is drawn in perspective: its depth is the
// delay, the ribs are the density, the echoes bouncing between the walls are the feedback, the colour of the
// reflections is the high cut (warm = dark, ice = bright), the fog is the mix. Every hat on the perc bus sends a
// wavefront down the hall; the walls glow with what the returns actually play.
//
//   one finger: sideways = delay, up and down = feedback
//   two fingers: pinch = mix (spread = more room), slide up and down together = high cut
//   double tap: the set's room
//
// On the phone the room is the returns (the engine's reverb and tempo delay). The stems already carry the set's
// Supermassive, so at the set's values the returns are silent; the core sketch sends perc 2 to them when the mix
// goes up. Moving the room's shape alone would then be silent, so this surface adds a small send that grows with
// how far feedback, delay, density and high cut are from the set (zero at the set), so the shape is heard too.

import { doubleTap, h, haptic, toast } from '../ui.js';
import { knob } from '../widgets/knob.js';
import { writer } from '../widgets/core.js';
import { setNorm, toNorm } from '../params.js';
import { levelOf } from './taps.js';
import { canvas, fit, rgba } from './util.js';

const IDS = { mix: 'mix.spaceMix', fb: 'mix.spaceFeedback', dl: 'mix.spaceDelay', dn: 'mix.spaceDensity', hc: 'mix.spaceHighCut' };
const BEST = { 'mix.spaceMix': 42.7, 'mix.spaceFeedback': 83.5, 'mix.spaceDelay': 36.5, 'mix.spaceDensity': 98.4, 'mix.spaceHighCut': 64.9 };

export function space(rt) {
  const { ctx, C, loop } = rt;
  const { store, engine, params } = ctx;
  const cv = canvas('mx-room', loop);
  const v = (k) => store.get(IDS[k]);
  const d = (k) => store.get(IDS[k]) - setNorm(params.get(IDS[k]));

  // --- the shape heard: a send that grows with the distance from the set's room --------------------------------
  const sendShape = () => {
    if (!engine.ctx) return;
    const mixPart = Math.max(0, d('mix'));
    const a = Math.max(mixPart * 1.4, 0.32 * Math.min(1, Math.abs(d('dn')) * 3 + Math.abs(d('hc')) * 1.5 + Math.abs(d('dl')) * 0.6));
    const b = Math.max(mixPart * 0.9, 0.3 * Math.min(1, Math.abs(d('fb')) * 1.5 + Math.abs(d('dl')) * 1.5));
    const perc = engine.bus('perc');
    perc.set('sendA', a);
    perc.set('sendB', b);
  };
  for (const id of Object.values(IDS)) ctx.own(engine.sketch(id, sendShape));

  // --- gestures ------------------------------------------------------------------------------------------------
  const W = Object.fromEntries(Object.entries(IDS).map(([k, id]) => [k, writer(ctx, id, 'room')]));
  const pts = new Map();
  let mode = null, last = null, touched = null, touchedT = 0;
  const pair = () => { const [a, b] = [...pts.values()]; return { d: Math.hypot(a.x - b.x, a.y - b.y), cy: (a.y + b.y) / 2 }; };
  const mark = (k) => { touched = k; touchedT = performance.now(); };
  cv.style.touchAction = 'none';
  cv.addEventListener('pointerdown', (e) => {
    try { cv.setPointerCapture(e.pointerId); } catch { /* synthetic pointers */ }
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (!mode) store.begin();
    mode = pts.size >= 2 ? 'two' : 'one';
    last = mode === 'two' ? pair() : { x: e.clientX, y: e.clientY, id: e.pointerId };
  });
  cv.addEventListener('pointermove', (e) => {
    if (!pts.has(e.pointerId)) return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const { w, h: hh } = loop.size(cv);
    if (mode === 'one' && last?.id === e.pointerId) {
      const dx = e.clientX - last.x, dy = e.clientY - last.y;
      if (Math.abs(dx) > 0.01) { W.dl.add(dx / (w * 1.3)); mark('dl'); }
      if (Math.abs(dy) > 0.01) { W.fb.add(-dy / (hh * 1.2)); if (Math.abs(dy) > Math.abs(dx)) mark('fb'); }
      last = { x: e.clientX, y: e.clientY, id: e.pointerId };
    } else if (mode === 'two' && pts.size >= 2) {
      const p = pair();
      const dd = p.d - last.d, dc = p.cy - last.cy;
      if (Math.abs(dd) > 0.01) { W.mix.add(dd / (w * 0.9)); mark('mix'); }
      if (Math.abs(dc) > 0.01) { W.hc.add(-dc / (hh * 1.1)); if (Math.abs(dc) > Math.abs(dd)) mark('hc'); }
      last = p;
    }
  });
  const up = (e) => {
    if (!pts.delete(e.pointerId)) return;
    if (pts.size === 0) { store.end(); mode = null; last = null; return; }
    if (pts.size === 1) { const [[id, p]] = [...pts.entries()]; mode = 'one'; last = { ...p, id }; }
    else last = pair();
  };
  cv.addEventListener('pointerup', up);
  cv.addEventListener('pointercancel', up);
  doubleTap(cv, () => { store.resetAll(Object.values(IDS)); haptic(true); toast('Space: the set\'s room'); });

  // --- the room --------------------------------------------------------------------------------------------------
  const waves = [];
  const dust = Array.from({ length: 160 }, () => ({ x: Math.random() * 2 - 1, y: Math.random() * 2 - 1, z: Math.random(), s: 0.2 + Math.random() * 0.8 }));
  ctx.own(engine.onStep((step, when) => {
    if (step % 2 !== 0) return;
    waves.push({ when, amp: null, hit: step % 4 === 2 });
    if (waves.length > 48) waves.shift();
  }));
  const buf = new Float32Array(1024);
  let wetA = 0, wetB = 0, percLv = -60;
  const lerpC = (a, b, t) => {
    const pa = parseInt(a.slice(1), 16), pb = parseInt(b.slice(1), 16);
    const ch = (s) => Math.round(((pa >> s) & 255) * (1 - t) + ((pb >> s) & 255) * t);
    return `#${((ch(16) << 16) | (ch(8) << 8) | ch(0)).toString(16).padStart(6, '0')}`;
  };

  const draw = (now) => {
    const { g, w, h: hh } = fit(loop, cv);
    if (!w) return;
    const mix = v('mix'), fb = v('fb'), dl = v('dl'), dn = v('dn'), hc = v('hc');
    const col = lerpC('#ff8a3d', '#cfeeff', hc);
    const t = rt.taps, ac = engine.ctx;
    if (t && engine.playing) {
      const a = levelOf(t.retA, buf), b = levelOf(t.retB, buf);
      wetA += (Math.max(0, (a.rms + 60) / 50) - wetA) * 0.15;
      wetB += (Math.max(0, (b.peak + 60) / 50) - wetB) * 0.25;
      percLv = engine.bus('perc').level().peak;
    } else { wetA *= 0.95; wetB *= 0.9; }
    // geometry
    const fx0 = 10, fy0 = 10, fx1 = w - 10, fy1 = hh - 10;
    const vx = w / 2, vy = hh * 0.45;
    const k = 1.1 + dl * 7;
    const sc = (z) => 1 / (1 + z * k);
    const rect = (z) => { const s = sc(z); return [vx + (fx0 - vx) * s, vy + (fy0 - vy) * s, vx + (fx1 - vx) * s, vy + (fy1 - vy) * s]; };
    // background: the hall's air, thicker with more mix
    g.fillStyle = '#060708'; g.fillRect(0, 0, w, hh);
    const back = rect(1);
    const fog = g.createRadialGradient(vx, vy, 4, vx, vy, w * 0.7);
    fog.addColorStop(0, rgba(col, 0.1 + mix * 0.35 + wetA * 0.25));
    fog.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = fog; g.fillRect(0, 0, w, hh);
    // the back wall
    g.fillStyle = rgba(col, 0.06 + 0.5 * Math.min(1, wetB) * (0.3 + fb * 0.7));
    g.fillRect(back[0], back[1], back[2] - back[0], back[3] - back[1]);
    // floor and ceiling rails
    g.lineWidth = 1;
    const rails = 7;
    for (let i = 0; i <= rails; i++) {
      const u = i / rails;
      const a = rect(0), b2 = rect(1);
      g.strokeStyle = rgba(col, 0.12 + 0.1 * wetA);
      g.beginPath(); g.moveTo(a[0] + (a[2] - a[0]) * u, a[3]); g.lineTo(b2[0] + (b2[2] - b2[0]) * u, b2[3]); g.stroke();
      g.beginPath(); g.moveTo(a[0] + (a[2] - a[0]) * u, a[1]); g.lineTo(b2[0] + (b2[2] - b2[0]) * u, b2[1]); g.stroke();
    }
    // ribs: density
    const ribs = 3 + Math.round(dn * 14);
    for (let i = 1; i <= ribs; i++) {
      const z = i / ribs, r = rect(z);
      g.strokeStyle = rgba(col, (0.5 - z * 0.38) * (0.5 + wetA * 0.5));
      g.lineWidth = i === ribs ? 1.6 : 1;
      g.strokeRect(r[0], r[1], r[2] - r[0], r[3] - r[1]);
    }
    // dust: density and the room's own sound
    const nd = Math.round(30 + dn * 130);
    g.fillStyle = rgba(col, 0.35 + wetA * 0.4);
    for (let i = 0; i < nd; i++) {
      const p = dust[i];
      p.z = (p.z + 0.0007 * p.s) % 1;
      const r = rect(p.z), x = (r[0] + r[2]) / 2 + p.x * (r[2] - r[0]) / 2, y = (r[1] + r[3]) / 2 + p.y * (r[3] - r[1]) / 2;
      const s = 0.6 + (1 - p.z) * 1.2;
      g.fillRect(x, y, s, s);
    }
    // wavefronts: down the hall in `delay`, then bouncing, each bounce `feedback` as loud
    if (ac && engine.playing) {
      // the eye needs a slower wave than the ear: a pass takes the delay time, but never under 0.3 s
      const travel = Math.max(0.3, (0.25 + dl * 1.75) * 60 / engine.bpm);
      const tnow = ac.currentTime;
      for (let i = waves.length - 1; i >= 0; i--) {
        const wv = waves[i];
        const age = tnow - wv.when;
        if (age < 0) continue;
        if (wv.amp == null) wv.amp = Math.max(0.15, Math.min(1, (percLv + 30) / 24)) * (wv.hit ? 1 : 0.7);
        const bounce = Math.floor(age / travel), ph = (age % travel) / travel;
        const amp = wv.amp * Math.pow(Math.max(0.12, fb * 0.95), bounce) * (0.55 + mix * 0.9);
        if (amp < 0.02 || age > 8) { waves.splice(i, 1); continue; }
        const z = bounce % 2 === 0 ? ph : 1 - ph;
        const r = rect(z);
        g.strokeStyle = rgba(col, Math.min(1, amp));
        g.lineWidth = 1 + amp * 2.5 * (1 - z * 0.6);
        g.shadowColor = col; g.shadowBlur = 10 * amp;
        g.strokeRect(r[0], r[1], r[2] - r[0], r[3] - r[1]);
      }
      g.shadowBlur = 0;
    } else waves.length = 0;
    // the front frame
    g.strokeStyle = 'rgba(255,255,255,0.12)'; g.lineWidth = 1;
    g.strokeRect(fx0, fy0, fx1 - fx0, fy1 - fy0);
    // HUD
    const hud = [['mix', 'MIX', mix], ['fb', 'FEEDBACK', fb], ['dl', 'DELAY', dl], ['dn', 'DENSITY', dn], ['hc', 'HIGH CUT', hc]];
    g.font = '700 8.5px ui-monospace, Menlo, monospace';
    const fresh = now - touchedT < 1600;
    hud.forEach(([key, label, val], i) => {
      const on = fresh && touched === key;
      const x = 18 + (i % 3) * ((w - 36) / 3), y = i < 3 ? 26 : hh - 18;
      g.fillStyle = on ? C.lcd : C.text3; g.textAlign = 'left';
      g.fillText(label, x, y);
      g.fillStyle = store.isSet(IDS[key]) ? C.acid : C.lcd;
      g.font = '600 11px ui-monospace, Menlo, monospace';
      g.fillText(`${Math.round(val * 100)}%`, x, y + (i < 3 ? 13 : -11));
      g.font = '700 8.5px ui-monospace, Menlo, monospace';
    });
    if (!fresh && mode == null) {
      g.textAlign = 'center'; g.fillStyle = 'rgba(233,231,226,0.32)'; g.font = '600 8.5px ui-monospace, Menlo, monospace';
      g.fillText('DRAG: SIDEWAYS DELAY · UP FEEDBACK', w / 2, vy + (fy1 - vy) * 0.5);
      g.fillText('TWO FINGERS: PINCH MIX · SLIDE HIGH CUT', w / 2, vy + (fy1 - vy) * 0.5 + 12);
    }
    g.textAlign = 'left';
  };
  loop.add({ el: cv, draw });

  const go = (fn, msg) => () => { store.begin(); for (const id of Object.values(IDS)) store.set(id, fn(id), { source: 'room' }); store.end(); haptic(true); toast(msg); };
  const el = h('section', { class: 'rack mx-space' },
    h('div', { class: 'rack-head' }, h('span', { class: 'rack-title', text: 'Space' }), h('span', { class: 'rack-sub', text: 'Supermassive on perc 2, heard on the returns' })),
    h('div', { class: 'mx-room-box' }, cv),
    h('div', { class: 'mx-space-knobs' }, ...Object.values(IDS).map((id) => knob(ctx, id, { size: 46 }))),
    h('div', { class: 'mx-asp-acts' },
      h('button', { type: 'button', class: 'mx-chip', text: 'The set\'s room', onclick: go((id) => setNorm(params.get(id)), 'Space: the set') }),
      h('button', { type: 'button', class: 'mx-chip is-hot', text: 'The space climb\'s best', onclick: go((id) => toNorm(params.get(id), BEST[id]), 'Space: the climb\'s best (mix 43%, feedback 84%, delay 37%)') })),
    h('p', { class: 'rack-note', text: 'Batch 6: space is the aspect Anthony preferred. The climb went from mix 28% to 43%, feedback 0 to 84%, delay 7 to 37%, density 91 to 98%, high cut 43 to 65%. "Colour and space need synths": in HW002 the synths play only in the break, so judge it on a loop with them too.' }));
  return { el, stop() { waves.length = 0; } };
}
