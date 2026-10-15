// Kraft, newsprint, cork, tin and the rest: the Rummage's materials, and its placeholder art, all drawn by code.
// The art pack (art/manifest.json) replaces the placeholders as its files arrive; until then (or for good, if a file
// is missing) each thing is a paper cut-out of the same size: a shape with a white cut edge, a material fill, a few
// ink lines. Everything is drawn in world units with the top left at (0, 0), so a caller can draw it at any scale.
//
//   material(name)                       a seamless 512 px texture canvas (drawn at half size: 256 world units)
//   pattern(g, name, scale, angle)       that texture as a fill for g
//   PAINT.prop(g, w, h, id) / machine(g, w, h, part) / gramophone / plinth / portal / artifact / hero / sign
//   decal(g, d)                          one small thing lying on the ground (a scrap, a button, a stamp ...)
import { hash, rng } from '../concepts/model.js';

export const C = {
  paper: '#fbf6ea', cream: '#efe4c9', kraft: '#b38a5a', ink: '#2b241c', teal: '#3e8580', tealD: '#2a5f5b',
  rust: '#b0532c', rustD: '#7a371b', mustard: '#d9a43a', brass: '#c99b47', brassD: '#8a6427', tin: '#a9b0b1',
  tinD: '#6f7779', wood: '#9a6a3f', woodD: '#5f3d22', red: '#c4432e', navy: '#33445c', pink: '#d99a8c',
  green: '#6e8a4c', black: '#221d18', gold: '#f1b64a',
};
export const FONT = "'American Typewriter', 'Courier New', ui-monospace, monospace";
const SIZE = 512;

// --- materials ---
const mats = new Map();
function canvas(w, h) { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; }
/** Draws fn at (x, y) and at its wrapped copies, so the texture tiles without a seam. */
function wrap(fn, x, y, reach = 40) {
  for (const dx of [-SIZE, 0, SIZE]) for (const dy of [-SIZE, 0, SIZE]) {
    if ((dx && Math.abs(x + dx - SIZE / 2) > SIZE / 2 + reach) || (dy && Math.abs(y + dy - SIZE / 2) > SIZE / 2 + reach)) continue;
    fn(x + dx, y + dy);
  }
}
function fibres(g, r, n, light, dark, len = 12, flat = 0) {
  g.lineCap = 'round';
  for (let i = 0; i < n; i++) {
    const x = r() * SIZE, y = r() * SIZE, a = (r() - 0.5) * Math.PI * (1 - flat) + (flat ? 0 : r() * Math.PI), l = 3 + r() * len;
    g.strokeStyle = r() < 0.5 ? light : dark; g.lineWidth = 0.6 + r() * 1.1;
    wrap((X, Y) => { g.beginPath(); g.moveTo(X, Y); g.lineTo(X + Math.cos(a) * l, Y + Math.sin(a) * l); g.stroke(); }, x, y);
  }
}
function blotches(g, r, n, colors, size = 60) {
  for (let i = 0; i < n; i++) {
    const x = r() * SIZE, y = r() * SIZE, rad = size * (0.4 + r());
    wrap((X, Y) => {
      const gr = g.createRadialGradient(X, Y, 0, X, Y, rad);
      gr.addColorStop(0, colors[i % colors.length]); gr.addColorStop(1, 'rgba(0,0,0,0)');
      g.fillStyle = gr; g.fillRect(X - rad, Y - rad, rad * 2, rad * 2);
    }, x, y, rad);
  }
}
function dots(g, r, n, colors, r0, r1) {
  for (let i = 0; i < n; i++) {
    const x = r() * SIZE, y = r() * SIZE, rad = r0 + r() * (r1 - r0);
    g.fillStyle = colors[Math.floor(r() * colors.length)];
    wrap((X, Y) => { g.beginPath(); g.arc(X, Y, rad, 0, 7); g.fill(); }, x, y, 4);
  }
}
const MATERIALS = {
  kraft(g, r) {
    g.fillStyle = '#b48b5b'; g.fillRect(0, 0, SIZE, SIZE);
    blotches(g, r, 26, ['rgba(255,230,190,0.10)', 'rgba(80,50,20,0.10)'], 70);
    fibres(g, r, 2600, 'rgba(255,236,200,0.20)', 'rgba(84,56,28,0.18)');
    dots(g, r, 300, ['rgba(70,45,20,0.35)', 'rgba(255,240,210,0.3)'], 0.4, 1.3);
  },
  cream(g, r) {
    g.fillStyle = '#efe4c8'; g.fillRect(0, 0, SIZE, SIZE);
    blotches(g, r, 14, ['rgba(190,150,90,0.10)', 'rgba(255,255,255,0.14)'], 80);
    fibres(g, r, 1400, 'rgba(255,255,255,0.35)', 'rgba(150,120,80,0.14)', 10);
  },
  newsprint(g, r) {
    g.fillStyle = '#e3dbc5'; g.fillRect(0, 0, SIZE, SIZE);
    blotches(g, r, 10, ['rgba(180,150,90,0.12)'], 90);
    g.fillStyle = 'rgba(45,40,34,0.42)';
    for (const col of [12, 268]) {
      for (let y = 10; y < SIZE - 8; y += 9) {
        if (r() < 0.05) { g.fillRect(col, y, 120 + r() * 100, 6); y += 6; continue; }
        for (let x = col; x < col + 232;) { const w = 5 + r() * 24; if (x + w > col + 232) break; g.fillRect(x, y, w, 3.1); x += w + 3.5; }
      }
    }
    fibres(g, r, 500, 'rgba(255,255,255,0.25)', 'rgba(120,100,70,0.12)', 8);
  },
  map(g, r) {
    g.fillStyle = '#e8d6aa'; g.fillRect(0, 0, SIZE, SIZE);
    blotches(g, r, 12, ['rgba(170,120,60,0.14)', 'rgba(255,250,230,0.15)'], 90);
    g.strokeStyle = 'rgba(120,80,40,0.22)'; g.lineWidth = 1;
    for (let k = 0; k < SIZE; k += 64) { g.beginPath(); g.moveTo(k + 0.5, 0); g.lineTo(k + 0.5, SIZE); g.moveTo(0, k + 0.5); g.lineTo(SIZE, k + 0.5); g.stroke(); }
    g.strokeStyle = 'rgba(60,100,140,0.45)'; g.lineWidth = 1.6;
    for (let k = 0; k < 3; k++) {
      const y0 = r() * SIZE;
      wrap((X, Y) => { g.beginPath(); for (let x = 0; x <= SIZE; x += 16) g.lineTo(X - SIZE / 2 + x, Y + Math.sin(x / 50 + k) * 20); g.stroke(); }, SIZE / 2, y0, 30);
    }
    g.strokeStyle = 'rgba(140,90,40,0.28)'; g.lineWidth = 1;
    for (let k = 0; k < 7; k++) {
      const x = r() * SIZE, y = r() * SIZE;
      for (let q = 1; q < 4; q++) wrap((X, Y) => { g.beginPath(); g.ellipse(X, Y, q * 11, q * 7, k, 0, 7); g.stroke(); }, x, y, 50);
    }
  },
  cork(g, r) {
    g.fillStyle = '#bb8653'; g.fillRect(0, 0, SIZE, SIZE);
    dots(g, r, 3800, ['rgba(120,74,34,0.75)', 'rgba(214,168,110,0.7)', 'rgba(90,55,25,0.6)'], 0.5, 2.3);
  },
  fabric(g, r) {
    g.fillStyle = '#6d899f'; g.fillRect(0, 0, SIZE, SIZE);
    for (let y = 0; y < SIZE; y += 2) { g.fillStyle = y % 4 ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.07)'; g.fillRect(0, y, SIZE, 1); }
    for (let x = 0; x < SIZE; x += 2) { g.fillStyle = x % 4 ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)'; g.fillRect(x, 0, 1, SIZE); }
    for (let x = 8; x < SIZE; x += 32) { g.fillStyle = 'rgba(240,230,205,0.55)'; g.fillRect(x, 0, 3, SIZE); }
    fibres(g, r, 300, 'rgba(255,255,255,0.18)', 'rgba(20,30,40,0.15)', 14);
  },
  tin(g, r) {
    for (let x = 0; x < SIZE; x += 32) {
      const gr = g.createLinearGradient(x, 0, x + 32, 0);
      gr.addColorStop(0, '#8d9597'); gr.addColorStop(0.45, '#c9cfcf'); gr.addColorStop(1, '#868e90');
      g.fillStyle = gr; g.fillRect(x, 0, 32, SIZE);
    }
    blotches(g, r, 16, ['rgba(150,75,30,0.35)', 'rgba(110,60,25,0.25)'], 40);
    fibres(g, r, 200, 'rgba(255,255,255,0.35)', 'rgba(40,40,40,0.2)', 20);
  },
  wood(g, r) {
    g.fillStyle = '#9c6b3f'; g.fillRect(0, 0, SIZE, SIZE);
    for (let y = 0; y < SIZE; y += 5 + r() * 9) {
      g.strokeStyle = r() < 0.5 ? 'rgba(70,40,18,0.3)' : 'rgba(230,180,120,0.18)'; g.lineWidth = 0.8 + r() * 1.6;
      const ph = r() * 6, amp = 1 + r() * 3;
      g.beginPath();
      for (let x = 0; x <= SIZE; x += 8) g.lineTo(x, y + Math.sin((x / SIZE) * Math.PI * 4 + ph) * amp);
      g.stroke();
    }
  },
  card(g, r) {
    g.fillStyle = '#958b7c'; g.fillRect(0, 0, SIZE, SIZE);
    fibres(g, r, 1600, 'rgba(255,255,255,0.14)', 'rgba(40,30,20,0.14)', 8);
    dots(g, r, 200, ['rgba(255,255,255,0.3)', 'rgba(30,20,10,0.3)'], 0.4, 1.2);
  },
  table(g, r) {
    g.fillStyle = '#2a1d14'; g.fillRect(0, 0, SIZE, SIZE);
    for (let y = 0; y < SIZE; y += 4 + r() * 10) {
      g.strokeStyle = r() < 0.6 ? 'rgba(0,0,0,0.35)' : 'rgba(120,80,45,0.16)'; g.lineWidth = 1 + r() * 2;
      const ph = r() * 6;
      g.beginPath();
      for (let x = 0; x <= SIZE; x += 8) g.lineTo(x, y + Math.sin((x / SIZE) * Math.PI * 2 + ph) * 3);
      g.stroke();
    }
  },
};
/** A seamless texture: a canvas the art pack's ground image replaces, if it has one by that name. */
const STAND_IN = { 'art:ground-a': 'kraft', 'art:ground-b': 'cork', 'art:ground-c': 'map' };
export function material(name) {
  let c = mats.get(name);
  if (!c && name.startsWith('art:')) return material(STAND_IN[name] ?? 'kraft');   // its image is on its way
  if (!c) {
    c = canvas(SIZE, SIZE);
    (MATERIALS[name] ?? MATERIALS.cream)(c.getContext('2d'), rng(hash(name)));
    mats.set(name, c);
  }
  return c;
}
/** Replaces a material with an image (the art pack's ground, its path strip). */
export function setMaterial(name, img) { mats.set(name, img); }
/** A material as a fill: `scale` world units per texture pixel, turned by `angle`. */
export function pattern(g, name, scale = 0.5, angle = 0, ox = 0, oy = 0) {
  const p = g.createPattern(material(name), 'repeat');
  try { p.setTransform(new DOMMatrix().translateSelf(ox, oy).rotateSelf((angle * 180) / Math.PI).scaleSelf(scale)); } catch { /* an old engine: unscaled */ }
  return p;
}

// --- drawing helpers, in world units ---
const poly = (g, pts) => { g.beginPath(); pts.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.closePath(); };
function rrect(g, x, y, w, h, r) { g.beginPath(); g.roundRect ? g.roundRect(x, y, w, h, r) : g.rect(x, y, w, h); }
function ell(g, x, y, rx, ry, a = 0) { g.beginPath(); g.ellipse(x, y, Math.max(0.1, rx), Math.max(0.1, ry), a, 0, Math.PI * 2); }
/** The cut-out look: the shape just traced gets a white paper edge outside, then its fill. */
function cut(g, fill, edge = 2.6) {
  g.save();
  g.lineJoin = 'round'; g.strokeStyle = C.paper; g.lineWidth = edge * 2; g.stroke();
  g.fillStyle = fill; g.fill();
  g.restore();
}
function lin(g, x0, y0, x1, y1, stops) {
  const gr = g.createLinearGradient(x0, y0, x1, y1);
  stops.forEach((c, i) => gr.addColorStop(i / (stops.length - 1), c));
  return gr;
}
function ink(g, w = 1.2, c = 'rgba(40,30,20,0.55)') { g.strokeStyle = c; g.lineWidth = w; g.lineCap = 'round'; g.lineJoin = 'round'; }
function line(g, pts) { g.beginPath(); pts.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.stroke(); }
/** A cream tag with typed words on it. */
export function tag(g, x, y, text, size = 9, rot = 0, fill = C.cream) {
  g.save();
  g.translate(x, y); g.rotate(rot);
  g.font = `600 ${size}px ${FONT}`;
  const w = g.measureText(text).width + size * 1.2, h = size * 1.7;
  rrect(g, -w / 2, -h / 2, w, h, 1.5);
  g.shadowColor = 'rgba(40,25,10,0.3)'; g.shadowBlur = 2; g.shadowOffsetY = 1;
  cut(g, fill, 1.2);
  g.shadowColor = 'transparent';
  g.fillStyle = C.ink; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(text, 0, 0.5);
  g.restore();
}
/** A shine: a soft white streak down a curved surface. */
function shine(g, x, y, w, h, a = 0.35) {
  g.fillStyle = lin(g, x, 0, x + w, 0, [`rgba(255,255,255,0)`, `rgba(255,255,255,${a})`, 'rgba(255,255,255,0)']);
  g.fillRect(x, y, w, h);
}

// --- props ---
const PROPS = {
  teapot(g, w, h) {
    ink(g, 8, C.paper); g.beginPath(); g.arc(w * 0.18, h * 0.58, w * 0.13, Math.PI * 0.5, Math.PI * 1.5); g.stroke();
    ink(g, 5, C.tealD); g.stroke();
    poly(g, [[w * 0.74, h * 0.62], [w * 0.97, h * 0.3], [w * 0.92, h * 0.27], [w * 0.7, h * 0.48]]); cut(g, C.teal);
    ell(g, w * 0.48, h * 0.63, w * 0.34, h * 0.3); cut(g, lin(g, w * 0.14, 0, w * 0.82, 0, ['#5aa39d', C.teal, C.tealD]));
    g.save(); ell(g, w * 0.48, h * 0.63, w * 0.34, h * 0.3); g.clip();
    g.fillStyle = C.cream; g.fillRect(0, h * 0.58, w, h * 0.09);
    g.fillStyle = C.red; for (let k = 0; k < 6; k++) { ell(g, w * (0.2 + k * 0.11), h * 0.625, 3.2, 3.2); g.fill(); }
    shine(g, w * 0.26, h * 0.36, w * 0.1, h * 0.5);
    g.restore();
    ell(g, w * 0.48, h * 0.35, w * 0.21, h * 0.06); cut(g, C.tealD);
    ell(g, w * 0.48, h * 0.27, 5, 5); cut(g, C.brass);
    ell(g, w * 0.48, h * 0.93, w * 0.22, h * 0.035); g.fillStyle = C.tealD; g.fill();
  },
  birdcage(g, w, h) {
    g.beginPath(); g.moveTo(w * 0.12, h * 0.88); g.lineTo(w * 0.12, h * 0.4); g.quadraticCurveTo(w * 0.12, h * 0.1, w * 0.5, h * 0.08);
    g.quadraticCurveTo(w * 0.88, h * 0.1, w * 0.88, h * 0.4); g.lineTo(w * 0.88, h * 0.88); g.closePath();
    cut(g, 'rgba(240,228,200,0.35)');
    poly(g, [[w * 0.42, h * 0.62], [w * 0.62, h * 0.55], [w * 0.66, h * 0.6], [w * 0.5, h * 0.7], [w * 0.36, h * 0.68]]); cut(g, C.mustard, 1.6);
    ink(g, 2.2, C.brassD);
    for (let k = 1; k < 8; k++) { const x = w * (0.12 + k * 0.095); line(g, [[x, h * 0.88], [x, h * 0.3], [w * 0.5, h * 0.09]]); }
    ink(g, 3, C.brass); line(g, [[w * 0.12, h * 0.4], [w * 0.88, h * 0.4]]);
    rrect(g, w * 0.06, h * 0.86, w * 0.88, h * 0.1, 3); cut(g, lin(g, 0, 0, w, 0, [C.brassD, C.brass, C.brassD]));
    ink(g, 3, C.brass); g.beginPath(); g.arc(w * 0.5, h * 0.05, 6, 0, 7); g.stroke();
  },
  suitcase(g, w, h) {
    ink(g, 9, C.paper); g.beginPath(); g.arc(w * 0.5, h * 0.32, w * 0.12, Math.PI, 0); g.stroke();
    ink(g, 5, C.woodD); g.stroke();
    rrect(g, w * 0.05, h * 0.3, w * 0.9, h * 0.66, 9); cut(g, lin(g, 0, h * 0.3, 0, h, ['#a4572f', '#86431f']));
    g.fillStyle = 'rgba(60,30,10,0.55)'; g.fillRect(w * 0.24, h * 0.3, 7, h * 0.66); g.fillRect(w * 0.7, h * 0.3, 7, h * 0.66);
    rrect(g, w * 0.36, h * 0.46, w * 0.26, h * 0.2, 3); cut(g, C.cream, 1.4);
    ell(g, w * 0.82, h * 0.78, w * 0.08, w * 0.08); cut(g, C.teal, 1.4);
    rrect(g, w * 0.1, h * 0.72, w * 0.16, h * 0.12, 2); cut(g, C.mustard, 1.4);
    ink(g, 1); g.setLineDash([3, 3]); rrect(g, w * 0.09, h * 0.34, w * 0.82, h * 0.58, 6); g.stroke(); g.setLineDash([]);
  },
  clock(g, w, h) {
    rrect(g, w * 0.18, h * 0.12, w * 0.64, h * 0.84, 6); cut(g, lin(g, w * 0.18, 0, w * 0.82, 0, [C.woodD, C.wood, C.woodD]));
    g.beginPath(); g.moveTo(w * 0.12, h * 0.16); g.quadraticCurveTo(w * 0.5, -h * 0.02, w * 0.88, h * 0.16); g.closePath(); cut(g, C.woodD);
    ell(g, w * 0.5, h * 0.28, w * 0.25, w * 0.25); cut(g, C.cream);
    ink(g, 1.2, C.ink); for (let k = 0; k < 12; k++) { const a = (k / 12) * 6.283; line(g, [[w * 0.5 + Math.cos(a) * w * 0.2, h * 0.28 + Math.sin(a) * w * 0.2], [w * 0.5 + Math.cos(a) * w * 0.23, h * 0.28 + Math.sin(a) * w * 0.23]]); }
    ink(g, 2.2, C.ink); line(g, [[w * 0.5, h * 0.28], [w * 0.5, h * 0.28 - w * 0.16]]); line(g, [[w * 0.5, h * 0.28], [w * 0.62, h * 0.31]]);
    rrect(g, w * 0.34, h * 0.48, w * 0.32, h * 0.36, 3); cut(g, '#3a2a1c', 1.5);
    ink(g, 2, C.brass); line(g, [[w * 0.5, h * 0.5], [w * 0.47, h * 0.74]]); ell(g, w * 0.47, h * 0.76, 8, 8); g.fillStyle = C.brass; g.fill();
  },
  typewriter(g, w, h) {
    rrect(g, w * 0.3, h * 0.02, w * 0.4, h * 0.4, 1); cut(g, C.paper, 1.4);
    ink(g, 1, 'rgba(40,35,30,0.4)'); for (let y = h * 0.08; y < h * 0.36; y += 5) line(g, [[w * 0.34, y], [w * 0.34 + w * 0.3 * ((y * 7) % 10) / 10 + 6, y]]);
    rrect(g, w * 0.08, h * 0.3, w * 0.84, h * 0.14, 6); cut(g, C.black);
    poly(g, [[w * 0.12, h * 0.42], [w * 0.88, h * 0.42], [w * 0.98, h * 0.94], [w * 0.02, h * 0.94]]); cut(g, lin(g, 0, h * 0.4, 0, h, ['#3c5a46', '#263b2e']));
    g.fillStyle = C.cream;
    for (let row = 0; row < 3; row++) for (let k = 0; k < 9 - row; k++) { ell(g, w * (0.18 + row * 0.04 + k * 0.08), h * (0.6 + row * 0.1), 4.4, 4.4); g.fill(); }
    tag(g, w * 0.5, h * 0.5, 'ROYAL', 6);
  },
  lamp(g, w, h) {
    ell(g, w * 0.5, h * 0.95, w * 0.3, h * 0.035); cut(g, C.brassD);
    rrect(g, w * 0.46, h * 0.3, w * 0.08, h * 0.65, 2); cut(g, C.brass, 1.6);
    poly(g, [[w * 0.24, h * 0.04], [w * 0.76, h * 0.04], [w * 0.98, h * 0.34], [w * 0.02, h * 0.34]]); cut(g, lin(g, 0, 0, w, 0, ['#c98272', C.pink, '#c98272']));
    g.fillStyle = C.mustard; for (let x = w * 0.05; x < w * 0.95; x += 6) g.fillRect(x, h * 0.34, 2, 7);
    ink(g, 1, 'rgba(120,50,40,0.35)'); for (let k = 1; k < 6; k++) line(g, [[w * (0.24 + k * 0.087), h * 0.05], [w * (0.02 + k * 0.16), h * 0.33]]);
  },
  oilcan(g, w, h) {
    ink(g, 8, C.paper); line(g, [[w * 0.62, h * 0.38], [w * 0.97, h * 0.04]]); ink(g, 4.5, C.tinD); line(g, [[w * 0.62, h * 0.38], [w * 0.97, h * 0.04]]);
    poly(g, [[w * 0.42, h * 0.3], [w * 0.62, h * 0.3], [w * 0.92, h * 0.94], [w * 0.1, h * 0.94]]); cut(g, lin(g, w * 0.1, 0, w * 0.92, 0, [C.tinD, '#ccd1d1', C.tinD]));
    ell(g, w * 0.51, h * 0.94, w * 0.41, h * 0.05); g.fillStyle = C.tinD; g.fill();
    rrect(g, w * 0.2, h * 0.6, w * 0.62, h * 0.18, 2); cut(g, C.red, 1.4);
    tag(g, w * 0.51, h * 0.69, 'OIL', 7, 0, C.mustard);
  },
  kettle(g, w, h) {
    ink(g, 9, C.paper); g.beginPath(); g.arc(w * 0.5, h * 0.42, w * 0.28, Math.PI * 1.08, Math.PI * 1.92); g.stroke();
    ink(g, 5, C.black); g.stroke();
    poly(g, [[w * 0.12, h * 0.6], [w * 0.0, h * 0.4], [w * 0.05, h * 0.38], [w * 0.22, h * 0.52]]); cut(g, C.red);
    ell(g, w * 0.52, h * 0.66, w * 0.38, h * 0.3); cut(g, lin(g, w * 0.14, 0, w * 0.9, 0, ['#de6a52', C.red, '#8f2c1c']));
    g.save(); ell(g, w * 0.52, h * 0.66, w * 0.38, h * 0.3); g.clip(); shine(g, w * 0.26, h * 0.4, w * 0.12, h * 0.5, 0.4); g.restore();
    ell(g, w * 0.52, h * 0.38, w * 0.15, h * 0.05); cut(g, C.black);
  },
  boot(g, w, h) {
    g.beginPath(); g.moveTo(w * 0.24, h * 0.06); g.lineTo(w * 0.64, h * 0.06); g.lineTo(w * 0.66, h * 0.56);
    g.quadraticCurveTo(w * 0.98, h * 0.62, w * 0.96, h * 0.86); g.lineTo(w * 0.96, h * 0.94); g.lineTo(w * 0.16, h * 0.94); g.lineTo(w * 0.2, h * 0.56); g.closePath();
    cut(g, lin(g, 0, 0, w, 0, ['#4a3020', '#6b4630', '#3a2516']));
    g.fillStyle = '#2a1a10'; g.fillRect(w * 0.14, h * 0.86, w * 0.84, h * 0.08);
    ink(g, 1.8, C.cream); for (let k = 0; k < 5; k++) line(g, [[w * 0.34, h * (0.14 + k * 0.08)], [w * 0.56, h * (0.18 + k * 0.08)]]);
  },
  wheel(g, w, h) {
    ink(g, 5, C.woodD); line(g, [[w * 0.5, h * 0.42], [w * 0.86, h * 0.98]]);
    ell(g, w * 0.5, h * 0.42, w * 0.46, w * 0.46); g.lineWidth = 10; g.strokeStyle = C.paper; g.stroke(); g.lineWidth = 6; g.strokeStyle = C.black; g.stroke();
    ink(g, 1.1, C.tinD); for (let k = 0; k < 16; k++) { const a = (k / 16) * 6.283; line(g, [[w * 0.5, h * 0.42], [w * 0.5 + Math.cos(a) * w * 0.43, h * 0.42 + Math.sin(a) * w * 0.43]]); }
    ell(g, w * 0.5, h * 0.42, 6, 6); cut(g, C.tin, 1.4);
  },
  crate(g, w, h) {
    rrect(g, w * 0.04, h * 0.1, w * 0.92, h * 0.86, 2); cut(g, lin(g, 0, 0, 0, h, ['#b98a55', '#93683c']));
    ink(g, 1.4, 'rgba(70,40,15,0.6)'); for (let k = 1; k < 4; k++) line(g, [[w * 0.04, h * (0.1 + k * 0.215)], [w * 0.96, h * (0.1 + k * 0.215)]]);
    ink(g, 6, '#7a522c'); line(g, [[w * 0.08, h * 0.14], [w * 0.92, h * 0.92]]);
    g.save(); g.translate(w * 0.5, h * 0.52); g.rotate(-0.08); g.font = `700 ${Math.round(h * 0.16)}px ${FONT}`; g.fillStyle = 'rgba(40,25,10,0.55)'; g.textAlign = 'center'; g.fillText('FRAGILE', 0, 0); g.restore();
  },
  globe(g, w, h) {
    ink(g, 4, C.brassD); g.beginPath(); g.arc(w * 0.5, h * 0.38, w * 0.44, Math.PI * 0.6, Math.PI * 1.9); g.stroke();
    rrect(g, w * 0.46, h * 0.7, w * 0.08, h * 0.2, 2); cut(g, C.woodD, 1.4);
    ell(g, w * 0.5, h * 0.93, w * 0.26, h * 0.04); cut(g, C.woodD);
    ell(g, w * 0.5, h * 0.38, w * 0.38, w * 0.38); cut(g, lin(g, w * 0.12, 0, w * 0.88, 0, ['#6aa6a8', '#3e7f86', '#2a5b62']));
    g.save(); ell(g, w * 0.5, h * 0.38, w * 0.38, w * 0.38); g.clip();
    g.fillStyle = C.mustard; poly(g, [[w * 0.3, h * 0.2], [w * 0.5, h * 0.24], [w * 0.46, h * 0.4], [w * 0.32, h * 0.36]]); g.fill();
    poly(g, [[w * 0.58, h * 0.36], [w * 0.78, h * 0.42], [w * 0.66, h * 0.58], [w * 0.56, h * 0.5]]); g.fill();
    shine(g, w * 0.26, h * 0.1, w * 0.1, h * 0.6, 0.3);
    g.restore();
  },
};
const FAMILY = Object.keys(PROPS);
const LABEL_ONLY = (g, w, h, id) => {
  const r = rng(hash(id));
  rrect(g, w * 0.08, h * 0.12, w * 0.84, h * 0.84, Math.min(w, h) * 0.2);
  cut(g, [C.teal, C.rust, C.mustard, C.navy, C.green][Math.floor(r() * 5)]);
  tag(g, w / 2, h * 0.5, id.toUpperCase().slice(0, 12), Math.max(7, Math.min(12, w / 9)));
};

// --- machines: megaliths of bric-a-brac ---
const MACHINE = {
  bed(g, w, h) {
    ink(g, 2, C.tinD); line(g, [[w * 0.62, h * 0.18], [w * 0.8, h * 0.0]]); ell(g, w * 0.8, h * 0.005, 4, 4); g.fillStyle = C.brass; g.fill();
    rrect(g, w * 0.08, h * 0.9, w * 0.14, h * 0.08, 2); cut(g, C.woodD); rrect(g, w * 0.78, h * 0.9, w * 0.14, h * 0.08, 2); cut(g, C.woodD);
    g.beginPath(); g.moveTo(w * 0.04, h * 0.92); g.lineTo(w * 0.04, h * 0.34); g.arc(w * 0.5, h * 0.34, w * 0.46, Math.PI, 0); g.lineTo(w * 0.96, h * 0.92); g.closePath();
    cut(g, lin(g, 0, 0, w, 0, ['#6e4526', '#a8743f', '#b9874f', '#6e4526']), 3.4);
    g.save(); g.clip(); g.globalAlpha = 0.35; g.fillStyle = pattern(g, 'wood', 0.35, 1.57); g.fillRect(0, 0, w, h); g.restore();
    g.beginPath(); g.moveTo(w * 0.16, h * 0.56); g.lineTo(w * 0.16, h * 0.34); g.arc(w * 0.5, h * 0.34, w * 0.34, Math.PI, 0); g.lineTo(w * 0.84, h * 0.56); g.closePath();
    cut(g, pattern(g, 'fabric', 0.3, 0.4), 1.6);
    ink(g, 5, '#5a3820');
    for (const k of [-1, 0, 1]) { g.beginPath(); g.moveTo(w * (0.5 + k * 0.2), h * 0.56); g.quadraticCurveTo(w * (0.5 + k * 0.08), h * 0.36, w * (0.5 + k * 0.14), h * 0.2); g.stroke(); }
    ell(g, w * 0.5, h * 0.68, w * 0.2, w * 0.2); cut(g, C.cream);
    ink(g, 1.2, C.ink); for (let k = 0; k <= 10; k++) { const a = Math.PI * (1.1 + k * 0.08); line(g, [[w * 0.5 + Math.cos(a) * w * 0.15, h * 0.68 + Math.sin(a) * w * 0.15], [w * 0.5 + Math.cos(a) * w * 0.18, h * 0.68 + Math.sin(a) * w * 0.18]]); }
    ink(g, 2, C.red); line(g, [[w * 0.5, h * 0.68 + w * 0.04], [w * 0.6, h * 0.68 - w * 0.13]]);
    for (const k of [-1, 0, 1]) { ell(g, w * (0.5 + k * 0.24), h * 0.8, w * 0.06, w * 0.06); cut(g, C.black, 1.6); ell(g, w * (0.5 + k * 0.24), h * 0.8, w * 0.025, w * 0.025); g.fillStyle = C.brass; g.fill(); }
    tag(g, w * 0.5, h * 0.88, 'THE WIRELESS', 9, -0.02);
  },
  drums(g, w, h) {
    ink(g, 4, C.woodD); line(g, [[w * 0.2, h * 0.02], [w * 0.6, h * 0.3]]); line(g, [[w * 0.86, h * 0.04], [w * 0.4, h * 0.3]]);
    ink(g, 3, C.tinD); line(g, [[w * 0.5, h * 0.08], [w * 0.5, h * 0.24]]);
    ell(g, w * 0.5, h * 0.08, w * 0.34, h * 0.03); cut(g, lin(g, w * 0.16, 0, w * 0.84, 0, [C.brassD, '#e8c26a', C.brassD]));
    g.beginPath(); g.moveTo(w * 0.24, h * 0.4); g.lineTo(w * 0.3, h * 0.22); g.quadraticCurveTo(w * 0.5, h * 0.16, w * 0.7, h * 0.22); g.lineTo(w * 0.76, h * 0.4); g.closePath();
    cut(g, lin(g, w * 0.24, 0, w * 0.76, 0, ['#5aa39d', C.teal, C.tealD]));
    for (const [x, c] of [[0.08, C.tin], [0.52, '#b9a77c']]) {
      rrect(g, w * x, h * 0.4, w * 0.4, h * 0.26, 3); cut(g, pattern(g, 'tin', 0.25));
      ink(g, 1.2, 'rgba(40,40,40,0.4)'); for (let k = 1; k < 5; k++) line(g, [[w * x, h * (0.4 + k * 0.052)], [w * (x + 0.4), h * (0.4 + k * 0.052)]]);
      rrect(g, w * (x + 0.04), h * 0.47, w * 0.32, h * 0.08, 1); cut(g, c, 1.2);
    }
    rrect(g, w * 0.04, h * 0.66, w * 0.92, h * 0.3, 6); cut(g, lin(g, 0, 0, w, 0, ['#8f2c1c', C.red, '#de6a52', C.red, '#8f2c1c']), 3.4);
    ell(g, w * 0.5, h * 0.665, w * 0.46, h * 0.03); cut(g, C.cream, 1.6);
    ink(g, 2, C.cream); g.beginPath(); for (let k = 0; k <= 8; k++) g.lineTo(w * (0.04 + k * 0.115), h * (k % 2 ? 0.92 : 0.7)); g.stroke();
    tag(g, w * 0.5, h * 0.86, 'THE CLATTER', 9, 0.02);
  },
  bass(g, w, h) {
    g.beginPath(); g.moveTo(w * 0.56, h * 0.2); g.quadraticCurveTo(w * 0.6, h * 0.06, w * 0.84, h * 0.04); g.lineTo(w * 0.98, h * 0.0); g.lineTo(w * 0.96, h * 0.16);
    g.quadraticCurveTo(w * 0.78, h * 0.12, w * 0.7, h * 0.22); g.closePath(); cut(g, lin(g, w * 0.5, 0, w, 0, [C.brassD, '#e8c26a', C.brass]));
    ell(g, w * 0.97, h * 0.08, w * 0.04, h * 0.08, 0.1); g.fillStyle = '#3a2a10'; g.fill();
    rrect(g, w * 0.04, h * 0.18, w * 0.92, h * 0.07, 3); cut(g, lin(g, 0, 0, w, 0, [C.woodD, C.wood, C.woodD]));
    const n = 9, y0 = h * 0.25, y1 = h * 0.8;
    for (let k = 0; k < n; k++) {
      const ya = y0 + ((y1 - y0) * k) / n, yb = y0 + ((y1 - y0) * (k + 1)) / n, ia = k % 2 ? 0.1 : 0.05, ib = k % 2 ? 0.05 : 0.1;
      poly(g, [[w * ia, ya], [w * (1 - ia), ya], [w * (1 - ib), yb], [w * ib, yb]]);
      g.fillStyle = k % 2 ? '#7a4a2a' : '#a8683e'; g.fill();
    }
    ink(g, 1.4, C.cream); for (let k = 0; k <= n; k++) { const y = y0 + ((y1 - y0) * k) / n; line(g, [[w * 0.08, y], [w * 0.92, y]]); }
    rrect(g, w * 0.04, h * 0.8, w * 0.92, h * 0.07, 3); cut(g, lin(g, 0, 0, w, 0, [C.woodD, C.wood, C.woodD]));
    rrect(g, w * 0.1, h * 0.87, w * 0.8, h * 0.1, 3); cut(g, pattern(g, 'card', 0.3));
    ell(g, w * 0.5, h * 0.5, w * 0.16, w * 0.16); cut(g, C.cream);
    ink(g, 2, C.ink); line(g, [[w * 0.5, h * 0.5], [w * 0.58, h * 0.47]]);
    tag(g, w * 0.5, h * 0.92, 'THE BELLOWS', 9, -0.015);
  },
};

// --- the Gramophone, its plinths, the tear ---
function gramophone(g, w, h, horn = [0.42, 0.2]) {
  const [hx, hy] = [w * horn[0], h * horn[1]];
  for (const x of [0.17, 0.79]) { rrect(g, w * x, h * 0.93, w * 0.06, h * 0.06, 2); cut(g, C.woodD, 1.6); }
  rrect(g, w * 0.12, h * 0.6, w * 0.76, h * 0.35, 6); cut(g, lin(g, 0, 0, w, 0, ['#6e4526', '#a8743f', '#c08d55', '#6e4526']), 3.4);
  g.save(); rrect(g, w * 0.12, h * 0.6, w * 0.76, h * 0.35, 6); g.clip(); g.globalAlpha = 0.35; g.fillStyle = pattern(g, 'wood', 0.3); g.fillRect(0, 0, w, h); g.restore();
  rrect(g, w * 0.16, h * 0.66, w * 0.68, h * 0.25, 4); ink(g, 1.6, 'rgba(50,25,10,0.5)'); g.stroke();
  for (const [sx, sy] of [[0.25, 0.8], [0.5, 0.85], [0.75, 0.8]]) {
    ell(g, w * sx, h * sy, w * 0.055, w * 0.055); cut(g, lin(g, 0, h * (sy - 0.04), 0, h * (sy + 0.04), [C.brass, C.brassD]), 1.6);
    ell(g, w * sx, h * sy, w * 0.036, w * 0.036); g.fillStyle = '#2a1c10'; g.fill();
  }
  ell(g, w * 0.5, h * 0.6, w * 0.34, h * 0.055); cut(g, C.black, 2);
  ink(g, 0.8, 'rgba(255,255,255,0.18)'); for (const k of [0.27, 0.22, 0.17]) { ell(g, w * 0.5, h * 0.6, w * k, h * k * 0.16); g.stroke(); }
  ell(g, w * 0.5, h * 0.6, w * 0.07, h * 0.014); g.fillStyle = C.red; g.fill();
  ink(g, 4, C.brassD); line(g, [[w * 0.8, h * 0.58], [w * 0.72, h * 0.5], [w * 0.6, h * 0.5]]);
  // the horn: a flower of brass and enamel petals rising from the arm
  const nx = w * 0.62, ny = h * 0.52, rx = w * 0.36, ry = h * 0.19, tilt = -0.32;
  const rim = (a) => [hx + Math.cos(a) * rx * Math.cos(tilt) - Math.sin(a) * ry * Math.sin(tilt), hy + Math.cos(a) * rx * Math.sin(tilt) + Math.sin(a) * ry * Math.cos(tilt)];
  const P = 8;
  for (let k = 0; k < P; k++) {
    const a0 = (k / P) * Math.PI * 2, a1 = ((k + 1) / P) * Math.PI * 2;
    const [x0, y0] = rim(a0), [x1, y1] = rim(a1), [xm, ym] = rim((a0 + a1) / 2);
    g.beginPath(); g.moveTo(nx, ny); g.quadraticCurveTo((nx + x0) / 2 + (hx - nx) * 0.1, (ny + y0) / 2, x0, y0);
    g.quadraticCurveTo(xm + (xm - hx) * 0.12, ym + (ym - hy) * 0.12, x1, y1);
    g.quadraticCurveTo((nx + x1) / 2, (ny + y1) / 2, nx, ny); g.closePath();
    cut(g, k % 2 ? lin(g, nx, ny, xm, ym, [C.brassD, C.brass, '#f0cf7e']) : lin(g, nx, ny, xm, ym, [C.tealD, C.teal, '#7cc0b8']), 1.8);
  }
  ell(g, hx, hy, rx * 0.36, ry * 0.36, tilt); g.fillStyle = 'rgba(40,24,8,0.75)'; g.fill();
  ell(g, hx, hy, rx * 0.16, ry * 0.16, tilt); g.fillStyle = '#120c06'; g.fill();
  tag(g, w * 0.5, h * 0.7, 'SH001', 9, 0.01, C.cream);
}
const PART_COLOR = { bed: C.navy, drums: C.rust, bass: C.green };
function plinth(g, w, h, part) {
  ell(g, w * 0.5, h * 0.9, w * 0.42, h * 0.08); cut(g, C.woodD);
  g.fillStyle = lin(g, w * 0.08, 0, w * 0.92, 0, ['#6e4526', '#b9874f', '#6e4526']); g.fillRect(w * 0.08, h * 0.3, w * 0.84, h * 0.6);
  g.save(); g.beginPath(); g.rect(w * 0.08, h * 0.3, w * 0.84, h * 0.6); g.clip(); g.globalAlpha = 0.4; g.fillStyle = pattern(g, 'cork', 0.2); g.fillRect(0, 0, w, h); g.restore();
  g.fillStyle = PART_COLOR[part] ?? C.teal; g.fillRect(w * 0.08, h * 0.55, w * 0.84, h * 0.12);
  ell(g, w * 0.5, h * 0.3, w * 0.46, h * 0.1); cut(g, lin(g, 0, 0, w, 0, [C.brassD, '#e8c26a', C.brass]), 2);
  if (part) tag(g, w * 0.5, h * 0.61, part.toUpperCase(), 7.5, 0, C.cream);
}
function portal(g, w, h) {
  const r = rng(77), pts = [];
  for (let k = 0; k <= 24; k++) { const t = k / 24, y = h * (0.03 + 0.92 * t), half = w * 0.4 * Math.sin(Math.PI * t) ** 0.8; pts.push([w * 0.5 + half + (r() - 0.5) * 10, y]); }
  for (let k = 24; k >= 0; k--) { const t = k / 24, y = h * (0.03 + 0.92 * t), half = w * 0.4 * Math.sin(Math.PI * t) ** 0.8; pts.push([w * 0.5 - half + (r() - 0.5) * 10, y]); }
  g.save(); g.shadowColor = 'rgba(241,182,74,0.75)'; g.shadowBlur = 16; poly(g, pts); cut(g, '#000', 4.5); g.restore();
  g.save(); poly(g, pts); g.clip();
  g.fillStyle = '#fff';
  for (let y = 0; y < h; y += 3) for (let x = 0; x < w; x += 3) {
    const sand = 0.16 + 0.22 * Math.sin(x * 0.07 + y * 0.03) * Math.sin(y * 0.05), dune = y > h * 0.58 ? 0.25 : 0;
    if (r() < sand + dune * (Math.sin(x * 0.1) * 0.5 + 0.5)) g.fillRect(x, y, 2, 2);
  }
  g.fillStyle = C.gold; for (let k = 0; k < 14; k++) g.fillRect(w * (0.3 + r() * 0.4), h * (0.2 + r() * 0.6), 2, 2);
  g.restore();
  // curls of paper where it tore
  g.fillStyle = C.paper;
  for (const [x, y, a] of [[0.2, 0.36, 0.5], [0.82, 0.5, -0.4], [0.26, 0.72, 0.9], [0.74, 0.24, -0.9]]) { g.save(); g.translate(w * x, h * y); g.rotate(a); poly(g, [[0, 0], [12, -4], [5, 8]]); g.fill(); g.restore(); }
}

// --- artifacts: a choice distilled into a small object ---
const OPTION_COLOR = { 1: [C.teal, C.tealD], 2: [C.rust, C.rustD], 3: [C.mustard, C.brassD] };
function artifact(g, w, h, part, id) {
  const [c, d] = OPTION_COLOR[id] ?? [C.navy, C.black];
  if (part === 'bed') {
    ell(g, w * 0.5, h * 0.52, w * 0.42, h * 0.42); cut(g, lin(g, 0, 0, w, h, [c, d]), 3);
    ink(g, 2, 'rgba(255,245,225,0.75)');
    for (const k of [0.3, 0.22]) { g.beginPath(); for (let x = -1; x <= 1; x += 0.1) g.lineTo(w * (0.5 + x * k * 1.1), h * (0.52 + Math.sin(x * 9) * 0.04 - (k - 0.26) * 1.4)); g.stroke(); }
  } else if (part === 'drums') {
    rrect(g, w * 0.14, h * 0.24, w * 0.72, h * 0.62, 5); cut(g, lin(g, 0, 0, w, 0, [d, c, d]), 3);
    ell(g, w * 0.5, h * 0.25, w * 0.36, h * 0.09); cut(g, C.cream, 1.6);
    ink(g, 1.8, 'rgba(255,245,225,0.8)'); g.beginPath(); for (let k = 0; k <= 6; k++) g.lineTo(w * (0.14 + k * 0.12), h * (k % 2 ? 0.8 : 0.38)); g.stroke();
  } else {
    rrect(g, w * 0.08, h * 0.22, w * 0.14, h * 0.62, 3); cut(g, C.woodD, 2.4);
    rrect(g, w * 0.78, h * 0.22, w * 0.14, h * 0.62, 3); cut(g, C.woodD, 2.4);
    poly(g, [[w * 0.22, h * 0.28], [w * 0.78, h * 0.28], [w * 0.78, h * 0.78], [w * 0.22, h * 0.78]]); cut(g, c, 1.4);
    ink(g, 2.2, d); g.beginPath(); for (let k = 0; k <= 8; k++) g.lineTo(w * (0.22 + k * 0.07), h * (k % 2 ? 0.3 : 0.76)); g.stroke();
  }
  ell(g, w * 0.74, h * 0.24, w * 0.15, w * 0.15); cut(g, C.cream, 1.6);
  g.fillStyle = C.ink; g.font = `700 ${Math.round(w * 0.2)}px ${FONT}`; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(String(id), w * 0.74, h * 0.25);
}

// --- the wanderer: a hooded traveller cut from paper, the gold scarf round the neck, a pack on the back ---
function hero(g, w, h, face) {
  const cloak = pattern(g, 'cream', 0.25), dark = '#3a2c20';
  const boots = (xs) => { for (const [x, y] of xs) { rrect(g, w * x, h * y, w * 0.15, h * 0.12, 4); cut(g, dark, 1.8); } };
  if (face === 'side') {
    boots([[0.3, 0.86], [0.5, 0.87]]);
    rrect(g, w * 0.1, h * 0.36, w * 0.32, h * 0.36, 8); cut(g, pattern(g, 'kraft', 0.2), 2);           // the pack
    ink(g, 1.4, 'rgba(60,35,15,0.6)'); line(g, [[w * 0.12, h * 0.48], [w * 0.4, h * 0.48]]);
    poly(g, [[w * 0.36, h * 0.3], [w * 0.68, h * 0.3], [w * 0.8, h * 0.88], [w * 0.24, h * 0.88]]); cut(g, cloak, 2.6);
    ink(g, 1.2, 'rgba(120,90,50,0.6)'); g.setLineDash([2.5, 2.5]); line(g, [[w * 0.62, h * 0.34], [w * 0.72, h * 0.84]]); g.setLineDash([]);
    ell(g, w * 0.52, h * 0.2, w * 0.24, h * 0.15); cut(g, '#d9cba9', 2.6);
    poly(g, [[w * 0.36, h * 0.1], [w * 0.3, h * 0.0], [w * 0.5, h * 0.06]]); cut(g, '#d9cba9', 1.6);
    ell(g, w * 0.66, h * 0.22, w * 0.11, h * 0.085); g.fillStyle = '#231a12'; g.fill();
    ell(g, w * 0.7, h * 0.21, 1.6, 1.6); g.fillStyle = C.paper; g.fill();
    rrect(g, w * 0.36, h * 0.3, w * 0.36, h * 0.07, 3); cut(g, lin(g, 0, 0, w, 0, [C.gold, '#c98f2a']), 1.4);
    return;
  }
  boots([[0.27, 0.87], [0.58, 0.87]]);
  if (face === 'back') {
    poly(g, [[w * 0.27, h * 0.3], [w * 0.73, h * 0.3], [w * 0.92, h * 0.89], [w * 0.08, h * 0.89]]); cut(g, cloak, 2.6);
    rrect(g, w * 0.24, h * 0.36, w * 0.52, h * 0.36, 9); cut(g, pattern(g, 'kraft', 0.2), 2);
    rrect(g, w * 0.24, h * 0.36, w * 0.52, h * 0.13, 7); cut(g, '#8d6438', 1.4);
    rrect(g, w * 0.46, h * 0.46, w * 0.08, h * 0.06, 1); cut(g, C.brass, 1);
    ell(g, w * 0.5, h * 0.19, w * 0.26, h * 0.16); cut(g, '#d9cba9', 2.6);
    poly(g, [[w * 0.42, h * 0.06], [w * 0.5, -h * 0.01], [w * 0.58, h * 0.06]]); cut(g, '#d9cba9', 1.4);
    ink(g, 1.2, 'rgba(120,90,50,0.5)'); line(g, [[w * 0.5, h * 0.06], [w * 0.5, h * 0.3]]);
    rrect(g, w * 0.26, h * 0.29, w * 0.48, h * 0.07, 3); cut(g, lin(g, 0, 0, w, 0, [C.gold, '#c98f2a']), 1.4);
    return;
  }
  poly(g, [[w * 0.27, h * 0.3], [w * 0.73, h * 0.3], [w * 0.92, h * 0.89], [w * 0.08, h * 0.89]]); cut(g, cloak, 2.6);
  rrect(g, w * 0.56, h * 0.58, w * 0.18, h * 0.16, 2); cut(g, pattern(g, 'map', 0.2), 1.2);                   // a patch
  ink(g, 3, '#8d6438'); line(g, [[w * 0.32, h * 0.32], [w * 0.36, h * 0.6]]); line(g, [[w * 0.68, h * 0.32], [w * 0.64, h * 0.6]]);
  ink(g, 1.2, 'rgba(120,90,50,0.6)'); g.setLineDash([2.5, 2.5]); line(g, [[w * 0.5, h * 0.38], [w * 0.5, h * 0.86]]); g.setLineDash([]);
  ell(g, w * 0.5, h * 0.19, w * 0.26, h * 0.16); cut(g, '#d9cba9', 2.6);
  poly(g, [[w * 0.42, h * 0.06], [w * 0.5, -h * 0.01], [w * 0.58, h * 0.06]]); cut(g, '#d9cba9', 1.4);
  ell(g, w * 0.5, h * 0.215, w * 0.15, h * 0.1); g.fillStyle = '#231a12'; g.fill();
  for (const x of [0.44, 0.56]) { ell(g, w * x, h * 0.21, 1.7, 1.9); g.fillStyle = C.paper; g.fill(); }
  rrect(g, w * 0.26, h * 0.29, w * 0.48, h * 0.075, 3); cut(g, lin(g, 0, 0, w, 0, [C.gold, '#c98f2a']), 1.4);
  ink(g, 1, 'rgba(120,70,10,0.6)'); for (const x of [0.36, 0.5, 0.64]) line(g, [[w * x, h * 0.295], [w * x, h * 0.36]]);
}

// --- the signpost at the crossroads ---
function sign(g, w, h, arms = []) {
  rrect(g, w * 0.47, h * 0.06, w * 0.06, h * 0.92, 2); cut(g, lin(g, 0, 0, w, 0, [C.woodD, C.wood, C.woodD]), 2);
  arms.forEach((a, i) => {
    const y = h * (0.1 + i * 0.17), len = w * 0.46, dir = a.dir, x0 = w * 0.5 - (dir < 0 ? len - 8 : 8);
    g.save(); g.translate(w * 0.5, y); g.rotate((i % 2 ? 0.04 : -0.035) * dir); g.translate(-w * 0.5, -y);
    const pts = dir > 0 ? [[x0, y - 10], [x0 + len - 10, y - 10], [x0 + len, y], [x0 + len - 10, y + 10], [x0, y + 10]]
      : [[x0 + len, y - 10], [x0 + 10, y - 10], [x0, y], [x0 + 10, y + 10], [x0 + len, y + 10]];
    poly(g, pts); cut(g, [C.cream, '#e9d6a7', C.cream, '#e2d3b8'][i % 4], 1.8);
    g.fillStyle = C.ink; g.font = `600 10px ${FONT}`; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText(a.text, x0 + len / 2 + (dir > 0 ? -4 : 4), y + 0.5);
    g.restore();
  });
}

export const PAINT = {
  prop(g, w, h, id) { (PROPS[id] ?? LABEL_ONLY)(g, w, h, id); },
  machine: (g, w, h, part) => MACHINE[part](g, w, h),
  gramophone, plinth, portal, artifact, hero, sign,
};
export const DEFAULT_PROP_IDS = FAMILY;

// --- small things on the ground ---
const DECAL_COLORS = [C.red, C.teal, C.mustard, C.navy, C.cream, C.green, C.pink, C.brassD];
/** One small thing lying on the ground, centred on its (x, y). */
export function decal(g, d) {
  const c = DECAL_COLORS[d.c], r = rng(d.n);
  g.save(); g.translate(d.x, d.y); g.rotate(d.a); g.scale(d.s, d.s);
  switch (d.kind) {
    case 'scrap': poly(g, [[-8 - r() * 4, -5], [7 + r() * 5, -7], [9, 6 + r() * 3], [-6, 7]]); cut(g, c, 1.2); break;
    case 'button': ell(g, 0, 0, 6, 6); cut(g, c, 1); g.fillStyle = 'rgba(0,0,0,0.45)'; for (const [x, y] of [[-1.8, -1.8], [1.8, -1.8], [-1.8, 1.8], [1.8, 1.8]]) { ell(g, x, y, 0.9, 0.9); g.fill(); } break;
    case 'stamp':
      g.fillStyle = C.paper; g.fillRect(-9, -11, 18, 22);
      g.fillStyle = 'rgba(0,0,0,0.12)'; for (let k = -9; k <= 9; k += 3) { ell(g, k, -11, 1, 1); g.fill(); ell(g, k, 11, 1, 1); g.fill(); }
      g.fillStyle = c; g.fillRect(-6.5, -8.5, 13, 17);
      g.fillStyle = 'rgba(255,255,255,0.7)'; g.fillRect(-4, 2, 8, 1.5); ell(g, 0, -2.5, 3, 3); g.fill();
      break;
    case 'ticket': rrect(g, -15, -6, 30, 12, 1); cut(g, C.cream, 1); g.fillStyle = C.red; g.fillRect(-15, -6, 5, 12); g.fillStyle = 'rgba(40,30,20,0.5)'; g.fillRect(-7, -2, 16, 1.4); g.fillRect(-7, 1.5, 10, 1.4); break;
    case 'screw': ell(g, 0, 0, 3.6, 3.6); g.fillStyle = C.tin; g.fill(); ink(g, 1, C.tinD); line(g, [[-2.6, 0], [2.6, 0]]); break;
    case 'string': ink(g, 1.4, c === C.cream ? C.red : c); g.beginPath(); g.moveTo(-16, 0); g.bezierCurveTo(-6, -12 * r(), 4, 12 * r(), 16, -2); g.stroke(); break;
    case 'tack': ell(g, 0, 0, 4, 4); g.fillStyle = C.brass; g.fill(); ell(g, -1.2, -1.2, 1.4, 1.4); g.fillStyle = 'rgba(255,255,255,0.7)'; g.fill(); break;
    case 'leaf': g.beginPath(); g.moveTo(-10, 0); g.quadraticCurveTo(0, -8, 10, 0); g.quadraticCurveTo(0, 8, -10, 0); g.fillStyle = ['#a8743f', '#8a6a2a', '#b0532c'][d.c % 3]; g.fill(); ink(g, 0.8, 'rgba(60,30,10,0.5)'); line(g, [[-9, 0], [9, 0]]); break;
  }
  g.restore();
}
/** A paper doily: a scalloped disc with rings of little holes. */
export function doily(g, cx, cy, rx, ry) {
  g.save(); g.translate(cx, cy); g.scale(1, ry / rx);
  const n = 64;
  g.beginPath();
  for (let k = 0; k < n; k++) { const a = (k / n) * Math.PI * 2, b = ((k + 1) / n) * Math.PI * 2; g.arc(Math.cos((a + b) / 2) * rx * 0.985, Math.sin((a + b) / 2) * rx * 0.985, (Math.PI * rx) / n * 1.05, a - Math.PI / 2, b + Math.PI / 2); }
  g.closePath();
  g.shadowColor = 'rgba(40,25,10,0.35)'; g.shadowBlur = 8; g.shadowOffsetY = 3;
  g.fillStyle = '#f7f1e3'; g.fill();
  g.shadowColor = 'transparent';
  g.fillStyle = 'rgba(120,90,60,0.28)';
  for (const [k, m, s] of [[0.9, 56, 4.2], [0.78, 44, 5], [0.62, 30, 6.5], [0.44, 20, 5.5]]) {
    for (let i = 0; i < m; i++) { const a = (i / m) * Math.PI * 2 + k; ell(g, Math.cos(a) * rx * k, Math.sin(a) * rx * k, s, s * 0.7, a); g.fill(); }
  }
  ink(g, 1.2, 'rgba(120,90,60,0.25)'); for (const k of [0.84, 0.7, 0.53]) { ell(g, 0, 0, rx * k, rx * k); g.stroke(); }
  g.restore();
}
