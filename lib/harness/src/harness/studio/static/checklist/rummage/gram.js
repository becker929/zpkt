// The Gramophone, opened (docs/rummage.md): the track's checklist as a machine. A sheet over the bottom of the
// screen, with the Gramophone itself still in view above it: its three plinths (what is on each, or which machine
// to go and operate), a big play control that plays the short as made (the render of the three choices, at full
// length, through the player), and the record sleeve that is the reward for finishing it.
//
//   openGramophone(host, { plinths, names, art, player, combo, finished, onPlay(combo) -> fresh, onClose })
//     -> { close(), playing() }
//
// `player` is player.js's, or null while the music isn't rendered: the short can still be finished (the plate, the
// sleeve), and the Gramophone says it will play when Live has made it.
import { haptic, onTap } from '../concepts/model.js';
import { MACHINES, PARTS } from './region.js';
import { CLOSE, PLAY, STOP, icon } from './stub.js';

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') el.className = v; else if (k === 'text') el.textContent = v; else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
}
const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

/** An artifact as a picture: its file, or its placeholder painted small. */
export function picture(art, key, px = 120) {
  const a = art.artifacts[key];
  if (a.url) return h('img', { src: a.url, alt: '' });
  const c = document.createElement('canvas'), k = Math.min(px / a.w, px / a.h), dpr = Math.min(3, devicePixelRatio || 1);
  c.width = Math.ceil(a.w * k * dpr); c.height = Math.ceil(a.h * k * dpr);
  const g = c.getContext('2d');
  g.setTransform(k * dpr, 0, 0, k * dpr, 0, 0);
  a.draw(g);
  return c;
}

export function openGramophone(host, { plinths, names, art, player, combo, finished, onPlay, onClose }) {
  let closed = false, raf = 0, ready = false;
  const x = h('button', { type: 'button', class: 'gm-x', 'aria-label': 'Back to the region' }, icon(CLOSE));
  const R = 44, CIRC = 2 * Math.PI * R;
  const ring = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  ring.setAttribute('viewBox', '0 0 100 100'); ring.setAttribute('class', 'gm-ring'); ring.setAttribute('aria-hidden', 'true');
  ring.innerHTML = `<circle cx="50" cy="50" r="${R}" class="gm-track"/><circle cx="50" cy="50" r="${R}" class="gm-done" stroke-dasharray="${CIRC}" stroke-dashoffset="${CIRC}"/>`;
  const glyph = h('span', { class: 'gm-glyph' }, icon(PLAY));
  const play = h('button', { type: 'button', class: 'gm-play', 'aria-label': 'Play the short' }, ring, glyph);
  const time = h('p', { class: 'gm-time' });
  const note = h('p', { class: 'gm-note' });
  const sleeve = h('button', { type: 'button', class: 'gm-sleeve', 'aria-label': 'The record sleeve' });
  const slots = PARTS.map((part) => {
    const key = plinths[part];
    return h('div', { class: `gm-slot ${part}${key ? ' full' : ''}`, 'data-part': part },
      h('figure', {}, key ? picture(art, key, 90) : h('i', { class: 'gm-empty' })),
      h('b', { text: MACHINES[part].name }),
      h('span', { text: key ? names[part] ?? `option ${key.split('-')[1]}` : `empty: operate it` }));
  });
  const root = h('section', { class: 'gm', role: 'dialog', 'aria-label': 'The Gramophone' },
    h('header', {}, h('div', {}, h('b', { text: 'The Gramophone' }), h('span', { text: 'SH001 · the short, as made' })), x),
    h('div', { class: 'gm-slots' }, slots),
    h('div', { class: 'gm-deck' }, play, h('div', { class: 'gm-words' }, time, note), sleeve));
  host.replaceChildren(root);
  host.classList.add('show'); host.setAttribute('aria-hidden', 'false');
  if (!combo) root.classList.add('waiting');

  const missing = PARTS.filter((p) => !plinths[p]).map((p) => MACHINES[p].name);
  const audible = !!(player && combo && (player.has ? player.has(combo) : true));
  let silent = false;
  function paint() {
    const on = !!player?.playing;
    glyph.replaceChildren(icon(on ? STOP : PLAY));
    play.setAttribute('aria-label', on ? 'Stop' : 'Play the short');
    root.classList.toggle('playing', on);
    note.textContent = !combo ? `Bring ${missing.join(', ').replace(/, ([^,]*)$/, ' and $1')} to finish the short.`
      : silent ? 'Finished. The short isn’t rendered yet: it plays here when Live has made it.'
        : on ? 'Playing the short as made.' : finished ? 'Finished. Recommit any machine to change it.' : 'All three are on. Play the short.';
  }
  function tick() {
    if (closed) return;
    const d = player?.duration || 0, p = player?.playing ? player.position() : 0;
    time.textContent = combo && audible && !silent ? `${clock(p)} / ${clock(d)}` : '';
    ring.lastChild.setAttribute('stroke-dashoffset', String(CIRC * (1 - (d ? Math.min(1, p / d) : 0))));
    raf = requestAnimationFrame(tick);
  }
  // the record sleeve for this combination: the reward. Finishing it, it fills the screen for a moment; after, it
  // is a small card in the sheet that brings it back
  const face = () => {
    const s = art.sleeve?.(combo);
    return s ? h('img', { src: s.url, alt: 'The record sleeve for SH001' })
      : h('div', { class: 'gm-mock' }, h('b', { text: 'SH001' }), h('div', {}, PARTS.map((p) => picture(art, plinths[p], 60))), h('span', { text: 'The Rummage' }));
  };
  let reveal = null, revealTimer = 0;
  function showSleeve(fresh) {
    sleeve.replaceChildren(face());
    sleeve.classList.add('show');
    if (fresh) open();
  }
  function open(fresh = true) {
    shut();
    reveal = h('section', { class: `gm-reveal${fresh ? ' fresh' : ''}`, role: 'dialog', 'aria-label': 'SH001 is finished' },
      h('figure', {}, face()),
      h('b', { text: fresh ? 'SH001 is finished' : 'SH001' }),
      h('span', { text: fresh ? 'A plate is hung in the museum. The sleeve is yours.' : PARTS.map((p) => names[p]).join(' · ') }));
    document.body.append(reveal);
    requestAnimationFrame(() => reveal?.classList.add('show'));
    onTap(reveal, shut);
    revealTimer = setTimeout(shut, fresh ? 6000 : 8000);
  }
  function shut() {
    clearTimeout(revealTimer);
    if (!reveal) return;
    const r = reveal;
    reveal = null;
    r.classList.remove('show');
    setTimeout(() => r.remove(), 400);
  }
  onTap(sleeve, () => { haptic(); open(false); });
  const loading = audible ? Promise.resolve(player.load([combo])).then(() => { ready = true; }, () => { ready = true; }) : null;
  function start() {
    Promise.resolve().then(() => player.play(combo, { loop: false })).then(paint, () => { silent = true; paint(); });
    paint();
  }
  onTap(play, () => {
    if (!combo) { haptic(); root.classList.remove('nudge'); void root.offsetWidth; root.classList.add('nudge'); return; }
    haptic(true);
    player?.wake?.();                          // inside the tap: iOS lets the audio start only from one
    if (player?.playing) { player.stop(); paint(); return; }
    const fresh = onPlay(combo);
    if (fresh) { finished = true; showSleeve(true); }
    if (!audible) { silent = true; paint(); return; }
    if (ready) start(); else { note.textContent = 'Loading the short…'; loading.then(() => { if (!closed) start(); }); }
  });
  const offEnded = player?.onEnded?.(() => { if (!closed) paint(); });
  onTap(x, () => close());
  function close() {
    if (closed) return;
    closed = true;
    cancelAnimationFrame(raf);
    offEnded?.();
    if (player?.playing) player.stop({ fade: 0.6 });
    shut();
    host.classList.remove('show'); host.setAttribute('aria-hidden', 'true');
    onClose?.();
  }
  if (finished && combo) showSleeve(false);
  paint();
  raf = requestAnimationFrame(tick);
  return { close, playing: () => !!player?.playing };
}
