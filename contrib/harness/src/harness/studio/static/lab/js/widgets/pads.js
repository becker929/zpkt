// padGrid(ctx, ids, {cols, depth, decay, labels, label, onHit}) -> element
//
// A grid of rubber pads, one per param: hit a pad and its param is thrown up (a stab of modulation on top of the
// knob, not saved) and falls back over `decay` beats. Where you hit sets the velocity: the centre of the pad is full
// force, the rim soft (a ring ripples out from the finger, the pad glows with the throw). Hold a pad and the throw
// holds; let go and it falls. Several fingers play several pads. A pad can be null (it only calls onHit).
//
//   cols    pads per row (default 4)
//   depth   the full-force throw, 0..1 of each param's range (default 0.6)
//   decay   beats to fall back (default 1)
//   onHit   fn(index, velocity, id) on every hit (a surface can trigger its own sound)
// Long press the title: choose a pad's param to inspect.

import { h, haptic, longPress } from '../ui.js';
import { shortLabel, stageColor } from './core.js';
import { chooser, modSource, tick } from './kit.js';

export function padGrid(ctx, ids, { cols = 4, depth = 0.6, decay = 1, labels, label = 'pads', onHit } = {}) {
  const mod = modSource(ctx, 'pads');
  const ps = ids.map((id) => (id ? ctx.params.get(id) : null));
  const lv = ids.map(() => 0), held = ids.map(() => false), shown = ids.map(() => -1);
  const vels = ids.map(() => h('span', { class: 'pad-vel' }));
  const pads = ids.map((id, i) => h('div', {
    class: 'pad', dataset: { param: id ?? '' }, style: { '--c': ps[i] ? stageColor(ps[i]) : 'var(--stage-play)' },
  }, h('span', { class: 'pad-name', text: labels?.[i] ?? (ps[i] ? shortLabel(ps[i]) : String(i + 1)) }), vels[i]));
  const title = h('div', { class: 'w-label pad-title', text: label });
  const el = h('div', { class: 'w-pads', dataset: { param: ids.filter(Boolean).join(' ') }, style: { '--cols': cols } },
    title, h('div', { class: 'pad-grid' }, ...pads));

  pads.forEach((pad, i) => {
    pad.style.touchAction = 'none';
    const fingers = new Set();
    pad.addEventListener('pointerdown', (e) => {
      try { pad.setPointerCapture(e.pointerId); } catch { /* synthetic pointer */ }
      fingers.add(e.pointerId);
      const r = pad.getBoundingClientRect();
      const x = e.clientX - r.left, y = e.clientY - r.top;
      const dist = Math.hypot(x - r.width / 2, y - r.height / 2) / Math.hypot(r.width / 2, r.height / 2);
      const vel = Math.max(0.15, Math.min(1, 1 - 0.85 * dist));
      held[i] = true;
      lv[i] = Math.max(lv[i], vel * depth);
      vels[i].textContent = String(Math.round(vel * 127));
      const ring = h('i', { class: 'pad-ring', style: { left: `${x}px`, top: `${y}px`, '--vel': vel.toFixed(2) } });
      pad.append(ring);
      setTimeout(() => ring.remove(), 520);
      pad.classList.add('is-down');
      haptic(vel > 0.6);
      if (ids[i]) mod.set(ids[i], lv[i]);
      onHit?.(i, vel, ids[i]);
    });
    const up = (e) => {
      fingers.delete(e.pointerId);
      if (fingers.size) return;
      held[i] = false;
      pad.classList.remove('is-down');
    };
    pad.addEventListener('pointerup', up);
    pad.addEventListener('pointercancel', up);
    pad.addEventListener('contextmenu', (e) => e.preventDefault());
  });
  longPress(title, () => { const list = ids.filter(Boolean); if (list.length && !ctx.local) chooser(ctx, list, label); });

  tick(ctx, (_t, dt) => {
    const tau = Math.max(0.02, (decay * (ctx.engine?.barSeconds ?? 1.5)) / 4 / 3);
    for (let i = 0; i < ids.length; i++) {
      if (!held[i] && lv[i] > 0) {
        lv[i] *= Math.exp(-dt / tau);
        if (lv[i] < 0.003) lv[i] = 0;
        if (ids[i]) mod.set(ids[i], lv[i]);
      }
      const g = Math.round((lv[i] / Math.max(0.01, depth)) * 100) / 100;
      if (g !== shown[i]) { shown[i] = g; pads[i].style.setProperty('--l', g); }
    }
  });
  return el;
}
