// Tunnel: three demoscene parts on one CRT, locked to the kick. A steel tunnel whose rings rush past one per beat
// (a hazard ring on every bar), an old-school plasma, and a rotozoomer over an HW002 floor plate.
//
// Drag across = X (the Decapitator's drive: the tunnel twists, the plasma tightens, the plate spins), drag up = Y
// (the 30 Hz shelf: the tunnel breathes deeper on the kick, the plasma warps, the plate zooms out), pinch = the
// third (colour boost: the seams burn). The panels are coloured by the kick's colour frequency, the far light by
// the master's mids. Double tap: the three back to the set.

import { h, haptic, toast } from '../ui.js';
import { writer } from '../widgets/core.js';
import { GLSL_COMMON, Program, glView, texture, triangle, xyTouch } from './gl.js';
import { barText, chips, load, readout, save, segments, shell } from './room.js';

const HEAD = `precision highp float;
varying vec2 vUv;
uniform vec2 uRes;
uniform float uTime, uBeats, uPulse, uX, uY, uZ, uHue, uDrive, uMid, uHigh;
uniform sampler2D uTile;
${GLSL_COMMON}
const vec3 MAGENTA = vec3(1.0, 0.24, 0.95);
const vec3 HAZARD = vec3(1.0, 0.36, 0.08);
`;

// The CRT around every part: barrel, chromatic split (three looks at the scene), scanlines, mask, vignette, grain.
const TAIL = `
void main(){
  vec2 q = vUv * 2.0 - 1.0;
  q *= 1.0 + 0.04 * dot(q, q);
  vec2 uv = q * 0.5 + 0.5;
  if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) { gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0); return; }
  vec2 p = (uv - 0.5) * 2.0 * vec2(uRes.x / uRes.y, 1.0);
  float k = 0.006 + 0.03 * uPulse + 0.012 * uDrive;
  vec3 col = vec3(scene(p * (1.0 + k)).r, scene(p).g, scene(p * (1.0 - k)).b);
  col = 1.0 - exp(-col * 1.5);
  col *= 0.8 + 0.2 * sin(gl_FragCoord.y * 1.5708);
  float mx = mod(gl_FragCoord.x, 3.0);
  col *= vec3(mx < 1.0 ? 1.08 : 0.9, (mx >= 1.0 && mx < 2.0) ? 1.08 : 0.9, mx >= 2.0 ? 1.08 : 0.9);
  vec2 c = uv - 0.5;
  col *= 1.0 - 1.1 * dot(c, c);
  col += (hash21(gl_FragCoord.xy + fract(uTime) * 100.0) - 0.5) * 0.035;
  col *= smoothstep(0.0, 0.012, uv.x) * smoothstep(0.0, 0.012, 1.0 - uv.x) * smoothstep(0.0, 0.012, uv.y) * smoothstep(0.0, 0.012, 1.0 - uv.y);
  gl_FragColor = vec4(col, 1.0);
}`;

const TUNNEL = `${HEAD}
vec3 scene(vec2 p){
  p += vec2(sin(uTime * 0.37), cos(uTime * 0.29)) * 0.08;
  float r = length(p);
  float a = atan(p.y, p.x);
  float breathe = 1.0 + 0.16 * uPulse * (0.25 + 1.2 * uY);
  float z = 0.32 / max(r * breathe, 0.001);
  float twist = (uX - 0.15) * 1.6;
  float segs = floor(mix(8.0, 20.0, uHue));
  float u = a / 6.2831853 * segs + z * twist * segs * 0.25 + uTime * 0.03 * segs;
  float v = z * 3.0 + uBeats;
  vec2 c = fract(vec2(u, v));
  vec2 id = floor(vec2(u, v));
  id.x = mod(id.x, segs);
  float e = min(min(c.x, 1.0 - c.x), min(c.y, 1.0 - c.y));
  float seam = smoothstep(0.08, 0.0, e);
  float n = hash21(id);
  vec3 hc = heat(uHue);
  vec3 col = vec3(0.06, 0.06, 0.07) * (0.35 + 0.9 * n) * (0.8 + 0.2 * sin(c.x * 40.0 + n * 9.0));
  col += smoothstep(0.05, 0.025, length(abs(c - 0.5) - vec2(0.38))) * 0.35;
  float bar4 = 1.0 - step(0.5, mod(id.y, 4.0));
  float stripes = step(0.5, fract(c.x * 2.0 + c.y * 1.0));
  col = mix(col, mix(vec3(0.015), HAZARD, stripes), bar4 * 0.9);
  col += hc * step(0.84, n) * (0.25 + 2.2 * uMid) * 0.6;
  float front = exp(-fract(v) * 5.0) * uPulse;
  col += seam * (MAGENTA * 0.3 + hc * (0.4 + 2.4 * uZ) * (0.3 + 1.6 * uPulse));
  col += hc * front * 0.35 * (0.3 + uZ);
  col *= smoothstep(0.0, 0.3, r) * (0.55 + 0.45 * smoothstep(9.0, 1.0, z));
  col += hc * exp(-r * 8.0) * (0.4 + 2.2 * uMid + uPulse);
  col += MAGENTA * exp(-r * 18.0) * 0.5;
  return col;
}
${TAIL}`;

const PLASMA = `${HEAD}
vec3 pal(float b){
  vec3 hc = heat(uHue);
  if (b < 0.25) return mix(vec3(0.01, 0.0, 0.02), MAGENTA * 0.55, b / 0.25);
  if (b < 0.5) return mix(MAGENTA * 0.55, HAZARD, (b - 0.25) / 0.25);
  if (b < 0.75) return mix(HAZARD, hc, (b - 0.5) / 0.25);
  return mix(hc, vec3(1.0, 0.97, 0.9), (b - 0.75) / 0.25);
}
vec3 scene(vec2 p){
  float t = uTime * 0.55;
  float f = mix(1.6, 7.0, uX);
  vec2 q = p * f;
  q += vec2(sin(q.y * 0.7 + t), cos(q.x * 0.6 - t)) * (0.2 + 2.2 * uY);
  float v = sin(q.x + t) + sin((q.y + t) * 0.8) + sin((q.x + q.y) * 0.6 + t * 1.3)
          + sin(length(q + vec2(sin(t * 0.7), cos(t * 0.5)) * 3.0) * 1.2 - t);
  float b = 0.5 + 0.5 * sin(v * 0.25 * 6.2831853 + uBeats * 0.25 + uPulse * 1.2);
  float levels = mix(26.0, 5.0, uDrive);
  b = floor(b * levels) / levels;
  vec3 col = pal(b) * (0.55 + 0.35 * uZ + 0.6 * uPulse);
  return col;
}
${TAIL}`;

const ROTO = `${HEAD}
vec3 scene(vec2 p){
  float ang = uTime * (0.1 + uX * 0.8) + uPulse * 0.04;
  float zoom = mix(0.55, 3.2, uY) * (1.0 - 0.14 * uPulse) * (1.0 + 0.25 * sin(uTime * 0.37));
  float cs = cos(ang); float sn = sin(ang);
  vec2 q = mat2(cs, -sn, sn, cs) * p * zoom + vec2(uTime * 0.07, uBeats * 0.125);
  q += sin(q.yx * 4.0 + uTime * 1.7) * 0.03 * (0.2 + 2.0 * uDrive);
  vec3 col = texture2D(uTile, q).rgb;
  col *= 0.75 + 0.4 * uZ + 0.9 * uPulse;
  col += heat(uHue) * uPulse * 0.08;
  return col;
}
${TAIL}`;

/** The rotozoomer's tile: a floor plate, 256 px (power of two, so it can repeat). */
function plateTile() {
  const N = 256, cv = document.createElement('canvas');
  cv.width = cv.height = N;
  const g = cv.getContext('2d');
  const grd = g.createLinearGradient(0, 0, N, N);
  grd.addColorStop(0, '#1d1f24'); grd.addColorStop(1, '#0d0e11');
  g.fillStyle = grd; g.fillRect(0, 0, N, N);
  g.strokeStyle = 'rgba(255,255,255,0.05)';
  for (let y = 0; y < N; y += 3) { g.beginPath(); g.moveTo(0, y + 0.5); g.lineTo(N, y + 0.5); g.stroke(); }
  g.save();
  g.beginPath(); g.rect(0, N * 0.74, N, N * 0.2); g.clip();
  g.fillStyle = '#0a0a0a'; g.fillRect(0, N * 0.74, N, N * 0.2);
  g.fillStyle = '#ff5a1f';
  for (let x = -N; x < N * 2; x += 32) { g.beginPath(); g.moveTo(x, N * 0.94); g.lineTo(x + 16, N * 0.94); g.lineTo(x + 16 + N * 0.2, N * 0.74); g.lineTo(x + N * 0.2, N * 0.74); g.fill(); }
  g.restore();
  g.font = `italic 900 ${N * 0.3}px -apple-system, "Helvetica Neue", Arial, sans-serif`;
  g.textAlign = 'center'; g.textBaseline = 'middle';
  const tg = g.createLinearGradient(0, N * 0.22, 0, N * 0.58);
  tg.addColorStop(0, '#2a2f9e'); tg.addColorStop(0.48, '#fbe9ff'); tg.addColorStop(0.5, '#ffffff'); tg.addColorStop(0.52, '#5a1a10'); tg.addColorStop(1, '#ff9a4a');
  g.fillStyle = '#000'; g.fillText('HW002', N / 2 + 4, N * 0.42 + 4);
  g.fillStyle = tg; g.fillText('HW002', N / 2, N * 0.42);
  g.strokeStyle = '#ff3df2'; g.lineWidth = 2; g.strokeText('HW002', N / 2, N * 0.42);
  for (const [x, y] of [[14, 14], [N - 14, 14], [14, N * 0.66], [N - 14, N * 0.66]]) {
    const rg = g.createRadialGradient(x - 2, y - 2, 1, x, y, 7);
    rg.addColorStop(0, '#8a909c'); rg.addColorStop(1, '#16181c');
    g.fillStyle = rg; g.beginPath(); g.arc(x, y, 6, 0, Math.PI * 2); g.fill();
  }
  g.strokeStyle = '#000'; g.lineWidth = 3; g.strokeRect(1.5, 1.5, N - 3, N - 3);
  return cv;
}

const SCENES = [['Tunnel', TUNNEL], ['Plasma', PLASMA], ['Rotozoom', ROTO]];

export function tunnel(room) {
  const { ctx, store } = room;
  const m = shell(room, {
    key: 'tunnel', title: 'Tunnel', sub: 'three demo parts on the kick', gl: true,
    note: 'Rings rush past one per beat, a hazard ring every bar. Drag across: X. Drag up: Y. Pinch: the third. Double tap: the three back to the set.',
  });
  const picks = chips(room, m, [
    { role: 'X', hint: 'drag across', def: 'rumble.drive' },
    { role: 'Y', hint: 'drag up and down', def: 'kick.sub30' },
    { role: 'Pinch', hint: 'pinch two fingers', def: 'kick.colour' },
  ]);
  m.el.insertBefore(picks.el, m.tools);
  let scene = Math.min(SCENES.length - 1, Math.max(0, load('tunnel.scene', 0)));
  const hudL = h('span', { class: 'pl-hud-l', text: SCENES[scene][0].toUpperCase() });
  const hudR = h('span', { class: 'pl-hud-r lcd-s', text: '001.1' });
  const hint = h('span', { class: 'pl-hud-hint is-gone' });
  let hideTimer = 0;
  const show = (text) => { clearTimeout(hideTimer); hint.textContent = text; hint.classList.remove('is-gone'); };
  const hide = () => { clearTimeout(hideTimer); hideTimer = setTimeout(() => hint.classList.add('is-gone'), 1200); };
  room.own(() => clearTimeout(hideTimer));
  const seg = segments(SCENES.map(([n]) => n), scene, (i) => { scene = i; save('tunnel.scene', i); hudL.textContent = SCENES[i][0].toUpperCase(); });
  m.tools.append(seg.el);

  const cv = glView(room, m, {
    dprMax: 1.5,
    setup(gl) {
      return { progs: SCENES.map(([, fs]) => new Program(gl, fs)), tri: triangle(gl), tile: texture(gl, plateTile(), { repeat: true }), time: 0 };
    },
    render(gl, st, dt, { W, H }) {
      const prog = st.progs[scene];
      if (!prog.ready()) return;
      const a = room.audio(), c = room.clock(), L = (id) => store.live(id);
      st.time += dt;
      const [X, Y, Z] = picks.ids;
      gl.viewport(0, 0, W, H);
      prog.use().tex('uTile', 0, st.tile)
        .set('uRes', W, H).set('uTime', st.time).set('uBeats', c.beats).set('uPulse', a.pulse)
        .set('uX', L(X)).set('uY', L(Y)).set('uZ', L(Z)).set('uHue', L('kick.colourFreq')).set('uDrive', L('rumble.drive'))
        .set('uMid', a.mid).set('uHigh', a.high);
      st.tri.draw();
      const t = c.playing ? barText(c) : 'STOP';
      if (hudR.textContent !== t) hudR.textContent = t;
    },
    dispose(gl, st) { st.progs.forEach((p) => p.dispose()); st.tri.dispose(); gl.deleteTexture(st.tile); },
  });
  m.view.append(h('div', { class: 'pl-hud' }, hudL, hint, hudR));

  let ws = null;
  xyTouch(cv, {
    onStart: () => { ws = picks.ids.map((id) => writer(ctx, id, 'play')); ws.forEach((w) => w.begin()); },
    onMove: (dx, dy) => {
      ws[0].add(dx / Math.max(200, cv.clientWidth)); ws[1].add(-dy / Math.max(200, cv.clientHeight));
      show(readout(room, picks.ids.slice(0, 2)));
    },
    onPinch: (dd) => { ws[2].add(dd / 260); show(readout(room, picks.ids.slice(2))); },
    onEnd: () => { ws?.forEach((w) => w.end()); ws = null; hide(); },
    onTap: () => haptic(),
    onDouble: () => {
      store.begin();
      for (const id of picks.ids) store.reset(id, { source: 'doubletap' });
      store.end();
      haptic(true);
      toast('Tunnel: X, Y and pinch at the set\'s values');
    },
  });
  return room.add(m);
}
