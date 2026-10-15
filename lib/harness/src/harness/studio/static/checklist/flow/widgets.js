// The production widgets: a full-bleed studio surface for one checklist item, its done measures, and the commit.
// Mocked: nothing plays (the sound rule: music is rendered files on the player engine, and here there are none), but
// the player engine's audibility cues are real (docs/sound.md): a switch shows as pending until the next bar, then
// becomes audible with rings at the control and a diagonal flash across the player.
//
//   openWidget(host, ctx) -> { destroy() }
//   ctx = { data, step, item, commit(), close(), haptic(strong) }
import { hash, rng, onTap, roles } from '../concepts/model.js';
import { DRIVE, EQ_STOPS, TAKES, EDGE, estimate } from './measures.js';

const BAR_MS = 1500;           // a bar at 160 BPM
const BEAT_MS = BAR_MS / 4;
const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

const SVG = new Set(['svg', 'path', 'line', 'circle', 'rect', 'g', 'text', 'polyline', 'pattern', 'defs']);
function h(tag, attrs = {}, ...kids) {
  const el = SVG.has(tag) ? document.createElementNS('http://www.w3.org/2000/svg', tag) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === 'class') el.setAttribute('class', v);
    else if (k === 'text') el.textContent = v;
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
}
const icon = (d, cls = 'ic') => h('svg', { class: cls, viewBox: '0 0 24 24', 'aria-hidden': 'true' }, h('path', { d }));
const BACK = 'M15 5l-7 7 7 7';
const CHECK = 'M5 12.5l4.5 4.5L19 7.5';

/** A kick-like waveform, two bars of four hits, the same for the same seed. `drive` 0..1 makes it denser and
 * squarer. Returns the path of a mirrored area in a 1000 x 200 box. */
function waveform(seed, drive = 0.5) {
  const r = rng(seed);
  const N = 320, top = [], bot = [];
  const hits = 8;
  for (let i = 0; i <= N; i++) {
    const x = (i / N) * 1000;
    const ph = (i / N) * hits;
    const k = ph - Math.floor(ph);                              // position within a beat
    const env = Math.exp(-k * (5.5 - drive * 2.2));
    const body = Math.pow(env, 0.6 + (1 - drive) * 0.6);
    const fizz = (r() - 0.5) * (0.12 + drive * 0.3) * env;
    const sat = Math.tanh((body + fizz) * (1 + drive * 2.4)) / Math.tanh(1 + drive * 2.4);
    const a = Math.max(0.015, sat) * 92 * (0.94 + r() * 0.06);
    top.push(`${x.toFixed(1)},${(100 - a).toFixed(1)}`);
    bot.push(`${x.toFixed(1)},${(100 + a).toFixed(1)}`);
  }
  return `M${top.join('L')}L${bot.reverse().join('L')}Z`;
}

export function openWidget(host, ctx) {
  const { step, item } = ctx;
  const key = `${step.id}.${item.id}`;
  const kind = key === 'kick.drive' ? 'drive' : key === 'kick.eq' ? 'eq' : 'generic';
  const timers = new Set();
  const later = (fn, ms) => { const t = setTimeout(() => { timers.delete(t); fn(); }, ms); timers.add(t); return t; };
  const offs = [];
  const listen = (el, ev, fn, o) => { el.addEventListener(ev, fn, o); offs.push(() => el.removeEventListener(ev, fn, o)); };
  const t0 = performance.now();

  // --- the choice and what it sounds like ---
  const options = kind === 'drive' ? DRIVE.map((p, i) => ({ v: i, short: 'ABCD'[i], long: `${p} %`, drive: (p - 37) / 13 }))
    : kind === 'eq' ? [...Array(EQ_STOPS)].map((_, i) => ({ v: i, short: String(i + 1), long: `mid warmth ${i - 3 > 0 ? '+' : ''}${i - 3}`, drive: 0.35 + i * 0.03 }))
    : TAKES.map((t, i) => ({ v: i, short: t, long: `take ${t}`, drive: 0.3 + i * 0.15 }));
  let heard = kind === 'drive' ? 1 : kind === 'eq' ? 3 : 0;     // what is audible now
  let asked = heard;                                              // what was asked for (pending until the bar)
  const label = (v) => (v === 'neither' ? 'Neither: batch 8.0 stays' : `${options[v].short} · ${options[v].long}`);
  const hue = (v) => (v === 'neither' ? 210 : 18 + (v / Math.max(1, options.length - 1)) * 26);
  const wave = (v) => (v === 'neither' ? waveform(hash(`${key}|neither`), 0.15) : waveform(hash(`${key}|${v}`), options[v].drive));

  // --- the frame ---
  const r = roles(step);
  const idx = step.items.indexOf(item);
  const role = r[idx];
  const status = item.why ?? { you: 'Your move', ready: 'Ready: the agent cleared the way (mocked)', clearing: 'The agent is on it (mocked)', done: 'Cleared', ahead: 'Further along the path' }[role] ?? '';
  const root = h('div', { class: `wg wg-${kind}`, 'data-cue': 'idle', 'data-kind': kind });
  root.style.setProperty('--hue', hue(heard));
  const back = h('button', { type: 'button', class: 'wg-back', 'aria-label': 'Back to the checklist' }, icon(BACK));
  onTap(back, () => ctx.close());
  const top = h('header', { class: 'wg-top' }, back,
    h('div', { class: 'wg-crumb' }, h('b', { text: step.n }), ` ${step.name} · ${idx + 1} of ${step.items.length}`),
    h('h1', { class: 'wg-title', text: item.title }),
    h('p', { class: 'wg-status', text: status }));

  // --- the player: a waveform of what you hear, and a dotted ghost of what you asked for ---
  const solid = h('path', { class: 'wf-solid', d: wave(heard) });
  const ghost = h('path', { class: 'wf-ghost', d: wave(heard) });
  const bars = h('g', { class: 'wf-grid' }, [...Array(9)].map((_, i) => h('line', { x1: i * 125, x2: i * 125, y1: 0, y2: 200, class: i % 4 === 0 ? 'bar' : '' })));
  const svg = h('svg', { class: 'wf', viewBox: '0 0 1000 200', preserveAspectRatio: 'none', 'aria-hidden': 'true' }, bars, solid, ghost);
  const now = h('div', { class: 'pl-now' }, h('span', { class: 'pl-dot' }), h('b', { text: label(heard) }));
  const wait = h('div', { class: 'pl-wait' }, h('span', { text: 'Waits for the next bar' }), h('i'), h('i'), h('i'), h('i'));
  const player = h('section', { class: 'wg-player', 'aria-label': 'Player (mocked: no audio)' },
    h('div', { class: 'pl-head' }, now, h('span', { class: 'pl-mock', text: 'Mocked: no audio' })),
    h('div', { class: 'pl-wave' }, svg), wait,
    h('div', { class: 'pl-sheen' }));

  // --- the measures ---
  const meas = h('section', { class: 'wg-measures', 'aria-label': 'Done measures (mocked)' });
  const words = h('div', { class: 'cm-words' });
  const pct = h('div', { class: 'cm-pct' });
  const commitBtn = h('button', { type: 'button', class: 'cm-btn' }, icon(CHECK), h('span', { text: 'Commit · check it off' }));
  onTap(commitBtn, () => { ctx.haptic?.(true); ctx.commit(); });
  const foot = h('footer', { class: 'wg-commit' }, h('div', { class: 'cm-row' }, words, pct), commitBtn);

  function paintMeasures() {
    const est = estimate(step, item, asked);
    root.dataset.settled = est.settled.toFixed(2);
    foot.dataset.emphasis = est.settled >= 0.75 ? 'high' : est.settled >= 0.5 ? 'mid' : 'low';
    foot.style.setProperty('--settled', est.settled.toFixed(3));
    words.replaceChildren(h('b', { text: est.words[0] }), ` ${est.words[1]}`);
    pct.replaceChildren(h('b', { text: String(Math.round(est.settled * 100)) }), h('span', { text: '% settled' }));
    const rows = est.dims.map((d) => {
      const x = (v) => `${(v * 100).toFixed(2)}%`;
      const lo = Math.max(0, d.zone[0] - EDGE), hi = Math.min(1, d.zone[1] + EDGE);
      return h('div', { class: 'ms-row', 'data-dim': d.id, 'data-where': d.inZone ? 'in' : d.edge ? 'edge' : 'out' },
        h('div', { class: 'ms-label' }, h('span', { text: d.label }), h('em', { text: d.inZone ? 'in the zone' : d.edge ? 'at the edge' : 'outside' })),
        h('div', { class: 'ms-track' },
          h('span', { class: 'ms-edge', style: `left:${x(lo)};width:${x(hi - lo)}` }),
          h('span', { class: 'ms-zone', style: `left:${x(d.zone[0])};width:${x(d.zone[1] - d.zone[0])}` }),
          h('span', { class: 'ms-mark', style: `left:${x(d.value)}` })));
    });
    const mv = est.movement, W = 120, H = 32, max = Math.max(...mv, 0.01);
    const pts = mv.map((m, i) => `${((i / (mv.length - 1)) * (W - 6) + 3).toFixed(1)},${(H - 3 - (m / max) * (H - 8)).toFixed(1)}`);
    const last = pts[pts.length - 1].split(',');
    const spark = h('svg', { class: 'ms-spark', viewBox: `0 0 ${W} ${H}`, 'aria-hidden': 'true' },
      h('polyline', { points: pts.join(' ') }), h('circle', { cx: last[0], cy: last[1], r: 3 }));
    meas.dataset.inZone = `${est.inZone.n}/${est.inZone.of}`;
    meas.dataset.converging = String(est.converging);
    meas.replaceChildren(
      h('div', { class: 'ms-head' }, h('b', { text: 'Done measures' }), h('span', { text: 'mocked' })),
      h('p', { class: 'ms-sum' }, h('b', { text: `${est.inZone.n} of ${est.inZone.of}` }), ' in the references’ zone'),
      ...rows,
      h('div', { class: 'ms-conv' }, spark, h('p', {},
        h('b', { text: est.converging ? 'Converging' : 'Not converging' }),
        h('span', { text: est.converging ? ' · each batch moves it less' : ' · this choice moves it more than the last batch did' }))),
      h('p', { class: 'ms-note', text: 'The zone is the four references’ range; the faint band beyond it is the 10 % edge.' }));
  }

  // --- the audibility cues: pending until the next bar, then audible ---
  let pendingTimer = 0, pendingEl = null, beatTimer = 0;
  function rings(el) {
    if (reduced()) return;
    const a = el.getBoundingClientRect(), b = root.getBoundingClientRect();
    for (let i = 0; i < 3; i++) {
      const ring = h('i', { class: 'wg-ring' });
      ring.style.left = `${a.left - b.left + a.width / 2}px`;
      ring.style.top = `${a.top - b.top + root.scrollTop + a.height / 2}px`;
      ring.style.setProperty('--d', `${i * 70}ms`);
      ring.style.setProperty('--s', String(3 + i * 1.6));
      root.append(ring);
      later(() => ring.remove(), 900 + i * 70);
    }
  }
  function beats() {
    const k = Math.floor(((performance.now() - t0) % BAR_MS) / BEAT_MS);
    [...wait.querySelectorAll('i')].forEach((d, i) => d.classList.toggle('on', i <= k));
  }
  function ask(v, el) {
    if (v === asked && root.dataset.cue !== 'pending') {
      if (v === heard) return;
    }
    asked = v;
    paintMeasures();
    paintControl();
    clearTimeout(pendingTimer); timers.delete(pendingTimer);
    pendingEl?.classList.remove('pending');
    if (v === heard) {                 // asked back for what is already playing: nothing to wait for
      root.dataset.cue = 'idle'; pendingEl = null; clearInterval(beatTimer); return;
    }
    pendingEl = el;
    el?.classList.add('pending');
    root.dataset.cue = 'pending';
    ghost.setAttribute('d', wave(v));
    ctx.haptic?.();
    clearInterval(beatTimer); beats(); beatTimer = setInterval(beats, 60);
    let delay = BAR_MS - ((performance.now() - t0) % BAR_MS);
    if (delay < 250) delay += BAR_MS;
    pendingTimer = later(() => audible(v, el), delay);
  }
  function audible(v, el) {
    clearInterval(beatTimer);
    heard = v;
    el?.classList.remove('pending');
    pendingEl = null;
    solid.setAttribute('d', wave(v));
    root.style.setProperty('--hue', hue(v));
    now.querySelector('b').textContent = label(v);
    root.dataset.cue = 'audible';
    root.dataset.heard = String(v);
    if (el) { el.classList.remove('audible'); void el.offsetWidth; el.classList.add('audible'); later(() => el.classList.remove('audible'), 800); }
    player.classList.remove('flash'); void player.offsetWidth; player.classList.add('flash');
    later(() => player.classList.remove('flash'), 900);
    rings(el ?? player);
    ctx.haptic?.(true);
    paintControl();
  }

  // --- the control ---
  const control = h('section', { class: 'wg-control' });
  let paintControl = () => {};
  if (kind === 'drive' || kind === 'generic') {
    const btns = options.map((o) => {
      const est = estimate(step, item, o.v);
      const b = h('button', { type: 'button', class: 'opt', 'data-v': String(o.v), 'aria-pressed': 'false' },
        h('b', { text: o.short }), h('span', { text: o.long }), h('small', { text: `${est.inZone.n}/${est.inZone.of} in zone` }));
      onTap(b, () => ask(o.v, b));
      return b;
    });
    const rowEls = [h('div', { class: 'opts', style: `--n:${options.length}` }, btns)];
    let neither = null;
    if (kind === 'drive') {
      neither = h('button', { type: 'button', class: 'opt opt-neither', 'data-v': 'neither', 'aria-pressed': 'false' },
        h('span', { text: 'Neither · keep batch 8.0' }));
      onTap(neither, () => ask('neither', neither));
      rowEls.push(neither);
    }
    control.append(
      h('div', { class: 'ct-head' }, h('b', { text: kind === 'drive' ? 'Batch 8.1' : 'Mocked studio surface' }),
        h('span', { text: kind === 'drive' ? 'four renders of the drive · pick by ear' : 'three takes of this item (mocked)' })),
      ...rowEls);
    paintControl = () => {
      for (const b of [...btns, neither].filter(Boolean)) {
        const v = b.dataset.v === 'neither' ? 'neither' : Number(b.dataset.v);
        b.setAttribute('aria-pressed', String(v === heard));
        b.classList.toggle('asked', v === asked && v !== heard);
      }
    };
  } else {
    // the macro: a dial that moves among rendered stops and snaps between them; it never processes audio
    const A0 = -135, A1 = 135, R = 96, C = 120;
    const ang = (i) => A0 + (i / (EQ_STOPS - 1)) * (A1 - A0);
    const pt = (a, rad) => { const t = (a - 90) * Math.PI / 180; return [C + rad * Math.cos(t), C + rad * Math.sin(t)]; };
    const arc = (a, b, rad) => { const [x0, y0] = pt(a, rad), [x1, y1] = pt(b, rad); return `M${x0.toFixed(2)} ${y0.toFixed(2)}A${rad} ${rad} 0 ${b - a > 180 ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`; };
    const track = h('path', { class: 'dl-track', d: arc(A0, A1, R) });
    const fill = h('path', { class: 'dl-fill' });
    const needle = h('line', { class: 'dl-needle', x1: C, y1: C });
    const ghostN = h('line', { class: 'dl-ghost', x1: C, y1: C });
    const stops = [...Array(EQ_STOPS)].map((_, i) => {
      const [x, y] = pt(ang(i), R + 20), [tx, ty] = pt(ang(i), R - 10), [ux, uy] = pt(ang(i), R + 4);
      const g = h('g', { class: 'dl-stop', 'data-v': String(i), role: 'button', tabindex: '0', 'aria-label': `Render ${i + 1}` },
        h('circle', { cx: x.toFixed(2), cy: y.toFixed(2), r: 17, class: 'dl-hit' }),
        h('line', { x1: tx.toFixed(2), y1: ty.toFixed(2), x2: ux.toFixed(2), y2: uy.toFixed(2), class: 'dl-tick' }),
        h('text', { x: x.toFixed(2), y: (y + 4.5).toFixed(2), 'text-anchor': 'middle', text: String(i + 1) }));
      return g;
    });
    const hub = h('circle', { class: 'dl-hub', cx: C, cy: C, r: 6 });
    const centre = h('text', { class: 'dl-big', x: C, y: C + 44, 'text-anchor': 'middle' });
    const sub = h('text', { class: 'dl-small', x: C, y: C + 62, 'text-anchor': 'middle' });
    const dial = h('svg', { class: 'dial', viewBox: '0 0 240 240', role: 'slider', 'aria-label': 'Mid warmth',
      'aria-valuemin': '1', 'aria-valuemax': String(EQ_STOPS) }, track, fill, ...stops, ghostN, needle, hub, centre, sub);
    const place = (line, i, len) => { const [x, y] = pt(ang(i), len); line.setAttribute('x2', x.toFixed(2)); line.setAttribute('y2', y.toFixed(2)); };
    paintControl = () => {
      fill.setAttribute('d', arc(A0, ang(heard) + 0.01, R));
      place(needle, heard, R - 30);
      place(ghostN, asked, R - 30);
      dial.classList.toggle('asking', asked !== heard);
      dial.setAttribute('aria-valuenow', String(heard + 1));
      centre.textContent = `Render ${(asked === heard ? heard : asked) + 1}`;
      sub.textContent = `of ${EQ_STOPS} · mid warmth ${options[asked].long.split(' ').pop()}`;
      for (const s of stops) {
        s.classList.toggle('heard', Number(s.dataset.v) === heard);
        s.classList.toggle('asked', Number(s.dataset.v) === asked && asked !== heard);
      }
    };
    for (const s of stops) onTap(s, () => ask(Number(s.dataset.v), s));
    // dragging moves the ghost across the stops; letting go asks for the one it is on
    let drag = null;
    const stopAt = (e) => {
      const b = dial.getBoundingClientRect();
      const x = e.clientX - (b.left + b.width / 2), y = e.clientY - (b.top + b.height / 2);
      let a = Math.atan2(y, x) * 180 / Math.PI + 90;
      if (a > 180) a -= 360;
      a = Math.max(A0, Math.min(A1, a));
      return Math.round(((a - A0) / (A1 - A0)) * (EQ_STOPS - 1));
    };
    listen(dial, 'pointerdown', (e) => {
      if (e.target.closest('.dl-stop')) return;
      drag = { id: e.pointerId, v: asked };
      try { dial.setPointerCapture(e.pointerId); } catch { /* a synthetic pointer */ }
    });
    listen(dial, 'pointermove', (e) => {
      if (!drag || e.pointerId !== drag.id) return;
      const v = stopAt(e);
      if (v !== drag.v) { drag.v = v; place(ghostN, v, R - 30); dial.classList.add('asking'); ctx.haptic?.(); }
    });
    const up = (e) => {
      if (!drag || e.pointerId !== drag.id) return;
      const v = drag.v; drag = null;
      ask(v, stops[v]);
    };
    listen(dial, 'pointerup', up);
    listen(dial, 'pointercancel', () => { drag = null; paintControl(); });
    control.append(
      h('div', { class: 'ct-head' }, h('b', { text: 'Mid warmth' }), h('span', { text: `a macro across ${EQ_STOPS} rendered stops` })),
      dial,
      h('p', { class: 'ct-note', text: 'The dial snaps between renders the agent made ahead; it never processes audio. Drag or tap a stop.' }));
  }

  root.append(top, player, control, meas, foot);
  host.replaceChildren(root);
  paintMeasures();
  paintControl();

  return {
    destroy() {
      for (const t of timers) clearTimeout(t);
      timers.clear();
      clearInterval(beatTimer);
      for (const off of offs) off();
      root.remove();
    },
  };
}
