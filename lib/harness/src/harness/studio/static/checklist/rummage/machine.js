// The studio machine (docs/rummage.md): a machine of The Rummage, operated full screen. Its panel art fills the
// screen; over its lower part, on a board screwed to the panel, are a heavy three-way rotary selector, the chosen
// option's name and line on a taped paper scrap, a play/stop button with a bar counter, and the commit lever. The
// short plays with this machine's option swapped in (the other parts as committed, or option 1), and turning the
// selector switches renders at the same playhead (player.js). Pulling the lever down (or holding it) commits: the
// lever slams, the screen shakes, the choice is distilled (paper scraps fly together into the artifact), stamped,
// and drops toward the wanderer's hands. Then onCommit(id), and the machine closes.
//
//   openMachine(host, { part, machine: { name, panel }, options: [{ id, name, about, artifact }], committed,
//                       player, onCommit(id), onClose({ committed }), feedback, audio }) -> { close(), context() }
//
// `panel` and `artifact` are image URLs, or null: then the machine draws itself in cut paper. `player` is
// createPlayer()'s (player.js), or null when the renders are not here yet: the selector still works. `feedback`:
// leave it out and the machine mounts the artist's thumbs as view 'rummage-machine'; pass the page's own (or false)
// and it doesn't, and the page's context() can include machine.context(). Open it inside the tap that asks for it:
// that tap wakes the audio (iOS). Every control acts on the touch itself (onTap), since iPhone WebKit can swallow
// the click on a page that animates.
import { haptic, hash, onTap, rng } from '../concepts/model.js';
import { HEAVY, shake } from '../map/check.js';
import { mountFeedback } from '../map/feedback.js';
import { land as knock, play as thud, soundId, wake as wakeSounds } from '../map/sounds.js';
import { comboKey } from './player.js';

const SLAM = 'cubic-bezier(.75,0,1,.55)';
const SNAP = 'cubic-bezier(.2,1.6,.4,1)';                // a detent: a little past, and back
const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms));
const ROMAN = ['', 'I', 'II', 'III', 'IV', 'V'];
export const PARTS = {
  bed: { n: 1, label: 'the bed', glyph: 'M4 15a8 8 0 0 1 16 0M7.5 15a4.5 4.5 0 0 1 9 0M11 15a1 1 0 0 1 2 0M3 19h18' },
  drums: { n: 2, label: 'the drums', glyph: 'M4 9c0-2 3.6-3 8-3s8 1 8 3v7c0 2-3.6 3-8 3s-8-1-8-3zM4 9c0 2 3.6 3 8 3s8-1 8-3M15 3l-3 6M9 3l3 6' },
  bass: { n: 3, label: 'the low end', glyph: 'M3 12c2-5 4-5 6 0s4 5 6 0 4-5 6 0M5 19h14M7 5h10' },
};
// Where each part comes in, in the fixed arrangement (docs/rummage.md): bars 1-8 bed, 9-16 + drums, 17-28 + bass,
// 29-32 the outro. A machine's preview loops from where its part comes in to the outro, so you hear it at once.
// audio.json may set its own as `preview: { part: [from bar, to bar) }`.
const ENTERS = { bed: 1, drums: 9, bass: 17 };
const OUTRO = 29;
const LATCH = 0.8;                                        // the lever commits past this far down
const HOLD_MS = 560;                                      // or when held this long

const SVG = new Set(['svg', 'path', 'circle', 'g', 'line', 'text', 'rect', 'polygon']);
function h(tag, attrs = {}, ...kids) {
  const el = SVG.has(tag) ? document.createElementNS('http://www.w3.org/2000/svg', tag) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') el.setAttribute('class', v);
    else if (k === 'text') el.textContent = v;
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
}
const icon = (d, cls = 'mc-ic') => h('svg', { class: cls, viewBox: '0 0 24 24', 'aria-hidden': 'true' }, h('path', { d }));
const PLAY = 'M8 5.5v13l10.5-6.5z';
const STOP = 'M7 7h10v10H7z';
const CLOSE = 'M6 6l12 12M18 6L6 18';

/** A torn edge, the same for the same seed: a clip-path polygon for a box, its edges ragged by up to `amp` px. */
function torn(seed, { amp = 5, step = 7, edges = 'trbl' } = {}) {
  const r = rng(hash(String(seed)));
  const pts = [];
  const side = (e, from, to, at) => {
    for (let i = 0; i <= step; i++) {
      const k = from + ((to - from) * i) / step;
      const d = edges.includes(e) ? (r() * amp).toFixed(1) : 0;
      pts.push(at(k, d));
    }
  };
  side('t', 0, 100, (k, d) => `${k}% ${d}px`);
  side('r', 0, 100, (k, d) => `calc(100% - ${d}px) ${k}%`);
  side('b', 100, 0, (k, d) => `${k}% calc(100% - ${d}px)`);
  side('l', 100, 0, (k, d) => `${d}px ${k}%`);
  return `polygon(${pts.join(',')})`;
}

function ensureCss(href) {
  const url = new URL(href, import.meta.url).href;
  if ([...document.querySelectorAll('link[rel=stylesheet]')].some((l) => l.href === url)) return;
  document.head.append(h('link', { rel: 'stylesheet', href: url }));
}

/** The preview's loop for a part, in seconds: [where it comes in, the outro). */
export function previewLoop(audio, part) {
  if (!audio?.seconds || !audio?.bars) return true;
  const bar = audio.seconds / audio.bars;
  const [a, b] = audio.preview?.[part] ?? [ENTERS[part] ?? 1, OUTRO];
  const from = (Math.max(1, a) - 1) * bar, to = Math.min(audio.bars, b - 1) * bar;
  return to - from >= bar ? [from, to] : true;
}

// --- the effects layer: sparks and dust on a hit, and paper scraps that fly together -----------------------------
function fxLayer(canvas) {
  const cx = canvas.getContext('2d');
  let parts = [], raf = 0, last = 0, dpr = 1, w = 0, ht = 0;
  const size = () => {
    dpr = Math.min(2, devicePixelRatio || 1);
    w = innerWidth; ht = innerHeight;
    canvas.width = w * dpr; canvas.height = ht * dpr;
  };
  size();
  addEventListener('resize', size);
  function spawn(p) { parts.push(p); if (!raf) raf = requestAnimationFrame(tick); }
  function tick(now) {
    const dt = Math.min(0.033, last ? (now - last) / 1000 : 0.016);
    last = now;
    cx.setTransform(dpr, 0, 0, dpr, 0, 0);
    cx.clearRect(0, 0, w, ht);
    parts = parts.filter((p) => (p.age += dt) < p.life);
    for (const p of parts) {
      if (p.age < 0) continue;
      let a = p.alpha, x, y, rot, s = p.size;
      if (p.kind === 'scrap') {                                        // along a curve, into the artifact
        const k = Math.min(1, p.age / p.life), e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
        x = (1 - e) * (1 - e) * p.x0 + 2 * (1 - e) * e * p.cx + e * e * p.x1;
        y = (1 - e) * (1 - e) * p.y0 + 2 * (1 - e) * e * p.cy + e * e * p.y1;
        rot = p.rot + p.spin * e; s = p.size * (1 - 0.65 * e); a = k > 0.85 ? (1 - k) / 0.15 : 1;
        cx.save(); cx.globalAlpha = a; cx.translate(x, y); cx.rotate(rot);
        cx.beginPath();
        p.pts.forEach(([px, py], i) => (i ? cx.lineTo(px * s, py * s) : cx.moveTo(px * s, py * s)));
        cx.closePath(); cx.fillStyle = p.color; cx.fill();
        cx.lineWidth = 1.2; cx.strokeStyle = '#fbf6ea'; cx.stroke();
        cx.restore();
        continue;
      }
      p.vx *= Math.pow(p.drag, dt * 60); p.vy = p.vy * Math.pow(p.drag, dt * 60) + p.g * dt;
      p.x += p.vx * dt; p.y += p.vy * dt; p.rot += p.spin * dt;
      if (p.floor != null && p.y > p.floor) { p.y = p.floor; p.vy *= -0.25; p.vx *= 0.5; p.spin *= 0.5; }
      const k = p.age / p.life;
      cx.globalAlpha = Math.max(0, a * (k < 0.7 ? 1 : 1 - (k - 0.7) / 0.3));
      if (p.kind === 'spark') {
        cx.strokeStyle = p.color; cx.lineWidth = p.size; cx.lineCap = 'round';
        const sp = Math.hypot(p.vx, p.vy) || 1, len = Math.min(24, sp * 0.03);
        cx.beginPath(); cx.moveTo(p.x, p.y); cx.lineTo(p.x - (p.vx / sp) * len, p.y - (p.vy / sp) * len); cx.stroke();
      } else if (p.kind === 'chip') {
        cx.save(); cx.translate(p.x, p.y); cx.rotate(p.rot); cx.fillStyle = p.color;
        cx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.62);
        cx.strokeStyle = '#fbf6ea'; cx.lineWidth = 0.8; cx.strokeRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.62);
        cx.restore();
      } else {
        cx.fillStyle = p.color; cx.beginPath(); cx.arc(p.x, p.y, p.size * (1 + k * 1.5), 0, Math.PI * 2); cx.fill();
      }
    }
    cx.globalAlpha = 1;
    if (parts.length) raf = requestAnimationFrame(tick);
    else { raf = 0; last = 0; cx.clearRect(0, 0, w, ht); }
  }
  const R = (a, b) => a + Math.random() * (b - a);
  const pick = (list) => list[Math.floor(Math.random() * list.length)];
  return {
    /** A hit at (x, y): sparks off it, paper chips that tumble and fall, dust that settles. */
    burst(x, y, { power = 1, colors = ['#fbf6ea'], floor = null } = {}) {
      for (let i = 0; i < Math.round(36 * power); i++) {
        const a = R(0, Math.PI * 2), v = R(340, 900) * power;
        spawn({ kind: 'spark', x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, g: 900, drag: 0.9, life: R(0.3, 0.7), age: 0,
          size: R(1.2, 2.4), color: Math.random() < 0.5 ? '#fff4d6' : pick(colors), alpha: 1, rot: 0, spin: 0 });
      }
      for (let i = 0; i < Math.round(26 * power); i++) {
        const a = R(-Math.PI * 0.95, -Math.PI * 0.05), v = R(200, 600);
        spawn({ kind: 'chip', x: x + R(-30, 30), y: y + R(-14, 14), vx: Math.cos(a) * v, vy: Math.sin(a) * v, g: 1600,
          drag: 0.985, life: R(1, 1.8), age: 0, size: R(4, 9), color: pick(colors), alpha: 1, rot: R(0, 6), spin: R(-14, 14), floor });
      }
      for (let i = 0; i < Math.round(18 * power); i++) {
        const a = R(0, Math.PI * 2), v = R(30, 140);
        spawn({ kind: 'dust', x: x + R(-30, 30), y: y + R(-4, 8), vx: Math.cos(a) * v * 1.8, vy: Math.sin(a) * v * 0.4 - 30,
          g: 60, drag: 0.94, life: R(1.2, 2.2), age: 0, size: R(1.5, 4), color: '#e9dcc0', alpha: 0.25, rot: 0, spin: 0 });
      }
    },
    /** Scraps from `sources` (rects) fly together into (x, y) over about `ms`. */
    converge(sources, x, y, { n = 80, ms = 820, colors }) {
      for (let i = 0; i < n; i++) {
        const src = sources[i % sources.length];
        const x0 = R(src.left, src.right), y0 = R(src.top, src.bottom);
        const mx = (x0 + x) / 2, my = (y0 + y) / 2, dx = x - x0, dy = y - y0;
        const bend = R(-0.55, 0.55);
        const corners = 4 + Math.floor(R(0, 3));
        const pts = Array.from({ length: corners }, (_, j) => {
          const a = (j / corners) * Math.PI * 2 + R(-0.3, 0.3), r = R(0.55, 1);
          return [Math.cos(a) * r, Math.sin(a) * r * 0.75];
        });
        spawn({ kind: 'scrap', x0, y0, x1: x + R(-10, 10), y1: y + R(-10, 10), cx: mx - dy * bend, cy: my + dx * bend,
          age: -R(0, ms * 0.3) / 1000, life: R(ms * 0.6, ms) / 1000, size: R(6, 15), color: pick(colors), alpha: 1,
          rot: R(0, 6), spin: R(-9, 9), pts });
      }
    },
    destroy() { cancelAnimationFrame(raf); removeEventListener('resize', size); parts = []; },
  };
}

// --- the machine ------------------------------------------------------------------------------------------------
export function openMachine(host, {
  part, machine = {}, options = [], committed = null, player = null, onCommit = () => {}, onClose = () => {},
  feedback, audio = player?.audio ?? null,
} = {}) {
  ensureCss('machine.css');
  if (feedback === undefined) ensureCss('../map/feedback.css');
  if (!document.querySelector('label.haptic')) {
    document.body.append(h('label', { class: 'haptic mc-haptic', 'aria-hidden': 'true' },
      h('input', { type: 'checkbox', switch: '', tabindex: '-1' })));
  }
  const info = PARTS[part] ?? { n: 1, label: part, glyph: PARTS.bed.glyph };
  const opts = options.length ? options : [1, 2, 3].map((id) => ({ id, name: `Option ${id}`, about: '' }));
  const mine = committed?.[part] ?? null;
  let selected = opts.some((o) => o.id === mine) ? mine : opts[0].id;
  let audible = null;                         // the option the speaker has now
  let state = 'open';                         // open | committing | closed
  const offs = [];
  const listen = (el, ev, fn, o) => { el.addEventListener(ev, fn, o); offs.push(() => el.removeEventListener(ev, fn, o)); };
  const comboFor = (id) => comboKey({ ...(committed ?? {}), [part]: id });
  const optOf = (id) => opts.find((o) => o.id === id) ?? opts[0];
  const loop = previewLoop(audio, part);
  const bar = audio?.seconds && audio?.bars ? audio.seconds / audio.bars : null;

  // --- the frame: the panel art (or cut paper), a board over its lower part, the controls on the board ---
  const root = h('div', { class: 'mc', 'data-part': part, 'data-state': 'open', 'data-cue': 'idle',
    'data-audio': player ? 'yes' : 'none', role: 'dialog', 'aria-label': `${machine.name ?? 'The machine'}: ${info.label}` });
  const stage = h('div', { class: 'mc-stage' });
  const panel = h('div', { class: 'mc-panel' });
  const paper = () => placeholder(part);
  if (machine.panel) {
    const img = h('img', { class: 'mc-art', src: machine.panel, alt: '', decoding: 'async', draggable: 'false' });
    img.addEventListener('error', () => { img.remove(); panel.append(paper()); root.dataset.art = 'none'; }, { once: true });
    panel.append(img);
    root.dataset.art = 'yes';
  } else {
    panel.append(paper());
    root.dataset.art = 'none';
  }
  const close = h('button', { type: 'button', class: 'mc-close', 'aria-label': 'Step back from the machine' }, icon(CLOSE));
  const top = h('header', { class: 'mc-top' }, close,
    h('div', { class: 'mc-plate' },
      h('span', { class: 'mc-tape', text: (machine.name ?? 'The machine').toUpperCase() }),
      h('span', { class: 'mc-sub', text: `${info.label} · machine ${info.n} of 3` })));

  // the label: the chosen option on a taped paper scrap
  const num = h('span', { class: 'mc-num' });
  const name = h('b', { class: 'mc-name' });
  const about = h('span', { class: 'mc-about' });
  const flag = h('span', { class: 'mc-flag' });
  const label = h('div', { class: 'mc-label', 'aria-live': 'polite' },
    h('i', { class: 'mc-tapebit' }), h('div', { class: 'mc-label-in' }, h('div', { class: 'mc-label-head' }, num, name, flag), about),
    h('i', { class: 'mc-sheen' }));
  const note = h('p', { class: 'mc-note' });

  // the selector: an enamel dial, a lamp and a tab per option, the knob
  const n = opts.length;
  const angles = opts.map((_, i) => (n === 1 ? 0 : -55 + (110 * i) / (n - 1)));
  const tabs = opts.map((o, i) => {
    const a = (angles[i] * Math.PI) / 180, R = 104;
    const b = h('button', { type: 'button', class: 'mc-tab', role: 'radio', 'data-id': o.id,
      'aria-label': `${ROMAN[o.id] ?? o.id}: ${o.name}`,
      style: `left:calc(50% + ${(Math.sin(a) * R).toFixed(1)}px);top:${(120 - Math.cos(a) * R).toFixed(1)}px` },
    h('i', { class: 'mc-lamp' }), h('span', { text: ROMAN[o.id] ?? String(o.id) }));
    onTap(b, () => { wakeAll(); select(o.id, { snap: true }); });
    return b;
  });
  const ticks = angles.map((deg) => h('line', { x1: 100, y1: 22, x2: 100, y2: 36, transform: `rotate(${deg} 100 100)` }));
  const dial = h('svg', { class: 'mc-dial', viewBox: '0 0 200 200', 'aria-hidden': 'true' },
    h('circle', { class: 'mc-dial-face', cx: 100, cy: 100, r: 88 }),
    h('circle', { class: 'mc-dial-ring', cx: 100, cy: 100, r: 80 }),
    h('path', { class: 'mc-dial-arc', d: arc(100, 100, 74, angles[0] - 8, angles[n - 1] + 8) }),
    h('g', { class: 'mc-dial-ticks' }, ticks));
  const turn = h('div', { class: 'mc-knob-turn' }, h('i', { class: 'mc-pointer' }));
  const knob = h('div', { class: 'mc-knob', role: 'slider', tabindex: '0', 'aria-label': 'Option',
    'aria-valuemin': String(opts[0].id), 'aria-valuemax': String(opts[n - 1].id) },
  turn, h('i', { class: 'mc-knob-gloss' }));
  const rings = h('div', { class: 'mc-rings', 'aria-hidden': 'true' });
  const selector = h('div', { class: 'mc-selector', role: 'radiogroup', 'aria-label': 'Choose an option' },
    dial, ...tabs, h('div', { class: 'mc-knob-seat' }), knob, rings);

  // the transport: play/stop, with the loop's progress round it, and the bar counter
  const ringLen = 2 * Math.PI * 30;
  const prog = h('circle', { class: 'mc-prog', cx: 34, cy: 34, r: 30, 'stroke-dasharray': ringLen.toFixed(1),
    'stroke-dashoffset': ringLen.toFixed(1) });
  const playIcon = icon(PLAY, 'mc-ic mc-ic-play');
  const stopIcon = icon(STOP, 'mc-ic mc-ic-stop');
  const play = h('button', { type: 'button', class: 'mc-play', 'aria-label': 'Play' },
    h('svg', { class: 'mc-play-ring', viewBox: '0 0 68 68', 'aria-hidden': 'true' }, h('circle', { class: 'mc-prog-bg', cx: 34, cy: 34, r: 30 }), prog),
    h('span', { class: 'mc-play-cap' }, playIcon, stopIcon));
  const counter = h('span', { class: 'mc-counter', text: bar ? 'BAR --' : 'NO RENDERS' });
  const where = h('span', { class: 'mc-where' });
  const transport = h('div', { class: 'mc-transport' }, play, h('div', { class: 'mc-readout' }, counter, where));

  // the lever: a T-handle in a slot, pulled down to commit
  const handle = h('div', { class: 'mc-handle' }, h('i', { class: 'mc-grip' }));
  const rod = h('i', { class: 'mc-rod' });
  const lever = h('button', { type: 'button', class: 'mc-lever', 'aria-label': 'Commit: pull the lever down' },
    h('i', { class: 'mc-slot' }), rod, handle,
    h('span', { class: 'mc-lever-plate' }, h('b', { text: 'COMMIT' }), h('i', { class: 'mc-chev' }), h('i', { class: 'mc-chev' })));
  const hint = h('span', { class: 'mc-hint', text: 'Pull down' });

  const board = h('div', { class: 'mc-board' }, h('div', { class: 'mc-board-in',
    style: `clip-path:${torn(`${part}-board`, { amp: 9, step: 14, edges: 't' })}` },
  h('i', { class: 'mc-screw s1' }), h('i', { class: 'mc-screw s2' }), h('i', { class: 'mc-screw s3' }), h('i', { class: 'mc-screw s4' })));
  const deck = h('section', { class: 'mc-deck' }, board, label, note,
    h('div', { class: 'mc-controls' }, selector, transport, h('div', { class: 'mc-lever-wrap' }, lever, hint)));
  label.style.setProperty('--clip', torn(`${part}-label`, { amp: 3.5, step: 9 }));
  stage.append(panel, h('div', { class: 'mc-scrim' }), top, deck);
  const fxCanvas = h('canvas', { class: 'mc-fx', 'aria-hidden': 'true' });
  const distill = h('div', { class: 'mc-distill', 'aria-hidden': 'true' });
  root.append(stage, distill, fxCanvas);
  host.append(root);
  const fx = fxLayer(fxCanvas);

  // preload the artifacts, so the one committed is there the moment it is distilled
  for (const o of opts) if (o.artifact) { const im = new Image(); im.decoding = 'async'; im.src = o.artifact; }

  // --- the thumbs ---
  function context() {
    const o = optOf(selected);
    return { view: 'rummage-machine', region: 'rummage', part, machine: machine.name ?? null, option: selected,
      option_name: o.name, combo: comboFor(selected), committed: committed ?? null, audible,
      playing: player?.playing ?? null, position: player ? Math.round(player.position() * 10) / 10 : null };
  }
  const thumbs = feedback === undefined ? mountFeedback({ context }) : null;

  // --- sound: the preview, and the interface's rendered knocks ---
  function wakeAll() { player?.wake(); wakeSounds(); }
  const offPlayer = player?.onChange((ev) => {
    if (state === 'closed') return;
    if (ev.why === 'switch' || ev.why === 'play') whenHeard(ev.at, () => heard(player.playing));
    else if (['stop', 'ended', 'background', 'restart'].includes(ev.why)) { if (!player.playing) { audible = null; paint(); } }
    else if (ev.why === 'error' && ev.failed === comboFor(selected)) paint();
  });
  /** Run `fn` when audio-clock time `at` reaches the speaker. */
  function whenHeard(at, fn) {
    const ctx = player?.context;
    const ms = ctx ? (at - ctx.currentTime + (ctx.outputLatency || ctx.baseLatency || 0)) * 1000 : 0;
    setTimeout(() => { if (state !== 'closed') fn(); }, Math.max(0, ms));
  }
  function heard(combo) {
    const o = opts.find((x) => comboFor(x.id) === combo);
    if (!o || !player.playing) return;
    const fresh = audible !== o.id;
    audible = o.id;
    paint();
    if (fresh) cueAudible();
  }
  async function startPreview() {
    if (!player) return;
    const first = comboFor(selected);
    if (!player.has(first)) { paint(); return; }
    player.load([first, ...opts.map((o) => comboFor(o.id)).filter((c) => c !== first)]);
    paint();
    await player.play(first, { loop, from: Array.isArray(loop) ? loop[0] : 0 });
    paint();
  }
  function stopPreview(fade) {
    player?.stop(fade ? { fade } : undefined);
    audible = null;
  }

  // --- the selection ---
  let angle = angles[opts.findIndex((o) => o.id === selected)];
  const setAngle = (deg) => { angle = deg; turn.style.transform = `rotate(${deg.toFixed(2)}deg)`; };
  setAngle(angle);
  let lastKnock = 0;
  function select(id, { snap = false, from = null } = {}) {
    if (state !== 'open') return;
    const i = opts.findIndex((o) => o.id === id);
    if (i < 0) return;
    const changed = id !== selected;
    selected = id;
    if (snap) snapKnob(angles[i], from);
    if (changed) {
      haptic(true);
      const now = performance.now();
      if (now - lastKnock > 90) { knock(soundId()); lastKnock = now; }
      board.parentElement.animate([{ transform: 'translateY(0)' }, { transform: `translate(${i > 1 ? 1.5 : -1.5}px, 1.5px)` },
        { transform: 'translateY(0)' }], { duration: 140, easing: 'ease-out' });
      label.classList.remove('swap'); void label.offsetWidth; label.classList.add('swap');
      if (player?.playing) {
        const combo = comboFor(id);
        if (player.has(combo)) player.switchTo(combo);
      }
    }
    paint();
  }
  function snapKnob(target, from = angle) {
    const start = from ?? angle;
    setAngle(target);
    if (reduced()) return;
    const over = target + Math.sign(target - start || 1) * 6;
    turn.animate([{ transform: `rotate(${start}deg)` }, { transform: `rotate(${over}deg)`, offset: 0.55 },
      { transform: `rotate(${target}deg)` }], { duration: 240, easing: HEAVY });
  }
  function cueAudible() {
    if (reduced()) return;
    rings.replaceChildren(...[0, 1, 2].map((i) => h('i', { style: `animation-delay:${i * 80}ms` })));
    label.classList.remove('flash'); void label.offsetWidth; label.classList.add('flash');
    haptic();
  }

  function paint() {
    const o = optOf(selected);
    num.textContent = `No. ${ROMAN[o.id] ?? o.id}`;
    name.textContent = o.name;
    about.textContent = o.about ?? '';
    flag.textContent = mine === o.id ? 'Committed' : '';
    label.style.setProperty('--tilt', `${[-1.6, 0.9, -0.5, 1.2][(o.id - 1) % 4]}deg`);
    knob.setAttribute('aria-valuenow', String(o.id));
    knob.setAttribute('aria-valuetext', `${ROMAN[o.id] ?? o.id}: ${o.name}`);
    const combo = comboFor(selected);
    const playing = Boolean(player?.playing);
    for (const t of tabs) {
      const id = Number(t.dataset.id), c = comboFor(id);
      t.setAttribute('aria-checked', String(id === selected));
      t.dataset.lamp = !player || !player.has(c) ? 'none' : playing && audible === id ? 'on'
        : playing && id === selected ? 'pending' : 'off';
      t.classList.toggle('mine', id === mine);
    }
    root.dataset.cue = !playing ? 'idle' : audible === selected ? 'audible' : player.has(combo) ? 'pending' : 'missing';
    root.dataset.playing = String(playing);
    play.setAttribute('aria-label', playing ? 'Stop' : 'Play');
    play.disabled = !player;
    note.textContent = !player ? 'The renders are not here yet: the selector works, and the sound comes when Live has made them.'
      : !player.has(combo) ? `${ROMAN[o.id] ?? o.id} with the others as they are isn't rendered yet.`
        : playing && audible !== selected ? `Loading ${ROMAN[o.id] ?? o.id}…` : '';
    note.hidden = !note.textContent;
  }

  // the knob: turned by a drag round its centre, tapped on to step, or by the keys
  let drag = null;
  listen(knob, 'pointerdown', (e) => {
    if (state !== 'open') return;
    wakeAll();
    const r = knob.getBoundingClientRect();
    const c = [r.left + r.width / 2, r.top + r.height / 2];
    drag = { id: e.pointerId, c, a0: Math.atan2(e.clientX - c[0], c[1] - e.clientY) * 180 / Math.PI, start: angle,
      x: e.clientX, y: e.clientY, t: performance.now(), moved: false,
      sideways: Math.hypot(e.clientX - c[0], e.clientY - c[1]) < 26 };   // from the middle: a sideways swipe turns it
    knob.setPointerCapture?.(e.pointerId);
    turn.getAnimations().forEach((a) => a.cancel());
    root.classList.add('turning');
  });
  listen(knob, 'pointermove', (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) > 6) drag.moved = true;
    if (!drag.moved) return;
    let d = drag.sideways ? (e.clientX - drag.x) * 0.9 : Math.atan2(e.clientX - drag.c[0], drag.c[1] - e.clientY) * 180 / Math.PI - drag.a0;
    if (d > 180) d -= 360; else if (d < -180) d += 360;
    const raw = Math.max(angles[0] - 18, Math.min(angles[n - 1] + 18, drag.start + d));
    const near = angles.reduce((b, a, i) => (Math.abs(a - raw) < Math.abs(angles[b] - raw) ? i : b), 0);
    setAngle(raw + (angles[near] - raw) * 0.45);                          // the detents pull
    if (opts[near].id !== selected) select(opts[near].id);
  });
  const endDrag = (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    const d = drag;
    drag = null;
    root.classList.remove('turning');
    const i = opts.findIndex((o) => o.id === selected);
    if (!d.moved && e.type === 'pointerup' && performance.now() - d.t < 500) {   // a tap steps to the next
      const next = opts[(i + 1) % n];
      select(next.id, { snap: true });
      return;
    }
    snapKnob(angles[i]);
  };
  listen(knob, 'pointerup', endDrag);
  listen(knob, 'pointercancel', endDrag);
  listen(knob, 'keydown', (e) => {
    const i = opts.findIndex((o) => o.id === selected);
    const j = e.key === 'ArrowRight' || e.key === 'ArrowUp' ? i + 1 : e.key === 'ArrowLeft' || e.key === 'ArrowDown' ? i - 1 : null;
    if (j == null) return;
    e.preventDefault();
    if (j >= 0 && j < n) select(opts[j].id, { snap: true });
  });

  // play / stop
  onTap(play, () => {
    if (!player || state !== 'open') return;
    if (player.playing) { stopPreview(); paint(); haptic(); return; }
    wakeAll();
    haptic();
    startPreview();
  });

  // the lever: dragged down past LATCH, or held, or Enter on it
  let pull = 0, lev = null;
  const ROD = 18;                                                          // px of rod above the handle at rest
  const travel = () => Math.max(60, lever.clientHeight - 118);
  const setPull = (p) => { pull = p; lever.style.setProperty('--pull', p.toFixed(4)); lever.style.setProperty('--travel', `${travel()}px`); };
  setPull(0);
  listen(lever, 'pointerdown', (e) => {
    if (state !== 'open') return;
    e.preventDefault();
    wakeAll();
    lever.setPointerCapture?.(e.pointerId);
    lever.getAnimations().forEach((a) => a.cancel());
    lev = { id: e.pointerId, y: e.clientY, x: e.clientX, p0: pull, moved: false, ticks: 0,
      hold: setTimeout(() => { if (lev && !lev.moved) { lev = null; lever.classList.remove('holding'); commit(); } }, HOLD_MS) };
    lever.classList.add('holding');
  });
  listen(lever, 'pointermove', (e) => {
    if (!lev || e.pointerId !== lev.id) return;
    const dy = e.clientY - lev.y;
    if (!lev.moved && Math.hypot(e.clientX - lev.x, dy) > 6) { lev.moved = true; clearTimeout(lev.hold); lever.classList.remove('holding'); }
    if (!lev.moved) return;
    const raw = Math.max(0, Math.min(1, lev.p0 + dy / travel()));
    setPull(raw < 0.08 ? raw * 0.5 : raw - 0.04);                       // stiff at first: it breaks away
    const tick = Math.floor(pull * 4);
    if (tick > lev.ticks) { lev.ticks = tick; haptic(); }
    if (pull >= LATCH) { clearTimeout(lev.hold); lev = null; lever.classList.remove('holding'); commit(); }
  });
  const letGo = (e) => {
    if (!lev || e.pointerId !== lev.id) return;
    clearTimeout(lev.hold);
    const moved = lev.moved;
    lev = null;
    lever.classList.remove('holding');
    if (state !== 'open') return;
    if (!moved) nudge();
    else springBack();
  };
  listen(lever, 'pointerup', letGo);
  listen(lever, 'pointercancel', letGo);
  listen(lever, 'click', (e) => { if (e.detail === 0) commit(); });       // the keyboard
  // The handle sits at `top: var(--pull) * var(--travel)`; its transform is free for the animations.
  function springBack() {
    const from = pull * travel();
    setPull(0);
    haptic();
    if (reduced()) return;
    handle.animate([{ transform: `translateY(${from}px)` }, { transform: 'translateY(-9px)', offset: 0.62 },
      { transform: 'translateY(0)' }], { duration: 400, easing: HEAVY });
    rod.animate([{ transform: `scaleY(${(ROD + from) / ROD})` }, { transform: 'scaleY(1)' }], { duration: 250, easing: HEAVY });
  }
  function nudge() {
    haptic();
    hint.classList.remove('show'); void hint.offsetWidth; hint.classList.add('show');
    if (reduced()) return;
    handle.animate([{ transform: 'translateY(0)' }, { transform: 'translateY(16px)', offset: 0.35 },
      { transform: 'translateY(-3px)', offset: 0.75 }, { transform: 'translateY(0)' }], { duration: 420, easing: 'ease-out' });
  }

  // --- the commit: slam, distil, stamp, drop ---
  async function commit() {
    if (state !== 'open') return;
    state = 'committing';
    root.dataset.state = 'committing';
    const id = selected;
    const o = optOf(id);
    const fast = reduced();
    const pal = palette(part);
    // 1. the slam
    const from = pull;
    setPull(1);
    if (!fast) {
      const ms = Math.max(60, 150 * (1 - from));
      handle.animate([{ transform: `translateY(${(from - 1) * travel()}px)` }, { transform: 'translateY(0)' }], { duration: ms, easing: SLAM });
      rod.animate([{ transform: `scaleY(${(ROD + from * travel()) / (ROD + travel())})` }, { transform: 'scaleY(1)' }], { duration: ms, easing: SLAM });
      await sleep(ms);
    }
    const lr = handle.getBoundingClientRect();
    haptic(true);
    thud(soundId());
    stopPreview(0.9);
    if (!fast) {
      shake(stage, 13, 460);
      fx.burst(lr.left + lr.width / 2, lr.bottom, { power: 0.9, colors: pal, floor: lr.bottom + 40 });
      handle.animate([{ transform: 'scaleY(.8)' }, { transform: 'none' }], { duration: 260, easing: HEAVY });
      lever.animate([{ transform: 'translateY(3px)' }, { transform: 'none' }], { duration: 200, easing: HEAVY });
      await sleep(110);                                               // the hit stop
    }
    // 2. the choice is distilled: the board dims, scraps fly together into the artifact
    root.dataset.state = 'distilling';
    const cx = innerWidth / 2, cy = Math.min(innerHeight * 0.4, 330);
    const art = artifactEl(o, part, info);
    const stampEl = h('div', { class: 'mc-stamp' }, h('b', { text: `SH001 · ${part.toUpperCase()} · ${ROMAN[id] ?? id}` }),
      h('span', { text: new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }).toUpperCase() }));
    const piece = h('div', { class: 'mc-piece', style: `left:${cx}px;top:${cy}px` }, h('i', { class: 'mc-glow' }), art, stampEl);
    distill.append(piece);
    if (!fast) {
      fx.converge([label.getBoundingClientRect(), selector.getBoundingClientRect(), panel.getBoundingClientRect()], cx, cy,
        { n: 90, ms: 820, colors: pal });
      await sleep(640);
    }
    piece.classList.add('in');
    haptic();
    if (!fast) {
      await art.animate([{ transform: 'scale(.2) rotate(-25deg)', opacity: 0 }, { transform: 'scale(1.14) rotate(4deg)', opacity: 1, offset: 0.6 },
        { transform: 'scale(1) rotate(-3deg)', opacity: 1 }], { duration: 420, easing: HEAVY, fill: 'forwards' }).finished;
      await sleep(120);
      // 3. the stamp
      await stampEl.animate([{ transform: 'translate(-50%, -50%) scale(3.2) rotate(-18deg)', opacity: 0 },
        { transform: 'translate(-50%, -50%) scale(1) rotate(-8deg)', opacity: 0.94 }], { duration: 190, easing: SLAM, fill: 'forwards' }).finished;
    }
    stampEl.classList.add('down');
    haptic(true);
    thud(soundId(), { strong: true });
    if (!fast) {
      shake(stage, 17, 540);
      shake(piece, 6, 300);
      fx.burst(cx, cy, { power: 1.3, colors: pal, floor: cy + 140 });
      art.animate([{ transform: 'scale(.9) rotate(-3deg)' }, { transform: 'scale(1) rotate(-3deg)' }], { duration: 300, easing: HEAVY, fill: 'forwards' });
      await sleep(560);
      // 4. it drops toward the wanderer's hands, and the machine goes
      root.classList.add('leaving');
      await piece.animate([{ transform: 'translate(0, 0) rotate(0deg) scale(1)' }, { transform: 'translate(0, -18px) rotate(-4deg) scale(1.04)', offset: 0.18 },
        { transform: `translate(0, ${innerHeight - cy + 40}px) rotate(14deg) scale(.55)` }],
      { duration: 620, easing: 'cubic-bezier(.5,0,.9,.5)', fill: 'forwards' }).finished;
    }
    try { onCommit(id); } catch (err) { console.warn('onCommit', err); }
    teardown({ committed: id });
  }

  // --- open, close ---
  function teardown(result) {
    if (state === 'closed') return;
    state = 'closed';
    root.dataset.state = 'closed';
    offs.forEach((f) => f());
    offPlayer?.();
    fx.destroy();
    thumbs?.destroy();
    root.remove();
    try { onClose(result); } catch (err) { console.warn('onClose', err); }
  }
  async function closeMachine() {
    if (state !== 'open') return;
    state = 'closing';
    root.dataset.state = 'closing';
    stopPreview(0.25);
    haptic();
    if (!reduced()) {
      await root.animate([{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'translateY(24px) scale(.98)' }],
        { duration: 240, easing: 'ease-in', fill: 'forwards' }).finished;
    }
    teardown({ committed: null });
  }
  onTap(close, closeMachine);
  listen(document, 'keydown', (e) => { if (e.key === 'Escape') closeMachine(); });

  paint();
  const entrance = reduced() ? [] : [
    root.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 220, easing: 'ease-out' }),
    panel.animate([{ transform: 'scale(1.08)' }, { transform: 'scale(1)' }], { duration: 700, easing: HEAVY }),
    deck.animate([{ transform: 'translateY(70%)' }, { transform: 'translateY(0)' }], { duration: 560, easing: HEAVY }),
    label.animate([{ transform: 'translateY(-40px) rotate(-8deg)', opacity: 0 }, { transform: 'none', opacity: 1 }],
      { duration: 520, delay: 260, easing: HEAVY, fill: 'backwards' }),
  ];
  Promise.all(entrance.map((a) => a.finished)).then(() => { root.dataset.ready = 'true'; }, () => {});   // settled in place
  if (player) { player.wake(); startPreview(); }

  // the bar counter and the loop's progress, while it plays
  let raf = 0, shown = '';
  const frame = () => {
    if (state === 'closed') return;
    raf = requestAnimationFrame(frame);
    if (!player || !bar) return;
    const playing = Boolean(player.playing);
    const pos = playing ? player.position() : 0;
    const b = Math.floor(pos / bar) + 1;
    const text = playing ? `BAR ${String(b).padStart(2, '0')}/${audio.bars}` : `${audio.bars} BARS`;
    if (text !== shown) {
      shown = text;
      counter.textContent = text;
      where.textContent = playing ? sectionOf(b) : 'stopped';
    }
    const [a, z] = Array.isArray(loop) ? loop : [0, audio.seconds];
    const k = playing ? Math.max(0, Math.min(1, (pos - a) / (z - a))) : 0;
    prog.setAttribute('stroke-dashoffset', (ringLen * (1 - k)).toFixed(1));
  };
  raf = requestAnimationFrame(frame);
  offs.push(() => cancelAnimationFrame(raf));

  return { close: closeMachine, context, get selected() { return selected; }, commit, select: (id) => select(id, { snap: true }) };
}

function sectionOf(b) {
  return b <= 8 ? 'the bed alone' : b <= 16 ? 'bed and drums' : b <= 28 ? 'all three' : 'the outro';
}

function arc(cx, cy, r, a0, a1) {
  const p = (a) => [cx + Math.sin((a * Math.PI) / 180) * r, cy - Math.cos((a * Math.PI) / 180) * r];
  const [x0, y0] = p(a0), [x1, y1] = p(a1);
  return `M${x0.toFixed(1)} ${y0.toFixed(1)}A${r} ${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1.toFixed(1)} ${y1.toFixed(1)}`;
}

/** The scraps' colours: the part's enamel, kraft, cream, brass, ink. */
function palette(part) {
  const acc = { bed: ['#2e7d78', '#9ccfc4'], drums: ['#c2402c', '#e8b23a'], bass: ['#2f4f8f', '#7d2a24'] }[part] ?? ['#c2402c', '#2e7d78'];
  return [...acc, '#c79d6a', '#f1e8d2', '#d9b25a', '#2a2320'];
}

/** The artifact: its art, or a medallion of cut paper with the part's sign and the option's number. */
function artifactEl(o, part, info) {
  if (o.artifact) return h('img', { class: 'mc-artifact', src: o.artifact, alt: o.name, draggable: 'false' });
  return h('div', { class: 'mc-artifact mc-medal', 'data-part': part },
    h('i', { class: 'mc-medal-ring' }),
    h('svg', { class: 'mc-medal-glyph', viewBox: '0 0 24 24', 'aria-hidden': 'true' }, h('path', { d: info.glyph })),
    h('b', { text: ROMAN[o.id] ?? String(o.id) }));
}

/** The panel when there is no art: the machine's face in cut paper, wood, brass and enamel. */
function placeholder(part) {
  const r = rng(hash(`${part}-panel`));
  const R = (a, b) => a + r() * (b - a);
  const scraps = Array.from({ length: 9 }, (_, i) => h('i', {
    class: `mc-ph-scrap k${i % 5}`,
    style: `left:${R(-8, 82).toFixed(0)}%;top:${R(6, 64).toFixed(0)}%;width:${R(18, 46).toFixed(0)}%;height:${R(5, 16).toFixed(0)}%;`
      + `transform:rotate(${R(-14, 14).toFixed(1)}deg);clip-path:${torn(`${part}-s${i}`, { amp: 4, step: 6 })}`,
  }));
  const dials = Array.from({ length: 3 }, (_, i) => h('i', {
    class: 'mc-ph-dial', style: `left:${(14 + i * 27 + R(-3, 3)).toFixed(0)}%;top:${(44 + R(-4, 6)).toFixed(0)}%;`
      + `--s:${R(44, 70).toFixed(0)}px;transform:rotate(${R(-60, 60).toFixed(0)}deg)`,
  }));
  return h('div', { class: 'mc-ph', 'data-part': part, 'aria-hidden': 'true' },
    h('i', { class: 'mc-ph-wood' }), ...scraps,
    h('i', { class: 'mc-ph-grille' }), h('i', { class: 'mc-ph-window' }, h('i', { class: 'mc-ph-needle' })),
    ...dials, h('i', { class: 'mc-ph-strip' }),
    h('i', { class: 'mc-screw p1' }), h('i', { class: 'mc-screw p2' }), h('i', { class: 'mc-screw p3' }), h('i', { class: 'mc-screw p4' }));
}
