// The preset library: starred surfaces (spec + values), shared across sessions and devices.
// Recall either arms the card if it is already in the open thread, or pushes a fresh copy to the bottom of the
// session as a 'surface' event, which the thread draws and arms like any new surface.
import { S } from './state.js';
import { valuesOf } from './spec.js';

let presets = [];

export async function loadLibrary() {
  try { presets = (await S.api('/app/ask/api/library')).library; } catch {}
  return presets;
}
export const library = () => presets;
export const isStarred = (card) => !!card.preset || presets.some((p) => p.source === card.id || p.id === card.from);

export async function star(card, name) {
  const { preset } = await S.api('/app/ask/api/library', { method: 'POST', body: { spec: card.spec, values: card.values, name, session: S.sessionId, source: card.id } });
  card.preset = preset.id;
  card.name = preset.name;
  await loadLibrary();
  return preset;
}

export async function rename(id, name) { await S.api(`/app/ask/api/library/${id}`, { method: 'PATCH', body: { name } }); return loadLibrary(); }
export async function removePreset(id) { await S.api(`/app/ask/api/library/${id}`, { method: 'DELETE' }); return loadLibrary(); }

/** Recall a preset. `focus(id)` is cards.focus (passed in to keep this module below cards.js). */
export async function recall(p, focus) {
  for (const c of S.cards.values()) {
    if (c.id === p.source || c.preset === p.id) {
      c.preset = p.id;
      c.values = valuesOf(c.spec, c.values, p.values);
      c.saveState();
      c.teardown(); c.render();
      return focus(c.id);
    }
  }
  if (!S.sessionId) throw new Error('Open a session first, then recall the preset into it');
  await S.api(`/app/ask/api/sessions/${S.sessionId}/surface`, { method: 'POST', body: { spec: p.spec, values: p.values, from: p.id, name: p.name } });
  return true;
}
