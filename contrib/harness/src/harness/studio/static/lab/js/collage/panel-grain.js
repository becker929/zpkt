// GRAIN: the tape's waveform as a surface to play with your fingers. Each finger is a grain voice: across picks the
// place in the tape, up and down the grain size (or pitch, or spray: the HEIGHT button). Lift to let go; with FREEZE
// on, a lifted finger keeps playing where it was. GHOST sends a voice wandering on its own. The strip above is the
// whole tape: drag it to move the window, the buttons zoom.

import { h, haptic, drag, toast } from '../ui.js';
import { knob } from '../widgets/knob.js';
import { toggle } from '../widgets/fader.js';
import { saveState, state } from './state.js';
import { bufferNow, drawWave, useSpans } from './sources.js';
import { fit, latch, push } from './bits.js';
import { clock } from './meta.js';

const ZOOMS = [0.5, 1, 2, 4, 8, 16, 32, 64, 160];
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));

export default function grainPanel(C) {
  const { store } = C;
  const over = h('canvas', { class: 'cg-over', 'aria-label': 'The whole tape: drag to move the window' });
  const scrub = h('canvas', { class: 'cg-scrub', 'aria-label': 'Grain surface: touch to play' });
  const lcd = h('div', { class: 'cg-lcd' });
  const yTag = h('div', { class: 'cg-ytag' });
  const hint = h('div', { class: 'cg-hint' }, h('b', { text: 'Touch the wave.' }), ' Each finger plays grains from where it is. Up and down: ', h('span', { class: 'cg-hint-y' }), '.');
  const zoomOut = push('', () => zoom(1), { icon: 'minus', cls: 'cg-zoom', title: 'Zoom out' });
  const zoomIn = push('', () => zoom(-1), { icon: 'plus', cls: 'cg-zoom', title: 'Zoom in' });

  // TILT: the phone's tilt plays the hands-free voices. Left and right move the frozen and ghost voices through the
  // window; forward and back make the grains shorter or longer (a modulation on SIZE, not saved).
  let tiltX = 0;
  const onTilt = (e) => {
    tiltX = clamp((e.gamma ?? 0) / 40, -1, 1);
    const b = clamp(((e.beta ?? 45) - 45) / 40, -1, 1);
    store.modulate('col.grain.size', -b * 0.35, 'collage-tilt');
    const w = win();
    if (C.ready) for (const v of C.grains.voices.values()) if (v.frozen || v.ghost) v.tilt = tiltX * w.len * 0.5;
  };
  const stopTilt = () => {
    window.removeEventListener('deviceorientation', onTilt);
    store.unmodulate('collage-tilt');
    if (C.ready) for (const v of C.grains.voices.values()) v.tilt = 0;
  };
  const tilt = latch('', {
    icon: 'tilt', cls: 'cg-tilt', title: 'Tilt: the phone moves the frozen and ghost voices, and the grain size',
    onChange: (on) => {
      if (!on) { stopTilt(); return; }
      const go = () => window.addEventListener('deviceorientation', onTilt);
      const ask = window.DeviceOrientationEvent?.requestPermission;
      if (!window.DeviceOrientationEvent) { tilt.set(false); toast('No motion sensor here'); return; }
      if (ask) {
        ask.call(window.DeviceOrientationEvent).then((r) => { if (r === 'granted') go(); else { tilt.set(false); toast('Motion access was not given'); } })
          .catch(() => { tilt.set(false); toast('Motion access was not given'); });
      } else go();
      toast('Tilt: left and right move the frozen voices, forward and back the grain size', 2400);
    },
  });
  C.own(stopTilt);

  const ghost = latch('Ghost', {
    icon: 'ghost', title: 'A voice that wanders the window on its own',
    onChange: (on) => { if (on) startGhost(); else C.grains?.lift('ghost'); },
  });
  const freeze = toggle(C.ctx, 'col.grain.freeze', { label: 'Freeze' });
  const height = toggle(C.ctx, 'col.grain.y', { label: 'Height' });
  const clockBtn = toggle(C.ctx, 'col.grain.sync', { label: 'Clock' });
  const knobs = [
    knob(C.ctx, 'col.grain.size', { size: 64 }), knob(C.ctx, 'col.grain.density', { size: 64 }),
    knob(C.ctx, 'col.grain.spray', { size: 64 }), knob(C.ctx, 'col.grain.pitch', { size: 64 }),
    knob(C.ctx, 'col.grain.rev', { size: 64, label: 'Back' }), knob(C.ctx, 'col.grain.drift', { size: 64 }),
    knob(C.ctx, 'col.grain.pan', { size: 64 }),
  ];

  const el = h('section', { class: 'cl-panel cg', 'aria-label': 'Grain' },
    h('div', { class: 'cg-over-row' }, zoomOut, h('div', { class: 'cg-over-box' }, over), zoomIn, tilt),
    h('div', { class: 'cg-scrub-box' }, scrub, h('i', { class: 'cl-crt' }), lcd, yTag, hint),
    h('div', { class: 'cl-knobrow' },
      h('div', { class: 'cl-tcol' }, freeze, ghost),
      ...knobs,
      h('div', { class: 'cl-tcol' }, height, clockBtn)));

  // --- the window: which part of the tape the surface shows -------------------------------------------------------
  const win = (id = state.sel) => {
    const buf = bufferNow(C.engine, id);
    const dur = buf?.duration ?? C.src(id)?.seconds ?? 8;
    let w = state.win[id];
    if (!w) {
      const len = Math.min(dur, 8);
      w = { start: Math.max(0, C.cue(id) - len * 0.25), len };
      if (C.ready && C.src(id) && buf) state.win[id] = w;      // keep it once the tape is known
    }
    w.len = Math.min(w.len, dur);
    w.start = clamp(w.start, 0, Math.max(0, dur - w.len));
    return { start: w.start, len: w.len, dur };
  };
  const setWin = (start, len) => {
    const w = state.win[state.sel] ?? (state.win[state.sel] = { start, len });
    w.start = start; w.len = len;
    win();
    saveState();
    dirty = true;
  };
  const zoom = (dir) => {
    const w = win();
    let i = ZOOMS.findIndex((z) => z >= w.len - 1e-6);
    if (i < 0) i = ZOOMS.length - 1;
    const len = Math.min(w.dur, ZOOMS[clamp(i + dir, 0, ZOOMS.length - 1)]);
    const mid = w.start + w.len / 2;
    setWin(mid - len / 2, len);
  };

  // --- the overview strip: drag (relative) to move the window, tap to jump ----------------------------------------
  drag(over, {
    onMove: (dx) => { const w = win(); const r = over.getBoundingClientRect(); setWin(w.start + (dx / r.width) * w.dur, w.len); },
    onTap: (e) => { const w = win(); const r = over.getBoundingClientRect(); setWin(((e.clientX - r.left) / r.width) * w.dur - w.len / 2, w.len); haptic(); },
  });

  // --- fingers ------------------------------------------------------------------------------------------------------
  scrub.style.touchAction = 'none';
  const fingers = new Map();
  const at = (e) => {
    const r = scrub.getBoundingClientRect();
    const w = win();
    return { pos: w.start + clamp((e.clientX - r.left) / r.width) * w.len, y: clamp((e.clientY - r.top) / r.height), x: e.clientX - r.left, yy: e.clientY - r.top };
  };
  const inUse = (pos) => (C.src()?.uses ?? []).some((u) => pos >= u.off && pos < u.off + u.len);
  scrub.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    if (!C.ready) { toast('Start the engine first'); return; }
    if (!bufferNow(C.engine, state.sel)) { toast('This tape is still loading'); return; }
    try { scrub.setPointerCapture(e.pointerId); } catch { /* synthetic pointer */ }
    const p = at(e);
    if (C.grains.hold(`p${e.pointerId}`, state.sel, p.pos, p.y)) {
      fingers.set(e.pointerId, { ...p, inside: inUse(p.pos) });
      haptic();
      hint.hidden = true;
    }
  });
  scrub.addEventListener('pointermove', (e) => {
    const f = fingers.get(e.pointerId);
    if (!f) return;
    const p = at(e);
    const inside = inUse(p.pos);
    if (inside !== f.inside) haptic();                  // crossing into or out of a piece the set uses
    fingers.set(e.pointerId, { ...p, inside });
    C.grains.move(`p${e.pointerId}`, p.pos, p.y);
  });
  const up = (e) => {
    const f = fingers.get(e.pointerId);
    if (!f) return;
    fingers.delete(e.pointerId);
    const frozen = store.real('col.grain.freeze') === 1;
    C.grains.lift(`p${e.pointerId}`, frozen);
    C.setCue(state.sel, f.pos);
    C.setLoaded({ src: state.sel, off: f.pos, len: 16, st: 0, rev: false });
    if (frozen) haptic();
  };
  scrub.addEventListener('pointerup', up);
  scrub.addEventListener('pointercancel', up);

  const startGhost = () => {
    if (!C.ready || !bufferNow(C.engine, state.sel)) { ghost.set(false); toast('Nothing to wander yet'); return; }
    const w = win();
    const v = C.grains.hold('ghost', state.sel, w.start + w.len / 2, 0.5, { ghost: true, amp: 0.9 });
    if (v) { v.range = w.len / 2; if (store.real('col.grain.drift') < 5) store.set('col.grain.drift', 0.4, { source: 'ghost' }); }
  };
  C.own(C.ev.on('ghost', (on) => ghost.set(on)));
  C.own(C.ev.on('select', () => {
    dirty = true; overDirty = true;
    if (ghost.getAttribute('aria-pressed') === 'true' && C.ready) { C.grains.lift('ghost'); startGhost(); }
  }));
  C.own(C.ev.on('buffer', (id) => { if (id === state.sel) { dirty = true; overDirty = true; } }));
  C.own(C.ev.on('cue', () => { overDirty = true; }));

  const yNames = ['grain size', 'pitch', 'spray'];
  C.own(store.on('col.grain.y', () => {
    const m = store.real('col.grain.y');
    el.querySelector('.cg-hint-y').textContent = yNames[m];
    yTag.textContent = ['UP: SHORT  DOWN: LONG', 'UP: +12 ST  DOWN: -12 ST', 'UP: WIDE  DOWN: TIGHT'][m];
  }));

  // --- drawing --------------------------------------------------------------------------------------------------------
  let dirty = true, overDirty = true, lastKey = '', lcdT = 0;
  const S = fit(scrub, () => { dirty = true; });
  const O = fit(over, () => { overDirty = true; });
  const layer = document.createElement('canvas');
  const olayer = document.createElement('canvas');

  const drawLayer = (w, buf) => {
    const W = scrub.width, H = scrub.height, dpr = S.dpr;
    layer.width = W; layer.height = H;
    const g = layer.getContext('2d');
    const bg = g.createLinearGradient(0, 0, 0, H);
    bg.addColorStop(0, '#0b0910'); bg.addColorStop(1, '#060508');
    g.fillStyle = bg; g.fillRect(0, 0, W, H);
    const X = (s) => ((s - w.start) / w.len) * W;
    // the clip's own bars (warped at 160 BPM) and beats when zoomed in
    const bar = C.engine.barSeconds || 1.5;
    const step = w.len > 40 ? bar * 4 : w.len > 12 ? bar : bar / 4;
    for (let s = Math.ceil(w.start / step) * step; s < w.start + w.len; s += step) {
      const major = Math.abs(s / bar - Math.round(s / bar)) < 1e-6;
      g.fillStyle = major ? 'rgba(224,183,255,0.14)' : 'rgba(224,183,255,0.06)';
      g.fillRect(Math.round(X(s)), 0, dpr, H);
    }
    g.fillStyle = 'rgba(255,255,255,0.05)'; g.fillRect(0, H / 2, W, dpr);
    // where the set uses this tape: acid
    for (const [ua, ub] of useSpans(C.src())) {
      const a = X(ua), b = X(ub);
      if (b < 0 || a > W) continue;
      g.fillStyle = 'rgba(198,255,61,0.06)'; g.fillRect(a, 0, b - a, H);
      g.fillStyle = 'rgba(198,255,61,0.75)';
      g.fillRect(a, 0, Math.max(dpr, b - a), 2 * dpr); g.fillRect(a, H - 2 * dpr, Math.max(dpr, b - a), 2 * dpr);
      g.fillRect(a, 0, dpr, 8 * dpr); g.fillRect(a, H - 8 * dpr, dpr, 8 * dpr);
    }
    if (buf) {
      g.save();
      g.shadowColor = 'rgba(224,183,255,0.55)'; g.shadowBlur = 10 * dpr;
      drawWave(g, buf, w.start, w.start + w.len, 0, H * 0.1, W, H * 0.8, { color: C.src()?.color ?? '#e0b7ff', gain: 0.92, alpha: 0.9 });
      g.restore();
    } else {
      g.fillStyle = 'rgba(224,183,255,0.4)'; g.font = `${12 * dpr}px ui-monospace, monospace`;
      g.fillText(C.ready ? 'LOADING THE TAPE…' : 'START THE ENGINE', 14 * dpr, H / 2);
    }
  };

  const drawOverLayer = (buf) => {
    const W = over.width, H = over.height;
    olayer.width = W; olayer.height = H;
    const g = olayer.getContext('2d');
    g.fillStyle = '#07070a'; g.fillRect(0, 0, W, H);
    if (!buf) return;
    for (const [a, b] of useSpans(C.src())) { g.fillStyle = 'rgba(198,255,61,0.35)'; g.fillRect((a / buf.duration) * W, 0, Math.max(O.dpr, ((b - a) / buf.duration) * W), H); }
    drawWave(g, buf, 0, buf.duration, 0, H * 0.1, W, H * 0.8, { color: '#8d7aa3', gain: 1 });
  };

  return {
    el,
    show() { dirty = true; overDirty = true; S.measure(); O.measure(); },
    draw(t) {
      const buf = bufferNow(C.engine, state.sel);
      const w = win();
      const key = `${state.sel}|${w.start.toFixed(4)}|${w.len}|${!!buf}|${scrub.width}x${scrub.height}`;
      if (dirty || key !== lastKey) { drawLayer(w, buf); lastKey = key; dirty = false; }
      if (overDirty) { drawOverLayer(buf); overDirty = false; }
      const g = S.g, W = scrub.width, H = scrub.height, dpr = S.dpr;
      g.drawImage(layer, 0, 0);
      const X = (s) => ((s - w.start) / w.len) * W;
      const now = C.ready ? C.engine.ctx.currentTime : 0;
      // grains: sparks that fade
      if (C.ready) {
        g.globalCompositeOperation = 'lighter';
        for (const r of C.grains.recent) {
          if (r.src !== state.sel) continue;
          const age = now - r.when;
          if (age < 0 || age > 0.8) continue;
          const k = 1 - age / 0.8;
          const a = X(r.pos), b = X(r.pos + r.span);
          if (b < 0 || a > W) continue;
          // a grain is a particle near its finger's height, drifting up as it fades
          const v = C.grains.voices.get(r.key);
          const y = ((v?.y ?? 0.5) + (r.jy ?? 0) * 0.35) * H - age * 40 * dpr;
          const hh = (6 + 18 * Math.min(1, r.size * 8)) * dpr;
          const ww = Math.max(3 * dpr, b - a);
          g.fillStyle = r.rev ? `rgba(89,199,255,${0.55 * k})` : `rgba(242,226,255,${0.6 * k})`;
          g.beginPath();
          g.roundRect ? g.roundRect(a, y - hh / 2, ww, hh, Math.min(ww, hh) / 2) : g.rect(a, y - hh / 2, ww, hh);
          g.fill();
          g.fillStyle = `rgba(224,183,255,${0.035 * k})`;
          g.fillRect(a, 0, Math.max(dpr, ww), H);
        }
        g.globalCompositeOperation = 'source-over';
        // playheads of the region players (audition, slices, the bed)
        g.fillStyle = 'rgba(255,255,255,0.85)';
        for (const hd of C.players.heads(state.sel)) { const x = X(hd.pos); if (x >= 0 && x <= W) g.fillRect(x, 0, 1.5 * dpr, H); }
        // voices
        for (const v of C.grains.voices.values()) {
          if (v.src !== state.sel) continue;
          const x = X(v.pos + v.wander + (v.tilt ?? 0)), y = (v.y ?? 0.5) * H;
          g.strokeStyle = v.ghost ? 'rgba(89,199,255,0.9)' : '#e0b7ff';
          g.lineWidth = 2 * dpr;
          g.setLineDash(v.frozen ? [4 * dpr, 4 * dpr] : v.ghost ? [2 * dpr, 3 * dpr] : []);
          g.beginPath(); g.arc(x, y, 24 * dpr, 0, Math.PI * 2); g.stroke();
          g.setLineDash([]);
          g.globalAlpha = 0.5; g.fillRect(x - dpr / 2, 0, dpr, H); g.globalAlpha = 1;
          g.fillStyle = v.ghost ? '#59c7ff' : '#e0b7ff';
          g.beginPath(); g.arc(x, y, 4 * dpr, 0, Math.PI * 2); g.fill();
          if (v.frozen || v.ghost) {
            g.font = `600 ${9 * dpr}px ui-monospace, monospace`;
            g.fillText(v.ghost ? 'GHOST' : 'FROZEN', x + 28 * dpr, y - 18 * dpr);
          }
        }
      }
      // the cue: where audition, the slicer and the bed's next drop start
      const cx = X(C.cue());
      if (cx >= 0 && cx <= W) {
        g.fillStyle = '#e0b7ff';
        g.beginPath(); g.moveTo(cx - 6 * dpr, 0); g.lineTo(cx + 6 * dpr, 0); g.lineTo(cx, 8 * dpr); g.closePath(); g.fill();
      }
      // overview
      const og = O.g, OW = over.width, OH = over.height;
      og.drawImage(olayer, 0, 0);
      if (buf) {
        const d = buf.duration;
        og.fillStyle = 'rgba(224,183,255,0.16)'; og.strokeStyle = '#e0b7ff'; og.lineWidth = 1.5 * O.dpr;
        const a = (w.start / d) * OW, b = ((w.start + w.len) / d) * OW;
        og.fillRect(a, 0, Math.max(2, b - a), OH);
        og.strokeRect(a + 0.5, 0.5, Math.max(2, b - a) - 1, OH - 1);
        og.fillStyle = '#fff';
        if (C.ready) for (const v of C.grains.voices.values()) if (v.src === state.sel) og.fillRect(((v.pos + v.wander) / d) * OW, 0, O.dpr, OH);
      }
      // LCD, ten times a second
      if (t - lcdT > 100) {
        lcdT = t;
        const vs = C.ready ? [...C.grains.voices.values()].filter((v) => v.src === state.sel) : [];
        const pos = vs.length ? vs[0].pos + vs[0].wander : C.cue();
        lcd.textContent = `${clock(pos, 2)}  ${vs.length ? `${vs.length} VOICE${vs.length > 1 ? 'S' : ''}` : 'CUE'}  ${C.src()?.name?.toUpperCase() ?? ''}`;
      }
    },
  };
}
