// Every control's value, in one place: widgets write here, the engine and other widgets listen.
//
// Values are normalised 0..1 (params.js turns them into units). A gesture (begin ... end) is one undo step.
// Four snapshot slots hold whole states; morph() glides between any two. The state survives a reload
// (localStorage, per phone), and diff() says what moved away from the set, in Live's terms.

import { setNorm, toReal } from './params.js';

const KEY = 'hw002-lab:v1';

export class Store {
  constructor(params) {
    this.params = params;
    this.values = new Map(params.list.map((p) => [p.id, setNorm(p)]));
    this.subs = new Map();          // id -> Set(fn)
    this.any = new Set();
    this.undoStack = [];
    this.redoStack = [];
    this.gesture = null;            // {id -> value before} while a gesture runs
    this.slots = [null, null, null, null];
    this.mods = new Map();          // id -> offset added by modulators (LFOs, physics, tilt), not saved
    this._saveTimer = 0;
    this._load();
  }

  // --- reading ---------------------------------------------------------------------------------------------
  get(id) { return this.values.get(id) ?? 0; }
  /** The value a listener should act on: the knob plus any modulation, clamped. */
  live(id) { return Math.min(1, Math.max(0, this.get(id) + (this.mods.get(id) ?? 0))); }
  real(id) { return toReal(this.params.get(id), this.live(id)); }
  isSet(id) { return Math.abs(this.get(id) - setNorm(this.params.get(id))) < 1e-4; }

  // --- writing ---------------------------------------------------------------------------------------------
  /** Set a value (0..1). `source` names who did it, so a widget can ignore its own echo. */
  set(id, value, { source = null, record = true } = {}) {
    if (!this.values.has(id)) return;
    const v = Math.min(1, Math.max(0, value));
    const before = this.values.get(id);
    if (Math.abs(v - before) < 1e-6) return;
    if (record) this._remember(id, before);
    this.values.set(id, v);
    this._emit(id, source);
    this._persist();
  }

  nudge(id, delta, opts) { this.set(id, this.get(id) + delta, opts); }

  /** A modulation offset (-1..1 of the range) on top of the knob: LFOs, tilt, physics. 0 removes it. */
  modulate(id, offset, source = 'mod') {
    if (!this.values.has(id)) return;
    if (!offset) this.mods.delete(id); else this.mods.set(id, offset);
    this._emit(id, source);
  }

  reset(id, opts) { this.set(id, setNorm(this.params.get(id)), opts); }
  resetAll(ids = [...this.values.keys()]) {
    this.begin();
    for (const id of ids) this.reset(id, { source: 'reset' });
    this.end();
  }

  /** Values move together as one undo step: begin(), any number of set(), end(). */
  begin() { if (!this.gesture) this.gesture = new Map(); }
  end() {
    const g = this.gesture;
    this.gesture = null;
    if (g && g.size) { this.undoStack.push(g); this.redoStack.length = 0; if (this.undoStack.length > 200) this.undoStack.shift(); }
  }

  undo() { this._swap(this.undoStack, this.redoStack); }
  redo() { this._swap(this.redoStack, this.undoStack); }

  /** Move `ids` a random amount (0..1 of their range) around where they are. */
  randomize(ids, amount = 0.25) {
    this.begin();
    for (const id of ids) this.set(id, this.get(id) + (Math.random() * 2 - 1) * amount, { source: 'random' });
    this.end();
  }

  // --- whole states ----------------------------------------------------------------------------------------
  snapshot(ids = [...this.values.keys()]) { return Object.fromEntries(ids.map((id) => [id, this.get(id)])); }

  apply(snap, { source = 'snapshot' } = {}) {
    this.begin();
    for (const [id, v] of Object.entries(snap)) this.set(id, v, { source });
    this.end();
  }

  /** Values a fraction `t` of the way from snapshot `a` to `b` (ids in both). Not an undo step per call. */
  morph(a, b, t, { source = 'morph' } = {}) {
    for (const id of Object.keys(a)) {
      if (!(id in b)) continue;
      const p = this.params.get(id);
      const v = p.scale === 'toggle' || p.scale === 'enum' ? (t < 0.5 ? a[id] : b[id]) : a[id] + (b[id] - a[id]) * t;
      this.set(id, v, { source, record: false });
    }
  }

  saveSlot(i) { this.slots[i] = this.snapshot(); this._persist(); this._emit('*slots', 'slots'); }
  recallSlot(i) { if (this.slots[i]) this.apply(this.slots[i], { source: 'slot' }); }

  /** What moved away from the set: [{id, live, from, to}] in the params' units. */
  diff() {
    const out = [];
    for (const p of this.params.list) {
      if (this.isSet(p.id)) continue;
      out.push({ id: p.id, live: p.live, label: p.label, from: p.set, to: toReal(p, this.get(p.id)), unit: p.unit });
    }
    return out;
  }

  // --- listening -------------------------------------------------------------------------------------------
  /** fn(value, id, source) on every change of `id` (and once now unless {now: false}). Returns an unsubscribe. */
  on(id, fn, { now = true } = {}) {
    if (!this.subs.has(id)) this.subs.set(id, new Set());
    this.subs.get(id).add(fn);
    if (now && this.values.has(id)) fn(this.live(id), id, 'init');
    return () => this.subs.get(id)?.delete(fn);
  }

  /** fn(id, value, source) on any change. */
  onAny(fn) { this.any.add(fn); return () => this.any.delete(fn); }

  // --- inside ----------------------------------------------------------------------------------------------
  _emit(id, source) {
    const v = this.values.has(id) ? this.live(id) : null;
    for (const fn of this.subs.get(id) ?? []) fn(v, id, source);
    for (const fn of this.any) fn(id, v, source);
  }

  _remember(id, before) {
    if (this.gesture) { if (!this.gesture.has(id)) this.gesture.set(id, before); return; }
    this.undoStack.push(new Map([[id, before]]));
    this.redoStack.length = 0;
  }

  _swap(from, to) {
    const step = from.pop();
    if (!step) return;
    const back = new Map();
    for (const [id, v] of step) { back.set(id, this.get(id)); this.values.set(id, v); this._emit(id, 'undo'); }
    to.push(back);
    this._persist();
  }

  _persist() {
    clearTimeout(this._saveTimer);
    this._saveTimer = setTimeout(() => {
      try {
        localStorage.setItem(KEY, JSON.stringify({ values: Object.fromEntries(this.values), slots: this.slots }));
      } catch { /* private mode: the state lives for this visit */ }
    }, 400);
  }

  _load() {
    try {
      const saved = JSON.parse(localStorage.getItem(KEY) || 'null');
      if (!saved) return;
      for (const [id, v] of Object.entries(saved.values ?? {})) if (this.values.has(id)) this.values.set(id, v);
      if (Array.isArray(saved.slots)) this.slots = saved.slots.slice(0, 4).concat([null, null, null, null]).slice(0, 4);
    } catch { /* a broken save starts from the set */ }
  }
}
