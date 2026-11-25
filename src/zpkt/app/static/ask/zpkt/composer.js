// What rides along with a message: attached images (screen, surface snapshot, file, paste) and the armed surface's
// state. Renders the chip row above the input; the page calls take() when it sends.
import { ICON } from './icons.js';
import { esc } from './draw.js';
import { S, onChange } from './state.js';
import { armedState } from './cards.js';
import { surfacePNG, screenPNG, filePNG, canCaptureScreen } from './capture.js';

let chips = null, tools = null, input = null;
let atts = [];             // { file, url }
let sendSurface = true;    // include the armed surface's state with the next message
let busy = 0;

export function mountComposer({ chipsEl, toolsEl, inputEl }) {
  chips = chipsEl; tools = toolsEl; input = inputEl;
  tools.innerHTML =
    (canCaptureScreen() ? `<button type="button" data-t="screen" title="Attach a screenshot (pick a DAW window)" aria-label="Attach a screenshot">${ICON.screen}</button>` : '') +
    `<button type="button" data-t="surface" title="Attach the armed surface as an image" aria-label="Attach the armed surface as an image">${ICON.surface}</button>` +
    `<button type="button" data-t="file" title="Attach an image" aria-label="Attach an image">${ICON.image}</button>` +
    '<input type="file" accept="image/*" multiple hidden>';
  const picker = tools.querySelector('input[type=file]');
  tools.addEventListener('click', (e) => {
    const t = e.target.closest('[data-t]')?.dataset.t;
    if (t === 'screen') attach(screenPNG(), 'screen');
    if (t === 'surface') attach(surfacePNG(), 'surface');
    if (t === 'file') picker.click();
  });
  picker.onchange = () => { for (const f of picker.files) attach(filePNG(f), f.name); picker.value = ''; };
  input.addEventListener('paste', (e) => {
    const imgs = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith('image/'));
    if (imgs.length) { e.preventDefault(); for (const f of imgs) attach(filePNG(f), 'pasted'); }
  });
  chips.addEventListener('click', (e) => {
    const rm = e.target.closest('[data-rm]');
    if (rm) { atts = atts.filter((a) => a.file !== rm.dataset.rm); render(); }
    if (e.target.closest('[data-sf]')) { sendSurface = !sendSurface; render(); }
  });
  onChange(render);
  render();
}

async function attach(pngPromise, name) {
  busy++; render();
  try {
    const dataUrl = await pngPromise;
    const { attachment } = await S.api('/app/ask/api/attachments', { method: 'POST', body: { dataUrl, name } });
    atts.push({ file: attachment.file, url: `/app/ask/api/attachments/${encodeURIComponent(attachment.file)}` });
  } catch (e) {
    if (e?.name !== 'NotAllowedError' && e?.name !== 'AbortError') S.toast(e.message || String(e), 5000);
  } finally { busy--; render(); }
}

function render() {
  if (!chips) return;
  const sf = armedState();
  const parts = atts.map((a) => `<span class="zc-chip img"><img src="${esc(a.url)}" alt=""><button data-rm="${esc(a.file)}" aria-label="Remove image">${ICON.close}</button></span>`);
  if (busy) parts.push('<span class="zc-chip note">attaching…</span>');
  if (sf) {
    parts.push(`<button class="zc-chip sf${sendSurface ? ' on' : ''}" data-sf="1" title="${sendSurface ? 'Its values go with your message. Tap to leave them out.' : 'Tap to send its values with your message.'}">` +
      `<span class="zs-dot on"></span>${esc(sf.title)}${sf.changed ? ` · ${sf.changed} changed` : ''}${sendSurface ? '' : ' · not sent'}</button>`);
  }
  chips.innerHTML = parts.join('');
  chips.hidden = !parts.length;
  const sb = tools?.querySelector('[data-t=surface]');
  if (sb) sb.disabled = !sf;
}

/** What to send with this message; clears the attachments (untake() puts them back if the send fails). */
let taken = [];
export function take() {
  const out = { attachments: atts.map((a) => a.file), surface: sendSurface ? armedState() : null };
  taken = atts; atts = [];
  render();
  return out;
}
export function untake() { atts = [...taken, ...atts]; taken = []; render(); }
export const isBusy = () => busy > 0;
