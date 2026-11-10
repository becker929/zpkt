// Hand-written WebGL for the Play machines (WebGL 2 where there is one, else 1; the shaders are GLSL ES 1.00 so
// both run them): a context, programs, one big triangle, render targets, textures from a 2D canvas, and glView(),
// which hangs a GL canvas in a machine and looks after it (built lazily where a compile stall cannot starve the
// audio, resized, rebuilt after a context loss, released on unmount).

import { h } from '../ui.js';

export const VS = 'attribute vec2 aPos;varying vec2 vUv;void main(){vUv=aPos*0.5+0.5;gl_Position=vec4(aPos,0.0,1.0);}';

/** Shared GLSL: hashes, value noise, the furnace's heat colour (the kick's colour frequency as a temperature). */
export const GLSL_COMMON = `
float hash21(vec2 p){ p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float hash31(vec3 p){ p = fract(p * 0.3183099 + vec3(0.71, 0.113, 0.419)); p *= 17.0; return fract(p.x * p.y * p.z * (p.x + p.y + p.z)); }
float noise3(vec3 x){
  vec3 i = floor(x); vec3 f = fract(x); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(hash31(i), hash31(i + vec3(1.0, 0.0, 0.0)), f.x),
                 mix(hash31(i + vec3(0.0, 1.0, 0.0)), hash31(i + vec3(1.0, 1.0, 0.0)), f.x), f.y),
             mix(mix(hash31(i + vec3(0.0, 0.0, 1.0)), hash31(i + vec3(1.0, 0.0, 1.0)), f.x),
                 mix(hash31(i + vec3(0.0, 1.0, 1.0)), hash31(i + vec3(1.0, 1.0, 1.0)), f.x), f.y), f.z);
}
vec3 heat(float h){
  vec3 c1 = vec3(1.0, 0.10, 0.02); vec3 c2 = vec3(1.0, 0.40, 0.05); vec3 c3 = vec3(1.0, 0.80, 0.42); vec3 c4 = vec3(0.62, 0.80, 1.0);
  return h < 0.33 ? mix(c1, c2, h / 0.33) : (h < 0.66 ? mix(c2, c3, (h - 0.33) / 0.33) : mix(c3, c4, clamp((h - 0.66) / 0.34, 0.0, 1.0)));
}
`;

export function context(canvas) {
  const o = { alpha: false, antialias: false, depth: false, stencil: false, premultipliedAlpha: false, preserveDrawingBuffer: false, powerPreference: 'high-performance' };
  return canvas.getContext('webgl2', o) || canvas.getContext('webgl', o) || canvas.getContext('experimental-webgl', o);
}

function shader(gl, type, src) {
  const s = gl.createShader(type);
  gl.shaderSource(s, src);
  gl.compileShader(s);
  return s;
}

/** A program from a fragment shader. ready() is false while a parallel compile runs (KHR_parallel_shader_compile). */
export class Program {
  constructor(gl, fs, vs = VS) {
    this.gl = gl;
    this.vs = shader(gl, gl.VERTEX_SHADER, vs);
    this.fs = shader(gl, gl.FRAGMENT_SHADER, fs);
    this.p = gl.createProgram();
    gl.attachShader(this.p, this.vs);
    gl.attachShader(this.p, this.fs);
    gl.bindAttribLocation(this.p, 0, 'aPos');
    gl.linkProgram(this.p);
    this.ext = gl.getExtension('KHR_parallel_shader_compile');
    this.ok = null;
    this.locs = new Map();
  }

  ready() {
    if (this.ok != null) return this.ok;
    const gl = this.gl;
    if (this.ext && !gl.getProgramParameter(this.p, this.ext.COMPLETION_STATUS_KHR)) return false;
    if (!gl.getProgramParameter(this.p, gl.LINK_STATUS)) {
      const log = gl.getShaderInfoLog(this.fs) || gl.getShaderInfoLog(this.vs) || gl.getProgramInfoLog(this.p);
      this.ok = false;
      throw new Error(`shader: ${log}`);
    }
    this.ok = true;
    return true;
  }

  use() { this.gl.useProgram(this.p); return this; }

  u(name) {
    if (!this.locs.has(name)) this.locs.set(name, this.gl.getUniformLocation(this.p, name));
    return this.locs.get(name);
  }

  /** set('uTime', t) / set('uRes', w, h) / ...: uniform1f..4f by the number of values. */
  set(name, a, b, c, d) {
    const gl = this.gl, l = this.u(name);
    if (l == null) return this;
    if (d !== undefined) gl.uniform4f(l, a, b, c, d);
    else if (c !== undefined) gl.uniform3f(l, a, b, c);
    else if (b !== undefined) gl.uniform2f(l, a, b);
    else gl.uniform1f(l, a);
    return this;
  }

  tex(name, unit, texture) {
    const gl = this.gl;
    gl.activeTexture(gl.TEXTURE0 + unit);
    gl.bindTexture(gl.TEXTURE_2D, texture);
    const l = this.u(name);
    if (l != null) gl.uniform1i(l, unit);
    return this;
  }

  dispose() {
    const gl = this.gl;
    gl.deleteProgram(this.p); gl.deleteShader(this.vs); gl.deleteShader(this.fs);
  }
}

/** The one big triangle every pass draws. */
export function triangle(gl) {
  const b = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, b);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  return {
    draw() {
      gl.bindBuffer(gl.ARRAY_BUFFER, b);
      gl.enableVertexAttribArray(0);
      gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    },
    dispose() { gl.deleteBuffer(b); },
  };
}

function texParams(gl, wrap = gl.CLAMP_TO_EDGE) {
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, wrap);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, wrap);
}

/** A render target (texture + framebuffer) of w x h; resize(w, h) reallocates. */
export function target(gl, w, h) {
  const tex = gl.createTexture();
  const fbo = gl.createFramebuffer();
  const t = {
    tex, fbo, w: 0, h: 0,
    resize(W, H) {
      if (W === t.w && H === t.h) return;
      t.w = W; t.h = H;
      gl.bindTexture(gl.TEXTURE_2D, tex);
      texParams(gl);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, W, H, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    },
    dispose() { gl.deleteTexture(tex); gl.deleteFramebuffer(fbo); },
  };
  t.resize(w, h);
  return t;
}

/** A texture from a canvas (or image); `repeat` only for power-of-two sizes. */
export function texture(gl, source, { repeat = false } = {}) {
  const tex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, source);
  texParams(gl, repeat ? gl.REPEAT : gl.CLAMP_TO_EDGE);
  return tex;
}

/**
 * A GL canvas in machine `m`: m.draw is set to build on first sight (where a stall is safe), then render.
 * setup(gl) -> state (programs not necessarily ready); render(gl, state, dt, {W, H, w, h}) draws a frame;
 * dispose(gl, state) frees. Pixel ratio capped at `dprMax`.
 */
export function glView(room, m, { setup, render, dispose, dprMax = 2 } = {}) {
  const cv = h('canvas', { class: 'pl-gl' });
  const msg = h('div', { class: 'pl-gl-msg', hidden: true });
  m.view.append(cv, msg);
  m.canvas = cv;
  let gl = null, st = null, failed = false, pending = false, lost = false;
  const fail = (text, err) => {
    failed = true;
    msg.textContent = text;
    msg.hidden = false;
    if (err) console.warn(`play/${m.key}:`, err.message || err);
  };
  // iOS can take a context back (memory, the app in the background): wait for it to come back, then rebuild.
  cv.addEventListener('webglcontextlost', (e) => { e.preventDefault(); lost = true; gl = null; st = null; });
  cv.addEventListener('webglcontextrestored', () => { lost = false; pending = false; });
  const build = () => {
    pending = false;
    if (!room.stats.mounted || lost) return;
    const t0 = performance.now();
    gl = context(cv);
    if (!gl) { fail('No WebGL on this browser: this machine stays dark.'); return; }
    if (gl.isContextLost()) { gl = null; return; }
    try { st = setup(gl); } catch (err) { gl = null; fail('This machine\'s shader did not build.', err); }
    (room.stats.build ??= {})[m.key] = Math.round(performance.now() - t0);
  };
  m.draw = (dt) => {
    if (failed || lost) return;
    if (!gl || !st) {
      if (!pending) { pending = true; room.whenSafe(build); }
      return;
    }
    const dpr = Math.min(devicePixelRatio || 1, dprMax);
    const w = Math.max(1, cv.clientWidth), hh = Math.max(1, cv.clientHeight);
    const W = Math.round(w * dpr), H = Math.round(hh * dpr);
    if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
    try { render(gl, st, dt, { W, H, w, h: hh, dpr }); } catch (err) { fail('This machine\'s shader did not build.', err); }
  };
  m.destroy = () => {
    if (gl && st) { try { dispose?.(gl, st); } catch { /* the context may be gone */ } }
    try { gl?.getExtension('WEBGL_lose_context')?.loseContext(); } catch { /* fine */ }
    gl = null; st = null;
  };
  m.glState = () => ({ gl: !!gl, failed, pending });
  return cv;
}

/** Drag and pinch on a GL view, for writing params: onMove(dx, dy, fine), onPinch(dDistance), taps. */
export function xyTouch(el, { onStart, onMove, onPinch, onEnd, onTap, onDouble }) {
  el.style.touchAction = 'none';
  const pts = new Map();
  let moved = false, fine = false, t0 = 0, x0 = 0, y0 = 0, last = -Infinity, spread = 0, active = false;
  const dist = () => { const [a, b] = [...pts.values()]; return Math.hypot(a.x - b.x, a.y - b.y); };
  el.addEventListener('pointerdown', (e) => {
    try { el.setPointerCapture?.(e.pointerId); } catch { /* synthetic pointers */ }
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 1) { moved = false; fine = false; t0 = performance.now(); x0 = e.clientX; y0 = e.clientY; active = true; onStart?.(e); }
    else if (pts.size === 2) { spread = dist(); moved = true; }
  });
  el.addEventListener('pointermove', (e) => {
    const p = pts.get(e.pointerId);
    if (!p) return;
    const dx = e.clientX - p.x, dy = e.clientY - p.y;
    p.x = e.clientX; p.y = e.clientY;
    if (pts.size >= 2) { const d = dist(); onPinch?.(d - spread, e); spread = d; return; }
    if (!moved) {
      if (Math.hypot(e.clientX - x0, e.clientY - y0) < 5) return;
      moved = true;
      if (performance.now() - t0 > 380) fine = true;
    }
    const k = fine ? 0.25 : 1;
    onMove?.(dx * k, dy * k, fine, e);
  });
  const up = (e) => {
    if (!pts.has(e.pointerId)) return;
    pts.delete(e.pointerId);
    if (pts.size || !active) return;
    active = false;
    if (!moved && e.type === 'pointerup' && Math.hypot(e.clientX - x0, e.clientY - y0) < 10) {
      const now = performance.now();
      if (now - last < 320) { last = -Infinity; onDouble?.(e); } else { last = now; onTap?.(e); }
    }
    onEnd?.(e, moved);
  };
  el.addEventListener('pointerup', up);
  el.addEventListener('pointercancel', up);
  el.addEventListener('contextmenu', (e) => e.preventDefault());
}
