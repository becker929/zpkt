// Hardware MIDI. Physical controls are mapped once per device to slots (encoders 0-15, pads 0-15); a surface's
// midiSlot then always lands on the same physical knob or pad, whatever the agent drew. Only the armed card
// receives input: the dispatch goes to one handler, set by cards.js.
import { emit, local, S } from './state.js';

const DEFAULT_MAP = { cc: {}, note: Object.fromEntries(Array.from({ length: 16 }, (_, i) => [`n${36 + i}`, i])) }; // GM drum pads

export const midi = {
  access: null,
  inputs: [],
  last: '',
  learn: null,                       // { kind: 'cc' | 'note', next }
  map: local.get('zpkt.midi', DEFAULT_MAP),
  handler: null,                     // ({ kind: 'cc' | 'note', slot, value: 0..1, raw }) => void
  supported: () => typeof navigator !== 'undefined' && !!navigator.requestMIDIAccess,
};
const saveMap = () => local.set('zpkt.midi', midi.map);

export async function enable() {
  if (!midi.supported()) throw new Error('This browser has no Web MIDI (Safari and iOS do not). Use Chrome or Edge on a computer.');
  if (!midi.access) {
    midi.access = await navigator.requestMIDIAccess({ sysex: false });
    midi.access.onstatechange = attach;
  }
  attach();
  local.set('zpkt.midi.on', true);
  return midi.inputs;
}

function attach() {
  midi.inputs = [];
  for (const input of midi.access.inputs.values()) {
    input.onmidimessage = (e) => receive(e.data);
    if (input.state === 'connected') midi.inputs.push(input.name);
  }
  emit();
}

export function startLearn(kind) { midi.learn = { kind, next: 0 }; midi.map[kind] = {}; saveMap(); emit(); }
export function stopLearn() { midi.learn = null; emit(); }
export function resetMap() { midi.map = JSON.parse(JSON.stringify(DEFAULT_MAP)); saveMap(); emit(); }

/** Decode one MIDI message, learn or map it, and hand it to the armed card. Exported for tests. */
export function receive([status, d1, d2 = 0]) {
  const type = status & 0xf0;
  let kind;
  if (type === 0xb0) kind = 'cc';
  else if (type === 0x90 && d2 > 0) kind = 'note';
  else return null;
  const key = (kind === 'cc' ? 'c' : 'n') + d1;
  const name = kind === 'cc' ? `CC ${d1}` : `Note ${d1}`;
  midi.last = kind === 'cc' ? `CC ${d1} = ${d2}` : `note ${d1} vel ${d2}`;
  const map = midi.map[kind];

  if (midi.learn?.kind === kind && !(key in map)) {
    map[key] = midi.learn.next++;
    saveMap();
    S.toast(`${name} → ${kind === 'cc' ? 'encoder' : 'pad'} slot ${map[key] + 1}`);
    if (midi.learn.next >= 16) midi.learn = null;
    emit();
    return null;
  }
  if (!(key in map) && kind === 'cc' && !midi.learn) {
    // Unmapped knob: give it the next free encoder slot, so a new controller works without a learn pass.
    const used = new Set(Object.values(map));
    let s = 0;
    while (used.has(s) && s < 16) s++;
    if (s < 16) { map[key] = s; saveMap(); S.toast(`${name} mapped to encoder slot ${s + 1} (change it under MIDI)`); }
  }
  const msg = key in map ? { kind, slot: map[key], value: d2 / 127, raw: d2 } : null;
  if (msg) midi.handler?.(msg);
  emit();
  return msg;
}

if (local.get('zpkt.midi.on', false) && midi.supported()) enable().catch(() => {});
