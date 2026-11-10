// The whole song's map: every clip on every track of HW002's full set (the manifest's `tracks`, in bars), its
// per-bar loudness, where the Short comes from (bars 121-140) and where the song breaks (81-96), and the four
// references' own loudness bar by bar with their breaks, so the song's shape sits next to theirs.
//
// Pinch to zoom, drag sideways to move, tap a bar to play the WHOLE SONG from there (its own player on the
// 'arr-song' bus; the stems are off meanwhile). Back to the Short: the button, the transport's stop, or leaving.

import { clamp, h, haptic, toast } from '../ui.js';

const G = 50;                                       // label gutter
const GROUP_COL = { 'kick group': '#ff5a1f', 'perc group': '#59c7ff', 'SFX group': '#e0b7ff', 'Break group': '#ffb547' };
const NAMES = [
  [/^kick$/, 'kick'], [/^rumble/, 'rumble'], [/^6-2022-05-30/, 'splash'], [/^perc 1/, 'perc 1'], [/^perc 2/, 'perc 2'],
  [/^10-ARC/, 'ARC'], [/^11-/, 'audio'], [/^12-2022-06-02/, 'chord'], [/^14-ARC/, 'ARC brk'], [/sound 4/, 'synth 4'],
  [/synth horn/, 'horn'], [/^17-2023-10-07/, 'rec'], [/beatbox/, 'beatbox'],
];
const short = (name) => (NAMES.find(([re]) => re.test(name))?.[1]) ?? name.replace(/^\d+-/, '').slice(0, 8);

export class SongMap {
  constructor(ctx, arranger, lanes, data) {
    this.ctx = ctx; this.e = ctx.engine; this.arr = arranger; this.lanes = lanes; this.data = data;
    this.cv = h('canvas', { class: 'arr-map-cv' });
    this.status = h('span', { class: 'map-status', text: 'Tap a bar: the whole song from there' });
    this.back = h('button', { type: 'button', class: 'arr-btn map-back', text: 'Back to the Short', onclick: () => { haptic(); this.stopSong(true); } });
    this.fitBtn = h('button', { type: 'button', class: 'arr-btn map-fit', text: 'Whole song', onclick: () => { this.x0 = 0; this.span = this.songBars; this.dirty = true; haptic(); } });
    this.el = h('div', { class: 'arr-map' }, h('div', { class: 'map-wrap' }, this.cv), h('div', { class: 'map-acts' }, this.status, this.fitBtn, this.back));
    this.songBars = Math.ceil(data.song.bars);
    this.x0 = 0; this.span = this.songBars;
    this.src = null; this.dirty = true; this.restarting = false;
    this.refs = data.refs.filter((r) => r.name !== 'HW002');
    this.rows();
    this._wire();
    const ro = new ResizeObserver(() => { this.dirty = true; });
    ro.observe(this.el);
    ctx.own(() => ro.disconnect());
    this.back.hidden = true;
  }

  rows() {
    const tracks = (this.e.manifest?.tracks ?? []).filter((t) => t.clips?.length && !t.muted && t.kind !== 'group' && t.kind !== 'return');
    this.tracks = tracks;
    this.layout = { ruler: 18, marks: 16, energy: 34, track: 9, ref: 11 };
    const L = this.layout;
    this.H = L.ruler + L.marks + L.energy + Math.max(1, tracks.length) * L.track + 6 + this.refs.length * L.ref + 4;
    this.cv.style.height = `${this.H}px`;
  }

  get ppb() { return (this.W - G - 6) / this.span; }
  X(bar) { return G + (bar - this.x0) * this.ppb; }
  barAt(px) { return this.x0 + (px - G) / this.ppb; }

  _wire() {
    const cv = this.cv;
    cv.style.touchAction = 'pan-y';
    const pts = new Map();
    let pinch = null, pan = null;
    const local = (e) => { const r = cv.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
    cv.addEventListener('pointerdown', (e) => {
      pts.set(e.pointerId, local(e));
      try { cv.setPointerCapture(e.pointerId); } catch { /* synthetic */ }
      if (pts.size === 2) {
        const [a, b] = [...pts.values()];
        pinch = { d: Math.abs(a.x - b.x) || 1, span: this.span, mid: this.barAt((a.x + b.x) / 2), midX: (a.x + b.x) / 2 };
        pan = null;
      } else if (pts.size === 1) pan = { x: local(e).x, lx: local(e).x, moved: false, t0: performance.now() };
    });
    cv.addEventListener('pointermove', (e) => {
      if (!pts.has(e.pointerId)) return;
      pts.set(e.pointerId, local(e));
      if (pinch && pts.size >= 2) {
        const [a, b] = [...pts.values()];
        const d = Math.abs(a.x - b.x) || 1;
        this.span = clamp(pinch.span * pinch.d / d, 8, this.maxBars());
        const mx = (a.x + b.x) / 2;
        this.x0 = clamp(pinch.mid - (mx - G) / this.ppb, -2, this.maxBars() - this.span + 2);
        this.dirty = true;
        return;
      }
      if (pan) {
        const x = local(e).x;
        if (!pan.moved && Math.abs(x - pan.x) < 6) return;
        pan.moved = true;
        this.x0 = clamp(this.x0 - (x - pan.lx) / this.ppb, -2, Math.max(-2, this.maxBars() - this.span + 2));
        pan.lx = x; this.dirty = true;
      }
    });
    const up = (e) => {
      const p = pts.get(e.pointerId);
      pts.delete(e.pointerId);
      if (pinch) { if (pts.size < 2) pinch = null; pan = null; return; }
      if (pan && !pan.moved && e.type === 'pointerup' && p) {
        const bar = Math.floor(this.barAt(p.x));
        if (bar >= 0 && bar < this.songBars) this.playSong(bar);
      }
      pan = null;
    };
    cv.addEventListener('pointerup', up);
    cv.addEventListener('pointercancel', up);
  }

  maxBars() { return Math.max(this.songBars, ...this.refs.map((r) => r.bars)) + 4; }

  get playing() { return this.arr.mode === 'song'; }

  /** The whole song from `bar` (0-based), on the engine's clock: the transport shows the song's bar. */
  async playSong(bar) {
    const e = this.e;
    if (!e.ctx || !e.manifest) { toast('Start the engine first'); return; }
    if (!e.manifest.full) { toast('No whole song in this build of the lab\'s audio'); return; }
    haptic(true);
    this.status.textContent = 'Loading the whole song…';
    const buf = e.buffers.get('full') ?? await this.lanes.loadFull();
    if (!buf || this.dead) { this.status.textContent = 'The whole song did not load'; return; }
    this.killSource();
    this.arr.mode = 'song';
    e.stems.enabled = false;
    this.restarting = true;
    if (e.playing) e.stop();
    this.restarting = false;
    this.lanes.stopAll();
    await e.start(bar);
    if (this.dead || this.arr.mode !== 'song') return;
    const when = e.timeOf(bar * 16), now = e.ctx.currentTime;
    const src = e.ctx.createBufferSource();
    src.buffer = buf;
    src.connect(e.bus('arr-song').input);
    src.start(Math.max(when, now), bar * e.barSeconds + Math.max(0, now - when));
    this.src = src;
    this.status.textContent = `The whole song from bar ${bar + 1}`;
    this.back.hidden = false;
    this.dirty = true;
  }

  killSource() {
    if (this.src) { try { this.src.stop(); } catch { /* ended */ } try { this.src.disconnect(); } catch { /* gone */ } }
    this.src = null;
  }

  /** Stop the song and give the stems back (and stop the transport if `transport`). */
  stopSong(transport = false) {
    const was = this.arr.mode === 'song';
    this.killSource();
    if (!was) return;
    this.arr.mode = 'short';
    this.e.stems.enabled = true;
    this.back.hidden = true;
    this.status.textContent = 'Tap a bar: the whole song from there';
    if (transport && this.e.playing) this.e.stop();
    this.arr.apply();
    this.dirty = true;
  }

  /** The engine stopped (the transport, or the song's end). */
  onEngineStop() { if (!this.restarting) this.stopSong(false); }

  onBar(bar) {
    if (this.arr.mode === 'song' && bar >= this.songBars) setTimeout(() => { if (this.arr.mode === 'song') this.stopSong(true); }, 50);
  }

  // --- drawing ---------------------------------------------------------------------------------------------------
  draw() {
    const r = this.el.getBoundingClientRect();
    if (!r.width) return;
    if (this.tracks.length === 0 && this.e.manifest?.tracks?.length) { this.rows(); this.dirty = true; }
    const dpr = Math.min(3, devicePixelRatio || 1);
    const W = Math.round(r.width);
    if (this.cv.width !== Math.round(W * dpr) || this.cv.height !== Math.round(this.H * dpr)) {
      this.cv.width = Math.round(W * dpr); this.cv.height = Math.round(this.H * dpr); this.dirty = true;
    }
    const playing = this.arr.mode === 'song' && this.e.playing;
    if (!this.dirty && !playing) return;
    this.dirty = false;
    this.W = W;
    const g = this.cv.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.paint(g, playing ? this.e.position().t : null);
  }

  paint(g, t) {
    const W = this.W, H = this.H, L = this.layout, d = this.data;
    g.fillStyle = '#0b0c0e'; g.fillRect(0, 0, W, H);
    g.save(); g.beginPath(); g.rect(G, 0, W - G, H); g.clip();
    // grid and ruler
    const stepBars = this.span > 120 ? 16 : this.span > 48 ? 8 : this.span > 20 ? 4 : 1;
    g.font = '600 8.5px ui-monospace, SF Mono, monospace'; g.textBaseline = 'middle'; g.textAlign = 'left';
    for (let b = Math.max(0, Math.floor(this.x0 / stepBars) * stepBars); b < this.x0 + this.span + 1; b += stepBars) {
      const x = Math.round(this.X(b)) + 0.5;
      g.strokeStyle = b % 16 === 0 ? 'rgba(255,255,255,0.1)' : 'rgba(255,255,255,0.045)';
      g.beginPath(); g.moveTo(x, L.ruler - 4); g.lineTo(x, H); g.stroke();
      if (b % (stepBars * (this.ppb * stepBars < 26 ? 2 : 1)) === 0) { g.fillStyle = '#a4a19a'; g.fillText(String(b + 1), x + 2, L.ruler / 2); }
    }
    let y = L.ruler;
    // marks: the break, the stems, the Short
    const mark = (a, b, col, text, fill) => {
      const x0 = this.X(a - 1), x1 = this.X(b);
      g.fillStyle = fill; g.fillRect(x0, y + 2, x1 - x0, L.marks - 4);
      g.strokeStyle = col; g.lineWidth = 1; g.strokeRect(x0 + 0.5, y + 2.5, x1 - x0 - 1, L.marks - 5);
      g.fillStyle = col; g.font = '700 8px ui-monospace, monospace';
      const tw = g.measureText(text).width;
      if (x1 - x0 > tw + 6) g.fillText(text, x0 + 3, y + L.marks / 2);
      else g.fillText(text, x1 + 3, y + L.marks / 2);
    };
    mark(d.song.break[0], d.song.break[1], 'rgb(255,90,31)', 'BREAK', 'rgba(255,90,31,0.2)');
    mark(d.song.short[0], d.song.short[1], 'rgb(89,199,255)', 'SHORT', 'rgba(89,199,255,0.18)');
    // the break and the Short as columns behind everything
    g.fillStyle = 'rgba(255,90,31,0.06)'; g.fillRect(this.X(d.song.break[0] - 1), y + L.marks, this.X(d.song.break[1]) - this.X(d.song.break[0] - 1), H);
    g.fillStyle = 'rgba(89,199,255,0.07)'; g.fillRect(this.X(d.song.short[0] - 1), y + L.marks, this.X(d.song.short[1]) - this.X(d.song.short[0] - 1), H);
    y += L.marks;
    // energy: per-bar loudness of the whole song
    const vals = d.song.lufs.filter((x) => x > -60).sort((a, b) => a - b);
    const hi = Math.ceil(vals.at(-1) ?? -6) + 1, lo = Math.min(Math.floor(vals[Math.floor(vals.length * 0.03)] ?? -30) - 1, hi - 8);
    const Y = (l) => y + L.energy - 3 - clamp((l - lo) / (hi - lo)) * (L.energy - 6);
    const grad = g.createLinearGradient(0, y, 0, y + L.energy);
    grad.addColorStop(0, 'rgba(255,181,71,0.45)'); grad.addColorStop(1, 'rgba(255,181,71,0.03)');
    g.beginPath(); g.moveTo(this.X(0), y + L.energy);
    d.song.lufs.forEach((l, i) => { g.lineTo(this.X(i), Y(l)); g.lineTo(this.X(i + 1), Y(l)); });
    g.lineTo(this.X(d.song.lufs.length), y + L.energy); g.closePath(); g.fillStyle = grad; g.fill();
    g.strokeStyle = '#ffb547'; g.lineWidth = 1.2; g.beginPath();
    d.song.lufs.forEach((l, i) => { if (i) g.lineTo(this.X(i), Y(l)); else g.moveTo(this.X(0), Y(l)); g.lineTo(this.X(i + 1), Y(l)); });
    g.stroke();
    y += L.energy;
    // tracks
    for (const t of this.tracks) {
      const col = GROUP_COL[t.group] ?? '#a4a19a';
      g.fillStyle = 'rgba(255,255,255,0.025)'; g.fillRect(G, y + 1, W - G, L.track - 2);
      g.fillStyle = col;
      for (const [a, b] of t.clips) {
        const x0 = this.X(a), x1 = this.X(b);
        if (x1 < G || x0 > W) continue;
        g.globalAlpha = 0.85; g.fillRect(x0, y + 1.5, Math.max(1, x1 - x0 - (this.ppb > 4 ? 0.6 : 0)), L.track - 3); g.globalAlpha = 1;
      }
      y += L.track;
    }
    y += 6;
    // the references: loudness per bar as a strip, breaks outlined
    for (const r of this.refs) {
      const sorted = [...r.lufs].sort((a, b) => a - b);
      const top = sorted[Math.floor(sorted.length * 0.9)] ?? -10;
      for (let i = 0; i < r.lufs.length; i++) {
        const x0 = this.X(i), x1 = this.X(i + 1);
        if (x1 < G || x0 > W) continue;
        const l = clamp((r.lufs[i] - (top - 14)) / 14);
        g.fillStyle = `rgba(233,231,226,${(0.05 + 0.55 * l).toFixed(3)})`;
        g.fillRect(x0, y + 2, Math.max(0.6, x1 - x0), L.ref - 4);
      }
      g.strokeStyle = '#ff5a1f'; g.lineWidth = 1;
      for (const [a, b] of r.breaks) if (b > a) g.strokeRect(this.X(a - 1) + 0.5, y + 1.5, this.X(b) - this.X(a - 1) - 1, L.ref - 3);
      y += L.ref;
    }
    // the song's playhead
    if (t != null) {
      const x = this.X(t);
      g.strokeStyle = '#ff5a1f'; g.lineWidth = 2; g.shadowColor = '#ff5a1f'; g.shadowBlur = 6;
      g.beginPath(); g.moveTo(x, L.ruler); g.lineTo(x, H); g.stroke(); g.shadowBlur = 0;
    }
    g.restore();
    // labels
    g.fillStyle = '#0b0c0e'; g.fillRect(0, 0, G, H);
    g.font = '600 8px ui-monospace, SF Mono, monospace'; g.textAlign = 'right'; g.textBaseline = 'middle';
    let yy = L.ruler + L.marks;
    g.fillStyle = '#ffb547'; g.fillText('LUFS', G - 5, yy + L.energy / 2); yy += L.energy;
    for (const tr of this.tracks) { g.fillStyle = GROUP_COL[tr.group] ?? '#a4a19a'; g.fillText(short(tr.name), G - 5, yy + L.track / 2); yy += L.track; }
    yy += 6;
    for (const r of this.refs) { g.fillStyle = '#a4a19a'; g.fillText(r.name, G - 5, yy + L.ref / 2); yy += L.ref; }
    if (!this.tracks.length) { g.fillStyle = '#6d6a65'; g.textAlign = 'left'; g.fillText('The set\'s tracks appear once the engine has started', G + 6, L.ruler + L.marks + L.energy + 8); }
  }
}
