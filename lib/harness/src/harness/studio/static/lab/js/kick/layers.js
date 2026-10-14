// The drum rack's layers as pads: Clubby 052 (the main hit), Clubby 060 (a shorter knock), the offbeat pad, and the
// sample layer (one of HW002's own kick hits). Tap a pad to hear that layer alone, now; slide on it to set its
// level. The LED flashes when the layer plays on the grid. A ROLL pad plays 16ths while held (slide up: 32nds).

import { h, haptic, inspect, longPress, toast } from '../ui.js';
import { toNorm } from '../params.js';
import { follow, writer } from '../widgets/core.js';
import { MODE } from './rig.js';
import { panel } from './util.js';

function pad(ctx, rig, { id, name, what, layer }) {
  const p = ctx.params.get(id);
  const w = writer(ctx, id, 'pad');
  const fill = h('i', { class: 'kx-pad-fill' });
  const setMark = h('i', { class: 'kx-pad-set', style: { bottom: `${toNorm(p, p.set) * 100}%` } });
  const read = h('span', { class: 'kx-pad-v' });
  const led = h('i', { class: 'kx-pad-led' });
  const el = h('div', { class: 'kx-pad', role: 'button', tabindex: '0', 'aria-label': `${name}: tap to hear, slide for level`, dataset: { layer } },
    h('div', { class: 'kx-pad-meter' }, fill, setMark),
    h('div', { class: 'kx-pad-face' }, led, h('b', { text: name }), h('span', { class: 'kx-pad-what', text: what }), read));
  follow(ctx, id, (v, _r, text) => {
    fill.style.height = `${v * 100}%`;
    read.textContent = text;
    el.classList.toggle('is-set', ctx.store.isSet(id));
  });
  el.style.touchAction = 'none';
  let y0 = 0, x0 = 0, ly = 0, moved = false, pid = null;
  el.addEventListener('pointerdown', (e) => {
    if (pid != null) return;
    pid = e.pointerId; y0 = ly = e.clientY; x0 = e.clientX; moved = false;
    try { el.setPointerCapture(e.pointerId); } catch { /* synthetic */ }
    el.classList.add('is-down');
  });
  el.addEventListener('pointermove', (e) => {
    if (e.pointerId !== pid) return;
    if (!moved && Math.hypot(e.clientX - x0, e.clientY - y0) < 7) return;
    if (!moved) { moved = true; w.begin(); }
    w.add(-(e.clientY - ly) / 200);
    ly = e.clientY;
  });
  const up = (e) => {
    if (e.pointerId !== pid) return;
    pid = null;
    el.classList.remove('is-down');
    if (moved) { w.end(); return; }
    if (e.type !== 'pointerup') return;
    rig.audition(layer);
    haptic(true);
    flash();
  };
  el.addEventListener('pointerup', up);
  el.addEventListener('pointercancel', up);
  longPress(el, () => inspect(id));
  const flash = () => { el.classList.remove('is-hit'); void el.offsetWidth; el.classList.add('is-hit'); };
  el.flash = flash;
  return el;
}

export function layers(ctx, rig) {
  const { store, engine } = ctx;
  const p052 = pad(ctx, rig, { id: 'kick.l052', name: '052', what: 'Clubby 052 · the hit', layer: '052' });
  const p060 = pad(ctx, rig, { id: 'kick.l060', name: '060', what: 'Clubby 060 · knock', layer: '060' });
  const poff = pad(ctx, rig, { id: 'kick.offbeat', name: 'OFF', what: 'offbeat pad · 8ths', layer: 'off' });
  const psmp = pad(ctx, rig, { id: 'ks.sampleLevel', name: 'SMP', what: 'HW002 hit · stem', layer: 'sample' });
  let alive = true;
  ctx.own(() => { alive = false; });
  const at = (when, fn) => { const ms = (when - (rig.ac?.currentTime ?? 0)) * 1000; setTimeout(() => { if (alive) fn(); }, Math.max(0, ms)); };
  ctx.own(rig.on((type, d) => {
    if (type !== 'beat') return;
    const synth = rig.playing !== MODE.STEM;
    at(d.when, () => {
      if (synth) { p052.flash(); p060.flash(); }
      if (store.real('ks.sample') > 0.5) psmp.flash();
    });
    if (synth && store.real('ks.offbeatOn') > 0.5) at(d.when + engine.stepSeconds * 2, () => poff.flash());
  }));

  // the sample layer: on/off, and which of the hits
  const hits = h('div', { class: 'kx-hits', role: 'group', 'aria-label': 'Sample hit' });
  const P = ctx.params.get('ks.sampleHit');
  const wh = writer(ctx, 'ks.sampleHit', 'hits');
  const renderHits = () => {
    const n = Math.max(1, Math.min(P.options.length, rig.samples.length || P.options.length));
    const cur = Math.round(store.real('ks.sampleHit'));
    hits.replaceChildren(...Array.from({ length: n }, (_, i) => {
      const b = h('button', { type: 'button', class: `kx-hit${i === cur ? ' is-on' : ''}`, text: String(i + 1), title: rig.samples[i]?.title ?? `Hit ${i + 1}` });
      b.addEventListener('click', () => { wh.begin(); wh.set(toNorm(P, i)); wh.end(); rig.audition('sample'); psmp.flash(); haptic(); });
      return b;
    }));
  };
  ctx.own(store.on('ks.sampleHit', renderHits));
  ctx.own(rig.on((type) => { if (type === 'samples') renderHits(); }));
  const ws = writer(ctx, 'ks.sample', 'layers');
  const smpOn = h('button', { type: 'button', class: 'kx-smp-on' }, h('i', { class: 'kx-src-led' }), h('span', { text: 'SAMPLE ON EVERY BEAT' }));
  smpOn.addEventListener('click', () => { ws.begin(); ws.set(store.get('ks.sample') >= 0.5 ? 0 : 1); ws.end(); haptic(); });
  follow(ctx, 'ks.sample', (_v, real) => { smpOn.classList.toggle('is-on', real === 1); psmp.classList.toggle('is-armed', real === 1); });

  const wo = writer(ctx, 'ks.offbeatOn', 'layers');
  const offOn = h('button', { type: 'button', class: 'kx-smp-on' }, h('i', { class: 'kx-src-led' }), h('span', { text: 'OFFBEAT HITS' }));
  offOn.addEventListener('click', () => { wo.begin(); wo.set(store.get('ks.offbeatOn') >= 0.5 ? 0 : 1); wo.end(); haptic(); });
  follow(ctx, 'ks.offbeatOn', (_v, real) => { offOn.classList.toggle('is-on', real === 1); poff.classList.toggle('is-armed', real === 1); });

  // ROLL: hold for 16ths, slide up for 32nds
  const roll = h('div', { class: 'kx-roll', role: 'button', tabindex: '0', 'aria-label': 'Hold for a kick roll' },
    h('b', { text: 'ROLL' }), h('span', { class: 'kx-roll-s', text: 'HOLD · 1/16' }), h('span', { class: 'kx-roll-h', text: 'slide up: 1/32' }));
  roll.style.touchAction = 'none';
  let ry = 0, rid = null;
  const rollState = (n) => {
    rig.roll = n;
    roll.classList.toggle('is-on', n > 0);
    roll.classList.toggle('is-fast', n === 2);
    roll.querySelector('.kx-roll-s').textContent = n === 2 ? 'ROLLING · 1/32' : n === 1 ? 'ROLLING · 1/16' : 'HOLD · 1/16';
  };
  roll.addEventListener('pointerdown', (e) => {
    rid = e.pointerId; ry = e.clientY;
    try { roll.setPointerCapture(e.pointerId); } catch { /* synthetic */ }
    if (!engine.playing) toast('Press play: the roll plays on the grid');
    rollState(1); haptic(true);
  });
  roll.addEventListener('pointermove', (e) => {
    if (e.pointerId !== rid) return;
    const n = ry - e.clientY > 30 ? 2 : 1;
    if (n !== rig.roll) { rollState(n); haptic(); }
  });
  const rollUp = (e) => { if (e.pointerId !== rid) return; rid = null; rollState(0); };
  roll.addEventListener('pointerup', rollUp);
  roll.addEventListener('pointercancel', rollUp);
  ctx.own(() => { rig.roll = 0; });

  renderHits();
  return panel('Layers', { sub: 'the drum rack: tap to hear, slide for level', cls: 'kx-layers' },
    h('div', { class: 'kx-pads' }, p052, p060, poff, psmp),
    h('div', { class: 'kx-layer-row' }, offOn, smpOn),
    h('div', { class: 'kx-layer-row' }, h('span', { class: 'kx-hits-l', text: 'HIT' }), hits),
    roll,
    h('p', { class: 'rack-note', text: 'The pads play the synth\'s layers (and the stem\'s own hit for SMP) through the kick chain. The stem\'s layers are inside its audio: their levels move the stem by a share of the change.' }));
}
