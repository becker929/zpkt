// The shelf: every tape as a cassette. A paper label (its name, its group), a window with its waveform and two
// reels that turn while it sounds, and a strip of the whole set's 177 bars marking where the set uses it (acid:
// what the set has). Tap: pick it and hear it from the next bar (tap again to stop). Long press: what it is.
// In BED mode, drag a cassette down onto a lane to lay it there.

import { h, haptic, longPress, toast } from '../ui.js';
import { bufferNow, drawWave, peaksNow, useSpans } from './sources.js';
import { state } from './state.js';
import { clock } from './meta.js';
import { icon } from './bits.js';

const REEL = '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10.5" class="r-rim"/><circle cx="12" cy="12" r="5.2" class="r-hub"/>'
  + [0, 60, 120, 180, 240, 300].map((a) => `<rect x="11.1" y="5.6" width="1.8" height="2.6" rx=".5" class="r-tooth" transform="rotate(${a} 12 12)"/>`).join('')
  + '</svg>';

export function buildShelf(C) {
  const row = h('div', { class: 'cl-shelf-row', role: 'list' });
  const el = h('div', { class: 'cl-shelf' }, row);
  const cards = new Map();
  let songBars = 177;

  const card = (src) => {
    const wave = h('canvas', { class: 'cl-tape-wave' });
    const uses = h('canvas', { class: 'cl-tape-uses' });
    const reelL = h('span', { class: 'cl-reel' }); reelL.innerHTML = REEL;
    const reelR = h('span', { class: 'cl-reel' }); reelR.innerHTML = REEL;
    const c = h('button', {
      type: 'button', class: `cl-tape${src.kind === 'rs' ? ' is-rs' : ''}`, role: 'listitem', dataset: { id: src.id },
      style: { '--tc': src.color }, 'aria-label': `${src.name}: ${src.long}`,
    },
    h('span', { class: 'cl-tape-label' },
      h('b', { text: src.name }),
      h('span', { class: 'cl-tape-tag', text: src.tag })),
    h('span', { class: 'cl-tape-window' }, reelL, wave, reelR),
    h('span', { class: 'cl-tape-foot' }, uses, h('span', { class: 'cl-tape-len', text: `${Math.round(src.seconds)}s` })),
    h('i', { class: 'cl-led cl-tape-led' }),
    src.kind === 'rs' ? h('i', { class: 'cl-tape-strip' }) : null);
    let dragging = null, suppress = false, x0 = 0, y0 = 0, pid = null;
    c.addEventListener('click', () => {
      if (suppress) { suppress = false; return; }
      haptic();
      const was = state.sel;
      C.select(src.id);
      if (C.ready) {
        const on = C.audition(src.id, { toggle: was === src.id });
        if (on === 'loading') toast(`${src.name} is still loading`);
      }
    });
    longPress(c, () => {
      suppress = true;
      const where = src.uses.length ? `the set uses it ${src.uses.length}x, from bar ${Math.floor(src.uses[0].bar) + 1}` : 'not in the set yet';
      toast(`${src.long} · ${clock(src.seconds, 0)} · ${where}`, 3200);
    });
    // drag down into the bed (BED mode only)
    c.addEventListener('pointerdown', (e) => { x0 = e.clientX; y0 = e.clientY; pid = e.pointerId; dragging = null; });
    c.addEventListener('pointermove', (e) => {
      if (e.pointerId !== pid || state.mode !== 'bed') return;
      const dx = e.clientX - x0, dy = e.clientY - y0;
      if (!dragging && dy > 18 && Math.abs(dy) > Math.abs(dx) * 1.3) {
        try { c.setPointerCapture(e.pointerId); } catch { /* synthetic pointer */ }
        dragging = h('div', { class: 'cl-ghost', style: { '--tc': src.color } }, h('b', { text: src.name }), h('span', { text: 'drop on a lane' }));
        document.body.append(dragging);
        haptic();
      }
      if (dragging) {
        dragging.style.transform = `translate(${e.clientX - 60}px, ${e.clientY - 26}px)`;
        C.ev.emit('dragover', e.clientX, e.clientY, src.id);
      }
    });
    const end = (e) => {
      if (e.pointerId !== pid) return;
      pid = null;
      if (!dragging) return;
      dragging.remove();
      dragging = null;
      suppress = true;
      setTimeout(() => { suppress = false; }, 400);
      C.ev.emit('drop', e.clientX, e.clientY, { src: src.id, off: C.cue(src.id), len: src.kind === 'rs' ? Math.round(src.seconds / C.engine.stepSeconds) : 16, st: 0, rev: false });
    };
    c.addEventListener('pointerup', end);
    c.addEventListener('pointercancel', end);
    return { el: c, wave, uses, src, drawn: false };
  };

  const drawThumb = (k) => {
    const buf = bufferNow(C.engine, k.src.id);
    if (!buf || !peaksNow(buf)) return;
    const dpr = Math.min(3, devicePixelRatio || 1);
    for (const cv of [k.wave, k.uses]) {
      const r = cv.getBoundingClientRect();
      cv.width = Math.max(1, Math.round(r.width * dpr)); cv.height = Math.max(1, Math.round(r.height * dpr));
    }
    const g = k.wave.getContext('2d');
    const W = k.wave.width, H = k.wave.height;
    g.clearRect(0, 0, W, H);
    // where the set uses it: acid bands under the wave
    g.fillStyle = 'rgba(198,255,61,0.16)';
    for (const [a, b] of useSpans(k.src)) g.fillRect((a / buf.duration) * W, 0, Math.max(dpr, ((b - a) / buf.duration) * W), H);
    drawWave(g, buf, 0, buf.duration, 0, H * 0.08, W, H * 0.84, { color: k.src.color, gain: 0.95 });
    // the set's arrangement: 177 bars, a tick where it plays
    const u = k.uses.getContext('2d');
    const UW = k.uses.width, UH = k.uses.height;
    u.clearRect(0, 0, UW, UH);
    u.fillStyle = 'rgba(255,255,255,0.08)';
    u.fillRect(0, UH / 2 - dpr / 2, UW, dpr);
    u.fillStyle = 'rgba(89,199,255,0.22)';                       // the stems' loop (the bed's 24 bars)
    u.fillRect(0, 0, (24 / songBars) * UW, UH);
    u.fillStyle = '#c6ff3d';
    for (const x of k.src.uses) u.fillRect((x.bar / songBars) * UW, 1, Math.max(dpr * 1.5, (x.bars / songBars) * UW), UH - 2);
    k.drawn = true;
  };

  const render = () => {
    const list = C.ready ? C.sources : [];
    songBars = C.engine.manifest?.full?.bars ?? 177;
    for (const [id, k] of cards) if (!list.some((s) => s.id === id)) { k.el.remove(); cards.delete(id); }
    for (const src of list) {
      if (!cards.has(src.id)) { const k = card(src); cards.set(src.id, k); }
      row.append(cards.get(src.id).el);
    }
    row.append(addCard);
    if (!list.length) row.prepend(...placeholders);
    else for (const p of placeholders) p.remove();
    mark();
    for (const k of cards.values()) if (!k.drawn) drawThumb(k);
  };

  const placeholders = Array.from({ length: 4 }, () => h('div', { class: 'cl-tape is-empty' }, h('span', { class: 'cl-tape-label' }, h('b', { text: '· · ·' }))));
  const addCard = h('button', { type: 'button', class: 'cl-tape is-add', 'aria-label': 'Resample: record the collage into a new tape' },
    icon('rec'), h('b', { text: 'Resample' }), h('span', { text: 'a new tape' }));
  addCard.addEventListener('click', () => { haptic(); C.mode('tape'); });

  const mark = () => {
    for (const [id, k] of cards) {
      const on = id === state.sel;
      k.el.classList.toggle('is-sel', on);
      k.el.setAttribute('aria-pressed', String(on));
    }
  };

  const scrollToSel = () => {
    const k = cards.get(state.sel);
    if (!k) return;
    const r = k.el.getBoundingClientRect(), rr = row.getBoundingClientRect();
    if (r.left < rr.left || r.right > rr.right) row.scrollTo({ left: row.scrollLeft + r.left - rr.left - 12, behavior: 'smooth' });
  };

  C.own(C.ev.on('sources', render));
  C.own(C.ev.on('ready', render));
  C.own(C.ev.on('buffer', (id) => { const k = cards.get(id); if (k) drawThumb(k); }));
  C.own(C.ev.on('select', () => { mark(); scrollToSel(); }));
  render();

  let lastState = new Map();
  return {
    el,
    /** reels turn while a tape sounds; the LED blinks while it waits for the bar */
    draw() {
      if (!C.ready) return;
      const t = C.engine.ctx.currentTime;
      for (const [id, k] of cards) {
        const sounding = C.players.sounding(id) + [...C.grains.voices.values()].filter((v) => v.src === id).length;
        const cued = !sounding && [...C.players.live].some((v) => v.id === id && v.when > t);
        const s = sounding ? 2 : cued ? 1 : 0;
        if (lastState.get(id) !== s) {
          lastState.set(id, s);
          k.el.classList.toggle('is-playing', s === 2);
          k.el.classList.toggle('is-cued', s === 1);
        }
      }
    },
    refresh: render,
  };
}
