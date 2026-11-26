// What rides along with a message: attached images (a screen frame, a file, a paste). Draws the chip row above the
// input; the page calls take() when it sends.
import { ICON } from './icons.js';
import { S } from './state.js';
import { screenPNG, filePNG, canCaptureScreen } from './capture.js';

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
let chips = null, tools = null, input = null;
let atts = [];             // { file, url }
let busy = 0;

export function mountComposer({ chipsEl, toolsEl, inputEl }) {
  chips = chipsEl; tools = toolsEl; input = inputEl;
  tools.innerHTML =
    (canCaptureScreen() ? `<button type="button" data-t="screen" title="Attach a screenshot" aria-label="Attach a screenshot">${ICON.screen}</button>` : '') +
    `<button type="button" data-t="file" title="Attach an image" aria-label="Attach an image">${ICON.image}</button>` +
    '<input type="file" accept="image/*" multiple hidden>';
  const picker = tools.querySelector('input[type=file]');
  tools.addEventListener('click', (e) => {
    const t = e.target.closest('[data-t]')?.dataset.t;
    if (t === 'screen') attach(screenPNG(), 'screen');
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
  });
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
  const parts = atts.map((a) => `<span class="zc-chip img"><img src="${esc(a.url)}" alt=""><button data-rm="${esc(a.file)}" aria-label="Remove image">${ICON.close}</button></span>`);
  if (busy) parts.push('<span class="zc-chip note">attaching…</span>');
  chips.innerHTML = parts.join('');
  chips.hidden = !parts.length;
}

/** What to send with this message; clears the attachments (untake() puts them back if the send fails). */
let taken = [];
export function take() {
  const out = { attachments: atts.map((a) => a.file) };
  taken = atts; atts = [];
  render();
  return out;
}
export function untake() { atts = [...taken, ...atts]; taken = []; render(); }
export const isBusy = () => busy > 0;
