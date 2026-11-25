// Side panels: the Library (surfaces in this thread + starred presets) and MIDI settings.
// Each fills an element the page provides; the page opens and closes its sheets.
import { ICON } from './icons.js';
import { esc } from './draw.js';
import { S, onChange } from './state.js';
import { focus } from './cards.js';
import { library, loadLibrary, recall, rename, removePreset } from './library.js';
import { midi, enable, startLearn, stopLearn, resetMap } from './midi.js';

const ago = (t) => { const s = (Date.now() - t) / 1000; return s < 3600 ? `${Math.max(1, Math.round(s / 60))} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : new Date(t).toLocaleDateString(); };

/* ---------- library ---------- */
export async function renderLibrary(el, { close }) {
  await loadLibrary();
  const here = [...S.cards.values()].filter((c) => c.el.isConnected);
  const row = (attrs, title, sub, extra = '') => `<div class="zl-row" ${attrs}><button class="zl-go"><b>${title}</b><small>${sub}</small></button>${extra}</div>`;
  el.innerHTML =
    '<h4>In this session</h4>' +
    (here.length ? here.map((c, i) => row(`data-here="${esc(c.id)}"`,
      `${S.active === c.id ? '<span class="zs-dot on"></span>' : ''}${esc(c.name || c.spec.title)}`,
      `${i + 1} of ${here.length} · ${c.spec.controls.length} controls · ${S.active === c.id ? 'armed' : 'frozen'}`)).join('')
      : '<p class="note">No surfaces yet. Ask the agent for one, e.g. “give me a surface for the kick’s decay, drive and level”.</p>') +
    '<h4>Library</h4>' +
    (library().length ? library().map((p) => row(`data-p="${esc(p.id)}"`, `${ICON.starOn} ${esc(p.name)}`,
      `${p.spec?.controls?.length || 0} controls · ${ago(p.updated)}`,
      `<button class="zs-ib" data-ren aria-label="Rename" title="Rename">Aa</button><button class="zs-ib" data-del aria-label="Delete" title="Delete">${ICON.close}</button>`)).join('')
      : '<p class="note">Star a surface to keep it here. Starred presets can be recalled into any session.</p>');

  el.onclick = async (e) => {
    const r = e.target.closest('.zl-row');
    if (!r) return;
    if (r.dataset.here) { close(); focus(r.dataset.here); return; }
    const p = library().find((x) => x.id === r.dataset.p);
    if (!p) return;
    try {
      if (e.target.closest('[data-del]')) { if (confirm(`Delete “${p.name}” from the library?`)) { await removePreset(p.id); renderLibrary(el, { close }); } return; }
      if (e.target.closest('[data-ren]')) { const n = prompt('Rename preset', p.name); if (n) { await rename(p.id, n); renderLibrary(el, { close }); } return; }
      close();
      await recall(p, focus);
    } catch (err) { S.toast(err.message, 5000); }
  };
}

/* ---------- MIDI ---------- */
export function renderMidi(el) {
  const draw = () => {
    const cc = Object.entries(midi.map.cc).sort((a, b) => a[1] - b[1]);
    const note = Object.entries(midi.map.note).sort((a, b) => a[1] - b[1]);
    const list = (m, kind) => m.length ? m.map(([k, s]) => `<span class="zm-map">${kind === 'cc' ? 'CC' : 'Note'} ${k.slice(1)} → ${s + 1}</span>`).join('') : '<span class="note">none</span>';
    el.innerHTML = !midi.supported()
      ? '<p class="note">This browser has no Web MIDI. Safari and iPhone do not support it; use Chrome or Edge on a computer with the controller plugged in.</p>'
      : `<p class="sub">Only the armed surface listens. Each physical knob and pad is mapped once to a slot; a surface’s <code>midiSlot</code> then always lands on the same hardware control.</p>
        <div class="zm-row"><b>Inputs</b> ${midi.access ? (midi.inputs.length ? midi.inputs.map(esc).join(', ') : 'none connected') : '<button class="zm-btn" data-m="enable">Enable MIDI</button>'}</div>
        <div class="zm-row"><b>Last message</b> <span class="mono">${esc(midi.last || '—')}</span></div>
        <div class="zm-row"><b>Encoders</b> ${list(cc, 'cc')}</div>
        <div class="zm-row"><b>Pads</b> ${list(note, 'note')}</div>
        ${midi.learn ? `<p class="zm-learn">Learning ${midi.learn.kind === 'cc' ? 'encoders' : 'pads'}: move ${midi.learn.kind === 'cc' ? 'knob' : 'pad'} ${midi.learn.next + 1} on your controller… <button class="zm-btn" data-m="stop">Done</button></p>`
          : `<div class="zm-row"><button class="zm-btn" data-m="cc">Learn encoders</button><button class="zm-btn" data-m="note">Learn pads</button><button class="zm-btn" data-m="reset">Reset</button></div>`}
        <p class="note">Unmapped knobs take the next free slot by themselves. Pads default to notes 36–51.</p>`;
  };
  el.onclick = async (e) => {
    const m = e.target.closest('[data-m]')?.dataset.m;
    try {
      if (m === 'enable') await enable();
      if (m === 'cc' || m === 'note') { if (!midi.access) await enable(); startLearn(m); }
      if (m === 'stop') stopLearn();
      if (m === 'reset') resetMap();
    } catch (err) { S.toast(err.message, 6000); }
  };
  draw();
  return onChange(draw); // the page calls the returned function when the sheet closes
}
