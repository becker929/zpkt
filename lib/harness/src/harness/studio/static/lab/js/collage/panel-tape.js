// TAPE: the machine every collage sound runs through. Hold the reels to stop the tape (the pitch falls to nothing,
// as long as STOP TIME); let go and it spins back up and lands on the grid. Drag across the reels to bend the speed
// like a jog wheel; it springs back when you let go. Varispeed, wow, flutter, reverse. And RESAMPLE: record the
// next 1-8 bars of the collage (or everything) into a new tape on the shelf, to grain, slice and lay out again.

import { h, haptic, toast } from '../ui.js';
import { knob } from '../widgets/knob.js';
import { fader, toggle } from '../widgets/fader.js';
import { state } from './state.js';
import { drawWave } from './sources.js';
import { fit, icon } from './bits.js';

const NS = 'http://www.w3.org/2000/svg';
const sv = (tag, attrs = {}) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; };

function reel(cx, cy) {
  const g = sv('g', { class: 'ct-reel' });
  const pack = sv('circle', { cx, cy, r: 50, class: 'ct-pack' });
  const spin = sv('g', { class: 'ct-spin' });
  spin.append(sv('circle', { cx, cy, r: 68, class: 'ct-flange' }));
  for (const a of [0, 120, 240]) {
    const p = sv('path', { class: 'ct-window', d: 'M0 -60 A60 60 0 0 1 46 -38.6 L19 -16 A25 25 0 0 0 0 -25 Z', transform: `translate(${cx} ${cy}) rotate(${a})` });
    spin.append(p);
  }
  spin.append(sv('circle', { cx, cy, r: 15, class: 'ct-hub' }));
  for (const a of [0, 60, 120, 180, 240, 300]) spin.append(sv('rect', { x: cx - 2, y: cy - 14, width: 4, height: 5, rx: 1, class: 'ct-tooth', transform: `rotate(${a} ${cx} ${cy})` }));
  spin.append(sv('circle', { cx, cy, r: 4, class: 'ct-axle' }));
  g.append(pack, spin);
  return { g, pack, spin, cx, cy, angle: 0 };
}

export default function tapePanel(C) {
  const { store, engine } = C;
  const svg = sv('svg', { viewBox: '0 0 400 196', class: 'ct-svg', 'aria-hidden': 'true' });
  const L = reel(98, 86), R = reel(302, 86);
  const path = sv('path', { class: 'ct-tape' });
  const head = sv('g', { class: 'ct-head' });
  head.append(sv('rect', { x: 176, y: 156, width: 48, height: 26, rx: 4, class: 'ct-headblock' }), sv('rect', { x: 196, y: 158, width: 8, height: 6, rx: 1, class: 'ct-gap' }), sv('circle', { cx: 200, cy: 174, r: 3.2, class: 'ct-lamp' }));
  const guides = [[150, 168], [250, 168]].map(([x, y]) => sv('circle', { cx: x, cy: y, r: 6, class: 'ct-guide' }));
  svg.append(L.g, R.g, path, ...guides, head);
  const lcd = h('div', { class: 'ct-lcd' });
  const tag = h('div', { class: 'ct-tag', text: 'HOLD TO STOP  ·  DRAG TO BEND' });
  const deck = h('div', { class: 'ct-deck' }, svg, h('i', { class: 'ct-screw a' }), h('i', { class: 'ct-screw b' }), h('i', { class: 'ct-screw c' }), h('i', { class: 'ct-screw d' }), lcd, tag);

  // --- the reels: hold = brake, drag = bend ----------------------------------------------------------------------
  deck.style.touchAction = 'none';
  let press = null, bend = 0, springing = false;
  deck.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    if (!C.ready) { toast('Start the engine first'); return; }
    try { deck.setPointerCapture(e.pointerId); } catch { /* synthetic pointer */ }
    press = { id: e.pointerId, x: e.clientX, y: e.clientY, mode: null, timer: 0 };
    press.timer = setTimeout(() => {
      if (!press || press.mode) return;
      press.mode = 'brake';
      C.G.tape.stop(store.real('col.tape.brake') / 1000);
      deck.classList.add('is-brake');
      haptic(true);
    }, 140);
  });
  deck.addEventListener('pointermove', (e) => {
    if (!press || e.pointerId !== press.id) return;
    const dx = e.clientX - press.x;
    if (!press.mode && Math.abs(dx) > 8) { press.mode = 'bend'; clearTimeout(press.timer); springing = false; haptic(); deck.classList.add('is-bend'); }
    if (press.mode === 'bend') {
      bend = Math.max(-0.5, Math.min(0.5, bend + (e.clientX - (press.lx ?? press.x)) / 300));
      store.modulate('col.tape.speed', bend, 'collage-bend');
    }
    press.lx = e.clientX;
  });
  const release = (e) => {
    if (!press || e.pointerId !== press.id) return;
    clearTimeout(press.timer);
    if (press.mode === 'brake') { C.G.tape.start(Math.max(0.12, (store.real('col.tape.brake') / 1000) * 0.55)); haptic(); }
    if (press.mode === 'bend') springing = true;
    deck.classList.remove('is-brake', 'is-bend');
    press = null;
  };
  deck.addEventListener('pointerup', release);
  deck.addEventListener('pointercancel', release);
  C.own(() => { if (press) clearTimeout(press.timer); });
  // another mode opens: let the reels go (a held brake starts the tape again, a bend springs back at once)
  C.own(C.ev.on('mode', (m) => {
    if (m === 'tape') return;
    if (press?.mode === 'brake' && C.ready) C.G.tape.start(0.3);
    if (press) clearTimeout(press.timer);
    press = null;
    bend = 0; springing = false;
    store.unmodulate('collage-bend');
    deck.classList.remove('is-brake', 'is-bend');
  }));

  // --- resample --------------------------------------------------------------------------------------------------
  const ring = sv('circle', { cx: 40, cy: 40, r: 36, class: 'ct-ring' });
  const ringSvg = sv('svg', { viewBox: '0 0 80 80', class: 'ct-ring-svg', 'aria-hidden': 'true' });
  ringSvg.append(sv('circle', { cx: 40, cy: 40, r: 36, class: 'ct-ring-track' }), ring);
  const rec = h('button', { type: 'button', class: 'ct-rec', 'aria-label': 'Resample: record the next bars into a new tape' }, ringSvg, h('span', { class: 'ct-rec-dot' }), h('span', { class: 'ct-rec-txt', text: 'REC' }));
  rec.addEventListener('click', () => { haptic(true); C.resample(); });
  const rstat = h('div', { class: 'ct-rstat' });
  const take = h('canvas', { class: 'ct-take' });
  const takeBox = h('button', { type: 'button', class: 'ct-take-box', 'aria-label': 'The last take: pick it' }, take, h('span', { class: 'ct-take-name' }));
  takeBox.addEventListener('click', () => { const r = state.rs.at(-1); if (r) { haptic(); C.select(r.id); C.audition(r.id); } });

  const el = h('section', { class: 'cl-panel ct', 'aria-label': 'Tape' },
    deck,
    h('div', { class: 'ct-resample' },
      h('div', { class: 'ct-rec-col' }, rec),
      h('div', { class: 'ct-rs-col' },
        h('div', { class: 'ct-rs-head' }, icon('rec', 'is-red'), h('b', { text: 'Resample' }), rstat),
        h('div', { class: 'ct-rs-btns' }, toggle(C.ctx, 'col.rs.bars', { label: 'Length' }), toggle(C.ctx, 'col.rs.input', { label: 'Input' })),
        takeBox)),
    h('div', { class: 'ct-speed' }, fader(C.ctx, 'col.tape.speed', { horizontal: true, length: 236, label: 'Varispeed' }), toggle(C.ctx, 'col.tape.rev', { label: 'Reverse' })),
    h('div', { class: 'cl-knobrow' },
      knob(C.ctx, 'col.tape.wow', { size: 64 }), knob(C.ctx, 'col.tape.flutter', { size: 64 }), knob(C.ctx, 'col.tape.brake', { size: 64 })));

  let takeKey = '';
  const T = fit(take, () => { takeKey = ''; });
  const drawTake = () => {
    const r = state.rs.at(-1);
    const key = `${r?.id}|${take.width}`;
    if (key === takeKey) return;
    takeKey = key;
    const g = T.g;
    g.fillStyle = '#0a090c'; g.fillRect(0, 0, take.width, take.height);
    el.querySelector('.ct-take-name').textContent = r ? `${r.name} · ${r.bars} ${r.bars === 1 ? 'bar' : 'bars'} · ${r.made}` : 'No take yet';
    if (r) drawWave(g, r.buffer, 0, r.buffer.duration, 0, take.height * 0.12, take.width, take.height * 0.76, { color: '#ff6b6b', gain: 0.9 });
  };
  C.own(C.ev.on('sources', () => { takeKey = ''; }));
  C.own(C.ev.on('buffer', () => { takeKey = ''; }));

  // --- drawing ---------------------------------------------------------------------------------------------------
  let last = 0, counter = 0.35, lcdT = 0;
  return {
    el,
    show() { takeKey = ''; T.measure(); },
    draw(t) {
      const dt = Math.min(0.05, (t - (last || t)) / 1000);
      last = t;
      if (springing) {
        bend *= Math.exp(-dt / 0.09);
        if (Math.abs(bend) < 0.004) { bend = 0; springing = false; }
        store.modulate('col.tape.speed', bend, 'collage-bend');
      }
      const run = C.ready ? C.G.tape.speed() : 1;
      const speed = (C.ready ? store.real('col.tape.speed') / 100 : 1) * run;
      const moving = C.ready && (C.players.live.size || C.grains.voices.size || engine.playing);
      const v = moving ? speed : 0;
      counter = (counter + v * dt * 0.004) % 1;
      const rl = 22 + 46 * Math.sqrt(1 - counter), rr = 22 + 46 * Math.sqrt(counter);
      L.pack.setAttribute('r', rl.toFixed(1)); R.pack.setAttribute('r', rr.toFixed(1));
      L.angle = (L.angle + (v * dt * 7200) / rl) % 360;
      R.angle = (R.angle + (v * dt * 7200) / rr) % 360;
      L.spin.setAttribute('transform', `rotate(${L.angle.toFixed(2)} ${L.cx} ${L.cy})`);
      R.spin.setAttribute('transform', `rotate(${R.angle.toFixed(2)} ${R.cx} ${R.cy})`);
      // the tape: from the left pack's foot, round the guides and the head, to the right pack
      path.setAttribute('d', `M${L.cx - rl * 0.5} ${L.cy + rl * 0.866} L150 174 L200 182 L250 174 L${R.cx + rr * 0.5} ${R.cy + rr * 0.866}`);
      deck.classList.toggle('is-moving', !!moving && run > 0.02);
      if (t - lcdT > 80) {
        lcdT = t;
        const st = C.ready ? C.G.tape.state : 'run';
        const word = { run: moving ? 'PLAY' : 'IDLE', stopping: 'STOP', stopped: 'STOPPED', starting: 'START' }[st];
        lcd.textContent = `${(speed * 100).toFixed(0).padStart(3, ' ')} %  ${word}`;
        // resample status
        const R2 = C.rec, now = C.ready ? engine.ctx.currentTime : 0;
        const bars = [1, 2, 4, 8][store.real('col.rs.bars')];
        let phase = 'idle', frac = 0, text = `${bars} ${bars === 1 ? 'bar' : 'bars'} of ${store.real('col.rs.input') ? 'everything' : 'the collage'}`;
        if (R2.phase === 'armed') {
          if (now < R2.when) { phase = 'armed'; text = 'Armed: from the next bar'; }
          else { phase = 'rec'; frac = Math.min(1, (now - R2.when) / (R2.end - R2.when)); text = `Recording ${(frac * R2.bars).toFixed(1)} / ${R2.bars}`; }
        }
        rec.dataset.phase = phase;
        ring.style.strokeDashoffset = String(226.2 * (1 - frac));
        rstat.textContent = text;
      }
      drawTake();
    },
  };
}
