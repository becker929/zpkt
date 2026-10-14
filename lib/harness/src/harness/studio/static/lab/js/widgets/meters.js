// Meters. Each takes a source: 'master' (default), a bus name ('kick', 'perc', 'sfx', or any bus a surface made), a
// Channel, or an AnalyserNode. They draw only while on screen, share the lab's one frame loop, and wait quietly for
// the audio to start.
//
// vu(ctx, source, {width, label, ref}) -> element
//   A backlit VU meter: an amber scale from -20 to +3 VU, a red zone past 0, a needle with real VU ballistics
//   (300 ms to settle). `ref` is the dBFS RMS that reads 0 VU (default -9 on the master, -14 on a bus).
//
// ledLadder(ctx, source, {height, segments, label}) -> element
//   An LED ladder: peak in lit segments from -48 to 0 dBFS (green, amber from -18, red from -6), the RMS as a
//   brighter core, a peak-hold LED that falls after a second, a clip LED that latches red (tap it to clear).
//
// scope(ctx, source, {width, height, label}) -> element
//   An oscilloscope on a CRT: the waveform triggered on a rising zero crossing, phosphor persistence, scanlines.
//
// spectrum(ctx, source, {width, height, label, bars}) -> element
//   A mini spectrum on a log axis (20 Hz to 20 kHz) with falling peak caps, and the three places HW002 differs
//   from its references marked: the sub under 40 Hz, the mids around 2 kHz, the air near 10 kHz.

import { h } from '../ui.js';
import { analyserOf, fitCanvas, HEX, rgba, tick } from './kit.js';

function reader(ctx, source) {
  let an = null, buf = null, fbuf = null;
  return {
    get node() { an ??= analyserOf(ctx, source); return an; },
    time() {
      const a = this.node; if (!a) return null;
      if (!buf || buf.length !== a.fftSize) buf = new Float32Array(a.fftSize);
      a.getFloatTimeDomainData(buf); return buf;
    },
    freq() {
      const a = this.node; if (!a) return null;
      if (!fbuf || fbuf.length !== a.frequencyBinCount) fbuf = new Float32Array(a.frequencyBinCount);
      a.getFloatFrequencyData(fbuf); return fbuf;
    },
    rate() { return this.node?.context.sampleRate ?? 44100; },
  };
}

const levels = (buf) => {
  let sum = 0, peak = 0;
  for (let i = 0; i < buf.length; i++) { const x = buf[i]; sum += x * x; const a = x < 0 ? -x : x; if (a > peak) peak = a; }
  return { rms: 20 * Math.log10(Math.sqrt(sum / buf.length) + 1e-9), peak: 20 * Math.log10(peak + 1e-9) };
};

const nameOf = (source) => (typeof source === 'string' ? source : source?.name ?? 'in');

export function vu(ctx, source = 'master', { width = 200, label, ref = source === 'master' || !source ? -9 : -14 } = {}) {
  const rd = reader(ctx, source);
  const cv = h('canvas', { class: 'vu-cv' });
  const el = h('div', { class: 'w-vu', style: { '--w': `${width}px` } }, h('div', { class: 'vu-face' }, cv), h('div', { class: 'w-label', text: label ?? `VU ${nameOf(source)}` }));
  let vuv = -20;
  tick(ctx, (_t, dt) => {
    const buf = rd.time();
    const target = buf ? Math.max(-22, Math.min(5, levels(buf).rms - ref)) : -22;
    vuv += (target - vuv) * (1 - Math.exp(-dt / 0.065));
    draw();
  }, el);
  const toA = (db) => {                                       // a VU scale is not linear in dB: use its voltage
    const v = Math.pow(10, db / 20), v0 = Math.pow(10, -20 / 20), v1 = Math.pow(10, 3 / 20);
    return -0.82 + 1.64 * Math.max(0, Math.min(1.04, (v - v0) / (v1 - v0)));
  };
  function draw() {
    const { g, W, H, d } = fitCanvas(cv);
    g.clearRect(0, 0, W, H);
    const cx = W / 2, cy = H * 1.02, R = H * 0.86;
    // scale
    g.lineWidth = 1.2 * d; g.font = `600 ${8.5 * d}px ui-monospace, Menlo, monospace`; g.textAlign = 'center'; g.textBaseline = 'middle';
    for (const db of [-20, -10, -7, -5, -3, -2, -1, 0, 1, 2, 3]) {
      const a = toA(db) - Math.PI / 2;
      const red = db > 0;
      g.strokeStyle = red ? HEX.alarm : 'rgba(255,190,90,0.85)';
      g.beginPath(); g.moveTo(cx + Math.cos(a) * R, cy + Math.sin(a) * R); g.lineTo(cx + Math.cos(a) * (R - 7 * d), cy + Math.sin(a) * (R - 7 * d)); g.stroke();
      if ([-20, -10, -5, -3, 0, 3].includes(db)) {
        g.fillStyle = red || db === 0 ? HEX.alarm : 'rgba(255,190,90,0.9)';
        g.fillText(db > 0 ? `+${db}` : String(db), cx + Math.cos(a) * (R + 9 * d), cy + Math.sin(a) * (R + 9 * d));
      }
    }
    g.lineWidth = 2.5 * d;
    g.strokeStyle = 'rgba(255,181,71,0.55)';
    g.beginPath(); g.arc(cx, cy, R - 10 * d, toA(-20) - Math.PI / 2, toA(0) - Math.PI / 2); g.stroke();
    g.strokeStyle = 'rgba(255,46,77,0.8)';
    g.beginPath(); g.arc(cx, cy, R - 10 * d, toA(0) - Math.PI / 2, toA(3) - Math.PI / 2); g.stroke();
    g.fillStyle = 'rgba(255,181,71,0.55)'; g.font = `800 ${11 * d}px ui-monospace, Menlo, monospace`;
    g.fillText('VU', cx, cy - R * 0.42);
    // needle
    const a = toA(vuv) - Math.PI / 2;
    g.shadowColor = 'rgba(0,0,0,0.6)'; g.shadowBlur = 4 * d; g.shadowOffsetX = 2 * d;
    g.strokeStyle = '#f3efe6'; g.lineWidth = 1.6 * d;
    g.beginPath(); g.moveTo(cx, cy); g.lineTo(cx + Math.cos(a) * (R + 2 * d), cy + Math.sin(a) * (R + 2 * d)); g.stroke();
    g.shadowBlur = 0; g.shadowOffsetX = 0;
    g.fillStyle = '#16181b'; g.beginPath(); g.arc(cx, cy, 13 * d, 0, Math.PI * 2); g.fill();
  }
  return el;
}

export function ledLadder(ctx, source = 'master', { height = 180, segments = 24, label } = {}) {
  const rd = reader(ctx, source);
  const cv = h('canvas', { class: 'led-cv' });
  const clip = h('button', { type: 'button', class: 'led-clip', 'aria-label': 'Clip (tap to clear)' });
  const el = h('div', { class: 'w-led', style: { '--h': `${height}px` } }, clip, cv, h('div', { class: 'w-label', text: label ?? nameOf(source) }));
  let pk = -70, rms = -70, hold = -70, holdT = 0, clipped = false;
  clip.addEventListener('click', () => { clipped = false; clip.classList.remove('is-on'); });
  const LO = -48;
  const colourAt = (db) => (db >= -6 ? HEX.alarm : db >= -18 ? HEX.lcd : '#57e38a');
  tick(ctx, (t, dt) => {
    const buf = rd.time();
    const l = buf ? levels(buf) : { rms: -70, peak: -70 };
    pk = l.peak > pk ? l.peak : pk - dt * 26;                   // fast attack, ~26 dB/s fall
    rms += (l.rms - rms) * (1 - Math.exp(-dt / 0.08));
    if (l.peak >= hold || t - holdT > 1000) { hold = l.peak; holdT = t; }
    if (l.peak > -0.1 && !clipped) { clipped = true; clip.classList.add('is-on'); }
    draw();
  }, el);
  function draw() {
    const { g, W, H, d } = fitCanvas(cv);
    g.clearRect(0, 0, W, H);
    const gap = 2 * d, sh = (H - gap * (segments - 1)) / segments;
    for (let i = 0; i < segments; i++) {
      const db = LO + (-LO) * ((i + 1) / segments);
      const y = H - (i + 1) * sh - i * gap;
      const lit = pk >= db - (-LO / segments);
      const core = rms >= db - (-LO / segments);
      const isHold = Math.abs(hold - db) < (-LO / segments) / 2 + 0.01;
      const c = colourAt(db);
      g.fillStyle = lit || isHold ? c : rgba(c, 0.09);
      if (lit && !core) g.globalAlpha = 0.55;
      g.fillRect(0, y, W, sh);
      g.globalAlpha = 1;
      if (lit) { g.fillStyle = 'rgba(255,255,255,0.18)'; g.fillRect(0, y, W, Math.max(1, sh * 0.3)); }
    }
  }
  return el;
}

export function scope(ctx, source = 'master', { width = 260, height = 110, label } = {}) {
  const rd = reader(ctx, source);
  const cv = h('canvas', { class: 'sc-cv' });
  const el = h('div', { class: 'w-scope', style: { '--w': `${width}px`, '--h': `${height}px` } },
    h('div', { class: 'sc-crt' }, cv, h('i', { class: 'sc-lines' })), h('div', { class: 'w-label', text: label ?? `scope~ ${nameOf(source)}` }));
  tick(ctx, () => {
    const { g, W, H, d } = fitCanvas(cv);
    g.fillStyle = 'rgba(4,8,6,0.55)';
    g.fillRect(0, 0, W, H);
    g.strokeStyle = 'rgba(198,255,61,0.07)'; g.lineWidth = d;
    g.beginPath();
    for (let i = 1; i < 8; i++) { g.moveTo((W * i) / 8, 0); g.lineTo((W * i) / 8, H); }
    for (let i = 1; i < 4; i++) { g.moveTo(0, (H * i) / 4); g.lineTo(W, (H * i) / 4); }
    g.stroke();
    const buf = rd.time();
    if (!buf) return;
    const span = Math.min(buf.length >> 1, 1400);
    let start = 0;
    for (let i = 1; i < buf.length - span; i++) if (buf[i - 1] < 0 && buf[i] >= 0) { start = i; break; }
    g.shadowColor = HEX.acid; g.shadowBlur = 8 * d;
    g.strokeStyle = 'rgba(214,255,120,0.95)'; g.lineWidth = 1.6 * d;
    g.beginPath();
    for (let i = 0; i < span; i += 2) {
      const x = (i / span) * W, y = H / 2 - buf[start + i] * H * 0.46;
      if (i) g.lineTo(x, y); else g.moveTo(x, y);
    }
    g.stroke();
    g.shadowBlur = 0;
  }, el);
  return el;
}

export function spectrum(ctx, source = 'master', { width = 260, height = 110, label, bars = 44 } = {}) {
  const rd = reader(ctx, source);
  const cv = h('canvas', { class: 'sp-cv' });
  const el = h('div', { class: 'w-spec', style: { '--w': `${width}px`, '--h': `${height}px` } },
    h('div', { class: 'sp-box' }, cv), h('div', { class: 'w-label', text: label ?? `spectrum~ ${nameOf(source)}` }));
  const lv = new Float32Array(bars).fill(-100), caps = new Float32Array(bars).fill(-100);
  const F0 = 20, F1 = 20000, LO = -96, HI = -12;
  const fx = (f) => Math.log(f / F0) / Math.log(F1 / F0);
  tick(ctx, (_t, dt) => {
    const fb = rd.freq();
    const sr = rd.rate();
    if (fb) {
      const binHz = sr / 2 / fb.length;
      for (let b = 0; b < bars; b++) {
        const f0 = F0 * Math.pow(F1 / F0, b / bars), f1 = F0 * Math.pow(F1 / F0, (b + 1) / bars);
        const i0 = Math.max(1, Math.floor(f0 / binHz)), i1 = Math.max(i0 + 1, Math.ceil(f1 / binHz));
        let m = -140;
        for (let i = i0; i < i1 && i < fb.length; i++) if (fb[i] > m) m = fb[i];
        lv[b] = m > lv[b] ? m : lv[b] - dt * 60;
        caps[b] = lv[b] > caps[b] ? lv[b] : caps[b] - dt * 18;
      }
    }
    draw();
  }, el);
  function draw() {
    const { g, W, H, d } = fitCanvas(cv);
    g.clearRect(0, 0, W, H);
    const bw = W / bars;
    const grd = g.createLinearGradient(0, H, 0, 0);
    grd.addColorStop(0, '#2a3d10'); grd.addColorStop(0.6, HEX.acid); grd.addColorStop(1, HEX.lcd);
    // the three gaps
    g.font = `700 ${7.5 * d}px ui-monospace, Menlo, monospace`; g.textAlign = 'center'; g.textBaseline = 'top';
    for (const [lo, hi, name] of [[25, 40, 'SUB'], [1000, 3200, 'MIDS'], [8000, 12500, 'AIR']]) {
      const x0 = fx(lo) * W, x1 = fx(hi) * W;
      g.fillStyle = 'rgba(89,199,255,0.07)'; g.fillRect(x0, 0, x1 - x0, H);
      g.fillStyle = 'rgba(89,199,255,0.6)'; g.fillText(name, (x0 + x1) / 2, 3 * d);
    }
    for (let b = 0; b < bars; b++) {
      const y = H - Math.max(0, Math.min(1, (lv[b] - LO) / (HI - LO))) * H;
      g.fillStyle = grd;
      g.fillRect(b * bw + 0.5 * d, y, bw - 1.2 * d, H - y);
      const cy = H - Math.max(0, Math.min(1, (caps[b] - LO) / (HI - LO))) * H;
      g.fillStyle = HEX.text; g.fillRect(b * bw + 0.5 * d, cy - 1.5 * d, bw - 1.2 * d, 1.5 * d);
    }
  }
  return el;
}
