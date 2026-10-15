// Stand-ins for the machine and the player (machine.js and player.js), so the region plays end to end before they
// land or if one fails to load: a plain overlay that lists a machine's three options, plays the short with the one
// chosen (through whatever player there is) and commits it; and a player that keeps time but makes no sound.
// Same interfaces as the real ones:
//
//   openStubMachine(host, { part, machine: { name, panel }, options: [{ id, name, about, artifact }], committed,
//                           player, onCommit(id), onClose() }) -> { close() }
//   silentPlayer({ audio }) -> { load(combos), play(combo, { loop }), switchTo(combo), stop(), playing, position(),
//                                duration, onEnded(fn), release() }
import { haptic, onTap } from '../concepts/model.js';
import { PARTS } from './region.js';

const SVG = 'http://www.w3.org/2000/svg';
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') el.className = v; else if (k === 'text') el.textContent = v; else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
}
export function icon(d, cls = '') {
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
  if (cls) svg.setAttribute('class', cls);
  for (const one of [].concat(d)) { const p = document.createElementNS(SVG, 'path'); p.setAttribute('d', one); svg.append(p); }
  return svg;
}
export const PLAY = 'M8 5v14l11-7z', STOP = 'M7 7h10v10H7z', CLOSE = 'M6 6l12 12M18 6L6 18';

export function openStubMachine(host, { part, machine, options, committed, player, onCommit, onClose }) {
  let pick = committed?.[part] ?? 1, playing = false, done = false;
  const combo = (id) => PARTS.map((p) => (p === part ? id : committed?.[p] ?? 1)).join('-');
  const x = h('button', { type: 'button', class: 'sm-x', 'aria-label': 'Close the machine' }, icon(CLOSE));
  const play = h('button', { type: 'button', class: 'sm-play', 'aria-label': 'Play' }, icon(PLAY));
  const lever = h('button', { type: 'button', class: 'sm-commit' });
  const rows = options.map((o) => {
    const b = h('button', { type: 'button', class: 'sm-opt', role: 'radio', 'data-id': String(o.id) },
      o.artifact ? h('img', { src: o.artifact, alt: '' }) : h('i', { text: String(o.id) }),
      h('span', {}, h('b', { text: o.name }), h('small', { text: o.about ?? '' })));
    onTap(b, () => {
      pick = o.id; haptic(); paint();
      if (playing) player.switchTo(combo(pick));
    });
    return b;
  });
  const root = h('section', { class: 'sm', role: 'dialog', 'aria-label': machine.name },
    machine.panel ? h('img', { class: 'sm-panel', src: machine.panel, alt: '' }) : null,
    h('header', {}, h('div', {}, h('b', { text: machine.name }), h('span', { text: `choose ${part === 'bass' ? 'the low end' : `the ${part}`}` })), x),
    h('div', { class: 'sm-opts', role: 'radiogroup', 'aria-label': 'Options' }, rows),
    h('footer', {}, play, lever));
  host.append(root);
  requestAnimationFrame(() => root.classList.add('show'));
  function paint() {
    for (const b of rows) b.setAttribute('aria-checked', String(Number(b.dataset.id) === pick));
    const o = options.find((q) => q.id === pick);
    lever.textContent = `Commit · ${o?.name ?? pick}`;
    play.replaceChildren(icon(playing ? STOP : PLAY));
    play.setAttribute('aria-label', playing ? 'Stop' : 'Play');
  }
  onTap(play, () => {
    haptic();
    if (playing) { player.stop(); playing = false; } else {
      playing = true;
      Promise.resolve(player.load([combo(pick)])).catch(() => null).then(() => { if (playing) player.play(combo(pick), { loop: true }); });
    }
    paint();
  });
  onTap(lever, () => { haptic(true); onCommit(pick); close(); });
  onTap(x, () => close());
  function close() {
    if (done) return;
    done = true;
    if (playing) player.stop();
    root.classList.remove('show');
    setTimeout(() => root.remove(), 260);
    onClose?.();
  }
  paint();
  return { close };
}

export function silentPlayer({ audio } = {}) {
  const duration = audio?.seconds ?? 64;
  let t0 = 0, at = 0, playing = false, loop = false, timer = 0;
  const ended = new Set();
  const p = {
    duration,
    get playing() { return playing; },
    load: async () => {},
    play(combo, { loop: l = false } = {}) {
      p.stop();
      playing = true; loop = l; t0 = performance.now(); at = 0;
      const tick = () => {
        if (!playing) return;
        if (p.position() >= duration && !loop) { playing = false; for (const fn of ended) fn(); return; }
        timer = setTimeout(tick, 250);
      };
      tick();
    },
    switchTo() {},
    stop() { playing = false; clearTimeout(timer); at = 0; },
    position() { return playing ? (at + (performance.now() - t0) / 1000) % (loop ? duration : Infinity) : 0; },
    onEnded(fn) { ended.add(fn); },
    release() { p.stop(); ended.clear(); },
    silent: true,
  };
  return p;
}
