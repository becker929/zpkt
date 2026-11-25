// Surface cards in the thread, and the "armed vs frozen" lifecycle.
// Exactly one card is armed (S.active): live widgets, the MIDI controller, the player. Every other card is frozen:
// a static SVG snapshot of its last values and peaks with an Arm button. Values save to the server (debounced),
// so a frozen or recalled card comes back as the user left it.
import { validate, valuesOf, coerce, changed } from './spec.js';
import { snapshotSVG, esc } from './draw.js';
import { layout, CARD_W } from './layout.js';
import { ICON } from './icons.js';
import { widget } from './widgets.js';
import { midi } from './midi.js';
import { S, emit, local } from './state.js';
import { isStarred, star, library } from './library.js';

const armedKey = () => `zpkt.armed.${S.sessionId}`;

// Panels being rendered from their card right now (by name), so every card of that panel shows it, on every device.
const rendering = new Set();
/** A `panel` event from the session: keep the Render buttons in step. */
export function panelEvent(e) {
  if (e.status === 'rendering') rendering.add(e.panel); else rendering.delete(e.panel);
  for (const c of S.cards.values()) {
    if (c.spec.panel !== e.panel) continue;
    const b = c.el.querySelector('[data-a=render]');
    if (b) { b.disabled = rendering.has(e.panel); b.textContent = b.disabled ? 'Rendering…' : 'Render'; }
    for (const x of c.el.querySelectorAll('[data-a=grid],[data-a=gridgo],[data-a=use]')) x.disabled = rendering.has(e.panel);
    // The values that were turned went into the new version; this card is the version it was rendered as.
    // Without this, a frozen "v1" showed v2's values over v1's sound.
    if (e.status === 'done' && changed(c.spec, c.values).length) { c.values = valuesOf(c.spec); c.saveState(); c.teardown(); c.render(); }
  }
}

class Card {
  constructor({ id, spec, warnings, values, name, origin, from }) {
    const saved = S.states[id] || {};
    Object.assign(this, { id, spec, warnings, name: name || null, origin: origin || null, from: from || null, preset: null });   // from: the preset it was recalled from
    this.values = valuesOf(spec, values, saved.values);   // only what each control can hold: a saved state may be stale
    this.peaks = saved.peaks && typeof saved.peaks === 'object' ? saved.peaks : {};
    this.region = {};
    this.widgets = null;
    this.el = document.createElement('div');
    this.el.className = 'zs-card';
    this.el.dataset.sid = id;
    this.el.addEventListener('click', (e) => this.onClick(e));
  }

  get armed() { return S.active === this.id; }

  /* ---- the interface widgets use ---- */
  set(k, v, from) {
    if (k.kind === 'toggle') v = !!v;
    v = coerce(k, v);
    if (v == null || this.values[k.id] === v) return;
    this.values[k.id] = v;
    if (k.kind !== 'ab' && k.kind !== 'pads' && k.kind !== 'deck') this.widgets?.get(k.id)?.redraw();
    this.saveState();
    if (from === 'drag') { clearTimeout(this.emitT); this.emitT = setTimeout(emit, 120); } else emit();
  }
  settled() { emit(); }
  flash() { this.el.classList.remove('zs-flash'); void this.el.offsetWidth; this.el.classList.add('zs-flash'); }
  saveState(extra = {}) {
    clearTimeout(this.saveT);
    this.pendingSave = { ...this.pendingSave, ...extra }; // merge, so a quick value change never drops the peaks
    this.saveT = setTimeout(() => {
      const body = { values: this.values, ...this.pendingSave };
      this.pendingSave = {};
      S.api?.(`/app/ask/api/surfaces/${encodeURIComponent(this.id)}`, { method: 'PUT', body }).catch(() => {});
      if (this.preset) S.api?.(`/app/ask/api/library/${this.preset}`, { method: 'PATCH', body: { values: this.values } }).catch(() => {});
    }, 400);
  }

  /* ---- drawing ---- */
  header() {
    // A panel starred from this thread keeps its library name and link after a reload.
    if (!this.preset) { const p = library().find((x) => x.source === this.id); if (p) { this.preset = p.id; this.name = this.name || p.name; } }
    const starred = isStarred(this);
    const notes = [this.spec.note, this.origin && `Recalled from ${this.origin}`].filter(Boolean);
    return `<div class="zs-head"><span class="zs-dot"></span>
      <b class="zs-title" title="${esc(this.spec.title)}">${esc(this.name || this.spec.title)}</b>
      <span class="zs-tag">${this.armed ? 'Armed' : 'Frozen'}</span>
      <button class="zs-ib" data-a="star" aria-label="${starred ? 'Starred' : 'Star to library'}" title="Star to library">${starred ? ICON.starOn : ICON.star}</button>
      ${this.armed && this.spec.panel && turnable(this.spec).length ? `<button class="zs-arm zs-render" data-a="grid" title="Render several versions at once and compare them"${rendering.has(this.spec.panel) ? ' disabled' : ''}>Grid</button><button class="zs-arm zs-render" data-a="render" title="Set these values in Live and render again (no agent)"${rendering.has(this.spec.panel) ? ' disabled' : ''}>${rendering.has(this.spec.panel) ? 'Rendering…' : 'Render'}</button>` : ''}
      ${this.armed ? `<button class="zs-ib" data-a="reset" aria-label="Back to the rendered values" title="Back to the rendered values">${ICON.reset}</button>`
                   : '<button class="zs-arm" data-a="arm">Arm</button>'}
    </div>${notes.map((n) => `<div class="zs-note">${esc(n)}</div>`).join('')}${this.warnings.length ? `<div class="zs-warn">${this.warnings.map(esc).join('<br>')}</div>` : ''}`;
  }

  render() {
    this.el.classList.toggle('armed', this.armed);
    this.el.classList.toggle('frozen', !this.armed);
    if (!this.armed) {
      this.el.innerHTML = this.header() + `<div class="zs-snap">${snapshotSVG(this.spec, this.values, this.peaks)}</div>`;
      return;
    }
    this.el.innerHTML = this.header() + '<div class="zs-body"></div>';
    const body = this.el.querySelector('.zs-body');
    this.widgets = new Map();
    // The same packing the frozen snapshot uses, so arming or freezing never moves a control.
    const L = layout(this.spec, CARD_W, true);
    body.style.width = `${Math.max(L.width, 200)}px`;
    body.style.height = `${L.height}px`;
    this.fit(body);
    if (!this.el.isConnected) queueMicrotask(() => this.fit());   // a new card is drawn before it is put in the thread
    for (const { c: k, x, y } of L.items) {
      const w = widget(this, k);
      w.el.style.left = `${x}px`;
      w.el.style.top = `${y}px`;
      this.widgets.set(k.id, w);
      body.append(w.el);
    }
  }

  /** On a screen narrower than the card, the live body shrinks as a whole (the frozen snapshot scales the same way). */
  fit(body = this.el.querySelector('.zs-body')) {
    const parent = this.el.parentElement;
    if (!body || !parent) return;
    const cs = getComputedStyle(this.el);
    const room = parent.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - 2;
    const want = parseFloat(body.style.width);
    body.style.zoom = room > 40 && room < want ? Math.max(0.5, room / want).toFixed(3) : '';
  }

  /** Freeze: tear down live widgets (stops decks, lets decoded audio go). */
  teardown() {
    for (const w of this.widgets?.values() || []) w.destroy?.();
    this.widgets = null;
  }

  /** Hardware input, routed here only while armed. */
  onMidi({ kind, slot, value }) {
    for (const k of this.spec.controls) {
      if (kind === 'cc' && k.midiSlot === slot) {
        if (k.kind === 'knob' || k.kind === 'fader') this.set(k, k.min + value * (k.max - k.min), 'drag');
        if (k.kind === 'toggle') this.set(k, value >= 0.5);
      }
      if (kind === 'note' && k.kind === 'pads') k.pads.forEach((p, i) => { if (p.midiSlot === slot) this.widgets?.get(k.id)?.hit(i); });
    }
  }

  /** The grid form: which knobs to vary (one or two), over what range, in how many steps. */
  gridForm() {
    const have = this.el.querySelector('.zs-grid');
    if (have) return have.remove();
    const rows = turnable(this.spec).map((k) => `<label class="zs-gr"><input type="checkbox" data-g="${k.id}"><span>${esc(k.label)}</span>
      ${k.kind === 'toggle' ? '<i>off / on</i>' : `<select data-gs="${k.id}" aria-label="Steps for ${esc(k.label)}">${[2, 3, 4, 5].map((n) => `<option${n === 3 ? ' selected' : ''}>${n}</option>`).join('')}</select>
      <select data-gr="${k.id}" aria-label="Range for ${esc(k.label)}"><option value="near">around here</option><option value="all">whole range</option></select>`}</label>`).join('');
    this.el.querySelector('.zs-head').insertAdjacentHTML('afterend', `<div class="zs-grid"><div class="zs-gh">Vary one or two controls. Every combination is rendered in Live.</div>${rows}
      <div class="zs-gf"><span class="zs-gn"></span><button class="zs-arm" data-a="gridgo" disabled>Render versions</button></div></div>`);
    const form = this.el.querySelector('.zs-grid');
    const count = () => {
      const on = [...form.querySelectorAll('[data-g]:checked')];
      for (const b of form.querySelectorAll('[data-g]')) b.disabled = !b.checked && on.length >= 2;
      const n = on.reduce((m, b) => m * (+form.querySelector(`[data-gs="${b.dataset.g}"]`)?.value || 2), 1);
      const ok = on.length > 0 && n <= 16;
      form.querySelector('.zs-gn').textContent = !on.length ? '' : n > 16 ? `${n} versions: at most 16` : `${n} versions`;
      form.querySelector('[data-a=gridgo]').disabled = !ok || rendering.has(this.spec.panel);
    };
    form.addEventListener('change', count);
    this.fit();
  }
  gridGo() {
    const form = this.el.querySelector('.zs-grid');
    const axes = {};
    for (const b of form.querySelectorAll('[data-g]:checked')) {
      const k = this.spec.controls.find((x) => x.id === b.dataset.g);
      if (k.kind === 'toggle') { axes[k.id] = { steps: 2 }; continue; }   // off and on
      const steps = +form.querySelector(`[data-gs="${k.id}"]`).value, span = k.max - k.min, v = this.values[k.id];
      const near = form.querySelector(`[data-gr="${k.id}"]`).value === 'near';
      // "Around here": a quarter of the travel either side, moved in from an end so it keeps its width.
      const lo = near ? Math.max(k.min, Math.min(k.max - span / 2, v - span / 4)) : k.min;
      axes[k.id] = { from: +lo.toFixed(6), to: +(near ? lo + span / 2 : k.max).toFixed(6), steps };
    }
    form.remove();
    panelEvent({ panel: this.spec.panel, status: 'rendering' });
    S.api(`/app/ask/api/sessions/${S.sessionId}/grid`, { method: 'POST', body: { panel: this.spec.panel, axes, values: this.values } })
      .catch((err) => { panelEvent({ panel: this.spec.panel, status: 'failed' }); S.toast(err.message || String(err), 5000); });
  }

  async onClick(e) {
    const a = e.target.closest('[data-a]')?.dataset.a;
    if (a === 'arm') arm(this.id);
    if (a === 'render') {
      // Straight to Live: the server runs `hands panel apply` with these values; the new card arrives as an event.
      panelEvent({ panel: this.spec.panel, status: 'rendering' });
      S.api(`/app/ask/api/sessions/${S.sessionId}/render`, { method: 'POST', body: { panel: this.spec.panel, values: this.values } })
        .catch((err) => { panelEvent({ panel: this.spec.panel, status: 'failed' }); S.toast(err.message || String(err), 5000); });
    }
    if (a === 'grid') this.gridForm();
    if (a === 'gridgo') this.gridGo();
    if (a === 'use') {
      const k = this.spec.controls.find((x) => x.kind === 'deck' && x.pick);
      panelEvent({ panel: this.spec.panel, status: 'rendering' });
      S.api(`/app/ask/api/sessions/${S.sessionId}/pick`, { method: 'POST', body: { panel: this.spec.panel, grid: k.pick, option: this.values[k.id] } })
        .catch((err) => { panelEvent({ panel: this.spec.panel, status: 'failed' }); S.toast(err.message || String(err), 5000); });
    }
    if (a === 'reset') { this.values = valuesOf(this.spec); this.saveState(); this.teardown(); this.render(); emit(); }
    if (a === 'star') {
      // Starred already (this card, or the preset it was recalled from): a second star would only make a copy.
      if (isStarred(this)) { S.toast('Already in the library. Rename or remove it under Surfaces.'); return; }
      const name = prompt('Name this preset', this.name || this.spec.title);
      if (name == null) return;
      try { await star(this, name); this.teardown(); this.render(); S.toast('Starred to the library'); }
      catch (err) { S.toast(err.message); }
    }
  }
}

// The controls a render can be asked to vary: what a knob, fader or switch holds.
const turnable = (spec) => spec.controls.filter((k) => k.kind === 'knob' || k.kind === 'fader' || k.kind === 'toggle');

midi.handler = (msg) => S.cards.get(S.active)?.onMidi(msg);
if (typeof window !== 'undefined') window.addEventListener('resize', () => S.cards.get(S.active)?.fit());

/** Make (or reuse, across streaming re-renders) the card for a surface. `live`: it just arrived, so it claims the arm. */
export function card({ id, raw, values, name, origin, from = null, live = false }) {
  const have = S.cards.get(id);
  if (have) return have.el;
  let v;
  try { v = validate(raw); }
  catch (e) {
    const el = document.createElement('div');
    el.className = 'zs-card zs-bad';
    el.innerHTML = `<b>Surface could not be drawn</b><small>${esc(e.message)}</small>`;
    return el;
  }
  const c = new Card({ id, ...v, values, name, origin, from });
  S.cards.set(id, c);
  if (live || (!S.active && local.get(armedKey()) === id)) arm(id, { quiet: !live });
  else c.render();
  return c.el;
}

export function arm(id, { quiet = false } = {}) {
  const c = S.cards.get(id);
  if (!c) return;
  const prev = S.cards.get(S.active);
  if (prev && prev !== c) { prev.teardown(); S.active = null; prev.render(); }
  if (prev === c) c.teardown();
  S.active = id;
  if (S.sessionId) local.set(armedKey(), id);
  c.render();
  if (!quiet) c.flash();
  emit();
}

export function disarm() {
  const c = S.cards.get(S.active);
  if (!c) return;
  c.teardown(); S.active = null; c.render(); emit();
}

/** Scroll a card into view and arm it. */
export function focus(id) {
  const c = S.cards.get(id);
  if (!c) return false;
  c.el.scrollIntoView({ block: 'center', behavior: 'smooth' });
  arm(id);
  return true;
}

/** After a replay: arm the card this device last armed here, else the newest. */
export function settle() {
  if (S.active && S.cards.has(S.active)) return;
  const ids = [...S.cards.keys()].filter((k) => S.cards.get(k).el.isConnected);
  const want = local.get(armedKey());
  const pick = ids.includes(want) ? want : ids[ids.length - 1];
  if (pick) arm(pick, { quiet: true });
}

/** Leave the session: freeze everything, forget the cards. */
export function clear() {
  for (const c of S.cards.values()) c.teardown();
  S.cards.clear();
  S.active = null;
  emit();   // the composer's chip for the armed card goes with it
}

/** The armed surface's state, sent with the next message. */
export function armedState() {
  const c = S.cards.get(S.active);
  if (!c) return null;
  const ab = c.spec.controls.find((k) => k.kind === 'ab');
  return { id: c.id, title: c.name || c.spec.title, ...(c.spec.panel ? { panel: c.spec.panel } : {}), values: { ...c.values }, changed: changed(c.spec, c.values).length, ...(ab ? { side: c.values[ab.id] } : {}) };
}
