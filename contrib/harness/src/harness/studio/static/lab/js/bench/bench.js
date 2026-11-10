// The Bench: a Max-style patcher for the phone. A dark floor with a faint grid that pans (drag the floor) and
// zooms (pinch, or the - and + buttons); boxes on it, each a widget from the library bound to params from any stage
// or a modulator on the bar clock, with a Max title bar ("live.dial kick.drive"), inlets on top and outlets
// underneath as little dark tabs; patch cords as drooping grey cables that light up cold blue while a signal runs
// through them.
//
//   tap a box             select it (the toolbar offers duplicate and delete)
//   drag a title bar      move the box (it snaps to the grid when you let go)
//   drag from an outlet   pull a cord; let go on an inlet to patch (the inlets you can reach light up)
//   long-press a cord     cut it (or tap it and press the cut button)
//   + object              the toolbox: modulators, controls, meters, comments
//   RUN / STOP            the modulators start stopped; RUN sets them going (on the bar clock), STOP halts them and
//                         takes every offset they put on params off again. The state is kept with the patch.
//
// A modulator patched into a param box moves its params (store.modulate through the widgets' modulation mixer:
// added to the knob, never saved); a one-param box patched into another param box drags that param along with its
// own move from the set; anything patched into a modulator scales its depth. Cutting a cord, deleting a box or
// leaving the surface takes the modulation off. The patch is kept on this phone.

import { drag, h, haptic, s, toast } from '../ui.js';
import { setNorm } from '../params.js';
import { barClock, modSource, tick } from '../widgets/kit.js';
import { TYPES, paramsOf, ports, titleOf } from './types.js';
import { modBody, modState, shape } from './mods.js';
import { defaultPatch, loadPatch, nextId, savePatch } from './patch.js';
import { openToolbox } from './toolbox.js';

const WORLD = 4000, GRID = 16, SNAP = 8, ZMIN = 0.35, ZMAX = 2.2;
const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
const cordKey = (c) => `${c.from[0]}:${c.from[1]}>${c.to[0]}:${c.to[1]}`;

const ICONS = {
  plus: 'M12 5v14M5 12h14',
  fit: 'M3 8V3h5M21 8V3h-5M3 16v5h5M21 16v5h-5M9 9h6v6H9z',
  minus: 'M5 12h14',
  zoom: 'M12 5v14M5 12h14',
  full: 'M14 4h6v6M20 4l-7 7M10 20H4v-6M4 20l7-7',
  shrink: 'M13 11h6M13 11V5M13 11l7-7M11 13H5M11 13v6M11 13l-7 7',
  dup: 'M8 8h12v12H8zM4 16V4h12',
  trash: 'M4 7h16M10 7V4h4v3M6 7l1 13h10l1-13',
  cut: 'M6 6l12 12M6 18L18 6',
  play: 'M8 5v14l11-7z',
  stop: 'M7 7h10v10H7z',
};
const icon = (name) => s('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true', class: 'bn-ic' }, s('path', { d: ICONS[name] }));

export class Bench {
  constructor(root, ctx) {
    this.root = root;
    this.ctx = ctx;
    this.patch = loadPatch(ctx.params);
    this.boxes = new Map();
    this.cordEls = new Map();
    this.mod = modSource(ctx, 'bench');
    this.clock = barClock(ctx.engine);
    this.written = new Map();
    this.view = { tx: 0, ty: 0, z: 1 };
    this.selected = null;
    this.selectedCord = null;
    this.visible = true;
    this.dead = false;
    this.running = !!this.patch.running;          // modulators move only while running (they start stopped)
    this.runFns = new Set();
    this.dirty = true;                            // modulator displays to redraw while stopped
    this.cleanups = [];
    this._build();
    for (const obj of this.patch.objects) this._addBox(obj);
    this._wire();
    this._routeAll();
    this._order();
    tick(ctx, () => this._run());
    ctx.own(() => this.destroy());
  }

  // --- building ------------------------------------------------------------------------------------------------
  _build() {
    const btn = (name, label, fn, cls = '') => {
      const b = h('button', { type: 'button', class: `bn-btn ${cls}`.trim(), 'aria-label': label, title: label }, icon(name));
      b.addEventListener('click', (e) => { e.stopPropagation(); haptic(); fn(); });
      return b;
    };
    this.cords = s('svg', { class: 'bn-cords', width: WORLD, height: WORLD, viewBox: `0 0 ${WORLD} ${WORLD}` });
    this.over = s('svg', { class: 'bn-over', width: WORLD, height: WORLD, viewBox: `0 0 ${WORLD} ${WORLD}` });
    this.temp = s('path', { class: 'cd-temp' });
    this.over.append(this.temp);
    this.world = h('div', { class: 'bn-world' }, this.cords, this.over);
    this.vp = h('div', { class: 'bn-vp', role: 'application', 'aria-label': 'The bench: a patcher' }, this.world);
    this.zoomRead = h('button', { type: 'button', class: 'bn-zoom', title: 'Back to 100 %', onclick: () => { haptic(); this.zoomTo(1); } });
    this.selName = h('span', { class: 'bn-sel' });
    this.selActs = h('span', { class: 'bn-acts' },
      btn('dup', 'Duplicate', () => this.duplicate(this.selected)),
      this.delBtn = btn('trash', 'Delete (tap twice)', () => this._armDelete(), 'is-danger'));
    this.cutBtn = btn('cut', 'Cut this cord', () => this.cut(this.selectedCord), 'is-danger');
    this.fullBtn = btn('full', 'Full screen', () => this.toggleFull());
    const add = h('button', { type: 'button', class: 'bn-add' }, icon('plus'), h('span', { text: 'object' }));
    add.addEventListener('click', () => { haptic(); this.toolbox(); });
    this.runBtn = h('button', { type: 'button', class: 'bn-run', 'aria-pressed': 'false' });
    this.runBtn.addEventListener('click', (e) => { e.stopPropagation(); haptic(true); if (this.running) this.stop(); else this.start(); });
    this.bar = h('div', { class: 'bn-bar' }, add, this.runBtn, this.selName, this.selActs, this.cutBtn,
      h('span', { class: 'bn-view' }, this.zoomRead, btn('fit', 'Show everything', () => this.fit()), this.fullBtn));
    this.el = h('div', { class: 'bench' }, this.vp, this.bar);
    this.root.append(this.el);
    this._select(null);
    this._paintRun();
  }

  _addBox(obj) {
    const t = TYPES[obj.type];
    const cleanups = [];
    const octx = { ...this.ctx, own: (fn) => { if (typeof fn === 'function') cleanups.push(fn); return fn; } };
    const box = { obj, cleanups, h: 120, out: 0, mod: null };
    const p0 = paramsOf(obj)[0] ? this.ctx.params.get(paramsOf(obj)[0]) : null;
    const name = h('span', { class: 'bx-arg' });
    const title = h('div', { class: 'bx-title' }, name);
    let body;
    try {
      if (t.kind === 'mod') {
        obj.state = modState(obj.type, obj.state);
        box.mod = modBody(octx, obj, () => { name.textContent = box.mod.title(); this.dirty = true; this.save(); });
        body = box.mod.el;
      } else {
        body = t.build(octx, obj, { state: obj.state, onState: (st) => { obj.state = st; this.save(); }, gate: () => this.running });
      }
    } catch (err) {
      console.error(err);
      body = h('p', { class: 'bn-note', text: `This box broke: ${err.message}` });
    }
    const { ins, outs } = ports(obj);
    box.ins = Array.from({ length: ins }, (_, i) => h('i', { class: 'bx-in', dataset: { port: i }, style: { left: `${10 + i * 26}px` } }));
    box.outs = Array.from({ length: outs }, (_, i) => h('i', { class: `bx-out${t.kind === 'mod' ? ' is-signal' : ''}`, dataset: { port: i }, style: { left: `${10 + i * 26}px` } }));
    const width = t.width ?? (obj.type === 'multislider' ? obj.params.length * 44 + 26 : 200);
    box.el = h('div', {
      class: `bx is-${t.kind}`, dataset: { id: obj.id, type: obj.type },
      style: { left: `${obj.x}px`, top: `${obj.y}px`, width: `${width}px`, '--c': t.kind === 'mod' ? 'var(--cold)' : p0 ? `var(--stage-${p0.stage})` : 'var(--steel-4)' },
    }, t.kind === 'note' ? null : title, h('div', { class: 'bx-body' }, body), ...box.ins, ...box.outs);
    name.textContent = box.mod ? box.mod.title() : titleOf(obj, this.ctx.params);
    this.world.insertBefore(box.el, this.over);
    this.boxes.set(obj.id, box);

    // the title bar selects and moves the box (a comment: its whole body); playing a widget does not select it
    const handle = t.kind === 'note' ? box.el : title;
    handle.addEventListener('pointerdown', () => this._select(obj.id));
    drag(handle, {
      onStart: () => { box.el.classList.add('is-moving'); haptic(); },
      onMove: (dx, dy) => {
        obj.x = clamp(obj.x + dx / this.view.z, 0, WORLD - 60);
        obj.y = clamp(obj.y + dy / this.view.z, 0, WORLD - 60);
        this._place(box);
      },
      onEnd: (_e, moved) => {
        box.el.classList.remove('is-moving');
        if (!moved) return;
        obj.x = Math.round(obj.x / SNAP) * SNAP; obj.y = Math.round(obj.y / SNAP) * SNAP;
        this._place(box);
        this.save();
      },
    });
    for (const o of box.outs) o.addEventListener('pointerdown', (e) => this._patchFrom(e, obj.id, Number(o.dataset.port)));
    if ('ResizeObserver' in window) {
      const ro = new ResizeObserver(() => { box.h = box.el.offsetHeight; this._routeBox(obj.id); });
      ro.observe(box.el);
      cleanups.push(() => ro.disconnect());
    }
    box.h = box.el.offsetHeight || box.h;
    return box;
  }

  _place(box) {
    box.el.style.left = `${box.obj.x}px`;
    box.el.style.top = `${box.obj.y}px`;
    this._routeBox(box.obj.id);
  }

  // --- the floor: pan, pinch, wheel ------------------------------------------------------------------------------
  _wire() {
    const vp = this.vp;
    vp.style.touchAction = 'none';
    const pts = new Map();
    let mode = null, moved = false, last = null, pinch = null, press = null;
    const isFloor = (t) => t === vp || t === this.world || t === this.cords || t?.classList?.contains('cd-hit');
    const down = (e) => {
      if (!isFloor(e.target)) return;
      if (e.isPrimary) pts.clear();                         // a new gesture: forget any finger whose lift we missed
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      try { vp.setPointerCapture(e.pointerId); } catch { /* synthetic pointer */ }
      if (pts.size === 1) {
        mode = 'pan'; moved = false; last = { x: e.clientX, y: e.clientY };
        const key = e.target.classList?.contains('cd-hit') ? e.target.dataset.key : null;
        clearTimeout(press?.timer);
        press = key ? { key, x: e.clientX, y: e.clientY, timer: setTimeout(() => { if (!moved) { mode = null; pts.clear(); press = null; this.cut(key, true); } }, 520), arm: setTimeout(() => { if (!moved) this.cordEls.get(key)?.g.classList.add('is-armed'); }, 200) } : null;
      } else if (pts.size === 2) {
        const [a, b] = [...pts.values()];
        const r = vp.getBoundingClientRect();
        const mx = (a.x + b.x) / 2 - r.left, my = (a.y + b.y) / 2 - r.top;
        pinch = { d: Math.hypot(a.x - b.x, a.y - b.y) || 1, z: this.view.z, wx: (mx - this.view.tx) / this.view.z, wy: (my - this.view.ty) / this.view.z };
        mode = 'pinch'; moved = true; this._unpress(press); press = null;
      }
    };
    const move = (e) => {
      if (!pts.has(e.pointerId)) return;
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (mode === 'pan') {
        if (!moved && Math.hypot(e.clientX - (press?.x ?? last.x), e.clientY - (press?.y ?? last.y)) > 6) { moved = true; this._unpress(press); press = null; }
        if (!moved) return;
        this.view.tx += e.clientX - last.x; this.view.ty += e.clientY - last.y;
        last = { x: e.clientX, y: e.clientY };
        this._applyView();
      } else if (mode === 'pinch' && pts.size >= 2) {
        const [a, b] = [...pts.values()];
        const r = vp.getBoundingClientRect();
        const z = clamp(pinch.z * (Math.hypot(a.x - b.x, a.y - b.y) / pinch.d), ZMIN, ZMAX);
        const mx = (a.x + b.x) / 2 - r.left, my = (a.y + b.y) / 2 - r.top;
        this.view = { z, tx: mx - pinch.wx * z, ty: my - pinch.wy * z };
        this._applyView();
      }
    };
    const up = (e) => {
      if (!pts.has(e.pointerId)) return;
      pts.delete(e.pointerId);
      if (pts.size === 1 && mode === 'pinch') { mode = 'pan'; last = [...pts.values()][0]; return; }
      if (pts.size) return;
      const tapped = mode === 'pan' && !moved && e.type === 'pointerup';
      if (press && tapped) { this._unpress(press); this._selectCord(press.key); press = null; mode = null; return; }
      this._unpress(press); press = null;
      if (tapped) { this._select(null); this._selectCord(null); }
      if (moved) this.save();
      mode = null;
    };
    // an overflow box can still be scrolled by the browser (a focused input, scrollIntoView): the view is ours
    vp.addEventListener('scroll', () => { if (vp.scrollTop || vp.scrollLeft) { vp.scrollTop = 0; vp.scrollLeft = 0; } });
    vp.addEventListener('pointerdown', down);
    vp.addEventListener('pointermove', move);
    vp.addEventListener('pointerup', up);
    vp.addEventListener('pointercancel', up);
    vp.addEventListener('wheel', (e) => {
      e.preventDefault();
      const r = vp.getBoundingClientRect();
      if (e.ctrlKey || e.metaKey) this.zoomBy(Math.exp(-e.deltaY / 200), e.clientX - r.left, e.clientY - r.top);
      else { this.view.tx -= e.deltaX; this.view.ty -= e.deltaY; this._applyView(); this.save(); }
    }, { passive: false });

    // the view once the bench has a size; draw the modulators only while the bench is on screen
    const init = () => this._initView();
    if ('ResizeObserver' in window) {
      const ro = new ResizeObserver(() => { init(); if (this.full) this._placeFull(); });
      ro.observe(vp);
      this.cleanups.push(() => ro.disconnect());
    }
    requestAnimationFrame(init);
    if ('IntersectionObserver' in window) {
      const io = new IntersectionObserver((es) => { this.visible = es.some((x) => x.isIntersecting); });
      io.observe(vp);
      this.cleanups.push(() => io.disconnect());
    }
    const onResize = () => { if (this.full) this._placeFull(); };
    window.addEventListener('resize', onResize);
    this.cleanups.push(() => window.removeEventListener('resize', onResize));
  }

  /** The first view: the saved one, or the top of the patch at a width that fits the phone. */
  _initView(fresh = false) {
    const vp = this.vp;
    if ((this.inited && !fresh) || !vp.clientWidth) return;
    this.inited = true;
    const v = fresh ? null : this.patch.view;
    if (v && Number.isFinite(v.z)) this.view = { tx: v.tx, ty: v.ty, z: clamp(v.z, ZMIN, ZMAX) };
    else { const z = clamp(vp.clientWidth / 392, ZMIN, 1.15); this.view = { z, tx: (vp.clientWidth - 384 * z) / 2, ty: 0 }; }
    this._applyView();
    for (const b of this.boxes.values()) b.h = b.el.offsetHeight || b.h;
    this._routeAll();
  }

  _unpress(press) {
    if (!press) return;
    clearTimeout(press.timer); clearTimeout(press.arm);
    this.cordEls.get(press.key)?.g.classList.remove('is-armed');
  }

  _applyView() {
    const { tx, ty, z } = this.view;
    const W = this.vp.clientWidth || 380, H = this.vp.clientHeight || 500;
    this.view.tx = clamp(tx, W - WORLD * z, W * 0.5);
    this.view.ty = clamp(ty, H - WORLD * z, H * 0.5);
    this.world.style.transform = `translate3d(${this.view.tx}px, ${this.view.ty}px, 0) scale(${z})`;
    this.vp.style.setProperty('--gs', `${GRID * z}px`);
    this.vp.style.setProperty('--gm', `${GRID * 5 * z}px`);
    this.vp.style.setProperty('--gx', `${this.view.tx}px`);
    this.vp.style.setProperty('--gy', `${this.view.ty}px`);
    this.zoomRead.textContent = `${Math.round(z * 100)}%`;
  }

  zoomBy(k, cx, cy) {
    const W = this.vp.clientWidth, H = this.vp.clientHeight;
    cx ??= W / 2; cy ??= H / 2;
    const { tx, ty, z } = this.view;
    const nz = clamp(z * k, ZMIN, ZMAX);
    const wx = (cx - tx) / z, wy = (cy - ty) / z;
    this.view = { z: nz, tx: cx - wx * nz, ty: cy - wy * nz };
    this._applyView();
    this.save();
  }

  zoomTo(z) { this.zoomBy(z / this.view.z); }

  /** Frame every box. */
  fit() {
    if (!this.boxes.size) return;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const b of this.boxes.values()) {
      x0 = Math.min(x0, b.obj.x); y0 = Math.min(y0, b.obj.y);
      x1 = Math.max(x1, b.obj.x + b.el.offsetWidth); y1 = Math.max(y1, b.obj.y + b.el.offsetHeight);
    }
    const W = this.vp.clientWidth, H = this.vp.clientHeight;
    const z = clamp(Math.min(W / (x1 - x0 + 28), H / (y1 - y0 + 28)), ZMIN, 1.2);
    this.view = { z, tx: (W - (x1 - x0) * z) / 2 - x0 * z, ty: (H - (y1 - y0) * z) / 2 - y0 * z };
    this._applyView();
    this.save();
  }

  // --- selection -----------------------------------------------------------------------------------------------
  _select(id, force = false) {
    if (id && id === this.selected && !force) return;
    if (this.armed) { clearTimeout(this.armT); this.armed = null; this.delBtn?.classList.remove('is-armed'); }
    if (this.selected) this.boxes.get(this.selected)?.el.classList.remove('is-sel');
    this.selected = id && this.boxes.has(id) ? id : null;
    const b = this.selected ? this.boxes.get(this.selected) : null;
    b?.el.classList.add('is-sel');
    if (b) this._selectCord(null);
    this.selName.textContent = b ? (b.mod ? b.mod.title() : titleOf(b.obj, this.ctx.params)) : this.selectedCord ? 'a cord' : '';
    this.el.classList.toggle('has-sel', !!b);
  }

  /** Delete takes two taps: the first arms the button (red, for 2.5 s), the second deletes. */
  _armDelete() {
    if (!this.selected) return;
    if (this.armed === this.selected) { clearTimeout(this.armT); this.armed = null; this.delBtn.classList.remove('is-armed'); this.remove(this.selected); return; }
    this.armed = this.selected;
    this.delBtn.classList.add('is-armed');
    this.selName.textContent = 'tap again to delete';
    clearTimeout(this.armT);
    this.armT = setTimeout(() => { this.armed = null; this.delBtn.classList.remove('is-armed'); this._select(this.selected, true); }, 2500);
  }

  _selectCord(key) {
    if (this.selectedCord) this.cordEls.get(this.selectedCord)?.g.classList.remove('is-sel');
    this.selectedCord = key && this.cordEls.has(key) ? key : null;
    if (this.selectedCord) { this.cordEls.get(this.selectedCord).g.classList.add('is-sel'); this._select(null); haptic(); }
    this.el.classList.toggle('has-cord', !!this.selectedCord);
    if (!this.selected) this.selName.textContent = this.selectedCord ? 'cord: hold or tap cut' : '';
  }

  // --- patching ------------------------------------------------------------------------------------------------
  _portXY(id, kind, i = 0) {
    const b = this.boxes.get(id);
    return { x: b.obj.x + 10 + i * 26 + 9, y: kind === 'in' ? b.obj.y : b.obj.y + b.h };
  }

  _toWorld(cx, cy) {
    const r = this.vp.getBoundingClientRect();
    return { x: (cx - r.left - this.view.tx) / this.view.z, y: (cy - r.top - this.view.ty) / this.view.z };
  }

  _patchFrom(e, fromId, port) {
    e.stopPropagation();
    e.preventDefault();
    const el = e.currentTarget;
    try { el.setPointerCapture(e.pointerId); } catch { /* synthetic pointer */ }
    const a = this._portXY(fromId, 'out', port);
    const targets = [];
    for (const [id, b] of this.boxes) b.ins.forEach((inEl, i) => { if (this.canConnect(fromId, id)) { targets.push({ id, i, el: inEl }); inEl.classList.add('is-open'); } });
    this.el.classList.add('is-patching');
    haptic();
    let hot = null;
    const moveTo = (cx, cy) => {
      const w = this._toWorld(cx, cy);
      let best = null, bd = 44 / this.view.z;
      for (const t of targets) {
        const p = this._portXY(t.id, 'in', t.i);
        const d = Math.hypot(p.x - w.x, p.y - w.y);
        if (d < bd) { bd = d; best = t; }
      }
      if (best !== hot) { hot?.el.classList.remove('is-hot'); hot = best; hot?.el.classList.add('is-hot'); if (hot) haptic(); }
      const b = hot ? this._portXY(hot.id, 'in', hot.i) : w;
      this.temp.setAttribute('d', cordPath(a, b));
    };
    moveTo(e.clientX, e.clientY);
    const mv = (ev) => { if (ev.pointerId === e.pointerId) moveTo(ev.clientX, ev.clientY); };
    const done = (ev) => {
      if (ev.pointerId !== e.pointerId) return;
      el.removeEventListener('pointermove', mv);
      el.removeEventListener('pointerup', done);
      el.removeEventListener('pointercancel', done);
      this.temp.setAttribute('d', '');
      for (const t of targets) t.el.classList.remove('is-open', 'is-hot');
      this.el.classList.remove('is-patching');
      if (hot && ev.type === 'pointerup') this.connect(fromId, port, hot.id, hot.i);
    };
    el.addEventListener('pointermove', mv);
    el.addEventListener('pointerup', done);
    el.addEventListener('pointercancel', done);
  }

  canConnect(fromId, toId) {
    if (fromId === toId || !this.boxes.has(toId) || !ports(this.boxes.get(toId).obj).ins) return false;
    if (this.patch.cords.some((c) => c.from[0] === fromId && c.to[0] === toId)) return false;
    const seen = new Set(), stack = [toId];                   // no loops: fromId must not hang off toId
    while (stack.length) {
      const n = stack.pop();
      if (n === fromId) return false;
      if (seen.has(n)) continue;
      seen.add(n);
      for (const c of this.patch.cords) if (c.from[0] === n) stack.push(c.to[0]);
    }
    return true;
  }

  connect(fromId, outlet, toId, inlet) {
    if (!this.canConnect(fromId, toId)) return false;
    this.patch.cords.push({ from: [fromId, outlet], to: [toId, inlet] });
    this._routeAll();
    this._order();
    this.save();
    haptic(true);
    return true;
  }

  cut(key, held = false) {
    const i = this.patch.cords.findIndex((c) => cordKey(c) === key);
    if (i < 0) return;
    this.patch.cords.splice(i, 1);
    if (this.selectedCord === key) this._selectCord(null);
    this._routeAll();
    this._order();
    this.save();
    haptic(true);
    toast(held ? 'Cord cut' : 'Cut');
  }

  _routeBox(id) {
    for (const c of this.patch.cords) if (c.from[0] === id || c.to[0] === id) this._routeCord(c);
  }

  _routeAll() {
    const keep = new Set(this.patch.cords.map(cordKey));
    for (const [key, el] of this.cordEls) if (!keep.has(key)) { el.g.remove(); this.cordEls.delete(key); }
    for (const c of this.patch.cords) this._routeCord(c);
  }

  _routeCord(c) {
    if (!this.boxes.has(c.from[0]) || !this.boxes.has(c.to[0])) return;
    const key = cordKey(c);
    let el = this.cordEls.get(key);
    if (!el) {
      const hit = s('path', { class: 'cd-hit', dataset: { key } });
      const line = s('path', { class: 'cd-line' });
      const glow = s('path', { class: 'cd-glow' });
      const flow = s('path', { class: 'cd-flow' });
      const g = s('g', { class: 'cd' }, line, glow, flow, hit);
      this.cords.append(g);
      el = { g, hit, line, glow, flow, a: -1 };
      this.cordEls.set(key, el);
    }
    const d = cordPath(this._portXY(c.from[0], 'out', c.from[1]), this._portXY(c.to[0], 'in', c.to[1]));
    for (const p of [el.hit, el.line, el.glow, el.flow]) p.setAttribute('d', d);
  }

  /** Evaluation order: sources before what they feed. */
  _order() {
    const ids = [...this.boxes.keys()];
    this.inbound = new Map();
    this.outbound = new Set();
    for (const c of this.patch.cords) {
      if (!this.inbound.has(c.to[0])) this.inbound.set(c.to[0], []);
      this.inbound.get(c.to[0]).push(c.from[0]);
      this.outbound.add(c.from[0]);
    }
    const indeg = new Map(ids.map((id) => [id, (this.inbound.get(id) ?? []).length]));
    const q = ids.filter((id) => !indeg.get(id));
    const out = [];
    while (q.length) {
      const id = q.shift();
      out.push(id);
      for (const c of this.patch.cords) if (c.from[0] === id) { indeg.set(c.to[0], indeg.get(c.to[0]) - 1); if (!indeg.get(c.to[0])) q.push(c.to[0]); }
    }
    this.order = out;
  }

  // --- the runtime: every frame -------------------------------------------------------------------------------
  _run() {
    if (this.dead) return;
    if (!this.running) {                                     // stopped: nothing moves; the displays rest at the downbeat
      if (this.written.size) { for (const pid of this.written.keys()) this.mod.set(pid, 0); this.written.clear(); }
      if (this.dirty && this.visible) {
        this.dirty = false;
        for (const b of this.boxes.values()) if (b.mod) { b.out = 0; b.mod.draw(0, 0); }
        for (const el of this.cordEls.values()) { el.a = 0; el.g.style.setProperty('--a', '0'); el.g.classList.remove('is-live'); }
      }
      return;
    }
    const t = this.clock();
    const store = this.ctx.store;
    const outs = new Map(), offsets = new Map();
    for (const id of this.order) {
      const b = this.boxes.get(id);
      if (!b) continue;
      const kind = TYPES[b.obj.type].kind;
      const ins = this.inbound.get(id) ?? [];
      let sum = 0;
      for (const src of ins) sum += outs.get(src) ?? 0;
      if (kind === 'mod') {
        const st = b.obj.state;
        const [v] = shape(b.obj.type, st, t);
        b.out = v * (st.depth / 100) * (ins.length ? clamp(1 + sum, 0, 2) : 1);
        outs.set(id, b.out);
      } else if (kind === 'ui') {
        const pids = paramsOf(b.obj);
        if (ins.length) for (const pid of pids) offsets.set(pid, (offsets.get(pid) ?? 0) + sum);
        if (pids.length === 1 && this.outbound.has(id)) {
          const pid = pids[0];
          outs.set(id, store.get(pid) + (offsets.get(pid) ?? 0) - setNorm(this.ctx.params.get(pid)));
        }
      }
    }
    for (const [pid, off] of offsets) {
      const prev = this.written.get(pid);
      if (prev == null || Math.abs(prev - off) > 0.0015) { this.mod.set(pid, clamp(off, -1, 1)); this.written.set(pid, off); }
    }
    for (const pid of [...this.written.keys()]) if (!offsets.has(pid)) { this.mod.set(pid, 0); this.written.delete(pid); }
    if (!this.visible) return;
    for (const c of this.patch.cords) {
      const el = this.cordEls.get(cordKey(c));
      if (!el) continue;
      const v = Math.min(1, Math.abs(outs.get(c.from[0]) ?? 0) * 3);
      if (Math.abs(v - el.a) > 0.03) { el.a = v; el.g.style.setProperty('--a', v.toFixed(2)); el.g.classList.toggle('is-live', v > 0.01); }
    }
    for (const b of this.boxes.values()) if (b.mod) b.mod.draw(t, b.out);
  }

  // --- run / stop --------------------------------------------------------------------------------------------
  /** Set the modulators going (on the bar clock while the transport plays, at 160 BPM when it does not). */
  start() {
    if (this.dead || this.running) return;
    this.running = true;
    this.patch.running = true;
    this._paintRun();
    this.save();
  }

  /** Halt every modulator, take every offset the bench put on params off again, stop the A/B/C tappers it holds. */
  stop() {
    if (this.dead) return;
    const was = this.running;
    this.running = false;
    this.patch.running = false;
    for (const pid of this.written.keys()) this.mod.set(pid, 0);
    this.written.clear();
    this.mod.clear();
    for (const b of this.boxes.values()) b.el.querySelector('.w-abc')?.stop?.();
    this.dirty = true;
    this._paintRun();
    if (was) this.save();
  }

  /** fn(running) whenever the bench starts or stops. Returns an unsubscribe. */
  onRun(fn) { this.runFns.add(fn); return () => this.runFns.delete(fn); }

  _paintRun() {
    this.runBtn.replaceChildren(h('i'), icon(this.running ? 'stop' : 'play'), h('span', { text: this.running ? 'stop' : 'run' }));
    this.runBtn.setAttribute('aria-pressed', String(this.running));
    this.runBtn.setAttribute('aria-label', this.running ? 'Stop the modulators' : 'Run the modulators');
    this.el.classList.toggle('is-running', this.running);
    for (const fn of this.runFns) { try { fn(this.running); } catch (err) { console.error(err); } }
  }

  // --- objects -------------------------------------------------------------------------------------------------
  /** Add a box of `type` over `params` at the middle of the view (or x, y). Returns its id. */
  add(type, params = [], opts = {}, at = null) {
    const W = this.vp.clientWidth || 380, H = this.vp.clientHeight || 500;
    const width = TYPES[type].width ?? params.length * 44 + 26;
    const c = at ?? this._freeSpot(this._toWorldLocal(W / 2, H / 4), width);
    const obj = { id: nextId(this.patch), type, x: Math.round(clamp(c.x - width / 2, 0, WORLD - width) / SNAP) * SNAP, y: Math.round(clamp(c.y - 40, 0, WORLD - 100) / SNAP) * SNAP, params, opts, state: undefined };
    this.patch.objects.push(obj);
    this._addBox(obj);
    this._order();
    this._select(obj.id);
    if (!at) this._reveal(obj);
    this.save();
    haptic(true);
    return obj.id;
  }

  /** Near (c.x, c.y), the first place a box `w` wide does not sit on another box (looking down, then right). */
  _freeSpot(c, w, hgt = 170) {
    const hits = (x, y) => [...this.boxes.values()].some((b) => x - w / 2 < b.obj.x + b.el.offsetWidth + 8 && x + w / 2 > b.obj.x - 8
      && y - 40 < b.obj.y + b.el.offsetHeight + 8 && y - 40 + hgt > b.obj.y - 8);
    for (let k = 0; k < 60; k++) {
      const x = c.x + Math.floor(k / 20) * (w + 24), y = c.y + (k % 20) * 40;
      if (!hits(x, y)) return { x, y };
    }
    return c;
  }

  /** Bring a box into view if it is not (its top a quarter of the way down). */
  _reveal(obj) {
    const W = this.vp.clientWidth, H = this.vp.clientHeight, { tx, ty, z } = this.view;
    const sx = obj.x * z + tx, sy = obj.y * z + ty;
    if (sx >= 0 && sx < W - 40 && sy >= 0 && sy < H - 80) return;
    this.view = { z, tx: sx < 0 || sx > W - 40 ? 16 - obj.x * z : tx, ty: H / 4 - obj.y * z };
    this._applyView();
  }

  _toWorldLocal(x, y) { return { x: (x - this.view.tx) / this.view.z, y: (y - this.view.ty) / this.view.z }; }

  duplicate(id) {
    const b = this.boxes.get(id);
    if (!b) return;
    const o = b.obj;
    const copy = JSON.parse(JSON.stringify({ ...o, id: nextId(this.patch), x: o.x + 24, y: o.y + 24 }));
    this.patch.objects.push(copy);
    this._addBox(copy);
    this._order();
    this._select(copy.id);
    this.save();
    toast('Duplicated');
  }

  remove(id) {
    const b = this.boxes.get(id);
    if (!b) return;
    for (const fn of b.cleanups.splice(0)) { try { fn(); } catch (err) { console.error(err); } }
    b.el.remove();
    this.boxes.delete(id);
    this.patch.objects = this.patch.objects.filter((o) => o.id !== id);
    this.patch.cords = this.patch.cords.filter((c) => c.from[0] !== id && c.to[0] !== id);
    if (this.selected === id) this._select(null);
    this._routeAll();
    this._order();
    this.save();
    toast(`Deleted ${b.mod ? b.mod.title() : titleOf(b.obj, this.ctx.params)}`);
  }

  /** Replace the whole patch (the starting one, or an empty bench). */
  replace(patch) {
    for (const id of [...this.boxes.keys()]) {
      const b = this.boxes.get(id);
      for (const fn of b.cleanups.splice(0)) { try { fn(); } catch (err) { console.error(err); } }
      b.el.remove();
    }
    this.boxes.clear();
    this.patch = patch;
    this.running = !!patch.running;
    this.written.forEach((_v, pid) => this.mod.set(pid, 0));
    this.written.clear();
    this.dirty = true;
    this._paintRun();
    for (const obj of patch.objects) this._addBox(obj);
    this._select(null);
    this._routeAll();
    this._order();
    this.patch.view = null;
    requestAnimationFrame(() => this._initView(true));
    this.save();
  }

  reset() { this.replace(defaultPatch(this.ctx.params)); toast('The starting patch'); }
  clear() { this.replace({ v: 1, objects: [], cords: [], view: null }); toast('An empty bench'); }

  toolbox() { this.closeToolbox?.(); this.closeToolbox = openToolbox(this); }

  // --- full screen -------------------------------------------------------------------------------------------
  toggleFull() {
    this.full = !this.full;
    if (this.full) {
      this.home = document.createComment('bench');
      this.el.before(this.home);
      document.body.append(this.el);
      this.el.classList.add('is-full');
      this._placeFull();
    } else {
      this.home?.replaceWith(this.el);
      this.home = null;
      this.el.classList.remove('is-full');
      this.el.style.top = ''; this.el.style.height = '';
    }
    this.fullBtn.replaceChildren(icon(this.full ? 'shrink' : 'full'));
    this.fullBtn.setAttribute('aria-label', this.full ? 'Back into the page' : 'Full screen');
  }

  _placeFull() {
    const top = document.getElementById('transport')?.getBoundingClientRect().bottom ?? 0;
    const bottom = document.getElementById('tabs')?.getBoundingClientRect().top ?? innerHeight;
    this.el.style.top = `${top}px`;
    this.el.style.height = `${Math.max(200, bottom - top)}px`;
  }

  // --- keeping -------------------------------------------------------------------------------------------------
  save() {
    if (this.dead) return;
    clearTimeout(this._saveT);
    this._saveT = setTimeout(() => { this.patch.view = { ...this.view }; savePatch(this.patch); }, 300);
  }

  destroy() {
    if (this.dead) return;
    this.runFns.clear();
    clearTimeout(this._saveT);
    clearTimeout(this.armT);
    this.patch.view = { ...this.view };
    savePatch(this.patch);
    this.dead = true;
    this.closeToolbox?.();
    for (const b of this.boxes.values()) for (const fn of b.cleanups.splice(0)) { try { fn(); } catch (err) { console.error(err); } }
    for (const fn of this.cleanups.splice(0)) { try { fn(); } catch (err) { console.error(err); } }
    for (const pid of this.written.keys()) this.mod.set(pid, 0);
    this.written.clear();
    this.mod.clear();
    if (this.full) { this.el.remove(); this.home?.remove(); }
  }
}

/** A patch cord: leaves the outlet downwards, enters the inlet from above, and droops with its length. */
export function cordPath(a, b) {
  const dx = b.x - a.x, dy = b.y - a.y;
  const k = Math.max(26, Math.abs(dy) * 0.42, Math.abs(dx) * 0.18);
  const sag = Math.min(110, Math.abs(dx) * 0.2 + (dy < 0 ? 40 : 0));
  const bow = Math.min(22, Math.hypot(dx, dy) * 0.09) * (dx < 0 ? -1 : 1);   // a cable is never quite straight
  const f = (x) => x.toFixed(1);
  return `M${f(a.x)} ${f(a.y)}C${f(a.x + bow)} ${f(a.y + k + sag)} ${f(b.x + bow)} ${f(b.y - k + sag)} ${f(b.x)} ${f(b.y)}`;
}
