// A find's card, full bleed: what it is, where it came from, why it surfaced now, where it can be used, and taking it
// into the track's crate. MOCKED: nothing plays. The player strip is drawn from the find's key and has no sound at
// all (docs/sound.md: music is rendered files on the player engine, and there are none here yet).
//
//   openCard(host, find, { data, taken, onTake(), onWork(key), onClose() })   -> { destroy() }
//   openSignal(host, find, { data, onWork(key), onClose() })                  -> { destroy() }
import { hash, rng } from '../concepts/model.js';
import { KINDS } from './finds.js';

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const BACK = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5l-7 7 7 7"/></svg>';
const PLAY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l10.5-6.5z"/></svg>';
const STOP = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7h10v10H7z"/></svg>';
const GO = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5l7 7-7 7"/></svg>';
// the same glyphs as on the map, in a 24 box
const GLYPH = {
  raw: '<path class="ln" d="M2 12h3.8l2.6-8 4.2 16 4.2-16 2.6 8H22"/>',
  collaged: '<path class="ln" d="M3 3h12v12H3zM9 9h12v12H9z"/>',
  processed: '<path class="ln" d="M3 5h15M3 12h10M3 19h15M17 9l4 3-4 3"/>',
  whole: '<path class="fl" d="M12 1.5 22.5 12 12 22.5 1.5 12Z"/>',
  learned: '<path class="ln" d="M1.5 12Q12 1.5 22.5 12Q12 22.5 1.5 12Z"/><circle class="fl" cx="12" cy="12" r="3.2"/>',
};
const glyph = (kind) => `<svg class="wl-c-glyph" viewBox="0 0 24 24" aria-hidden="true">${GLYPH[kind]}</svg>`;

function titleOf(data, key) {
  const [sid, iid] = key.split('.');
  const step = data.steps.find((s) => s.id === sid);
  const it = step?.items.find((x) => x.id === iid);
  return it ? { step, it } : null;
}

/** A strip of bars, the same for the same key: a sketch of a waveform, not a measurement. */
function strip(key) {
  const r = rng(hash(`${key}|strip`));
  const n = 64, bars = [];
  let env = 0.4;
  for (let i = 0; i < n; i++) {
    env = Math.min(1, Math.max(0.12, env + (r() - 0.48) * 0.35));
    const h = Math.max(3, env * (0.55 + r() * 0.45) * 48);
    bars.push(`<rect x="${i * 5 + 1}" y="${(25 - h / 2).toFixed(1)}" width="3" height="${h.toFixed(1)}" rx="1"/>`);
  }
  return `<svg class="wl-c-wave" viewBox="0 0 320 50" preserveAspectRatio="none" aria-hidden="true">${bars.join('')}<rect class="wl-c-head" x="0" y="0" width="2" height="50"/></svg>`;
}

function tapOn(el, fn, offs) {
  let d = null;
  const dn = (e) => { d = [e.clientX, e.clientY]; };
  const up = (e) => { const ok = d && Math.hypot(e.clientX - d[0], e.clientY - d[1]) < 12; d = null; if (ok) fn(e); };
  const ck = (e) => { if (e.detail === 0) fn(e); };
  el.addEventListener('pointerdown', dn); el.addEventListener('pointerup', up); el.addEventListener('click', ck);
  offs.push(() => { el.removeEventListener('pointerdown', dn); el.removeEventListener('pointerup', up); el.removeEventListener('click', ck); });
}

export function openCard(host, find, { data, taken = false, onTake = () => {}, onWork = () => {}, onClose = () => {} }) {
  const k = KINDS[find.kind];
  const from = find.cache ? null : titleOf(data, find.key);
  const step = data.steps.find((s) => s.id === find.step);
  const uses = (find.useIn || []).map((key) => ({ key, t: titleOf(data, key) })).filter((u) => u.t);
  host.innerHTML = `<article class="wl-card" data-key="${esc(find.key)}" data-kind="${find.kind}" role="dialog" aria-label="${esc(find.title)}">
    <header class="wl-c-top"><button type="button" class="wl-c-back" aria-label="Back">${BACK}</button>
      <span class="wl-c-where">The Wasteland · ${esc(step ? `${step.n} ${step.name}` : '')}${find.cache ? ' · cache' : ''}</span></header>
    <div class="wl-c-body">
      <div class="wl-c-badge">${glyph(find.kind)}<span><b>${esc(k.label)}</b> · ${esc(k.from)}</span></div>
      <h1 class="wl-c-title">${esc(find.title)}</h1>
      <p class="wl-c-size">${esc(find.size)}</p>
      <p class="wl-c-what">${esc(find.what)}</p>
      <p class="wl-c-why">${esc(find.why)}${from ? ` <span>(${esc(from.it.title)})</span>` : ''}.</p>
      <section class="wl-c-player" aria-label="Player (mocked: no audio)">
        <button type="button" class="wl-c-play" aria-label="Play (mocked)" aria-pressed="false">${PLAY}</button>
        ${strip(find.key)}
        <span class="wl-c-mock">mocked: no audio</span>
      </section>
      ${uses.length ? `<section class="wl-c-uses"><h2>Use in</h2><ul>${uses.map((u) => `<li><button type="button" class="wl-c-use" data-key="${u.key}">
        <b>${esc(u.t.step.n)}</b><span>${esc(u.t.it.title)}</span>${GO}</button></li>`).join('')}</ul></section>` : ''}
    </div>
    <footer class="wl-c-foot">
      <button type="button" class="wl-c-take" aria-pressed="${taken}"></button>
      <button type="button" class="wl-c-pass">Not for me</button>
    </footer>
  </article>`;
  const root = host.firstElementChild, offs = [];
  const take = root.querySelector('.wl-c-take');
  const crate = `${data.track}'s crate`;
  const paint = () => {
    take.setAttribute('aria-pressed', String(taken));
    take.innerHTML = taken
      ? `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg><span>In ${esc(crate)}</span>`
      : `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg><span>Take into ${esc(data.track)}</span>`;
  };
  paint();
  tapOn(take, () => { taken = !taken; paint(); onTake(taken); }, offs);
  tapOn(root.querySelector('.wl-c-back'), () => onClose(), offs);
  // "Not for me" closes; with the real agent it is also a signal: it learns what Anthony passes over (docs/studio-agent.md)
  tapOn(root.querySelector('.wl-c-pass'), () => onClose(), offs);
  for (const b of root.querySelectorAll('.wl-c-use')) tapOn(b, () => onWork(b.dataset.key), offs);
  const play = root.querySelector('.wl-c-play'), head = root.querySelector('.wl-c-head');
  let anim = null;
  tapOn(play, () => {
    const on = play.getAttribute('aria-pressed') !== 'true';
    play.setAttribute('aria-pressed', String(on));
    play.innerHTML = on ? STOP : PLAY;
    anim?.cancel(); anim = null;
    // the playhead moves; nothing sounds
    if (on) anim = head.animate([{ transform: 'translateX(0)' }, { transform: 'translateX(318px)' }], { duration: 6000, iterations: Infinity });
  }, offs);
  return { destroy() { anim?.cancel(); for (const off of offs) off(); host.innerHTML = ''; } };
}

/** A signal through the fog: something is out there. What reaches it, and that nothing waits on it. */
export function openSignal(host, find, { data, onWork = () => {}, onClose = () => {} }) {
  const k = KINDS[find.kind];
  const t = titleOf(data, find.key);
  host.innerHTML = `<article class="wl-card signal" data-key="${esc(find.key)}" role="dialog" aria-label="A signal">
    <header class="wl-c-top"><button type="button" class="wl-c-back" aria-label="Back">${BACK}</button>
      <span class="wl-c-where">The Wasteland · ${esc(t ? `${t.step.n} ${t.step.name}` : '')}</span></header>
    <div class="wl-c-body">
      <div class="wl-c-blip" aria-hidden="true"><i></i><i></i><b></b></div>
      <h1 class="wl-c-title">Something's out here</h1>
      <p class="wl-c-size">${esc(k.label)} · ${esc(k.from)}</p>
      <p class="wl-c-what">Settle <b>${esc(t ? t.it.title : find.key)}</b> to reach it.</p>
      <p class="wl-c-why">Nothing is locked: you can release without it.</p>
    </div>
    <footer class="wl-c-foot">
      <button type="button" class="wl-c-work">${GO}<span>Work on it</span></button>
      <button type="button" class="wl-c-pass">Later</button>
    </footer>
  </article>`;
  const root = host.firstElementChild, offs = [];
  tapOn(root.querySelector('.wl-c-work'), () => onWork(find.key), offs);
  tapOn(root.querySelector('.wl-c-back'), () => onClose(), offs);
  tapOn(root.querySelector('.wl-c-pass'), () => onClose(), offs);
  return { destroy() { for (const off of offs) off(); host.innerHTML = ''; } };
}
