// The radial (pie) menu, two ways:
//
// pie(x, y, items, {title, current}) -> Promise<index | -1>
//   A pie of up to 12 wedges around a screen point. Press, slide into a wedge and let go to pick (one gesture), or
//   tap to open it and tap a wedge. The centre, outside, or Escape cancels (-1). A haptic tick on every wedge.
//   The promise has .cancel() to close it from outside (a surface unmounting).
//
// radial(ctx, id, {label, size}) -> element
//   An enum or on/off param as a round hardware button that shows its option; press and slide to pick another from
//   a pie of all of them (the set's option is marked acid in the pie). Long press without sliding: the inspector.

import { h, haptic, inspect, s } from '../ui.js';
import { follow, shortLabel, stageColor, writer } from './core.js';
import { setNorm } from '../params.js';

const R0 = 34;

export function pie(x, y, items, { title, current = -1, marked = -1 } = {}) {
  let resolve, done = false;
  const pr = new Promise((r) => { resolve = r; });
  const n = Math.max(1, Math.min(12, items.length));
  const R = n > 8 ? 136 : 118;
  const vw = innerWidth, vh = innerHeight;
  const cx = Math.max(R + 8, Math.min(vw - R - 8, x)), cy = Math.max(R + 8, Math.min(vh - R - 8, y));
  const span = (Math.PI * 2) / n;
  const wedge = (i) => {
    const a0 = -Math.PI / 2 + i * span - span / 2 + 0.03, a1 = a0 + span - 0.06;
    const p = (r, a) => `${(cx + r * Math.cos(a)).toFixed(1)} ${(cy + r * Math.sin(a)).toFixed(1)}`;
    const large = span > Math.PI ? 1 : 0;
    return `M${p(R0 + 4, a0)}L${p(R, a0)}A${R} ${R} 0 ${large} 1 ${p(R, a1)}L${p(R0 + 4, a1)}A${R0 + 4} ${R0 + 4} 0 ${large} 0 ${p(R0 + 4, a0)}Z`;
  };
  const paths = items.slice(0, n).map((_, i) => s('path', { d: wedge(i), class: `pie-w${i === current ? ' is-current' : ''}${i === marked ? ' is-marked' : ''}` }));
  const texts = items.slice(0, n).map((it, i) => {
    const a = -Math.PI / 2 + i * span, r = (R + R0) / 2 + 6;
    const words = String(it).split(/\s+(?=\()/);
    return s('text', { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) - (words.length > 1 ? 5 : 0), class: `pie-t${n > 8 ? ' is-small' : ''}` },
      ...words.slice(0, 2).map((w, j) => s('tspan', { x: cx + r * Math.cos(a), dy: j ? 13 : 4, text: w.replace(/[()]/g, '') })));
  });
  const centre = s('g', { class: 'pie-c' },
    s('circle', { cx, cy, r: R0 }),
    s('path', { d: `M${cx - 7} ${cy - 7}L${cx + 7} ${cy + 7}M${cx + 7} ${cy - 7}L${cx - 7} ${cy + 7}` }));
  const svg = s('svg', { class: 'pie-svg', width: vw, height: vh, viewBox: `0 0 ${vw} ${vh}` },
    s('circle', { cx, cy, r: R + 6, class: 'pie-bg' }), ...paths, ...texts, centre);
  const el = h('div', { class: 'w-pie', role: 'menu', 'aria-label': title ?? 'Choose' }, svg,
    title ? h('div', { class: 'pie-title', style: { left: `${cx}px`, top: `${cy - R - 30}px` }, text: title }) : null);
  document.body.append(el);
  requestAnimationFrame(() => el.classList.add('is-open'));

  let hot = -1, travelled = false;
  const which = (e) => {
    const dx = e.clientX - cx, dy = e.clientY - cy, dist = Math.hypot(dx, dy);
    if (dist < R0) return -1;
    if (dist > R + 90) return -2;
    let a = Math.atan2(dy, dx) + Math.PI / 2 + span / 2;
    a = ((a % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);
    return Math.floor(a / span) % n;
  };
  const light = (i) => {
    if (i === hot) return;
    hot = i;
    paths.forEach((p, j) => p.classList.toggle('is-hot', j === i));
    if (i >= 0) haptic();
  };
  const finish = (i) => {
    if (done) return;
    done = true;
    window.removeEventListener('pointermove', move, true);
    window.removeEventListener('pointerup', up, true);
    window.removeEventListener('pointerdown', down, true);
    window.removeEventListener('keydown', key, true);
    el.classList.remove('is-open');
    setTimeout(() => el.remove(), 140);
    if (i >= 0) haptic(true);
    resolve(i);
  };
  const move = (e) => { const i = which(e); if (i >= 0) travelled = true; light(Math.max(-1, i)); };
  const up = (e) => {
    const i = which(e);
    if (travelled) { finish(i >= 0 ? i : -1); return; }
    if (i === -2) finish(-1);                       // a tap that opened the pie leaves it open
  };
  const down = (e) => { e.stopPropagation(); travelled = true; light(Math.max(-1, which(e))); if (which(e) === -2 || which(e) === -1) { finish(-1); } };
  const key = (e) => { if (e.key === 'Escape') finish(-1); };
  window.addEventListener('pointermove', move, true);
  window.addEventListener('pointerup', up, true);
  setTimeout(() => { if (!done) window.addEventListener('pointerdown', down, true); }, 0);
  window.addEventListener('keydown', key, true);
  pr.cancel = () => finish(-1);
  return pr;
}

export function radial(ctx, id, { label, size = 72 } = {}) {
  const p = ctx.params.get(id);
  const w = writer(ctx, id, 'radial');
  const opts = p.scale === 'toggle' ? [p.off ?? 'Off', p.on ?? 'On'] : p.options ?? [];
  const n = opts.length;
  const face = h('span', { class: 'rd-face' });
  const sub = h('span', { class: 'rd-sub' });
  const btn = h('button', { type: 'button', class: 'rd-btn', 'aria-haspopup': 'menu', 'aria-label': p.label }, face, sub);
  const el = h('div', { class: 'w-radial', dataset: { param: id }, style: { '--size': `${size}px`, '--c': stageColor(p) } },
    h('div', { class: 'w-label', text: label ?? shortLabel(p) }), btn);
  let cur = 0;
  follow(ctx, id, (v) => {
    cur = Math.round(v * (n - 1));
    const [main, rest] = String(opts[cur] ?? '').split(/\s+(?=\()/);
    face.textContent = main;
    sub.textContent = (rest ?? '').replace(/[()]/g, '');
    el.classList.toggle('is-set', ctx.store.isSet(id));
  });
  let open = null, timer = 0;
  btn.addEventListener('pointerdown', (e) => {
    if (open) return;
    const r = btn.getBoundingClientRect();
    clearTimeout(timer);
    const x0 = e.clientX, y0 = e.clientY;
    // held still for 700 ms (the finger never left the button): the inspector instead of the pie
    const stop = () => { clearTimeout(timer); window.removeEventListener('pointermove', mv, true); window.removeEventListener('pointerup', stop, true); };
    const mv = (ev) => { if (Math.hypot(ev.clientX - x0, ev.clientY - y0) > 8) stop(); };
    window.addEventListener('pointermove', mv, true);
    window.addEventListener('pointerup', stop, true);
    timer = setTimeout(() => { stop(); if (open && !ctx.local) { open.cancel(); inspect(id); } }, 700);
    open = pie(r.left + r.width / 2, r.top + r.height / 2, opts, { title: p.label, current: cur, marked: Math.round(setNorm(p) * (n - 1)) });
    open.then((i) => {
      stop();
      open = null;
      if (i < 0 || i === cur) return;
      w.begin(); w.set(n > 1 ? i / (n - 1) : 0); w.end();
    });
  });
  btn.style.touchAction = 'none';
  ctx.own(() => { clearTimeout(timer); open?.cancel(); });
  return el;
}
