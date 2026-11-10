// The Short's timeline: one canvas, a lane per part of the arrangement, every edge a handle you drag with a thumb.
//
//   ruler    bar numbers, the 33-50 s target zone, the length handle (the end), tap: play from that bar
//   form     the sections; breaks move (drag the block) and stretch (drag its right edge); the drop stretches left
//   energy   per-bar loudness of the Short (amber), the set's Short (acid, dashed), the references' shape (ghost)
//   kick     the scooped opening (drag its end), the full kick (drag where it enters), the pre-kick gaps
//   hats     a matrix of the four layers; drag the start of a row to move where that layer enters
//   splash   long and short splashes; drag a tail to change its beats, tap the lane for every 4/8/16 bars/once
//   sfx      the ARC RAIDERS hits and the chord loop; tap to cycle where SFX enters
//
// Drags are relative and snap to each param's step (4/8-bar grid for lengths); a tick on every step, a strong one
// on the set's value. Long press a handle: the inspector. Double tap a handle: back to the set.

import { clamp, haptic, inspect, toast } from '../ui.js';
import { format, setNorm, toNorm } from '../params.js';
import { writer } from '../widgets/core.js';
import { TARGET, BAR_S, LAYERS, SPLASH_EVERY, sections } from './model.js';

const LANES = [
  { key: 'ruler', h: 36 },
  { key: 'form', h: 40, label: 'FORM' },
  { key: 'energy', h: 60, label: 'LUFS' },
  { key: 'kick', h: 32, label: 'KICK' },
  { key: 'hats', h: 52, label: 'HATS' },
  { key: 'splash', h: 32, label: 'SPLSH' },
  { key: 'sfx', h: 28, label: 'SFX' },
];
/** A phone on its side has ~300 px under the transport: the lanes get shorter. */
const LANES_COMPACT = [
  { key: 'ruler', h: 32 },
  { key: 'form', h: 34, label: 'FORM' },
  { key: 'energy', h: 42, label: 'LUFS' },
  { key: 'kick', h: 28, label: 'KICK' },
  { key: 'hats', h: 44, label: 'HATS' },
  { key: 'splash', h: 28, label: 'SPLSH' },
  { key: 'sfx', h: 24, label: 'SFX' },
];
const COMPACT = '(orientation: landscape) and (max-height: 500px)';
const G = 38;                       // gutter for lane labels
const PAD_R = 12;
const COL = {
  bg: '#0c0d10', lane: '#111317', rule: '#22262c', text: '#6d6a65', text2: '#a4a19a',
  stage: '#59c7ff', hazard: '#ff5a1f', acid: '#c6ff3d', lcd: '#ffb547', cold: '#59c7ff', alarm: '#ff2e4d',
};
const LAYER_COL = { A: '#3f9fd6', B: '#ff8a3d', C: '#59c7ff', D: '#b8ecff' };

export class Timeline {
  constructor(ctx, arranger, data, { refsShape } = {}) {
    this.ctx = ctx; this.arr = arranger; this.data = data; this.refsShape = refsShape;
    this.cv = document.createElement('canvas');
    this.cv.className = 'arr-tl-cv';
    this.cv.setAttribute('role', 'img');
    this.cv.setAttribute('aria-label', 'The Short as a timeline: sections, loudness, kick, hats, splashes, SFX');
    this.el = document.createElement('div');
    this.el.className = 'arr-tl';
    this.el.append(this.cv);
    const mq = matchMedia(COMPACT);
    const layout = () => {
      this.lanes = mq.matches ? LANES_COMPACT : LANES;
      this.RH = this.lanes[0].h;
      this.H = this.lanes.reduce((a, l) => a + l.h, 0);
      this.cv.style.height = `${this.H}px`;
      this.dirty = true; this._hc = null;
    };
    layout();
    mq.addEventListener?.('change', layout);
    ctx.own(() => mq.removeEventListener?.('change', layout));
    this.V = 28;                    // bars visible
    this.drag = null;
    this.hover = null;
    this.dirty = true;
    this.lastPos = null;
    this.setPlan = arranger.plan(this.setSnapshot());
    this._wire();
    const ro = new ResizeObserver(() => { this.dirty = true; });
    ro.observe(this.el);
    ctx.own(() => ro.disconnect());
  }

  /** The set's own values of every arr.* param, normalised (for the acid "set" curve). */
  setSnapshot() {
    const snap = {};
    for (const p of this.ctx.params.stage('arrange')) snap[p.id] = setNorm(p);
    return snap;
  }

  // --- geometry ------------------------------------------------------------------------------------------------
  laneY(key) { let y = 0; for (const l of this.lanes) { if (l.key === key) return [y, l.h]; y += l.h; } return [0, 0]; }
  laneAt(y) { let t = 0; for (const l of this.lanes) { if (y >= t && y < t + l.h) return l.key; t += l.h; } return null; }
  get ppb() { return (this.W - G - PAD_R) / this.V; }
  x(bar) { return G + bar * this.ppb; }
  barAt(x) { return (x - G) / this.ppb; }

  fit() {
    const L = this.arr.pl?.L ?? 20;
    if (!this.drag) this.V = clamp(Math.ceil((L + 6) / 4) * 4, 24, 44);
  }

  // --- handles ---------------------------------------------------------------------------------------------------
  handles() {
    const pl = this.arr.pl;
    if (this._hc && this._hc.pl === pl && this._hc.V === this.V) return this._hc.out;
    const out = this._handles(pl);
    this._hc = { pl, V: this.V, out };
    return out;
  }

  _handles(pl) {
    const v = pl.values, out = [];
    const add = (lane, id, bar, opts = {}) => { if (this.ctx.params.has(id)) out.push({ lane, id, bar, unit: 'bar', dir: 1, ...opts }); };
    add('ruler', 'arr.length', pl.L, { label: 'LENGTH' });
    const brk = (flag, at, len, name) => {
      if (!(v[flag] >= 0.5) || !(v[len] > 0)) return;
      const from = Math.round(v[at]) - 1, to = Math.min(pl.L, from + Math.round(v[len]));
      if (to <= from) return;
      add('form', `arr.${len}`, to, { label: name, edge: true });
      add('form', `arr.${at}`, from, { label: `${name} AT`, body: [from, to] });
    };
    brk('breakOn', 'breakAt', 'breakBars', 'BREAK');
    brk('secondBreak', 'break2At', 'break2Bars', 'BREAK 2');
    add('form', 'arr.dropBars', pl.drop.from, { label: 'DROP', dir: -1, edge: true });
    add('kick', 'arr.intro', Math.min(v.intro, pl.L), { label: 'SCOOP', side: -1 });
    add('kick', 'arr.kickIn', v.kickIn - 1, { label: 'KICK IN', side: 1 });
    for (const [k, L] of LAYERS.entries()) add('hats', `arr.hat${L}`, v[`hat${L}`] - 1, { label: `HAT ${L}`, row: k });
    for (const b of pl.bars) {
      if (!b.splash) continue;
      add('splash', b.splash.long ? 'arr.splashLong' : 'arr.splashShort', b.i + b.splash.beats / 4,
        { unit: 'beat', label: b.splash.long ? 'LONG SPLASH' : 'SHORT SPLASH', edge: true });
    }
    return out.filter((hd) => hd.bar <= this.V + 0.5);
  }

  hit(px, py) {
    // handles in the lane under the finger, and in a lane next to it if the finger is within 14 px of it
    const near = (key) => { const [y0, h] = this.laneY(key); return py < y0 ? y0 - py : py > y0 + h ? py - y0 - h : 0; };
    const hs = this.handles().filter((hd) => near(hd.lane) <= 14);
    const R = 22;
    let best = null, bd = Infinity;
    for (const hd of hs) {
      const lane = hd.lane;
      const vy = near(lane) * 1.2;
      if (hd.body && px > this.x(hd.body[0]) + 10 && px < this.x(hd.body[1]) - 10) {
        if (bd > 0.5 + vy) { best = hd; bd = 0.5 + vy; }
        continue;
      }
      let d = Math.abs(px - this.x(hd.bar));
      if (d > R) continue;
      d += vy;
      if (lane === 'hats') {
        const [y0, h] = this.laneY('hats');
        const row = 3 - Math.floor((py - y0) / (h / 4));
        d += Math.abs(row - hd.row) * 6;
      }
      if (hd.side && Math.abs(px - this.x(hd.bar)) < 14) d += (Math.sign(px - this.x(hd.bar)) === hd.side ? -3 : 3);
      if (d < bd) { bd = d; best = hd; }
    }
    return best;
  }

  // --- input -----------------------------------------------------------------------------------------------------
  _wire() {
    const cv = this.cv;
    cv.style.touchAction = 'none';
    let start = null, timer = 0, lastTap = { t: -Infinity, id: null };
    const pt = (e) => { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    const down = (e) => {
      if (start) { start.fine = true; if (this.drag) this.drag.fine = true; return; }
      const [px, py] = pt(e);
      const hd = this.hit(px, py);
      start = { id: e.pointerId, px, py, x0: e.clientX, moved: false, t0: performance.now(), hd, lane: this.laneAt(py) };
      try { cv.setPointerCapture(e.pointerId); } catch { /* synthetic pointer */ }
      clearTimeout(timer);
      if (hd) timer = setTimeout(() => { if (start && !start.moved) { start.long = true; haptic(true); inspect(hd.id); } }, 480);
    };
    const move = (e) => {
      if (!start || e.pointerId !== start.id) return;
      const dxTotal = e.clientX - start.x0;
      if (!start.moved && Math.abs(dxTotal) < 5) return;
      if (!start.moved) {
        start.moved = true; clearTimeout(timer);
        if (!start.hd) return;
        const p = this.ctx.params.get(start.hd.id);
        // ties at one edge: the hats' rows decide by the first move's direction
        let hd = start.hd;
        if (hd.lane === 'hats') {
          const same = this.handles().filter((o) => o.lane === 'hats' && Math.abs(o.bar - hd.bar) < 0.01);
          if (same.length > 1) hd = dxTotal > 0 ? same.at(-1) : same[0];
        }
        const pp = this.ctx.params.get(hd.id);
        const w = writer(this.ctx, hd.id, 'timeline');
        w.begin();
        this.drag = { hd, p: pp, w, startReal: this.ctx.store.real(hd.id), acc: 0, last: this.ctx.store.real(hd.id), fine: !!start.fine || performance.now() - start.t0 > 350 };
        void p;
      }
      if (!this.drag) return;
      const k = this.drag.fine ? 0.25 : 1;
      this.drag.acc += (e.clientX - (start.lx ?? start.x0)) * k;
      start.lx = e.clientX;
      this._dragTo();
    };
    const up = (e) => {
      if (!start || e.pointerId !== start.id) return;
      clearTimeout(timer);
      const s = start; start = null;
      if (this.drag) { this.drag.w.end(); this.drag = null; this.fit(); this.dirty = true; return; }
      if (s.moved || s.long || e.type !== 'pointerup') return;
      // a tap
      const now = performance.now();
      if (s.hd && lastTap.id === s.hd.id && now - lastTap.t < 320) {
        this.ctx.store.reset(s.hd.id, { source: 'doubletap' }); haptic(true);
        toast(`${this.ctx.params.get(s.hd.id).label}: the set's value`);
        lastTap = { t: -Infinity, id: null };
        return;
      }
      lastTap = { t: now, id: s.hd?.id ?? null };
      this.tap(s.lane, s.px, s.hd);
    };
    cv.addEventListener('pointerdown', down);
    cv.addEventListener('pointermove', move);
    cv.addEventListener('pointerup', up);
    cv.addEventListener('pointercancel', up);
    cv.addEventListener('contextmenu', (e) => e.preventDefault());
  }

  _dragTo() {
    const d = this.drag, p = d.p, hd = d.hd;
    const per = hd.unit === 'beat' ? this.ppb / 4 : this.ppb;
    let real = d.startReal + hd.dir * d.acc / per;
    const step = p.step ?? 1;
    real = clamp(Math.round(real / step) * step, p.min, p.max);
    if (real !== d.last) {
      d.last = real;
      d.w.set(toNorm(p, real));
      if (Math.abs(real - (p.set ?? p.min)) < 1e-6) haptic(true); else haptic();
    }
    this.dirty = true;
  }

  tap(lane, px, hd) {
    const store = this.ctx.store, bar = Math.floor(this.barAt(px));
    const cycle = (id) => {
      const p = this.ctx.params.get(id);
      const n = p.options.length, cur = Math.round(store.real(id));
      store.begin(); store.set(id, toNorm(p, (cur + 1) % n), { source: 'timeline' }); store.end();
      haptic(); toast(`${p.label}: ${p.options[(cur + 1) % n]}`);
    };
    if (lane === 'splash' && !hd) return cycle('arr.splashEvery');
    if (lane === 'sfx') return cycle('arr.sfxBuild');
    if (lane === 'form' && !hd && bar >= 0 && bar < (this.arr.pl?.L ?? 0)) {
      const v = this.arr.pl.values;
      const on = (flag, at, len) => {
        const P = (id) => this.ctx.params.get(id);
        store.begin();
        store.set(flag, 1, { source: 'timeline' });
        store.set(at, toNorm(P(at), clamp(Math.floor(bar / 4) * 4 + 1, P(at).min, P(at).max)), { source: 'timeline' });
        if ((store.real(len) || 0) < 4) store.set(len, toNorm(P(len), 4), { source: 'timeline' });
        store.end();
        haptic(true); toast('A break: drag it, stretch its right edge, double tap to take it out');
      };
      if (v.breakOn < 0.5) return on('arr.breakOn', 'arr.breakAt', 'arr.breakBars');
      if (v.secondBreak < 0.5 && this.ctx.params.has('arr.break2At')) return on('arr.secondBreak', 'arr.break2At', 'arr.break2Bars');
      return;
    }
    if (lane === 'form' && hd?.body) {
      return toast('Drag to move, drag the right edge to stretch, double tap to take it out');
    }
    if ((lane === 'ruler' || lane === 'energy') && !hd && bar >= 0) {
      this.onSeek?.(clamp(bar, 0, (this.arr.pl?.L ?? 1) - 1));
    }
  }

  // --- drawing ---------------------------------------------------------------------------------------------------
  draw(where) {
    const r = this.el.getBoundingClientRect();
    if (!r.width) return;
    const dpr = Math.min(3, devicePixelRatio || 1);
    const W = Math.round(r.width), H = this.H;
    if (this.cv.width !== Math.round(W * dpr) || this.cv.height !== Math.round(H * dpr)) {
      this.cv.width = Math.round(W * dpr); this.cv.height = Math.round(H * dpr); this.dirty = true;
    }
    const posKey = where ? `${where.i}:${Math.round(where.t * 40)}` : 'none';
    if (!this.dirty && posKey === this.lastPos) return;
    this.lastPos = posKey; this.dirty = false;
    this.W = W;
    if (!this.drag) this.fit();
    const g = this.cv.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.g = g;
    this.paint(where);
  }

  paint(where) {
    const g = this.g, W = this.W, H = this.H, pl = this.arr.pl;
    if (!pl) return;
    g.clearRect(0, 0, W, H);
    g.fillStyle = COL.bg; g.fillRect(0, 0, W, H);
    // lanes
    let y = 0;
    for (const l of this.lanes) {
      if (l.key !== 'ruler') {
        g.fillStyle = COL.lane; g.fillRect(G, y + 1, W - G - 4, l.h - 2);
        g.fillStyle = COL.text; g.font = '600 8.5px ui-monospace, SF Mono, Menlo, monospace';
        g.textBaseline = 'middle'; g.textAlign = 'left';
        g.fillText(l.label, 6, l.key === 'energy' ? y + 9 : y + l.h / 2);
      }
      y += l.h;
    }
    this.grid();
    this.ruler(pl);
    this.form(pl);
    this.energyLane(pl);
    this.kick(pl);
    this.hats(pl);
    this.splash(pl);
    this.sfx(pl);
    // the pre-kick gaps silence every lane
    const [hy] = this.laneY('hats'), [sy, sh] = this.laneY('sfx');
    for (const b of pl.bars) {
      if (!b.gap) continue;
      const x0 = this.x(b.i + b.gap.from / 4), x1 = this.x(b.i + 1);
      g.fillStyle = 'rgba(8,8,10,0.72)'; g.fillRect(x0, hy, x1 - x0, sy + sh - hy);
    }
    // beyond the end
    const xe = this.x(pl.L);
    g.fillStyle = 'rgba(0,0,0,0.55)'; g.fillRect(xe, this.RH, W - xe, H - this.RH);
    this.playhead(where);
    if (this.drag) this.tag();
  }

  grid() {
    const g = this.g, top = this.RH;
    for (let b = 0; b <= this.V; b++) {
      const x = Math.round(this.x(b)) + 0.5;
      g.strokeStyle = b % 8 === 0 ? 'rgba(255,255,255,0.13)' : b % 4 === 0 ? 'rgba(255,255,255,0.07)' : 'rgba(255,255,255,0.03)';
      g.lineWidth = 1;
      g.beginPath(); g.moveTo(x, b % 4 === 0 ? 20 : top); g.lineTo(x, this.H); g.stroke();
    }
  }

  ruler(pl) {
    const g = this.g;
    // the 33-50 s target zone: a lit strip along the top
    const lo = TARGET.lo / BAR_S, hi = TARGET.hi / BAR_S;
    const zx0 = this.x(lo), zx1 = this.x(Math.min(hi, this.V));
    g.fillStyle = 'rgba(198,255,61,0.12)'; g.fillRect(zx0, 3, zx1 - zx0, 12);
    g.fillStyle = 'rgba(198,255,61,0.75)'; g.fillRect(zx0, 3, 1, 12); if (hi < this.V) g.fillRect(zx1 - 1, 3, 1, 12);
    g.font = '700 8px ui-monospace, SF Mono, monospace'; g.textBaseline = 'middle'; g.textAlign = 'left';
    const xe = this.x(pl.L);
    const label = hi < this.V ? '33-50 s' : '33 s →';
    if (Math.abs(xe - (zx0 + 24)) > 30 || xe > zx1) g.fillText(label, zx0 + 4, 9.5);
    // bar numbers
    g.fillStyle = COL.text2; g.font = '600 9px ui-monospace, SF Mono, monospace'; g.textAlign = 'left'; g.textBaseline = 'alphabetic';
    for (let b = 0; b < this.V; b += 4) if (Math.abs(this.x(b) - xe) > 18) g.fillText(String(b + 1), this.x(b) + 3, this.RH - 5);
    // the set's length
    const sp = this.ctx.params.get('arr.length');
    g.fillStyle = COL.acid; g.fillRect(this.x(sp.set) - 1, 17, 2, this.RH - 19);
    // the end handle: the length in bars over its seconds
    const inT = pl.seconds >= TARGET.lo && pl.seconds <= TARGET.hi;
    g.fillStyle = this.drag?.hd.id === 'arr.length' ? '#ff7a45' : COL.hazard;
    roundRect(g, xe - 17, 2, 34, this.RH - 4, 6); g.fill();
    g.fillStyle = '#120400'; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.font = '800 12px ui-monospace, SF Mono, monospace'; g.fillText(String(pl.L), xe, 11);
    g.font = '700 8.5px ui-monospace, SF Mono, monospace'; g.fillText(`${pl.seconds.toFixed(0)}s`, xe, this.RH - 12);
    g.fillStyle = inT ? COL.acid : COL.alarm; g.fillRect(xe - 12, this.RH - 5, 24, 2);
  }

  form(pl) {
    const g = this.g, [y0, h] = this.laneY('form');
    for (const s of sections(pl)) {
      const x0 = this.x(s.from) + 1, x1 = this.x(s.to) - 1, w = x1 - x0;
      let fill = 'rgba(89,199,255,0.18)', stroke = 'rgba(89,199,255,0.45)', text = COL.text2;
      if (s.name === 'BREAK') { fill = 'rgba(255,90,31,0.16)'; stroke = COL.hazard; text = COL.hazard; }
      else if (s.name === 'SCOOP') { fill = 'rgba(89,199,255,0.10)'; }
      else if (s.name === 'NO KICK') { fill = 'rgba(255,255,255,0.04)'; stroke = 'rgba(255,255,255,0.15)'; }
      else if (s.name === 'DROP') { fill = 'rgba(89,199,255,0.42)'; stroke = COL.stage; text = '#e9f8ff'; }
      else { const n = s.name.length; fill = `rgba(89,199,255,${0.12 + n * 0.06})`; }
      g.fillStyle = fill; roundRect(g, x0, y0 + 5, w, h - 10, 4); g.fill();
      g.strokeStyle = stroke; g.lineWidth = 1; g.stroke();
      if (s.name === 'BREAK') hatch(g, x0, y0 + 5, w, h - 10, 'rgba(255,90,31,0.22)');
      if (s.name === 'SCOOP') hatch(g, x0, y0 + 5, w, h - 10, 'rgba(89,199,255,0.25)');
      g.save(); g.beginPath(); g.rect(x0, y0, w, h); g.clip();
      g.fillStyle = text; g.textAlign = 'center'; g.textBaseline = 'middle';
      for (const size of [10, 8.5, 7]) {                // the whole name, as large as fits; none if it cannot
        g.font = `700 ${size}px ui-monospace, SF Mono, monospace`;
        if (g.measureText(s.name).width + 4 <= w) { g.fillText(s.name, x0 + w / 2, y0 + h / 2); break; }
      }
      g.restore();
    }
    // handles: break edges and the drop's left edge
    for (const hd of this.handles().filter((o) => o.lane === 'form' && o.edge)) this.grip(this.x(hd.bar), y0 + 6, h - 12, hd);
  }

  energyLane(pl) {
    const g = this.g, [y0, h] = this.laneY('energy');
    const lv = this.levels(), key = `${lv.splash}|${lv.break}|${lv.chord}`;
    const shape = this.arr.useShape;
    if (!this._ec || this._ec.pl !== pl || this._ec.key !== key || this._ec.shape !== shape) {
      this._ec = { pl, key, shape, cur: this.arr.energy(pl, lv).map((x) => x.lufs) };
    }
    if (this._se?.shape !== shape) this._se = { shape, lufs: this.arr.energy(this.setPlan).map((x) => x.lufs) };
    this.setEnergy = this._se.lufs;
    const cur = this._ec.cur;
    // the scale follows the Short (at least 8 LU tall), in whole LU
    const all = [...cur, ...this.setEnergy].filter((x) => x > -60);
    let hi = Math.ceil(Math.max(...all, -14) + 1), lo = Math.floor(Math.min(...all, -18) - 1);
    if (hi - lo < 8) lo = hi - 8;
    this.eRange = [lo, hi];
    const Y = (l) => y0 + h - 4 - clamp((l - lo) / (hi - lo)) * (h - 8);
    // scale marks
    const marks = [];
    for (let l = Math.ceil(lo / 3) * 3; l <= hi; l += 3) marks.push(l);
    g.strokeStyle = 'rgba(255,255,255,0.06)'; g.setLineDash([2, 3]);
    for (const l of marks) { g.beginPath(); g.moveTo(G, Y(l)); g.lineTo(this.W - 4, Y(l)); g.stroke(); }
    g.setLineDash([]);
    g.fillStyle = 'rgba(164,161,154,0.6)'; g.font = '600 7.5px ui-monospace, monospace'; g.textAlign = 'left'; g.textBaseline = 'bottom';
    for (const l of marks.filter((_, k) => k % 2 === 0)) g.fillText(String(l), G + 2, Y(l) - 1);
    // the references' shape (ghost): their break depth at their place, scaled into this length
    if (this.refsShape) {
      const peak = Math.max(...cur.filter((x) => x > -60), -20);
      const ghost = this.refsShape(pl.L).map((d) => peak + d);
      g.strokeStyle = 'rgba(233,231,226,0.28)'; g.setLineDash([4, 4]); g.lineWidth = 1.2;
      steps(g, ghost, (i) => this.x(i), Y); g.stroke(); g.setLineDash([]);
    }
    // the set's own Short
    g.strokeStyle = 'rgba(198,255,61,0.55)'; g.setLineDash([2, 3]); g.lineWidth = 1.2;
    steps(g, this.setEnergy, (i) => this.x(i), Y); g.stroke(); g.setLineDash([]);
    // now
    const grad = g.createLinearGradient(0, y0, 0, y0 + h);
    grad.addColorStop(0, 'rgba(255,181,71,0.35)'); grad.addColorStop(1, 'rgba(255,181,71,0.02)');
    g.beginPath(); steps(g, cur, (i) => this.x(i), Y, false);
    g.lineTo(this.x(cur.length), y0 + h - 2); g.lineTo(this.x(0), y0 + h - 2); g.closePath();
    g.fillStyle = grad; g.fill();
    g.strokeStyle = COL.lcd; g.lineWidth = 1.8; g.shadowColor = 'rgba(255,181,71,0.6)'; g.shadowBlur = 6;
    steps(g, cur, (i) => this.x(i), Y); g.stroke();
    g.shadowBlur = 0;
    this.cur = cur;
  }

  levels() {
    const s = this.ctx.store, d = (id) => (s.params.has(id) ? s.real(id) - (s.params.get(id).set ?? 0) : 0);
    return { splash: d('arr.splashLevel'), break: d('arr.breakLevel'), chord: d('arr.chordLevel') };
  }

  kick(pl) {
    const g = this.g, [y0, h] = this.laneY('kick');
    let run = null;
    const flush = () => {
      if (!run) return;
      const x0 = this.x(run.from) + 1, x1 = this.x(run.to) - 1;
      if (run.kind === 'scoop') {
        g.fillStyle = 'rgba(89,199,255,0.14)'; roundRect(g, x0, y0 + 6, x1 - x0, h - 12, 3); g.fill();
        hatch(g, x0, y0 + 6, x1 - x0, h - 12, 'rgba(89,199,255,0.5)');
        g.strokeStyle = 'rgba(89,199,255,0.6)'; g.stroke();
      } else {
        const grad = g.createLinearGradient(0, y0 + 6, 0, y0 + h - 6);
        grad.addColorStop(0, '#6fd0ff'); grad.addColorStop(1, '#2a7fb0');
        g.fillStyle = grad; roundRect(g, x0, y0 + 6, x1 - x0, h - 12, 3); g.fill();
        // four on the floor
        g.fillStyle = 'rgba(0,0,0,0.35)';
        for (let b = run.from; b < run.to; b++) for (let q = 0; q < 4; q++) {
          const xx = this.x(b + q / 4); if (this.ppb > 10) g.fillRect(xx + 1, y0 + h / 2 - 1, Math.max(1, this.ppb / 4 - 2), 2);
        }
      }
      run = null;
    };
    for (const b of pl.bars) {
      const k = b.kick;
      if (!k) { flush(); continue; }
      if (run && run.kind === k && !b.entry) run.to = b.i + 1; else { flush(); run = { kind: k, from: b.i, to: b.i + 1 }; }
    }
    flush();
    // pre-kick gaps
    for (const b of pl.bars) {
      if (!b.gap) continue;
      const x0 = this.x(b.i + b.gap.from / 4), x1 = this.x(b.i + 1);
      g.fillStyle = b.gap.style === 0 ? 'rgba(224,183,255,0.28)' : 'rgba(0,0,0,0.7)';
      g.fillRect(x0, y0 + 3, x1 - x0, h - 6);
      g.strokeStyle = b.gap.style === 0 ? '#e0b7ff' : 'rgba(255,255,255,0.3)'; g.setLineDash([2, 2]);
      g.strokeRect(x0 + 0.5, y0 + 3.5, x1 - x0 - 1, h - 7); g.setLineDash([]);
      if (b.wuh && x1 - x0 > 8) {
        g.fillStyle = '#e0b7ff'; g.font = '700 8px ui-monospace, monospace'; g.textAlign = 'left'; g.textBaseline = 'middle';
        const xs = this.x(b.i + b.wuh.at / 4);
        if (this.ppb * b.wuh.beats / 4 > 22) g.fillText('WUH', xs + 2, y0 + h / 2);
      }
    }
    for (const hd of this.handles().filter((o) => o.lane === 'kick')) this.grip(this.x(hd.bar), y0 + 4, h - 8, hd);
  }

  hats(pl) {
    const g = this.g, [y0, h] = this.laneY('hats');
    const rh = (h - 4) / 4;
    for (const b of pl.bars) {
      const x0 = this.x(b.i) + 1, w = Math.max(1, this.ppb - 2);
      LAYERS.forEach((L, k) => {
        const yy = y0 + 2 + (3 - k) * rh;
        const on = b.hats.includes(L);
        const forced = on && b.drop && b.i + 1 < pl.values[`hat${L}`];
        g.fillStyle = on ? LAYER_COL[L] : 'rgba(255,255,255,0.04)';
        g.globalAlpha = on ? (forced ? 0.55 : 0.9) : 1;
        g.fillRect(x0, yy + 1, w, rh - 2);
        g.globalAlpha = 1;
      });
    }
    // row letters
    g.font = '700 8px ui-monospace, monospace'; g.textAlign = 'right'; g.textBaseline = 'middle';
    LAYERS.forEach((L, k) => { g.fillStyle = L === 'B' ? COL.hazard : COL.text2; g.fillText(L, G - 3, y0 + 2 + (3 - k + 0.5) * rh); });
    for (const hd of this.handles().filter((o) => o.lane === 'hats')) {
      const yy = y0 + 2 + (3 - hd.row) * rh;
      this.grip(this.x(hd.bar), yy, rh, hd, true);
    }
  }

  splash(pl) {
    const g = this.g, [y0, h] = this.laneY('splash');
    for (const b of pl.bars) {
      if (!b.splash) continue;
      const x0 = this.x(b.i), x1 = this.x(b.i + b.splash.beats / 4);
      const grad = g.createLinearGradient(x0, 0, x1, 0);
      grad.addColorStop(0, b.splash.long ? 'rgba(255,181,71,0.75)' : 'rgba(255,181,71,0.5)');
      grad.addColorStop(0.35, b.splash.long ? 'rgba(255,181,71,0.85)' : 'rgba(255,181,71,0.55)');
      grad.addColorStop(1, 'rgba(255,181,71,0.05)');
      g.fillStyle = grad;
      g.beginPath(); g.moveTo(x0, y0 + h - 5); g.lineTo(x0 + Math.min(this.ppb * 0.75, x1 - x0) , y0 + 5); g.lineTo(x1, y0 + h / 2); g.lineTo(x1, y0 + h - 5); g.closePath(); g.fill();
      g.fillStyle = COL.lcd; g.beginPath(); g.moveTo(x0, y0 + 4); g.lineTo(x0 + 6, y0 + 4); g.lineTo(x0, y0 + 11); g.closePath(); g.fill();
    }
    const every = SPLASH_EVERY[Math.round(pl.values.splashEvery)] ?? 8;
    g.fillStyle = COL.text; g.font = '600 8px ui-monospace, monospace'; g.textAlign = 'right'; g.textBaseline = 'middle';
    g.fillText(every ? `/${every}` : '1x', this.W - 8, y0 + h / 2);
    for (const hd of this.handles().filter((o) => o.lane === 'splash')) this.grip(this.x(hd.bar), y0 + 4, h - 8, hd);
  }

  sfx(pl) {
    const g = this.g, [y0, h] = this.laneY('sfx');
    for (const b of pl.bars) {
      const x0 = this.x(b.i) + 1, w = this.ppb - 2;
      if (b.chord != null) {
        g.strokeStyle = 'rgba(224,183,255,0.7)'; g.lineWidth = 1.2; g.beginPath();
        for (let k = 0; k <= 8; k++) { const xx = x0 + w * k / 8; const yy = y0 + h - 7 - Math.sin((b.chord * 8 + k) * 0.8) * 2.5; if (k) g.lineTo(xx, yy); else g.moveTo(xx, yy); }
        g.stroke();
      }
      if (b.arc === 0) {
        const x1 = this.x(Math.min(pl.L, b.i + 2)) - 1;
        g.fillStyle = 'rgba(255,90,31,0.7)'; roundRect(g, x0, y0 + 5, x1 - x0, h - 14, 3); g.fill();
        g.fillStyle = '#120400'; g.font = '800 8px ui-monospace, monospace'; g.textAlign = 'left'; g.textBaseline = 'middle';
        if (x1 - x0 > 24) g.fillText('ARC', x0 + 3, y0 + h / 2 - 4);
      }
    }
    if (pl.sfxAt == null) { g.fillStyle = COL.text; g.font = '600 8px ui-monospace, monospace'; g.textAlign = 'left'; g.fillText('SFX withheld: tap', G + 6, y0 + h / 2); }
  }

  /** An edge handle: a vertical grip, hazard while touched. */
  grip(x, y, h, hd, small = false) {
    const g = this.g, on = this.drag?.hd.id === hd.id;
    const p = this.ctx.params.get(hd.id);
    const atSet = this.ctx.store.isSet(hd.id);
    g.fillStyle = on ? COL.hazard : atSet ? COL.acid : '#e9e7e2';
    const w = small ? 3 : 4;
    roundRect(g, x - w / 2, y, w, h, 2); g.fill();
    if (!small) { g.fillStyle = 'rgba(0,0,0,0.6)'; g.fillRect(x - 0.5, y + h / 2 - 3, 1, 6); }
    void p;
  }

  playhead(where) {
    if (!where || where.i < 0 || where.done) {
      if (where && where.i < 0) {
        const g = this.g;
        g.fillStyle = COL.hazard; g.font = '800 11px ui-monospace, monospace'; g.textAlign = 'center'; g.textBaseline = 'middle';
        g.fillText(`COUNT ${where.count}`, this.x(0) + 40, this.RH / 2);
      }
      return;
    }
    const g = this.g, x = this.x(where.t);
    g.strokeStyle = COL.hazard; g.lineWidth = 2; g.shadowColor = COL.hazard; g.shadowBlur = 8;
    g.beginPath(); g.moveTo(x, this.RH); g.lineTo(x, this.H); g.stroke(); g.shadowBlur = 0;
    g.fillStyle = COL.hazard; g.beginPath(); g.moveTo(x - 5, this.RH); g.lineTo(x + 5, this.RH); g.lineTo(x, this.RH + 6); g.closePath(); g.fill();
    if (where.variant != null && where.variant >= 0) {
      g.fillStyle = COL.cold; g.font = '800 10px ui-monospace, monospace'; g.textAlign = 'left'; g.textBaseline = 'top';
      g.fillText('ABC'[where.variant], x + 4, this.RH + 2);
    }
  }

  /** The value of the handle being dragged, as a flag over the lane. */
  tag() {
    const d = this.drag, g = this.g;
    const [y0] = this.laneY(d.hd.lane);
    const real = this.ctx.store.real(d.hd.id);
    let text = `${d.hd.label} ${format(d.p, real)}`;
    if (d.hd.id === 'arr.length') text += ` · ${(real * BAR_S).toFixed(0)} s`;
    if (d.hd.unit === 'bar' && d.p.unit === 'bar') text = `${d.hd.label} · BAR ${Math.round(real)}`;
    g.font = '700 11px ui-monospace, SF Mono, monospace';
    const tw = g.measureText(text).width + 14;
    const hx = this.x(this.handles().find((o) => o.id === d.hd.id)?.bar ?? 0);
    const x = clamp(hx - tw / 2, 2, this.W - tw - 2), y = Math.max(0, y0 - 22);
    g.fillStyle = 'rgba(7,7,7,0.92)'; roundRect(g, x, y, tw, 20, 5); g.fill();
    g.strokeStyle = COL.hazard; g.lineWidth = 1; g.stroke();
    g.fillStyle = this.ctx.store.isSet(d.hd.id) ? COL.acid : COL.lcd; g.textAlign = 'left'; g.textBaseline = 'middle';
    g.fillText(text, x + 7, y + 10.5);
  }
}

function roundRect(g, x, y, w, h, r) {
  w = Math.max(0, w);
  r = Math.min(r, w / 2, h / 2);
  g.beginPath();
  g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath();
}

function hatch(g, x, y, w, h, color) {
  g.save(); g.beginPath(); g.rect(x, y, w, h); g.clip();
  g.strokeStyle = color; g.lineWidth = 1;
  for (let k = -h; k < w; k += 5) { g.beginPath(); g.moveTo(x + k, y + h); g.lineTo(x + k + h, y); g.stroke(); }
  g.restore();
}

/** A per-bar step line (flat across each bar, sloped over the bar line). */
function steps(g, vals, X, Y, begin = true) {
  if (begin) g.beginPath();
  vals.forEach((v, i) => {
    const y = Y(v);
    if (i === 0) g.moveTo(X(0), y); else g.lineTo(X(i) + 1.5, y);
    g.lineTo(X(i + 1) - 1.5, y);
  });
}
