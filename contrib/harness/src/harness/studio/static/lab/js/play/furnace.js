// Furnace: a raymarched kick monolith in a dark foundry, on an old CRT with a chrome scroller and copper bars.
//
// What you see is HW002's state: the slab's cracks glow at the kick's colour frequency (484 Hz a deep red heat,
// 2.2 kHz yellow-white, 6 kHz blue-white) and as hard as the colour boost; its surface boils with COLDFIRE's drive;
// the floor ripples on every kick as deep as the 30 Hz shelf (at the set's -14.8 dB it barely moves: the missing
// sub); Supermassive's mix fills the room with haze; the Decapitator shakes the camera. The master's low band and
// the beat phase make it pulse on the kick.
//
// Touch writes knobs (one undo step per touch): drag across = X (COLDFIRE drive), drag up = Y (colour frequency),
// pinch = the third (space mix). The camera sits where X and Y are. Double tap: those three back to the set.

import { h, haptic, toast } from '../ui.js';
import { writer } from '../widgets/core.js';
import { GLSL_COMMON, Program, glView, target, texture, triangle, xyTouch } from './gl.js';
import { barText, chips, clamp, readout, shell, shortOf } from './room.js';

const SCENE = `precision highp float;
varying vec2 vUv;
uniform vec2 uRes;
uniform float uTime, uPulse, uBeat, uDrive, uHue, uBoost, uSpace, uSub, uRumble, uFlash;
uniform vec2 uCam;
${GLSL_COMMON}
float sdBox(vec3 p, vec3 b){ vec3 q = abs(p) - b; return length(max(q, 0.0)) + min(max(q.x, max(q.y, q.z)), 0.0); }
float slab(vec3 p){
  float s = 1.0 + 0.05 * uPulse;
  p.y -= 0.05;
  p /= s;
  float d = sdBox(p, vec3(0.7, 1.8, 0.26)) - 0.025;
  if (d < 0.3) {
    float n = noise3(p * 3.1 + vec3(0.0, -uTime * 0.7, uTime * 0.25)) * 0.65 + noise3(p * 7.3 + vec3(uTime * 0.4, 0.0, 0.0)) * 0.35;
    d += (n - 0.5) * (0.03 + 0.28 * uDrive);
  }
  return d * s * 0.7;
}
float crack(vec3 p){
  p.y -= 0.05;
  vec3 q = p * vec3(2.2, 1.1, 2.2) + vec3(0.0, uTime * 0.08, 0.0);
  float n = noise3(q * 1.7) * 0.62 + noise3(q * 4.3) * 0.38;
  float w = 0.012 + 0.075 * uDrive;
  return smoothstep(w, 0.0, abs(n - 0.5));
}
vec3 nrm(vec3 p){
  const vec2 e = vec2(0.003, -0.003);
  return normalize(e.xyy * slab(p + e.xyy) + e.yyx * slab(p + e.yyx) + e.yxy * slab(p + e.yxy) + e.xxx * slab(p + e.xxx));
}
vec3 sky(vec3 rd, vec3 hc){
  vec3 col = mix(vec3(0.012, 0.002, 0.014), vec3(0.0005, 0.0, 0.002), smoothstep(-0.05, 0.6, rd.y));
  col += hc * 0.06 * exp(-abs(rd.y) * 12.0);
  float a = atan(rd.x, rd.z);
  float stack = step(0.93, fract(a * 3.0)) * step(rd.y, 0.05 + 0.08 * hash21(vec2(floor(a * 3.0), 1.0)));
  col = mix(col, vec3(0.0), stack * 0.85);
  return col;
}
void main(){
  vec2 uv = (vUv * 2.0 - 1.0) * vec2(uRes.x / uRes.y, 1.0);
  float az = (uCam.x - 0.5) * 2.4 + sin(uTime * 0.11) * 0.15;
  float el = mix(0.1, 0.78, uCam.y);
  float rad = 8.2 - 0.35 * uPulse;
  vec3 ta = vec3(0.0, 0.12, 0.0);
  vec3 ro = ta + rad * vec3(sin(az) * cos(el), sin(el), cos(az) * cos(el));
  float sh = uRumble * uPulse * 0.11;
  ro += vec3(noise3(vec3(uTime * 31.0, 1.0, 0.0)) - 0.5, noise3(vec3(2.0, uTime * 29.0, 0.0)) - 0.5, 0.0) * sh;
  vec3 ww = normalize(ta - ro);
  vec3 uu = normalize(cross(ww, vec3(0.0, 1.0, 0.0)));
  vec3 vv = cross(uu, ww);
  vec3 rd = normalize(uv.x * uu + (uv.y - 0.08) * vv + 2.1 * ww);
  vec3 hc = heat(uHue);
  float energy = 0.45 + 1.7 * uBoost;
  float t = 0.0; float glow = 0.0; float m = 0.0;
  for (int i = 0; i < 88; i++) {
    vec3 p = ro + rd * t;
    float a = slab(p);
    float b = p.y + 1.75;
    float d = min(a, b);
    glow += exp(-max(a, 0.0) * 4.0) * max(d, 0.03) * 0.3;
    if (d < 0.0015 * t) { m = a < b ? 1.0 : 2.0; break; }
    t += d;
    if (t > 40.0) break;
  }
  vec3 p = ro + rd * t;
  vec3 col;
  if (m > 0.5 && m < 1.5) {
    vec3 n = nrm(p);
    vec3 l = normalize(vec3(-0.4, 0.75, 0.55));
    float dif = max(dot(n, l), 0.0);
    float fre = pow(1.0 - max(dot(n, -rd), 0.0), 3.0);
    float spe = pow(max(dot(reflect(rd, n), l), 0.0), 40.0);
    col = vec3(0.012, 0.012, 0.016) * (0.3 + dif);
    col += spe * vec3(0.55, 0.65, 0.9) * 0.45;
    col += fre * vec3(1.0, 0.24, 0.95) * 0.5;
    col += sky(reflect(rd, n), hc) * 1.5 * (0.3 + fre);
    col += hc * crack(p) * energy * (0.7 + 3.6 * uPulse + uFlash * 3.0);
    col += hc * smoothstep(-0.4, -1.75, p.y) * 0.3 * energy * (0.4 + uPulse);
  } else if (m > 1.5) {
    float r = length(p.xz) + 0.001;
    float front = uBeat * 7.5;
    float w = sin((r - front) * 10.0) * exp(-abs(r - front) * 1.5) * (1.0 - uBeat) * step(0.001, uPulse + uFlash);
    float amp = 0.05 + 0.75 * uSub;
    vec3 n = normalize(vec3(p.x / r * w * amp, 1.0, p.z / r * w * amp));
    float conc = noise3(vec3(p.xz * 2.3, 0.0)) * 0.5 + noise3(vec3(p.xz * 9.0, 3.0)) * 0.25;
    vec3 base = vec3(0.016, 0.015, 0.018) * (0.4 + conc);
    vec2 g = abs(fract(p.xz * 0.5) - 0.5);
    base += smoothstep(0.46, 0.5, max(g.x, g.y)) * vec3(0.06, 0.012, 0.06) * exp(-length(p.xz) * 0.12);
    col = base + hc * exp(-r * 0.55) * (0.12 + 0.6 * uPulse) * energy;
    col += hc * abs(w) * amp * 0.9 * exp(-abs(r - front) * 0.6);
    vec3 rr = reflect(rd, n);
    float t2 = 0.05; float hit = 0.0; vec3 q = p;
    for (int j = 0; j < 40; j++) {
      q = p + rr * t2;
      float a = slab(q);
      if (a < 0.004) { hit = 1.0; break; }
      t2 += a;
      if (t2 > 14.0) break;
    }
    float fre = 0.06 + 0.94 * pow(1.0 - max(dot(n, -rd), 0.0), 5.0);
    vec3 refl = hit > 0.5 ? hc * crack(q) * energy * (0.6 + 3.0 * uPulse) + vec3(0.015) : sky(rr, hc);
    col += refl * fre * 0.95;
    col *= exp(-t * 0.02);
  } else {
    col = sky(rd, hc);
  }
  float fogK = 0.008 + 0.06 * uSpace;
  vec3 fogC = hc * 0.025 + vec3(0.008, 0.001, 0.01);
  col = mix(col, fogC, 1.0 - exp(-t * fogK));
  col += hc * glow * (0.1 + 1.1 * uSpace) * (0.45 + 1.5 * uPulse + uFlash) * energy * 0.5;
  col = 1.0 - exp(-col * 1.8);
  gl_FragColor = vec4(pow(col, vec3(0.8)), 1.0);
}`;

const POST = `precision highp float;
varying vec2 vUv;
uniform sampler2D uScene;
uniform sampler2D uText;
uniform vec2 uRes;
uniform float uTime, uPulse, uAb, uScroll, uTextAspect, uHue, uDrive, uFlash, uBand;
${GLSL_COMMON}
vec3 chrome(float y){
  vec3 c;
  if (y > 0.52) c = mix(vec3(1.0, 0.93, 1.0), vec3(0.16, 0.2, 0.62), (y - 0.52) / 0.48);
  else if (y > 0.47) c = vec3(1.0);
  else c = mix(vec3(0.42, 0.16, 0.08), vec3(1.0, 0.7, 0.36), (0.47 - y) / 0.47);
  return mix(c, c * vec3(1.0, 0.55, 1.0), 0.3);
}
vec3 copper(float i){
  return i < 1.0 ? vec3(1.0, 0.24, 0.95) : (i < 2.0 ? vec3(1.0, 0.35, 0.12) : (i < 3.0 ? vec3(0.78, 1.0, 0.24) : (i < 4.0 ? vec3(0.35, 0.78, 1.0) : (i < 5.0 ? vec3(1.0, 0.71, 0.28) : vec3(1.0, 0.24, 0.95)))));
}
void main(){
  vec2 q = vUv * 2.0 - 1.0;
  q *= 1.0 + 0.035 * dot(q, q);
  vec2 uv = q * 0.5 + 0.5;
  if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) { gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0); return; }
  vec2 c = uv - 0.5;
  float k = uAb * (0.004 + 0.035 * dot(c, c));
  vec3 col = vec3(texture2D(uScene, uv + c * k).r, texture2D(uScene, uv).g, texture2D(uScene, uv - c * k).b);
  vec2 eg = vec2(uv.x * 24.0, uv.y * 13.0 - uTime * 1.4);
  vec2 cell = floor(eg);
  vec2 f = fract(eg) - 0.5;
  float rnd = hash21(cell);
  vec2 off = vec2(hash21(cell + 7.1), hash21(cell + 3.3)) - 0.5;
  float ember = smoothstep(0.08, 0.0, length(f - off * 0.6)) * step(0.84 - 0.22 * uDrive, rnd);
  col += heat(uHue) * ember * (0.2 + 1.0 * uPulse) * smoothstep(0.95, 0.4, uv.y);
  float b0 = 0.035;
  float b1 = b0 + uBand;
  float ly = (uv.y - b0) / (b1 - b0);
  if (ly > -0.2 && ly < 1.3) {
    vec3 cop = vec3(0.0);
    for (int i = 0; i < 6; i++) {
      float fi = float(i);
      float cy = 0.5 + 0.42 * sin(uTime * 1.6 + fi * 0.62);
      float bar = clamp(1.0 - abs(ly - cy) / 0.085, 0.0, 1.0);
      cop = max(cop, copper(fi) * bar * bar * (3.0 - 2.0 * bar));
    }
    float inBand = step(0.0, ly) * step(ly, 1.0);
    col = mix(col, col * 0.25 + cop * 0.5, inBand);
    float wy = ly + sin(uv.x * 5.5 + uTime * 2.6) * 0.06;
    float tu = uv.x * (uRes.x / (uRes.y * uBand)) / uTextAspect + uScroll;
    float mask = 0.0;
    float shadow = 0.0;
    if (wy > 0.0 && wy < 1.0) mask = texture2D(uText, vec2(fract(tu), 1.0 - wy)).r;
    float sy = wy + 0.08;
    if (sy > 0.0 && sy < 1.0) shadow = texture2D(uText, vec2(fract(tu - 0.0025), 1.0 - sy)).r;
    col *= 1.0 - shadow * 0.8;
    col = mix(col, chrome(wy) * (1.0 + 0.35 * uPulse), mask);
  }
  col += heat(uHue) * uFlash * 0.12;
  col *= 0.8 + 0.2 * sin(gl_FragCoord.y * 1.5708);
  float mx = mod(gl_FragCoord.x, 3.0);
  col *= vec3(mx < 1.0 ? 1.08 : 0.9, (mx >= 1.0 && mx < 2.0) ? 1.08 : 0.9, mx >= 2.0 ? 1.08 : 0.9);
  col *= 1.0 - 1.1 * dot(c, c);
  col += (hash21(gl_FragCoord.xy + fract(uTime) * 100.0) - 0.5) * 0.04;
  col *= smoothstep(0.0, 0.012, uv.x) * smoothstep(0.0, 0.012, 1.0 - uv.x) * smoothstep(0.0, 0.012, uv.y) * smoothstep(0.0, 0.012, 1.0 - uv.y);
  gl_FragColor = vec4(col, 1.0);
}`;

/** The scroller's text as a white-on-black strip (a texture), heavy italic, sized to the GPU's limit. */
function scrollStrip(gl, text) {
  const max = Math.min(8192, gl.getParameter(gl.MAX_TEXTURE_SIZE) || 4096);
  let H = 96;
  const cv = document.createElement('canvas');
  const g = cv.getContext('2d');
  const font = (px) => `italic 900 ${px}px -apple-system, "SF Pro Display", "Helvetica Neue", Arial, sans-serif`;
  g.font = font(H * 0.74);
  let W = Math.ceil(g.measureText(text).width);
  if (W > max) { H = Math.floor(H * max / W); g.font = font(H * 0.74); W = Math.ceil(g.measureText(text).width); }
  cv.width = Math.min(max, W); cv.height = H;
  g.fillStyle = '#000'; g.fillRect(0, 0, cv.width, H);
  g.font = font(H * 0.74);
  g.fillStyle = '#fff'; g.textBaseline = 'middle';
  g.fillText(text, 0, H * 0.54);
  return { tex: texture(gl, cv), aspect: cv.width / H };
}

export function furnace(room) {
  const { ctx, store } = room;
  const m = shell(room, {
    key: 'furnace', title: 'Furnace', sub: 'a raymarched kick monolith', gl: true,
    note: 'Drag across: X. Drag up: Y. Pinch: the third. Two fingers or hold, then drag: fine. Double tap: those three back to the set. The cracks glow at the colour frequency; the floor ripples as deep as the sub.',
  });
  const picks = chips(room, m, [
    { role: 'X', hint: 'drag across', def: 'kick.drive' },
    { role: 'Y', hint: 'drag up and down', def: 'kick.colourFreq' },
    { role: 'Pinch', hint: 'pinch two fingers', def: 'mix.spaceMix' },
  ]);
  m.el.insertBefore(picks.el, m.tools);
  m.tools.remove();

  const hudL = h('span', { class: 'pl-hud-l', text: 'FURNACE' });
  const hudR = h('span', { class: 'pl-hud-r lcd-s', text: '001.1' });
  const hint = h('span', { class: 'pl-hud-hint', text: 'drag · pinch · double tap' });
  const scrollerText = () => {
    const [x, y, z] = picks.ids.map((id) => shortOf(room.params.get(id)).toUpperCase());
    return `HW002   ///   INDUSTRIAL HARD TECHNO AT 160 BPM   ///   THE KICK CARRIES THE GENRE   ///   DRAG ACROSS: ${x}   ///   DRAG UP: ${y}   ///   PINCH: ${z}   ///   THE CRACKS GLOW AT THE COLOUR FREQUENCY   ///   GREETINGS TO BSLS, DJ JS X REDLOTUS, KSMS AND REMON VERHOEVE   ///   `;
  };
  let flash = 0, textDirty = false;
  room.own(picks.onChange(() => { textDirty = true; }));

  const cv = glView(room, m, {
    setup(gl) {
      const st = {
        scene: new Program(gl, SCENE), post: new Program(gl, POST), tri: triangle(gl),
        rt: target(gl, 64, 64), text: scrollStrip(gl, scrollerText()),
        time: 0, scroll: 0, scale: 0.8, ema: 1 / 60, n: 0,
      };
      return st;
    },
    render(gl, st, dt, { W, H, w, h: hh }) {
      if (!st.scene.ready() || !st.post.ready()) return;
      if (textDirty) { textDirty = false; gl.deleteTexture(st.text.tex); st.text = scrollStrip(gl, scrollerText()); }
      const a = room.audio(), c = room.clock(), L = (id) => store.live(id);
      st.time += dt;
      st.ema = st.ema * 0.94 + dt * 0.06;
      if (++st.n % 40 === 0) {
        if (st.ema > 0.023 && st.scale > 0.45) st.scale *= 0.88;
        else if (st.ema < 0.0172 && st.scale < 1.0) st.scale = Math.min(1.0, st.scale * 1.06);
      }
      flash *= Math.exp(-dt * 5);
      room.stats.furnaceScale = st.scale;
      const sw = Math.max(64, Math.round(w * st.scale)), sh = Math.max(48, Math.round(hh * st.scale));
      st.rt.resize(sw, sh);
      const [X, Y] = picks.ids;
      gl.bindFramebuffer(gl.FRAMEBUFFER, st.rt.fbo);
      gl.viewport(0, 0, sw, sh);
      st.scene.use()
        .set('uRes', sw, sh).set('uTime', st.time).set('uPulse', a.pulse).set('uBeat', c.playing ? c.beatPhase : 0)
        .set('uDrive', L('kick.drive')).set('uHue', L('kick.colourFreq')).set('uBoost', clamp((L('kick.colour') - 0.5) * 2.2))
        .set('uSpace', L('mix.spaceMix')).set('uSub', L('kick.sub30')).set('uRumble', L('rumble.drive'))
        .set('uFlash', flash).set('uCam', L(X), L(Y));
      st.tri.draw();
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      gl.viewport(0, 0, W, H);
      const band = 0.17;
      st.scroll = (st.scroll + dt * 150 / (hh * band * st.text.aspect)) % 1;
      st.post.use().tex('uScene', 0, st.rt.tex).tex('uText', 1, st.text.tex)
        .set('uRes', W, H).set('uTime', st.time).set('uPulse', a.pulse).set('uAb', 0.6 + 2.4 * a.pulse + 1.6 * L('rumble.drive'))
        .set('uScroll', st.scroll).set('uTextAspect', st.text.aspect).set('uHue', L('kick.colourFreq'))
        .set('uDrive', L('kick.drive')).set('uFlash', flash).set('uBand', band);
      st.tri.draw();
      const t = c.playing ? barText(c) : 'STOP';
      if (hudR.textContent !== t) hudR.textContent = t;
    },
    dispose(gl, st) { st.scene.dispose(); st.post.dispose(); st.tri.dispose(); st.rt.dispose(); gl.deleteTexture(st.text.tex); },
  });
  m.view.append(h('div', { class: 'pl-hud' }, hudL, hint, hudR));

  let ws = null, hideTimer = 0;
  const show = (text) => { clearTimeout(hideTimer); hint.textContent = text; hint.classList.remove('is-gone'); };
  const hide = () => { clearTimeout(hideTimer); hideTimer = setTimeout(() => hint.classList.add('is-gone'), 1200); };
  room.own(() => clearTimeout(hideTimer));
  const begin = () => { ws = picks.ids.map((id) => writer(ctx, id, 'play')); ws.forEach((w) => w.begin()); };
  xyTouch(cv, {
    onStart: () => { begin(); m.el.classList.add('is-touched'); },
    onMove: (dx, dy) => {
      ws[0].add(dx / Math.max(200, cv.clientWidth)); ws[1].add(-dy / Math.max(200, cv.clientHeight));
      show(readout(room, picks.ids.slice(0, 2)));
    },
    onPinch: (dd) => { ws[2].add(dd / 260); show(readout(room, picks.ids.slice(2))); },
    onEnd: () => { ws?.forEach((w) => w.end()); ws = null; m.el.classList.remove('is-touched'); hide(); },
    onTap: () => { flash = 1; haptic(); },
    onDouble: () => {
      store.begin();
      for (const id of picks.ids) store.reset(id, { source: 'doubletap' });
      store.end();
      haptic(true);
      toast('Furnace: X, Y and pinch at the set\'s values');
    },
  });
  return room.add(m);
}
