// Live widgets for the armed card: pointer, wheel and keyboard input on top of the shared drawings.
// Each widget gets the card's small interface (values, set, hit, flash, saveState) and returns
// { el, redraw(), destroy() }. Frozen cards never create widgets.
import { draw, defs, sizeOf, AB_LANE, PAL_CSS } from './draw.js';
import { ICON } from './icons.js';
import { Deck, oneShot } from './player.js';
import { mediaUrl, S } from './state.js';

function base(card, k, extra = () => ({})) {
  const [w, h] = sizeOf(k);
  const el = document.createElement('div');
  el.className = `zs-w zs-${k.kind}`;
  el.style.width = `${w}px`;
  el.style.height = `${sizeOf(k, true)[1]}px`;
  const holder = document.createElement('div');
  el.append(holder);
  const redraw = () => { holder.innerHTML = `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">${defs()}${draw(k, card.values[k.id], PAL_CSS, extra())}</svg>`; };
  redraw();
  return { el, redraw, w, h };
}

function slider(card, k) {
  const W = base(card, k);
  const { el } = W;
  const span = k.max - k.min;
  const fine = (e) => (e.shiftKey ? 0.1 : 1);
  el.tabIndex = 0;
  el.setAttribute('role', 'slider');
  el.setAttribute('aria-label', k.label);
  el.setAttribute('aria-valuemin', k.min);
  el.setAttribute('aria-valuemax', k.max);
  const redraw = () => { W.redraw(); el.setAttribute('aria-valuenow', card.values[k.id]); };
  redraw();
  let drag = null;
  el.addEventListener('pointerdown', (e) => { e.preventDefault(); el.setPointerCapture?.(e.pointerId); drag = { y: e.clientY, v: card.values[k.id] }; });
  el.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const px = k.kind === 'fader' ? W.h - 56 : 160; // drag distance for the full range; Shift for fine
    card.set(k, drag.v + ((drag.y - e.clientY) / px) * span * fine(e), 'drag');
  });
  const end = () => { if (drag) { drag = null; card.settled(); } };
  el.addEventListener('pointerup', end);
  el.addEventListener('pointercancel', end);
  el.addEventListener('dblclick', () => card.set(k, k.value));
  el.addEventListener('wheel', (e) => { e.preventDefault(); card.set(k, card.values[k.id] - Math.sign(e.deltaY) * (k.step || span / 100) * fine(e), 'drag'); }, { passive: false });
  el.addEventListener('keydown', (e) => {
    const d = { ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1, PageUp: 10, PageDown: -10 }[e.key];
    if (d) { e.preventDefault(); card.set(k, card.values[k.id] + d * (k.step || span / 100)); }
    if (e.key === 'Home') card.set(k, k.min);
    if (e.key === 'End') card.set(k, k.max);
  });
  return { el, redraw };
}

function toggle(card, k) {
  const W = base(card, k);
  const { el } = W;
  el.tabIndex = 0;
  el.setAttribute('role', 'switch');
  el.setAttribute('aria-label', k.label);
  const redraw = () => { W.redraw(); el.setAttribute('aria-checked', String(!!card.values[k.id])); };
  redraw();
  const flip = () => card.set(k, !card.values[k.id]);
  el.addEventListener('click', flip);
  el.addEventListener('keydown', (e) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); flip(); } });
  return { el, redraw };
}

function pads(card, k) {
  const lit = {};
  const W = base(card, k, () => ({ lit }));
  W.el.addEventListener('pointerdown', (e) => {
    const g = e.target.closest('[data-pad]');
    if (g) { e.preventDefault(); hit(+g.dataset.pad); }
  });
  function hit(i) {
    const p = k.pads[i];
    if (!p) return;
    lit[i] = true; W.redraw();
    setTimeout(() => { delete lit[i]; W.redraw(); }, 140);
    card.set(k, p.label); // the last pad played is the control's value
    if (p.src) oneShot(mediaUrl(p.src)).catch((e) => S.toast(`Pad ${p.label}: ${e.message}`));
  }
  return { el: W.el, redraw: W.redraw, hit };
}

function abDeck(card, k) {
  let region = card.region?.[k.id];
  const W = base(card, k, () => ({ peaks: card.peaks[k.id], region }));
  const { el } = W;
  el.insertAdjacentHTML('beforeend', `<div class="zs-tr">
    <button class="zs-ib" data-a="play" aria-label="Play loop">${ICON.play}</button>
    <button class="zs-ab" data-s="a">A</button><button class="zs-ab" data-s="b">B</button>
    <select aria-label="Switch on"><option value="bar">on the bar</option><option value="beat">on the beat</option><option value="now">now</option></select>
    <span class="zs-st"></span></div>`);
  const q = el.querySelector('select');
  const statusEl = el.querySelector('.zs-st');
  const playBtn = el.querySelector('[data-a=play]');
  q.value = k.quantize;
  const sides = (pending) => {
    for (const b of el.querySelectorAll('[data-s]')) {
      b.classList.toggle('on', !pending && b.dataset.s === card.values[k.id]);
      b.classList.toggle('pending', b.dataset.s === pending);
    }
  };
  const playhead = ({ side, frac }) => {
    const g = el.querySelector('.zs-ph');
    const r = region?.[side];
    if (!g || !r) return;
    const x = AB_LANE.x + (r[0] + (r[1] - r[0]) * Math.max(0, Math.min(1, frac || 0))) * AB_LANE.width(k);
    g.innerHTML = `<line x1="${x}" x2="${x}" y1="${AB_LANE[side]}" y2="${AB_LANE[side] + AB_LANE.h}" style="stroke:#fff;stroke-width:1.6;filter:drop-shadow(0 0 3px #fff)"/>`;
  };
  const deck = new Deck({ ...k, quantize: q.value }, { a: mediaUrl(k.a.src), b: mediaUrl(k.b.src) }, {
    onStatus: (t) => { statusEl.textContent = t; },
    onFrame: playhead,
    onSwitched: () => { sides(null); W.redraw(); card.flash(); },
  });
  q.onchange = () => { deck.spec.quantize = q.value; };
  deck.load().then((r) => {
    if (!r) return;
    region = r.region;
    card.region = { ...(card.region || {}), [k.id]: r.region };
    card.peaks[k.id] = r.peaks;
    card.saveState({ peaks: card.peaks });
    W.redraw(); sides(null);
  }).catch((e) => { statusEl.textContent = `could not load: ${e.message}`; });

  el.addEventListener('click', (e) => {
    if (e.target.closest('[data-a=play]')) {
      if (deck.playing) { deck.stop(); playBtn.innerHTML = ICON.play; playBtn.setAttribute('aria-label', 'Play loop'); el.querySelector('.zs-ph').innerHTML = ''; }
      else { deck.play(card.values[k.id]); if (deck.playing) { playBtn.innerHTML = ICON.stop; playBtn.setAttribute('aria-label', 'Stop'); } }
    }
    const s = e.target.closest('[data-s]')?.dataset.s;
    if (s) {
      card.set(k, s);
      // Not yet audible: the chosen side shows as pending until the switch lands on the beat.
      if (deck.switchTo(s) > 0) sides(s); else { sides(null); W.redraw(); }
    }
  });
  sides(null);
  return { el, redraw: () => { W.redraw(); sides(null); }, destroy: () => deck.destroy() };
}

// A deck of versions: A, B, C, ... of the same bars, switched on the bar. "Matched" plays the copies that were turned
// to one loudness when they were rendered (a louder version otherwise always sounds better). "Use" keeps the one heard.
function versions(card, k) {
  const W = base(card, k);
  const { el } = W;
  const hasMatched = k.sources.some((s) => s.matched);
  el.insertAdjacentHTML('beforeend', `<div class="zs-tr">
    <button class="zs-ib" data-a="play" aria-label="Play loop">${ICON.play}</button>
    ${hasMatched ? '<button class="zs-vb zs-match" data-a="match" aria-pressed="true" title="Play the copies turned to one loudness">Matched</button>' : ''}
    <select aria-label="Switch on"><option value="bar">on the bar</option><option value="beat">on the beat</option><option value="now">now</option></select>
    ${k.pick && card.spec.panel ? '<button class="zs-vb zs-use" data-a="use" title="Make this version the panel\'s values, in Live too"></button>' : ''}
    </div><div class="zs-st zs-vst"></div><div class="zs-vs">${k.sources.map((s) => `<button class="zs-ab" data-s="${s.label}" title="${s.note.replace(/"/g, '&quot;')}">${s.label}</button>`).join('')}</div>`);
  const q = el.querySelector('select'), statusEl = el.querySelector('.zs-st'), playBtn = el.querySelector('[data-a=play]'), useBtn = el.querySelector('[data-a=use]');
  q.value = k.quantize;
  let matched = hasMatched, deck = null;
  const sides = (pending) => {
    for (const b of el.querySelectorAll('[data-s]')) {
      b.classList.toggle('on', !pending && b.dataset.s === card.values[k.id]);
      b.classList.toggle('pending', b.dataset.s === pending);
    }
    if (useBtn) useBtn.textContent = `Use ${card.values[k.id]}`;
  };
  const showPlay = (on) => { playBtn.innerHTML = on ? ICON.stop : ICON.play; playBtn.setAttribute('aria-label', on ? 'Stop' : 'Play loop'); };
  function build(thenPlay) {
    deck?.destroy();
    const spec = { loop: k.loop, quantize: q.value, ...Object.fromEntries(k.sources.map((s) => [s.label, s])) };
    const urls = Object.fromEntries(k.sources.map((s) => [s.label, mediaUrl((matched && s.matched) || s.src)]));
    const d = deck = new Deck(spec, urls, {
      onStatus: (t) => { if (deck === d) statusEl.textContent = t; },
      onSwitched: () => { sides(null); W.redraw(); card.flash(); },
    });
    d.load().then((r) => { if (r && deck === d && thenPlay) { d.play(card.values[k.id]); showPlay(d.playing); } })
      .catch((e) => { if (deck === d) statusEl.textContent = `could not load: ${e.message}`; });
  }
  build(false);
  q.onchange = () => { deck.spec.quantize = q.value; };
  el.addEventListener('click', (e) => {
    if (e.target.closest('[data-a=play]')) {
      if (deck.playing) { deck.stop(); showPlay(false); } else { deck.play(card.values[k.id]); showPlay(deck.playing); }
    }
    const m = e.target.closest('[data-a=match]');
    if (m) { matched = !matched; m.setAttribute('aria-pressed', String(matched)); const was = deck.playing; showPlay(false); build(was); }
    const s = e.target.closest('[data-s]')?.dataset.s;
    if (s) {
      card.set(k, s);
      if (deck.switchTo(s) > 0) sides(s); else { sides(null); W.redraw(); }
    }
  });
  sides(null);
  return { el, redraw: () => { W.redraw(); sides(null); }, destroy: () => deck?.destroy() };
}

const MAKERS = { knob: slider, fader: slider, toggle, pads, ab: abDeck, deck: versions };

/** A live widget for control k of an armed card. */
export const widget = (card, k) => MAKERS[k.kind](card, k);
