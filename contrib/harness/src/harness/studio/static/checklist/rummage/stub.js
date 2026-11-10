// A stand-in for the machine (machine.js), so the region plays end to end if the real one fails to load (or with
// ?stub in the URL): a plain overlay that lists a machine's three options, plays the short with the one chosen
// through the player (none while the renders aren't here: then it says so) and commits it. The same interface:
//
//   openStubMachine(host, { part, machine: { name, panel }, options: [{ id, name, about, artifact }], committed,
//                           player, onCommit(id), onClose({ committed }) }) -> { close(), commit(), select(id), selected }
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
  let pick = committed?.[part] ?? 1, playing = false, done = false, result = null;
  const combo = (id) => PARTS.map((p) => (p === part ? id : committed?.[p] ?? 1)).join('-');
  const x = h('button', { type: 'button', class: 'sm-x', 'aria-label': 'Close the machine' }, icon(CLOSE));
  const play = h('button', { type: 'button', class: 'sm-play', 'aria-label': 'Play' }, icon(PLAY));
  const lever = h('button', { type: 'button', class: 'sm-commit' });
  const rows = options.map((o) => {
    const b = h('button', { type: 'button', class: 'sm-opt', role: 'radio', 'data-id': String(o.id) },
      o.artifact ? h('img', { src: o.artifact, alt: '' }) : h('i', { text: String(o.id) }),
      h('span', {}, h('b', { text: o.name }), h('small', { text: o.about ?? '' })));
    onTap(b, () => select(o.id));
    return b;
  });
  const root = h('section', { class: 'sm', role: 'dialog', 'aria-label': machine.name },
    machine.panel ? h('img', { class: 'sm-panel', src: machine.panel, alt: '' }) : null,
    h('header', {}, h('div', {}, h('b', { text: machine.name }), h('span', { text: `choose ${part === 'bass' ? 'the low end' : `the ${part}`}` })), x),
    h('div', { class: 'sm-opts', role: 'radiogroup', 'aria-label': 'Options' }, rows),
    h('p', { class: 'sm-note' }), h('footer', {}, play, lever));
  const note = root.querySelector('.sm-note');
  host.append(root);
  requestAnimationFrame(() => root.classList.add('show'));
  function paint() {
    for (const b of rows) b.setAttribute('aria-checked', String(Number(b.dataset.id) === pick));
    const o = options.find((q) => q.id === pick);
    lever.textContent = `Commit · ${o?.name ?? pick}`;
    play.replaceChildren(icon(playing ? STOP : PLAY));
    play.setAttribute('aria-label', playing ? 'Stop' : 'Play');
    play.disabled = !player;
    note.textContent = player ? '' : 'The renders are not here yet: choose by name, and hear it when Live has made them.';
  }
  function select(id) {
    pick = id; haptic(); paint();
    if (playing) player?.switchTo(combo(pick));
  }
  onTap(play, () => {
    haptic();
    if (!player) return;
    player.wake?.();
    if (playing) { player.stop(); playing = false; } else {
      playing = true;
      Promise.resolve(player.load([combo(pick)])).catch(() => null).then(() => { if (playing) player.play(combo(pick), { loop: true }); });
    }
    paint();
  });
  function commit() { haptic(true); result = pick; onCommit(pick); close(); }
  onTap(lever, commit);
  onTap(x, () => close());
  function close() {
    if (done) return;
    done = true;
    if (playing) player?.stop();
    root.classList.remove('show');
    setTimeout(() => root.remove(), 260);
    onClose?.({ committed: result });
  }
  paint();
  return { close, commit, select, get selected() { return pick; } };
}
