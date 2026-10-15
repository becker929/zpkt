// The Rummage's permanent state and its rules (docs/rummage.md): what each machine has committed, the one artifact
// carried, what sits on the Gramophone's three plinths, and every time the short was finished. Nothing is locked:
// any machine can be operated in any order, and recommitted later.
//
// The state is the region's, kept by the harness (GET and POST /studio/api/regions/rummage/state, replaced whole).
// Every change is also kept in this browser; when the harness can't take it (no region API yet, the Mac asleep) it
// stays marked unsent, and is sent the next time the page finds the API. So the region plays the same either way.
//
//   const flow = await createFlow()
//   flow.state                     { committed: {bed, drums, bass}, carrying, plinths: {bed, drums, bass}, completions, version }
//   flow.commit(part, id)          -> { artifact, dropped }: the choice, distilled into an artifact, now carried;
//                                     what was carried before (if anything else) goes back to its machine
//   flow.place()                   -> { part, artifact, replaced } | null: the carried artifact onto its plinth
//   flow.combo()                   -> '2-1-3' when all three plinths are filled, else null
//   flow.finish(combo)             -> true the first time this combination is finished (a completion is kept)
//   flow.mode                      'api' once the harness has the state, 'local' while it can't
//   hangPlate({ combo, file, sleeve, names })   the finished short's plate in the museum (track sh001)
import { PARTS } from './region.js';

const API = '/studio/api/regions/rummage/state';
const KEY = 'rummage:state';
const PLATES = 'rummage:plates';
const ART = /^(bed|drums|bass)-[123]$/;

const fresh = () => ({ committed: { bed: null, drums: null, bass: null }, carrying: null, plinths: { bed: null, drums: null, bass: null }, completions: [], version: 0 });
/** Whatever came back, made into the state's shape (unknown keys are kept for the server's sake). */
export function normalize(s) {
  const out = { ...fresh(), ...(s && typeof s === 'object' ? s : {}) };
  const id = (v) => (Number.isInteger(v) && v >= 1 && v <= 3 ? v : null);
  out.committed = Object.fromEntries(PARTS.map((p) => [p, id(s?.committed?.[p])]));
  out.plinths = Object.fromEntries(PARTS.map((p) => { const v = s?.plinths?.[p]; return [p, typeof v === 'string' && ART.test(v) && v.startsWith(`${p}-`) ? v : null]; }));
  out.carrying = typeof s?.carrying === 'string' && ART.test(s.carrying) ? s.carrying : null;
  out.completions = Array.isArray(s?.completions) ? s.completions.filter((c) => c && typeof c.combo === 'string') : [];
  out.version = Number.isFinite(s?.version) ? s.version : 0;
  return out;
}
const readLocal = () => { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch { return {}; } };
function writeLocal(state, unsent) { try { localStorage.setItem(KEY, JSON.stringify({ state, unsent })); } catch { /* this visit only */ } }

async function send(state) {
  const r = await fetch(API, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(state) });
  if (!r.ok) throw new Error(`state ${r.status}`);
  return normalize(await r.json());
}

export async function createFlow() {
  const local = readLocal();
  let state = normalize(local.state), mode = 'local', unsent = !!local.unsent;
  try {
    const r = await fetch(API, { cache: 'no-store' });
    if (r.ok) {
      mode = 'api';
      const theirs = normalize(await r.json());
      if (unsent && local.state) {
        // changes made here while the harness couldn't take them: they are the newest, so they go up
        try { state = await send({ ...state, version: theirs.version }); unsent = false; } catch { /* next time */ }
      } else state = theirs;
      writeLocal(state, unsent);
    }
  } catch { /* the harness isn't there: this browser's copy */ }

  let chain = Promise.resolve();
  function save() {
    writeLocal(state, true);
    if (mode !== 'api') return chain;
    const snap = JSON.parse(JSON.stringify(state));
    chain = chain.then(() => send(snap)).then((back) => {
      state.version = back.version;
      writeLocal(state, false);
    }).catch(() => { /* kept here, marked unsent */ });
    return chain;
  }

  const flow = {
    get state() { return state; },
    get mode() { return mode; },
    saved: () => chain,
    commit(part, id) {
      const artifact = `${part}-${id}`, before = state.carrying;
      state.committed[part] = id;
      state.carrying = artifact;
      save();
      return { artifact, dropped: before && before !== artifact ? before : null };
    },
    place() {
      const artifact = state.carrying;
      if (!artifact) return null;
      const part = artifact.split('-')[0], replaced = state.plinths[part];
      state.plinths[part] = artifact;
      state.carrying = null;
      save();
      return { part, artifact, replaced: replaced && replaced !== artifact ? replaced : null };
    },
    combo() {
      if (!PARTS.every((p) => state.plinths[p])) return null;
      return PARTS.map((p) => state.plinths[p].split('-')[1]).join('-');
    },
    finish(combo) {
      const last = state.completions[state.completions.length - 1];
      if (last?.combo === combo) return false;
      state.completions.push({ at: new Date().toISOString(), combo });
      save();
      return true;
    },
    /** For the tests and the lead: start over. */
    reset() { state = fresh(); return save(); },
  };
  return flow;
}

// --- the plate: the finished short, hung in the museum (the artist's gallery, track sh001) ---
async function postPlate(plate) {
  const r = await fetch('/studio/api/artist/plates', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(plate) });
  if (!r.ok) throw new Error(`plate ${r.status}`);
  return r.json();
}
const waiting = () => { try { return JSON.parse(localStorage.getItem(PLATES)) || []; } catch { return []; } };
function setWaiting(list) { try { localStorage.setItem(PLATES, JSON.stringify(list.slice(-20))); } catch { /* this visit only */ } }
/** Plates that couldn't be hung (the harness was away), sent now. */
export async function hangWaiting() {
  const list = waiting(), left = [];
  for (const p of list) { try { await postPlate(p); } catch { left.push(p); } }
  setWaiting(left);
}
export async function hangPlate({ combo, file, sleeve = null, names = {} }) {
  const ids = combo.split('-');
  const plate = {
    track: 'sh001', step: 'release', item: 'short', title: 'SH001',
    work: { id: 'gramophone', version: 1, title: 'The Gramophone', params: {} },
    done: PARTS.map((p, i) => `${p}-${ids[i]}`), unlocked: [],
    render: { path: file ?? null, label: `SH001 · ${PARTS.map((p) => names[p] ?? p).join(' · ')}`, url: file ? `/studio/regions/rummage/audio/${file}` : null },
    combo, choices: Object.fromEntries(PARTS.map((p, i) => [p, { id: Number(ids[i]), name: names[p] ?? null }])),
    sleeve: sleeve ?? null, client_ts: Date.now(),
  };
  try { return await postPlate(plate); } catch { setWaiting([...waiting(), plate]); return null; }
}
