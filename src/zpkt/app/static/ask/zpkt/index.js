// Entry point: the surface system's interface to the page (index.html's inline script uses window.Zpkt).
//   init({ api, toast })              once
//   openSession(id)                   before replaying a session's events
//   hydrate(bubble, { live })         after a message bubble's markdown is (re)drawn
//   fromEvent(e, { live })            a recalled preset arriving as a 'surface' event -> card element
//   settle()                          after the replay: arm the right card
//   mountComposer(...), take()        the chip row and what rides along with a message
//   renderLibrary(el, opts), renderMidi(el)   the side panels
//   mediaUrl(src)                     a path an agent wrote, as a fetchable URL
import { S, onChange, mediaUrl } from './state.js';
import { card, settle, clear, armedState, focus, arm, disarm, panelEvent } from './cards.js';
import { loadLibrary } from './library.js';
import { mountComposer, take, untake, isBusy } from './composer.js';
import { renderLibrary, renderMidi } from './panels.js';
import { ICON } from './icons.js';

async function openSession(id) {
  clear();
  S.sessionId = id;
  S.states = {};
  if (id) { try { S.states = (await S.api(`/app/ask/api/surfaces?session=${id}`)).states || {}; } catch {} }
}

/**
 * Placeholders from the markdown renderer: <div class="zs-slot" data-k="0" data-spec="…">; the bubble has data-seq.
 * A card's id is session/seq/index, stable across replays and streaming re-renders.
 */
function hydrate(bubble, { live }) {
  for (const slot of bubble.querySelectorAll('.zs-slot')) {
    const c = card({ id: `${S.sessionId}/${bubble.dataset.seq}/${slot.dataset.k}`, raw: slot.dataset.spec, live });
    c._md = slot._md;   // the page's streaming redraw keeps a block whose source has not changed (index.html patch())
    slot.replaceWith(c);
  }
}

const fromEvent = (e, { live }) => card({ id: `${S.sessionId}/${e.seq}/r`, raw: e.spec, values: e.values, name: e.name, origin: e.from ? 'the library' : null, from: e.from || null, live });

window.Zpkt = {
  init({ api, toast }) { S.api = api; if (toast) S.toast = toast; loadLibrary(); },
  openSession, hydrate, fromEvent, settle, armedState, focus, arm, disarm, onChange, mediaUrl, panelEvent,
  mountComposer, take, untake, isBusy, renderLibrary, renderMidi, ICON,
};
window.dispatchEvent(new Event('zpkt-ready'));
