// The Gemini chat (contrib/docs/gemini.md): chats live on the Mac, answers stream as NDJSON events, tool steps and
// images show inline, and any reply can be handed to Claude as a harness job.
const $ = (s) => document.querySelector(s);
const API = '/studio/gemini/api';
const ICON = {
  send: '<path d="M12 19V5M6 11l6-6 6 6"/>',
  stop: '<rect x="7" y="7" width="10" height="10" fill="currentColor"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
};

let state = { chats: [], settings: {}, usage: null, branch: '' };
let chat = null;            // the open chat, as the server keeps it
let models = [];
let pending = [];           // images to attach: {mime, data}
let ctrl = null;            // while answering
let live = null;            // the answer being streamed: {el, segs: [...]}
const remembered = (() => { try { return localStorage.getItem('gemini.chat'); } catch { return null; } })();
const remember = (id) => { try { id ? localStorage.setItem('gemini.chat', id) : localStorage.removeItem('gemini.chat'); } catch {} };

const dollars = (d) => (d >= 1 ? '$' + d.toFixed(2) : d >= 0.01 ? '$' + d.toFixed(3) : d > 0 ? '<$0.01' : '$0');
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

async function api(path, opts = {}) {
  const r = await fetch(API + path, { headers: { 'content-type': 'application/json' }, ...opts });
  const j = await r.json().catch(() => ({}));
  if (r.status === 401) { location.href = '/login?next=/studio/gemini/'; throw new Error('Sign in first.'); }
  if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
}

/* ---------- markdown (escape first, then format) ---------- */
function inline(s) {
  s = esc(s);
  const codes = [];
  s = s.replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return '\u0000' + (codes.length - 1) + '\u0000'; });
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\(((?:https?:\/\/|\/)[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => '<code>' + codes[i] + '</code>');
}
function md(src) {
  const L = src.replace(/\r\n/g, '\n').split('\n');
  let out = '', i = 0;
  const isRow = (l) => /^\s*\|.*\|\s*$/.test(l);
  const cells = (l) => l.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
  while (i < L.length) {
    const l = L[i];
    let m;
    if (/^\s*```/.test(l)) {
      const buf = []; i++;
      while (i < L.length && !/^\s*```/.test(L[i])) buf.push(L[i++]);
      i++;
      out += `<pre><button class="cp" type="button">Copy</button><code>${esc(buf.join('\n'))}</code></pre>`;
    } else if ((m = l.match(/^(#{1,4})\s+(.*)/))) {
      out += `<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`; i++;
    } else if (isRow(l) && i + 1 < L.length && /^\s*\|?\s*:?-{2,}/.test(L[i + 1])) {
      const head = cells(l); i += 2;
      let rows = '';
      while (i < L.length && isRow(L[i])) { rows += '<tr>' + cells(L[i]).map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>'; i++; }
      out += `<div class="tbl"><table><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>`;
    } else if (/^\s*[-*]\s+/.test(l) || /^\s*\d+[.)]\s+/.test(l)) {
      const ord = /^\s*\d+[.)]/.test(l); let items = '';
      while (i < L.length && (ord ? /^\s*\d+[.)]\s+/ : /^\s*[-*]\s+/).test(L[i])) {
        items += `<li>${inline(L[i].replace(/^\s*(?:[-*]|\d+[.)])\s+/, ''))}</li>`; i++;
      }
      out += ord ? `<ol>${items}</ol>` : `<ul>${items}</ul>`;
    } else if (/^>\s?/.test(l)) {
      const buf = [];
      while (i < L.length && /^>\s?/.test(L[i])) buf.push(L[i++].replace(/^>\s?/, ''));
      out += `<blockquote>${inline(buf.join(' '))}</blockquote>`;
    } else if (!l.trim()) { i++; }
    else {
      const buf = [];
      while (i < L.length && L[i].trim() && !/^(\s*```|#{1,4}\s|\s*[-*]\s+|\s*\d+[.)]\s+|>)/.test(L[i]) && !isRow(L[i])) buf.push(L[i++]);
      if (!buf.length) buf.push(L[i++]);
      out += `<p>${inline(buf.join('\n')).replace(/\n/g, '<br>')}</p>`;
    }
  }
  return out;
}

/* ---------- what a stored chat looks like on screen ---------- */
// A turn: what he typed, then everything the model did until it answered (text, tool steps, images).
function turns(contents) {
  const out = [];
  let cur = null;
  for (const c of contents) {
    const isReply = c.role === 'user' && c.parts.some((p) => p.functionResponse);
    if (c.role === 'user' && !isReply) {
      out.push({ user: c }); cur = { segs: [], dollars: 0, model: '' }; out.push({ model: cur });
      continue;
    }
    if (!cur) { cur = { segs: [], dollars: 0, model: '' }; out.push({ model: cur }); }
    for (const p of c.parts) {
      if (p.text && !p.thought) addText(cur.segs, p.text);
      else if (p.functionCall) cur.segs.push({ step: p.functionCall });
      else if (p._images) cur.segs.push({ images: p._images });
    }
    if (c._meta?.usage) { cur.dollars += c._meta.usage.dollars || 0; cur.model = c._meta.model; }
  }
  return out.filter((t) => t.user || t.model.segs.length || t.model.err);
}
function addText(segs, text) {
  const last = segs[segs.length - 1];
  if (last && 'text' in last) last.text += text; else segs.push({ text });
}

function stepLine(call) {
  const a = call.args || {};
  const say = {
    zpkt_list: () => ['list', a.path || '/'],
    zpkt_read: () => ['read', a.path + (a.offset > 1 ? `:${a.offset}` : '')],
    zpkt_search: () => ['search', `/${a.pattern}/` + (a.path ? ` in ${a.path}` : '') + (a.glob ? ` ${a.glob}` : '')],
    zpkt_log: () => ['git log', a.path || ''],
    list_images: () => ['images', a.batch || 'newest'],
    make_image: () => ['make image', a.title || (a.prompt || '').slice(0, 60)],
  }[call.name];
  const [verb, what] = say ? say() : [call.name, JSON.stringify(a).slice(0, 80)];
  return `<div class="step"><span><b>${esc(verb)}</b> ${esc(what)}</span></div>`;
}

function imagesHTML(list) {
  return '<div class="made">' + list.map((im) =>
    `<a href="/studio/images/files/${esc(im.file)}" target="_blank" rel="noopener"><img src="/studio/images/files/${esc(im.thumb)}" width="${im.width}" height="${im.height}" alt="" loading="lazy"></a>`).join('') + '</div>';
}

function modelHTML(t, streaming) {
  let h = '<div class="bubble">';
  for (const s of t.segs) {
    if ('text' in s) h += md(s.text);
    else if (s.step) h += stepLine(s.step);
    else if (s.images) h += imagesHTML(s.images);
  }
  if (streaming) h += '<span class="dots"></span>';
  if (t.err) h += `<p class="err">${esc(t.err)}</p>`;
  h += '</div>';
  if (!streaming) {
    const text = t.segs.filter((s) => 'text' in s).map((s) => s.text).join('\n\n');
    h += '<div class="acts">' +
      (text ? '<button type="button" data-a="copy">Copy</button>' : '') +
      (t.last ? '<button type="button" data-a="retry">Retry</button>' : '') +
      (text ? '<button type="button" data-a="claude" class="claude">Send to Claude</button>' : '') +
      (t.dollars ? `<span class="cost">${esc(t.model || '')} ${dollars(t.dollars)}</span>` : '') + '</div>';
  }
  return h;
}

function userHTML(c) {
  const files = c.parts.filter((p) => p.file);
  const text = c.parts.filter((p) => p.text).map((p) => p.text).join('').trim();
  let h = '';
  if (files.length) h += '<div class="attached">' + files.map((p) => `<img src="/studio/gemini/files/${esc(chat.id)}/${esc(p.file)}" alt="">`).join('') + '</div>';
  if (text) h += `<div class="bubble">${esc(text)}</div>`;
  return h;
}

function render() {
  $('#title').textContent = chat?.title || 'Gemini';
  sub();
  const th = $('#thread');
  if (!chat || !chat.contents.length) {
    th.innerHTML = `<div class="empty"><h2>Gemini in zpkt</h2><div>It can read the repo and make images for the wall. Any reply can go to Claude as a job.</div>
      <div class="tries">${['What changed in zpkt this week?', 'Explain how the harness serves the studio pages.', 'Summarise the newest journal entry.']
        .map((q) => `<button type="button" data-try="${esc(q)}">${esc(q)}</button>`).join('')}</div></div>`;
  } else {
    const ts = turns(chat.contents);
    const lastModel = [...ts].reverse().find((t) => t.model);
    if (lastModel) lastModel.model.last = true;
    th.innerHTML = '';
    ts.forEach((t, i) => {
      const d = document.createElement('div');
      d.className = 'm ' + (t.user ? 'user' : 'model');
      d.dataset.i = i;
      d.innerHTML = t.user ? userHTML(t.user) : modelHTML(t.model, false);
      if (t.model) d._turn = t.model;
      th.append(d);
    });
  }
  renderList();
  scroll(true);
}

function sub() {
  const parts = [];
  const s = chat?.settings || state.settings;
  if (s.model) parts.push(s.model);
  if (s.zpkt) parts.push('zpkt' + (state.branch && state.branch !== 'main' ? ` @ ${state.branch}` : ''));
  if (chat?.dollars) parts.push(dollars(chat.dollars));
  $('#sub').textContent = parts.join(' · ');
}

function renderList() {
  const l = $('#list'); l.innerHTML = '';
  for (const c of state.chats) {
    const d = document.createElement('div');
    d.className = 'g-item' + (c.id === chat?.id ? ' on' : '');
    d.innerHTML = `<button type="button" class="t"><span></span><i>${esc(c.updated.slice(0, 10))}${c.dollars ? ' · ' + dollars(c.dollars) : ''}</i></button>
      <button type="button" class="x" aria-label="Delete chat"><svg viewBox="0 0 24 24">${ICON.x}</svg></button>`;
    d.querySelector('.t span').textContent = c.title;
    d.querySelector('.t').onclick = () => { document.body.classList.remove('nav'); open(c.id); };
    d.querySelector('.x').onclick = async () => {
      if (!confirm(`Delete “${c.title}”?`)) return;
      await api(`/chats/${c.id}`, { method: 'DELETE' });
      if (chat?.id === c.id) { chat = null; remember(null); }
      await refresh(); render();
    };
    l.append(d);
  }
  const u = state.usage;
  $('#spend').textContent = u ? `${u.month}: chat ${dollars(u.chat)} · ${u.image_count} images ${dollars(u.images)} (est.)` : '';
}

function scroll(force) {
  const s = $('#msgs');
  if (force || s.scrollHeight - s.scrollTop - s.clientHeight < 160) s.scrollTop = s.scrollHeight;
}

async function refresh() { state = await api('/state'); }
async function open(id) {
  if (ctrl) return;
  try { chat = await api(`/chats/${id}`); remember(id); } catch { chat = null; remember(null); }
  render();
}

/* ---------- a turn, streamed ---------- */
function setBusy(on) {
  $('#send').classList.toggle('stop', on);
  $('#send-icon').innerHTML = on ? ICON.stop : ICON.send;
  $('#send').setAttribute('aria-label', on ? 'Stop' : 'Send');
}

async function stream(path, body) {
  ctrl = new AbortController(); setBusy(true);
  const t = { segs: [], dollars: 0, model: '' };
  const el = document.createElement('div'); el.className = 'm model';
  $('#thread').querySelector('.empty')?.remove();
  $('#thread').append(el);
  let raf = 0;
  const paint = () => { raf = 0; el.innerHTML = modelHTML(t, true); scroll(); };
  const upd = () => { if (!raf) raf = requestAnimationFrame(paint); };
  paint();
  let id = chat?.id;
  try {
    const r = await fetch(API + path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body), signal: ctrl.signal });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `HTTP ${r.status}`);
    const rd = r.body.getReader(), dec = new TextDecoder();
    let buf = '';
    for (;;) {
      const { done, value } = await rd.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let k;
      while ((k = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, k); buf = buf.slice(k + 1);
        if (!line.trim()) continue;
        const ev = JSON.parse(line);
        if (ev.type === 'chat') { id = ev.id; remember(id); $('#title').textContent = ev.title; }
        else if (ev.type === 'text') addText(t.segs, ev.text);
        else if (ev.type === 'tool') t.segs.push({ step: { name: ev.name, args: ev.args } });
        else if (ev.type === 'images') t.segs.push({ images: ev.images });
        else if (ev.type === 'usage') { t.dollars += ev.dollars; t.model = ev.model; }
        else if (ev.type === 'error') t.err = ev.error;
        upd();
      }
    }
  } catch (e) {
    if (e.name !== 'AbortError') t.err = e.message;
  } finally {
    ctrl = null; setBusy(false);
    if (raf) cancelAnimationFrame(raf);
  }
  // The Mac's copy is the truth: load it again (an aborted answer keeps what was saved before it stopped).
  await refresh().catch(() => {});
  if (id) { try { chat = await api(`/chats/${id}`); } catch {} }
  render();
  if (t.err) {
    const last = [...$('#thread').querySelectorAll('.m.model')].pop();
    last?.querySelector('.bubble')?.insertAdjacentHTML('beforeend', `<p class="err">${esc(t.err)}</p>`);
    scroll(true);
  }
}

async function send() {
  if (ctrl) { ctrl.abort(); return; }
  const text = $('#in').value.trim();
  if (!text && !pending.length) return;
  const images = pending;
  pending = []; $('#in').value = ''; grow(); renderPrev();
  // show his message at once
  $('#thread').querySelector('.empty')?.remove();
  const u = document.createElement('div'); u.className = 'm user';
  u.innerHTML = (images.length ? '<div class="attached">' + images.map((x) => `<img src="data:${x.mime};base64,${x.data}" alt="">`).join('') + '</div>' : '') +
    (text ? `<div class="bubble">${esc(text)}</div>` : '');
  $('#thread').append(u); scroll(true);
  await stream(`/chats/${chat ? chat.id : 'new'}/send`, { text, images, settings: chat ? undefined : state.settings });
}

/* ---------- actions under a reply ---------- */
$('#thread').addEventListener('click', async (e) => {
  const tr = e.target.closest('[data-try]');
  if (tr) { $('#in').value = tr.dataset.try; grow(); send(); return; }
  const cp = e.target.closest('.cp');
  if (cp) { await navigator.clipboard?.writeText(cp.nextElementSibling.textContent); cp.textContent = 'Copied'; setTimeout(() => (cp.textContent = 'Copy'), 1200); return; }
  const a = e.target.closest('[data-a]')?.dataset.a;
  if (!a) return;
  const el = e.target.closest('.m'), t = el._turn;
  const text = t.segs.filter((s) => 'text' in s).map((s) => s.text).join('\n\n');
  if (a === 'copy') { await navigator.clipboard?.writeText(text); e.target.textContent = 'Copied'; }
  if (a === 'retry' && !ctrl) { el.remove(); await stream(`/chats/${chat.id}/retry`, {}); }
  if (a === 'claude') openJob(el, text);
});

function openJob(el, text) {
  const asked = el.previousElementSibling?.classList.contains('user') ? el.previousElementSibling.textContent.trim() : '';
  $('#job-title').value = (asked || chat.title).slice(0, 80);
  $('#job-prompt').value =
    `From the Gemini chat “${chat.title}” (/studio/gemini/, chat ${chat.id}).\n\n` +
    (asked ? `Anthony asked Gemini:\n${asked}\n\n` : '') +
    `Gemini answered:\n${text}\n\nDo what this calls for in zpkt. Check Gemini's claims against the repo first.`;
  $('#job-msg').textContent = '';
  $('#job-ok').disabled = false;
  sheet('#job', true);
}
$('#job-form').onsubmit = async (e) => {
  e.preventDefault();
  $('#job-ok').disabled = true;
  try {
    const r = await fetch('/api/rpc', { method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ method: 'job', params: { prompt: $('#job-prompt').value, title: $('#job-title').value } }) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
    $('#job-msg').innerHTML = `Started job <b>${esc(j.job_id)}</b>. <a href="/skrng/#jobs">Follow it</a>.`;
  } catch (err) {
    $('#job-msg').textContent = 'Could not start it: ' + err.message;
    $('#job-ok').disabled = false;
  }
};
$('#job-x').onclick = () => sheet('#job', false);

/* ---------- settings ---------- */
function sheet(id, on) { $(id).classList.toggle('open', on); $(id).setAttribute('aria-hidden', String(!on)); }
async function loadModels() {
  try { models = (await api('/models')).models; } catch (e) { models = []; $('#model').innerHTML = `<option value="">Could not load models: ${esc(e.message)}</option>`; }
}
function openSettings() {
  const s = chat?.settings || state.settings;
  const list = models.some((m) => m.id === s.model) ? models : [{ id: s.model, name: s.model }, ...models];
  $('#model').innerHTML = list.map((m) => `<option value="${esc(m.id)}">${esc(m.id)}</option>`).join('');
  $('#model').value = s.model; $('#zpkt').checked = !!s.zpkt; $('#sys').value = s.system || '';
  $('#temp').value = s.temperature ?? 1; $('#tv').textContent = $('#temp').value;
  sheet('#set', true);
}
$('#gear').onclick = openSettings;
$('#temp').oninput = (e) => ($('#tv').textContent = e.target.value);
$('#set-x').onclick = () => sheet('#set', false);
$('#set-form').onsubmit = async (e) => {
  e.preventDefault();
  const s = { model: $('#model').value, zpkt: $('#zpkt').checked, system: $('#sys').value, temperature: Number($('#temp').value) };
  state.settings = (await api('/settings', { method: 'POST', body: JSON.stringify(s) })).settings;
  if (chat) chat = { ...(await api(`/chats/${chat.id}`, { method: 'PATCH', body: JSON.stringify({ settings: s }) })), dollars: chat.dollars };
  sheet('#set', false); sub();
};
for (const id of ['#set', '#job']) $(id).addEventListener('click', (e) => { if (e.target.id === id.slice(1)) sheet(id, false); });

/* ---------- composer ---------- */
function grow() { const t = $('#in'); t.style.height = 'auto'; t.style.height = t.scrollHeight + 'px'; }
$('#in').addEventListener('input', grow);
$('#in').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && matchMedia('(hover:hover)').matches) { e.preventDefault(); send(); }
});
$('#send').onclick = send;
$('#attach').onclick = () => $('#file').click();
$('#file').onchange = async (e) => {
  for (const f of e.target.files) pending.push(await shrink(f));
  e.target.value = ''; renderPrev();
};
function renderPrev() {
  const p = $('#prev'); p.innerHTML = '';
  pending.forEach((x, i) => {
    const d = document.createElement('div');
    d.innerHTML = `<img src="data:${x.mime};base64,${x.data}" alt=""><button type="button" aria-label="Remove"><svg viewBox="0 0 24 24">${ICON.x}</svg></button>`;
    d.querySelector('button').onclick = () => { pending.splice(i, 1); renderPrev(); };
    p.append(d);
  });
}
// downscale to keep requests small (long edge 1600 px, JPEG)
function shrink(file) {
  return new Promise((res) => {
    const im = new Image(), u = URL.createObjectURL(file);
    im.onload = () => {
      const k = Math.min(1, 1600 / Math.max(im.width, im.height));
      const cv = document.createElement('canvas'); cv.width = Math.round(im.width * k); cv.height = Math.round(im.height * k);
      cv.getContext('2d').drawImage(im, 0, 0, cv.width, cv.height);
      URL.revokeObjectURL(u);
      res({ mime: 'image/jpeg', data: cv.toDataURL('image/jpeg', 0.85).split(',')[1] });
    };
    im.src = u;
  });
}

/* ---------- chrome ---------- */
$('#new').onclick = () => { if (ctrl) return; chat = null; remember(null); document.body.classList.remove('nav'); render(); $('#in').focus(); };
$('#menu').onclick = () => document.body.classList.add('nav');
$('#scrim').onclick = () => document.body.classList.remove('nav');

(async () => {
  await refresh().catch((e) => { $('#thread').innerHTML = `<p class="err">${esc(e.message)}</p>`; });
  const want = new URLSearchParams(location.search).get('chat') || remembered;
  if (want && state.chats.some((c) => c.id === want)) await open(want); else render();
  loadModels();
})();
