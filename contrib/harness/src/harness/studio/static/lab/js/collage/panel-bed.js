// BED: six lanes over the stems' 24-bar loop. Tap an empty lane to drop what is loaded (the last tape, slice,
// resample or found sound you touched), or drag a cassette down from the shelf. Drag a clip to move it (across:
// bars, up and down: lanes), drag its right edge to change its length, hold it to take it off. Two fingers: zoom.
// The faint lane on top is what the set itself has in these bars (tap one to load it). Presets lay out the set's
// own collage: these 24 bars, or its break.

import { h, haptic, toast } from '../ui.js';
import { saveState, state } from './state.js';
import { bufferNow, drawWave } from './sources.js';
import { BARS, LANES, LOOP, clearBed, ghosts, place, preset, remove, undoBed } from './bed.js';
import { fit, icon, latch, numbox, push } from './bits.js';
import { barBeat, clock, lenText } from './meta.js';

const RULER = 22, GHOST = 20;
let LANE = 38;
const LENS = [1, 2, 4, 8, 16, 32, 64, 128];

export default function bedPanel(C) {
  const { engine } = C;
  const cv = h('canvas', { class: 'cb-tl', 'aria-label': 'The bed: six lanes over 24 bars' });
  cv.style.height = `${RULER + GHOST + LANES * LANE}px`;
  cv.style.touchAction = 'none';

  // --- the loaded item ----------------------------------------------------------------------------------------------
  const chipText = h('span', { class: 'cb-chip-text' });
  const lenDn = push('', () => setLen(-1), { icon: 'minus', cls: 'cb-mini', title: 'Shorter' });
  const lenUp = push('', () => setLen(1), { icon: 'plus', cls: 'cb-mini', title: 'Longer' });
  const hear = push('', () => { if (state.loaded) C.auditionItem(state.loaded); }, { icon: 'ear', cls: 'cb-mini', title: 'Hear it' });
  const chip = h('div', { class: 'cb-chip' }, h('i', { class: 'cb-chip-sw' }), chipText, lenDn, lenUp, hear);
  const setLen = (d) => {
    const it = state.loaded;
    if (!it) return;
    let i = 0;
    while (i + 1 < LENS.length && LENS[i + 1] <= it.len) i++;
    it.len = LENS[Math.max(0, Math.min(LENS.length - 1, LENS[i] === it.len || d > 0 ? i + d : i))];
    saveState();
    renderChip();
  };
  const renderChip = () => {
    const it = state.loaded, src = it && C.src(it.src);
    chip.style.setProperty('--tc', src?.color ?? '#555');
    chipText.textContent = src ? `${src.name} ${clock(it.off)}${it.st ? ` ${it.st > 0 ? '+' : ''}${it.st}st` : ''}${it.rev ? ' rev' : ''} · ${lenText(it.len)}` : 'Pick a tape to drop';
  };

  // --- the selected clip ------------------------------------------------------------------------------------------
  let sel = null;
  const insName = h('b', { class: 'cb-ins-name' });
  const nb = (label, get, set, fmt, step, min, max, px) => numbox({ label, get: () => (sel ? get(sel) : 0), set: (v) => { if (sel) { set(sel, v); saveState(); C.ev.emit('bed'); } }, fmt: (v) => (sel ? fmt(v) : '--'), step, min, max, px });
  const nStart = nb('Start', (c) => c.start, (c, v) => { c.start = Math.max(0, Math.min(LOOP - c.len, v)); }, (v) => barBeat(v), 4, 0, LOOP - 1);
  const nLen = nb('Length', (c) => c.len, (c, v) => { c.len = Math.max(1, Math.min(LOOP - c.start, v)); }, (v) => lenText(v), 1, 1, LOOP);
  const nOff = nb('From', (c) => c.off, (c, v) => { c.off = Math.max(0, v); }, (v) => clock(v, 2), 0.02, 0, 600, 8);
  const nSt = nb('Pitch', (c) => c.st ?? 0, (c, v) => { c.st = v; }, (v) => `${v > 0 ? '+' : ''}${v} st`, 1, -24, 24);
  const nGain = nb('Gain', (c) => Math.round(20 * Math.log10(Math.max(1e-3, c.gain ?? 1))), (c, v) => { c.gain = Math.pow(10, v / 20); }, (v) => `${v > 0 ? '+' : ''}${v} dB`, 1, -30, 6);
  const nums = [nStart, nLen, nOff, nSt, nGain];
  const revBtn = latch('Back', { icon: 'rev', onChange: (on) => { if (sel) { sel.rev = on; saveState(); C.ev.emit('bed'); } } });
  const hearBtn = push('Hear', () => { if (sel) C.auditionItem(sel); }, { icon: 'ear' });
  const delBtn = push('Off', () => { if (sel) { remove(C, sel); sel = null; renderIns(); toast('Off the bed'); } }, { icon: 'trash' });
  const ins = h('div', { class: 'cb-ins' },
    h('div', { class: 'cb-ins-head' }, h('i', { class: 'cb-chip-sw' }), insName),
    h('div', { class: 'cb-nums' }, ...nums),
    h('div', { class: 'cl-btnrow' }, revBtn, hearBtn, delBtn));
  const renderIns = () => {
    ins.classList.toggle('is-empty', !sel);
    const src = sel && C.src(sel.src);
    ins.style.setProperty('--tc', src?.color ?? '#444');
    insName.textContent = sel ? `${src?.name ?? sel.src} on lane ${sel.lane + 1}` : 'Tap a clip to edit it';
    for (const n of nums) n.render();
    revBtn.set(!!sel?.rev);
  };

  // --- presets and the stems ------------------------------------------------------------------------------------
  let sfxWas = null;
  const sfxBtn = latch('SFX stem', {
    on: !engine.ctx || engine.bus('sfx').mute.gain.value > 0.5, title: 'The SFX stem (the set\'s own collage) under the bed',
    onChange: (on) => {
      if (!engine.ctx) return;
      const ch = engine.bus('sfx');
      if (sfxWas == null) sfxWas = ch.mute.gain.value;
      ch.set('mute', on ? 0 : 1);
      toast(on ? 'SFX stem back in' : 'SFX stem out: the bed over the drums');
    },
  });
  C.own(() => { if (sfxWas != null && engine.ctx) engine.bus('sfx').set('on', sfxWas > 0.5 ? 1 : 0); });
  const presets = h('div', { class: 'cl-btnrow cb-presets' },
    push('Set 1-24', () => { const n = preset(C, 'intro'); toast(n ? `The set's own collage in these 24 bars: ${n} clips` : 'No set clips here'); sel = null; renderIns(); }, { cls: 'cb-preset', title: 'Lay out what the set has in these 24 bars' }),
    push('Set break', () => { const n = preset(C, 'break'); toast(n ? `The set's break (bars 81-96): ${n} clips` : 'No break clips'); sel = null; renderIns(); }, { cls: 'cb-preset', title: 'Lay out the set\'s break, bars 81-96' }),
    sfxBtn);
  const tools = h('div', { class: 'cl-btnrow' },
    push('Undo', () => { if (undoBed(C)) { sel = null; renderIns(); toast('Bed: undone'); } else toast('Nothing to undo'); }, { icon: 'undo' }),
    push('Clear', () => { clearBed(C); sel = null; renderIns(); toast('Bed cleared (Undo brings it back)'); }, { icon: 'trash' }));

  const el = h('section', { class: 'cl-panel cb', 'aria-label': 'Bed' },
    h('div', { class: 'cb-top' }, chip),
    h('div', { class: 'cb-tl-box' }, cv),
    presets, ins, tools);

  // --- geometry -----------------------------------------------------------------------------------------------------
  let dirty = true;
  const F = fit(cv, () => { dirty = true; });
  /** Lane height follows the screen: shorter lanes on a short screen. */
  const lay = () => {
    const lane = el.closest('.cl')?.classList.contains('is-compact') ? 31 : 38;
    if (lane !== LANE) { LANE = lane; cv.style.height = `${RULER + GHOST + LANES * LANE}px`; dirty = true; }
  };
  const pps = () => (F.w / LOOP) * state.zoom;             // CSS px per 16th
  const clampScroll = () => { state.scroll = Math.max(0, Math.min(LOOP - F.w / pps(), state.scroll)); };
  const xOf = (step) => (step - state.scroll) * pps();
  const stepAt = (x) => state.scroll + x / pps();
  const laneAt = (y) => Math.floor((y - RULER - GHOST) / LANE);
  const snap = () => (pps() * 4 >= 14 ? 4 : 16);
  const hit = (x, y) => {
    const lane = laneAt(y);
    if (lane < 0 || lane >= LANES) return null;
    for (let i = state.bed.length - 1; i >= 0; i--) {
      const c = state.bed[i];
      if (c.lane === lane && x >= xOf(c.start) && x <= xOf(c.start + c.len)) return c;
    }
    return null;
  };
  let ghostList = [];
  const ghostAt = (x, y) => {
    if (y < RULER || y >= RULER + GHOST) return null;
    return ghostList.find((g) => x >= xOf(g.start) && x <= xOf(g.start + g.len)) ?? null;
  };

  // --- touch ----------------------------------------------------------------------------------------------------------
  const pts = new Map();
  let g0 = null, lpTimer = 0, lastTap = { t: 0, clip: null };
  const local = (e) => { const r = cv.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
  cv.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    try { cv.setPointerCapture(e.pointerId); } catch { /* synthetic pointer */ }
    const p = local(e);
    pts.set(e.pointerId, p);
    clearTimeout(lpTimer);
    if (pts.size === 2) {
      const [a, b] = [...pts.values()];
      g0 = { mode: 'pinch', d: Math.hypot(a.x - b.x, a.y - b.y) || 1, z: state.zoom, anchor: stepAt((a.x + b.x) / 2), mid: (a.x + b.x) / 2 };
      return;
    }
    if (pts.size > 2) return;
    const c = hit(p.x, p.y);
    if (c) {
      const edge = p.x > xOf(c.start + c.len) - 16 && xOf(c.start + c.len) - xOf(c.start) > 26;
      g0 = { mode: edge ? 'resize' : 'move', clip: c, x: p.x, y: p.y, start: c.start, len: c.len, lane: c.lane, moved: false };
      sel = c; renderIns(); dirty = true;
      lpTimer = setTimeout(() => {
        if (!g0 || g0.moved || g0.clip !== c) return;
        haptic(true);
        remove(C, c);
        if (sel === c) { sel = null; renderIns(); }
        toast(`${C.src(c.src)?.name ?? 'Clip'}: off the bed`);
        g0 = null;
      }, 520);
    } else g0 = { mode: 'pan', x: p.x, y: p.y, scroll: state.scroll, moved: false };
  });
  cv.addEventListener('pointermove', (e) => {
    if (!pts.has(e.pointerId) || !g0) return;
    const p = local(e);
    pts.set(e.pointerId, p);
    if (g0.mode === 'pinch' && pts.size >= 2) {
      const [a, b] = [...pts.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y) || 1;
      const z = Math.max(1, Math.min(10, g0.z * d / g0.d));
      if (Math.abs(z - state.zoom) > 1e-3) {
        state.zoom = z;
        const mid = (a.x + b.x) / 2;
        state.scroll = g0.anchor - mid / pps();
        clampScroll();
        dirty = true;
      }
      return;
    }
    const dx = p.x - g0.x, dy = p.y - g0.y;
    if (!g0.moved && Math.hypot(dx, dy) < 6) return;
    g0.moved = true;
    clearTimeout(lpTimer);
    if (g0.mode === 'pan') { state.scroll = g0.scroll - dx / pps(); clampScroll(); dirty = true; return; }
    const q = snap();
    if (g0.mode === 'move') {
      const c = g0.clip;
      const start = Math.max(0, Math.min(LOOP - c.len, Math.round((g0.start + dx / pps()) / q) * q));
      const lane = Math.max(0, Math.min(LANES - 1, g0.lane + Math.round(dy / LANE)));
      if (start !== c.start || lane !== c.lane) { c.start = start; c.lane = lane; haptic(); renderIns(); }
    } else if (g0.mode === 'resize') {
      const c = g0.clip;
      const len = Math.max(Math.min(q, g0.len), Math.min(LOOP - c.start, Math.round((g0.len + dx / pps()) / q) * q));
      if (len !== c.len) { c.len = len; haptic(); renderIns(); }
    }
  });
  const up = (e) => {
    if (!pts.has(e.pointerId)) return;
    const p = pts.get(e.pointerId);
    pts.delete(e.pointerId);
    clearTimeout(lpTimer);
    if (!g0) return;
    if (g0.mode === 'pinch') { if (!pts.size) { g0 = null; saveState(); } return; }
    if (!g0.moved && e.type === 'pointerup') tap(p, g0);
    if (g0.moved && g0.mode !== 'pan') { saveState(); C.ev.emit('bed'); }
    if (g0.mode === 'pan') saveState();
    g0 = null;
  };
  cv.addEventListener('pointerup', up);
  cv.addEventListener('pointercancel', up);
  C.own(() => clearTimeout(lpTimer));

  const tap = (p, g) => {
    if (g.mode === 'move' || g.mode === 'resize') {
      const now = performance.now();
      if (lastTap.clip === g.clip && now - lastTap.t < 320) { C.auditionItem(g.clip); haptic(); lastTap = { t: 0, clip: null }; }
      else lastTap = { t: now, clip: g.clip };
      return;
    }
    const gh = ghostAt(p.x, p.y);
    if (gh) {
      C.setLoaded({ src: gh.src, off: gh.off, len: gh.len, st: 0, rev: false });
      C.auditionItem(state.loaded);
      haptic();
      toast(`Loaded the set's own: ${C.src(gh.src)?.name} ${lenText(gh.len)}`);
      return;
    }
    const lane = laneAt(p.y);
    if (lane < 0 || lane >= LANES) return;
    drop(lane, stepAt(p.x));
  };

  const drop = (lane, step, item = state.loaded) => {
    if (!item) { toast('Pick a tape on the shelf first'); return null; }
    if (!C.ready) { toast('Start the engine first'); return null; }
    const q = snap();
    const clip = place(C, item, lane, Math.floor(step / q) * q);
    sel = clip; renderIns();
    haptic();
    return clip;
  };

  // drag from the shelf
  let hover = null;
  C.own(C.ev.on('dragover', (x, y) => {
    const r = cv.getBoundingClientRect();
    if (x < r.left || x > r.right || y < r.top || y > r.bottom) { hover = null; return; }
    const lane = laneAt(y - r.top);
    hover = lane >= 0 && lane < LANES ? { lane, step: Math.floor(stepAt(x - r.left) / snap()) * snap() } : null;
  }));
  C.own(C.ev.on('drop', (x, y, item) => {
    const r = cv.getBoundingClientRect();
    hover = null;
    if (x < r.left || x > r.right || y < r.top || y > r.bottom) return;
    const lane = laneAt(y - r.top);
    if (lane < 0 || lane >= LANES) return;
    C.setLoaded(item);
    const clip = drop(lane, stepAt(x - r.left), item);
    if (clip) toast(`${C.src(item.src)?.name} at bar ${Math.floor(clip.start / 16) + 1}`);
  }));
  C.own(C.ev.on('loaded', renderChip));
  C.own(C.ev.on('bed', () => { if (sel && !state.bed.includes(sel)) sel = null; renderIns(); dirty = true; }));
  C.own(C.ev.on('sources', () => { ghostList = ghosts(C); dirty = true; renderChip(); }));
  C.own(C.ev.on('buffer', () => { dirty = true; }));
  ghostList = C.ready ? ghosts(C) : [];

  // --- drawing --------------------------------------------------------------------------------------------------------
  const layer = document.createElement('canvas');
  const drawLayer = () => {
    const W = cv.width, H = cv.height, d = F.dpr;
    layer.width = W; layer.height = H;
    const g = layer.getContext('2d');
    g.fillStyle = '#0a0a0c'; g.fillRect(0, 0, W, H);
    for (let l = 0; l < LANES; l++) {
      g.fillStyle = l % 2 ? '#111215' : '#0d0e10';
      g.fillRect(0, (RULER + GHOST + l * LANE) * d, W, LANE * d);
    }
    g.font = `700 ${9 * d}px ui-monospace, monospace`;
    g.fillStyle = 'rgba(255,255,255,0.13)';
    for (let l = 0; l < LANES; l++) g.fillText(String(l + 1), W - 12 * d, (RULER + GHOST + l * LANE + LANE / 2 + 3) * d);
    g.fillStyle = '#08080a'; g.fillRect(0, 0, W, RULER * d);
    g.fillStyle = 'rgba(198,255,61,0.04)'; g.fillRect(0, RULER * d, W, GHOST * d);
    const pp = pps();
    // grid: beats when there is room, bars, every 4th bar heavy with its number
    g.font = `600 ${10 * d}px ui-monospace, monospace`;
    for (let s = 0; s <= LOOP; s += pp * 4 >= 9 ? 4 : 16) {
      const x = xOf(s) * d;
      if (x < -2 || x > W + 2) continue;
      const bar = s % 16 === 0, four = s % 64 === 0;
      g.fillStyle = four ? 'rgba(224,183,255,0.32)' : bar ? 'rgba(255,255,255,0.10)' : 'rgba(255,255,255,0.04)';
      g.fillRect(Math.round(x), (four ? 0 : RULER * 0.55) * d, Math.max(1, d * (four ? 1.2 : 1)), H);
      if (bar && (four || pp * 16 > 34)) { g.fillStyle = four ? '#e0b7ff' : '#6d6a65'; g.fillText(String(s / 16 + 1), x + 3 * d, 13 * d); }
    }
    // the set's own clips here: faint, acid
    for (const gh of ghostList) {
      const x = xOf(gh.start) * d, w = Math.max(2 * d, gh.len * pp * d);
      g.fillStyle = 'rgba(198,255,61,0.12)';
      g.fillRect(x, (RULER + 5) * d, w - d, (GHOST - 10) * d);
      g.fillStyle = C.src(gh.src)?.color ?? '#c6ff3d';
      g.fillRect(x, (RULER + 5) * d, Math.max(2 * d, w - d), 2 * d);
      g.fillStyle = 'rgba(198,255,61,0.7)';
      g.fillRect(x, (RULER + 5) * d, d, (GHOST - 10) * d);
    }
    g.fillStyle = 'rgba(198,255,61,0.6)'; g.font = `600 ${8 * d}px ui-monospace, monospace`;
    g.fillText('THE SET', 4 * d, (RULER + GHOST - 6) * d);
    // clips
    for (const c of state.bed) {
      const src = C.src(c.src);
      const x = xOf(c.start) * d, w = Math.max(3 * d, c.len * pp * d);
      const y = (RULER + GHOST + c.lane * LANE + 3) * d, hh = (LANE - 6) * d;
      if (x > W || x + w < 0) continue;
      const col = src?.color ?? '#888';
      g.fillStyle = '#16161a'; g.fillRect(x, y, w, hh);
      g.fillStyle = col; g.globalAlpha = 0.22; g.fillRect(x, y, w, hh); g.globalAlpha = 1;
      const buf = bufferNow(engine, c.src);
      if (buf && w > 8 * d) {
        const rate = Math.pow(2, ((c.st ?? 0) + (C.G?.pitchOf(c.src) ?? 0)) / 12);
        const span = c.len * engine.stepSeconds * rate;
        g.save(); g.beginPath(); g.rect(x, y, w, hh); g.clip();
        if (c.rev) { g.translate(x * 2 + w, 0); g.scale(-1, 1); }
        drawWave(g, buf, c.off, c.off + span, x, y + hh * 0.18, w, hh * 0.78, { color: col, gain: 0.9, alpha: 0.85 });
        g.restore();
      }
      g.fillStyle = col; g.fillRect(x, y, w, 3 * d);                     // the label tape on top
      g.strokeStyle = c === sel ? '#fff' : 'rgba(0,0,0,0.8)'; g.lineWidth = (c === sel ? 2 : 1) * d;
      g.strokeRect(x + 0.5, y + 0.5, w - 1, hh - 1);
      if (w > 30 * d) {
        g.fillStyle = '#e9e7e2'; g.font = `700 ${9 * d}px ui-monospace, monospace`;
        g.fillText(`${(src?.name ?? c.src).toUpperCase()}${c.rev ? ' <' : ''}${c.st ? ` ${c.st > 0 ? '+' : ''}${c.st}` : ''}`.slice(0, Math.floor(w / (6 * d))), x + 4 * d, y + 13 * d);
      }
      if (c === sel && w > 26 * d) { g.fillStyle = '#fff'; g.fillRect(x + w - 5 * d, y + hh * 0.3, 2 * d, hh * 0.4); }
    }
    if (!state.bed.length) {
      const cy = (RULER + GHOST + (LANES * LANE) / 2) * d;
      g.fillStyle = 'rgba(8,8,10,0.85)';
      g.fillRect(W / 2 - 150 * d, cy - 26 * d, 300 * d, 46 * d);
      g.fillStyle = 'rgba(224,183,255,0.75)'; g.font = `700 ${11 * d}px ui-monospace, monospace`; g.textAlign = 'center';
      g.fillText('TAP A LANE TO DROP THE TAPE', W / 2, cy - 6 * d);
      g.fillStyle = 'rgba(233,231,226,0.45)'; g.font = `500 ${10 * d}px ui-monospace, monospace`;
      g.fillText('or drag a cassette down, or lay the set\'s bed', W / 2, cy + 10 * d);
      g.textAlign = 'start';
    }
    dirty = false;
  };

  renderChip();
  renderIns();
  return {
    el,
    show() { lay(); F.measure(); clampScroll(); dirty = true; ghostList = C.ready ? ghosts(C) : []; renderChip(); },
    draw() {
      if (!lay.t || performance.now() - lay.t > 500) { lay.t = performance.now(); lay(); }
      if (dirty || g0) drawLayer();
      const g = F.g, d = F.dpr, H = cv.height;
      g.drawImage(layer, 0, 0);
      if (hover) {
        g.fillStyle = 'rgba(224,183,255,0.25)';
        g.fillRect(xOf(hover.step) * d, (RULER + GHOST + hover.lane * LANE) * d, (state.loaded?.len ?? 16) * pps() * d, LANE * d);
      }
      const p = engine.position();
      if (p.playing) {
        const s = ((p.bar % BARS) + p.phase) * 16;
        const x = xOf(s) * d;
        g.fillStyle = 'rgba(224,183,255,0.18)'; g.fillRect(x - 6 * d, 0, 6 * d, H);
        g.fillStyle = '#e0b7ff'; g.fillRect(x, 0, 1.5 * d, H);
      }
    },
  };
}
