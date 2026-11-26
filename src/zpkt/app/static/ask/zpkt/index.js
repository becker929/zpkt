// Entry point for the composer's parts (index.html's inline script uses window.Zpkt).
//   init({ api, toast })              once
//   openSession(id)                   which session a relative media path belongs to
//   mountComposer(...), take()        the chip row and the images that ride along with a message
//   mediaUrl(src)                     a path an agent wrote, as a fetchable URL
// Controls are not drawn here any more: an agent makes a page and links to it, and the page lives on the Desk.
import { S, mediaUrl } from './state.js';
import { mountComposer, take, untake, isBusy } from './composer.js';

window.Zpkt = {
  init({ api, toast }) { S.api = api; if (toast) S.toast = toast; },
  openSession(id) { S.sessionId = id; },
  mediaUrl, mountComposer, take, untake, isBusy,
};
window.dispatchEvent(new Event('zpkt-ready'));
