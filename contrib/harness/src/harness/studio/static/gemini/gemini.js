// Gemini CLI on the phone (contrib/docs/gemini.md). The Mac runs Gemini CLI in zpkt over ACP; this page shows a
// session's events (what it said and thought, the tools it ran, what it asks), answers its questions, and follows a
// turn that is still running even after a reload.
const $ = (s) => document.querySelector(s);
const API = '/studio/gemini/api';
const ICON = {
  send: '<path d="M12 19V5M6 11l6-6 6 6"/>',
  stop: '<rect x="7" y="7" width="10" height="10" fill="currentColor"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
};
const MODES = [
  ['default', 'Asks first'], ['autoEdit', 'Auto-edit'], ['yolo', 'YOLO'], ['plan', 'Read-only'],
];

let state = { sessions: [], usage: null, offers: {}, cwd: '' };
let cur = null;             // the open session's record
let blocks = [];            // what the thread shows, built from the events
let lastN = -1;             // the newest event seen
let following = null;       // the events stream's AbortController
let pending = [];           // images to attach
let draftMode = 'default';  // the mode a new session starts in
const remembered = (() => { try { return localStorage.getItem('gemini.session'); } catch { return null; } })();
const remember = (id) => { try { id ? localStorage.setItem('gemini.session', id) : localStorage.removeItem('gemini.session'); } catch {} };

const dollars = (d) => (d >= 1 ? '$' + d.toFixed(2) : d >= 0.01 ? '$' + d.toFixed(3) : d > 0 ? '<$0.01' : '$0');
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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

/* ---------- events -> blocks ---------- */
// A block is one thing on screen: what he typed, a stretch of text or thought, a tool, a question, a plan, the end
// of a turn. Events that amend an earlier one (`of`) replace that block's data.
function take(ev) {
  lastN = Math.max(lastN, ev.n);
  if (ev.type === 'note' && ev.mode && cur) { cur.mode = ev.mode; header(); }
  const last = blocks[blocks.length - 1];
  const key = ev.of ?? ev.n;
  if (ev.of != null) {
    const b = blocks.find((x) => x.key === ev.of);
    if (b) { b.ev = ev; b.dirty = true; return; }
  }
  if ((ev.type === 'text' || ev.type === 'thought') && last && last.ev.type === ev.type && !last.closed) {
    last.text += ev.text; last.dirty = true; return;
  }
  if (ev.type === 'idle') { if (last) last.closed = true; return; }
  if (ev.type === 'plan') {
    const p = [...blocks].reverse().find((x) => x.ev.type === 'plan' && !x.closed);
    if (p && p === last) { p.ev = ev; p.dirty = true; return; }
  }
  if (last) last.closed = last.closed || ev.type !== last.ev.type;
  blocks.push({ key, ev, text: ev.text || '', dirty: true });
}

function toolHTML(t, open) {
  const kind = t.kind || 'tool';
  const status = t.status || '';
  let body = '';
  for (const c of t.content || []) {
    if (c.diff != null) body += `<details${open ? ' open' : ''}><summary>${esc(short(c.diff))}</summary><pre>${diffHTML(c.old, c.new)}</pre></details>`;
    else if (c.text) body += `<details${open ? ' open' : ''}><summary>output</summary><pre>${esc(c.text)}</pre></details>`;
  }
  return `<div class="tool ${esc(status)}"><div class="h"><span class="k">${esc(kind)}</span><span class="t">${esc(t.title || '')}</span><span class="s">${esc(status.replace('_', ' '))}</span></div>${body}</div>`;
}
const short = (p) => (state.cwd && p.startsWith(state.cwd + '/') ? p.slice(state.cwd.length + 1) : p);
function diffHTML(a, b) {
  const A = (a || '').split('\n'), B = (b || '').split('\n');
  let i = 0; while (i < A.length && i < B.length && A[i] === B[i]) i++;
  let j = 0; while (j < A.length - i && j < B.length - i && A[A.length - 1 - j] === B[B.length - 1 - j]) j++;
  const ctx = (l) => esc(l) + '\n';
  if (!a) return B.map((l) => `<span class="add">+ ${esc(l)}</span>\n`).join('');      // a new file
  let out = A.slice(Math.max(0, i - 2), i).map(ctx).join('');
  out += A.slice(i, A.length - j).map((l) => `<span class="del">- ${esc(l)}</span>\n`).join('');
  out += B.slice(i, B.length - j).map((l) => `<span class="add">+ ${esc(l)}</span>\n`).join('');
  out += A.slice(A.length - j, A.length - j + 2).map(ctx).join('');
  return out;
}

function blockHTML(b) {
  const e = b.ev;
  switch (e.type) {
    case 'user':
      return `<div class="m user">${(e.files || []).length ? '<div class="attached">' + e.files.map((f) => `<img src="/studio/gemini/files/${esc(cur.id)}/${esc(f)}" alt="">`).join('') + '</div>' : ''}${b.text.trim() ? `<div class="bubble">${esc(b.text)}</div>` : ''}</div>`;
    case 'text': return `<div class="m model"><div class="bubble">${md(b.text)}</div></div>`;
    case 'thought': return `<details class="thought"><summary>Thinking</summary><div>${esc(b.text.trim())}</div></details>`;
    case 'tool': return toolHTML(e, false);
    case 'permission': {
      const done = e.answered != null;
      const picked = (e.options || []).find((o) => o.id === e.answered);
      return `<div class="ask${done ? ' done' : ''}" data-pid="${esc(e.id)}"><p>${done ? 'Asked' : 'Gemini asks'}</p>${toolHTML(e.tool || {}, !done)}` +
        (done ? `<div class="ans">${esc(picked ? picked.name : 'No answer (stopped)')}</div>`
          : `<div class="opts">${(e.options || []).map((o) => `<button type="button" data-opt="${esc(o.id)}" class="${o.kind === 'allow_once' ? 'allow' : ''}">${esc(o.name)}</button>`).join('')}</div>`) + '</div>';
    }
    case 'plan': return `<ul class="plan">${(e.entries || []).map((x) => `<li class="${esc(x.status)}">${esc(x.content)}</li>`).join('')}</ul>`;
    case 'note': return `<p class="note">${esc(e.text)}</p>`;
    case 'error': return `<p class="err">${esc(e.text)}</p>`;
    case 'done':
      return `<div class="acts"><button type="button" data-a="copy">Copy</button><button type="button" data-a="claude" class="claude">Send to Claude</button>` +
        `<span class="cost">${esc(e.model || '')} ${e.dollars ? dollars(e.dollars) : ''}${e.stop && e.stop !== 'end_turn' ? ' · ' + esc(e.stop) : ''}</span></div>`;
    default: return '';
  }
}

let raf = 0;
function paint() {
  raf = 0;
  const th = $('#thread');
  if (!cur) {
    th.innerHTML = `<div class="empty"><h2>Gemini CLI in zpkt</h2><div>It works in the repo on the Mac: reads, edits, runs hands and ears. Pick how much it may do without asking, below.</div>
      <div class="tries">${['What changed in zpkt this week?', 'Check that hands can reach Live, and tell me what set is open.', 'Read the newest journal entry and list its open questions.']
        .map((q) => `<button type="button" data-try="${esc(q)}">${esc(q)}</button>`).join('')}</div></div>`;
    return;
  }
  if (th.querySelector('.empty')) th.innerHTML = '';
  for (const b of blocks) {
    if (!b.dirty) continue;
    const wrap = document.createElement('div');
    wrap.innerHTML = blockHTML(b);
    const el = wrap.firstElementChild || document.createElement('span');
    el._block = b;
    if (b.el) {
      el.querySelectorAll('details').forEach((d, k) => { const was = b.el.querySelectorAll('details')[k]; if (was) d.open = was.open; });
      b.el.replaceWith(el);
    } else th.append(el);
    b.el = el; b.dirty = false;
  }
  scroll();
}
const repaint = () => { if (!raf) raf = requestAnimationFrame(paint); };

function scroll(force) {
  const s = $('#msgs');
  if (force || s.scrollHeight - s.scrollTop - s.clientHeight < 200) s.scrollTop = s.scrollHeight;
}

function header() {
  $('#title').textContent = cur?.title || 'Gemini CLI';
  const bits = [];
  if (cur?.model) bits.push(cur.model);
  if (cur?.running) bits.push(cur.asking ? 'waiting for you' : 'working');
  if (cur?.dollars) bits.push(dollars(cur.dollars));
  $('#sub').textContent = bits.join(' · ');
  const mode = cur ? cur.mode : draftMode;
  $('#modes').innerHTML = MODES.map(([id, name]) =>
    `<button type="button" role="radio" aria-checked="${id === mode}" data-mode="${id}" class="${id === mode ? 'on' : ''}${id === 'yolo' ? ' hot' : ''}">${name}</button>`).join('');
  const busy = !!cur?.running;
  $('#send').classList.toggle('stop', busy);
  $('#send-icon').innerHTML = busy ? ICON.stop : ICON.send;
  $('#send').setAttribute('aria-label', busy ? 'Stop' : 'Send');
}

function renderList() {
  const l = $('#list'); l.innerHTML = '';
  for (const s of state.sessions) {
    const d = document.createElement('div');
    d.className = 'g-item' + (s.id === cur?.id ? ' on' : '');
    const flag = s.asking ? ' · <b>asks</b>' : s.running ? ' · <b>working</b>' : '';
    d.innerHTML = `<button type="button" class="t"><span></span><i>${esc(s.updated.slice(0, 10))}${s.dollars ? ' · ' + dollars(s.dollars) : ''}${flag}</i></button>
      <button type="button" class="x" aria-label="Forget session"><svg viewBox="0 0 24 24">${ICON.x}</svg></button>`;
    d.querySelector('.t span').textContent = s.title;
    d.querySelector('.t').onclick = () => { document.body.classList.remove('nav'); open(s.id); };
    d.querySelector('.x').onclick = async () => {
      if (!confirm(`Forget “${s.title}” here? Gemini CLI keeps its own copy.`)) return;
      try { await api(`/sessions/${s.id}`, { method: 'DELETE' }); } catch (e) { alert(e.message); return; }
      if (cur?.id === s.id) close();
      await refresh();
    };
    l.append(d);
  }
  const u = state.usage;
  $('#spend').textContent = u ? `${u.month}: Gemini CLI ${dollars(u.agent)} · ${u.image_count} images ${dollars(u.images)} (est.)` : '';
}

async function refresh() {
  state = await api('/state');
  if (cur) { const s = state.sessions.find((x) => x.id === cur.id); if (s) cur = { ...cur, ...s }; }
  renderList(); header();
}

function close() {
  following?.abort(); following = null;
  cur = null; blocks = []; lastN = -1; remember(null);
  $('#thread').innerHTML = ''; header(); paint(); renderList();
}

async function open(id) {
  following?.abort(); following = null;
  let s;
  try { s = await api(`/sessions/${id}`); } catch { close(); return; }
  cur = s; blocks = []; lastN = -1; remember(id);
  $('#thread').innerHTML = '';
  s.events.forEach(take);
  if (blocks.length) blocks[blocks.length - 1].closed = !s.running;
  delete cur.events;
  paint(); scroll(true); header(); renderList();
  if (s.running) follow();
}

// Follows the session's events until it is idle; reconnects if the stream drops while it is still working.
async function follow() {
  if (!cur) return;
  const id = cur.id;
  following?.abort();
  const ctrl = following = new AbortController();
  for (let tries = 0; tries < 50 && cur?.id === id && !ctrl.signal.aborted; tries++) {
    try {
      const r = await fetch(`${API}/sessions/${id}/events?after=${lastN}`, { signal: ctrl.signal });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
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
          take(ev);
          if (ev.type === 'permission' && ev.answered == null) { cur.asking = true; header(); }
          if (ev.type === 'idle') { cur.running = false; cur.asking = false; }
          repaint();
        }
      }
    } catch (e) {
      if (ctrl.signal.aborted) return;
    }
    if (cur?.id !== id || !cur.running) break;
    await sleep(1000);
    try { const s = await api(`/sessions/${id}`); cur.running = s.running; s.events.filter((ev) => ev.n > lastN).forEach(take); repaint(); } catch {}
    if (!cur.running) break;
  }
  if (following === ctrl) following = null;
  await refresh().catch(() => {});
}

/* ---------- sending ---------- */
async function send() {
  if (cur?.running) { await api(`/sessions/${cur.id}/cancel`, { method: 'POST' }).catch((e) => alert(e.message)); return; }
  const text = $('#in').value.trim();
  if (!text && !pending.length) return;
  const images = pending;
  $('#send').disabled = true;
  try {
    if (!cur) {
      $('#sub').textContent = 'starting Gemini CLI…';
      const s = await api('/sessions', { method: 'POST', body: JSON.stringify({ mode: draftMode }) });
      cur = s; blocks = []; lastN = -1; remember(s.id);
      $('#thread').innerHTML = '';
    }
    await api(`/sessions/${cur.id}/prompt`, { method: 'POST', body: JSON.stringify({ text, images }) });
    pending = []; $('#in').value = ''; grow(); renderPrev();
    cur.running = true; header();
    follow();
    refresh().catch(() => {});
  } catch (e) {
    alert(e.message);
  } finally {
    $('#send').disabled = false;
  }
}

$('#modes').addEventListener('click', async (e) => {
  const m = e.target.closest('[data-mode]')?.dataset.mode;
  if (!m) return;
  if (m === 'yolo' && !confirm('YOLO: Gemini runs every edit and command without asking. Use it?')) return;
  if (!cur) { draftMode = m; header(); return; }
  try { cur = { ...cur, ...(await api(`/sessions/${cur.id}`, { method: 'PATCH', body: JSON.stringify({ mode: m }) })) }; }
  catch (err) { alert(err.message); }
  header();
  if (!cur.running) { const s = await api(`/sessions/${cur.id}`); s.events.filter((ev) => ev.n > lastN).forEach(take); repaint(); }
});

/* ---------- in the thread ---------- */
$('#thread').addEventListener('click', async (e) => {
  const tr = e.target.closest('[data-try]');
  if (tr) { $('#in').value = tr.dataset.try; grow(); send(); return; }
  const cp = e.target.closest('.cp');
  if (cp) { await navigator.clipboard?.writeText(cp.nextElementSibling.textContent); cp.textContent = 'Copied'; setTimeout(() => (cp.textContent = 'Copy'), 1200); return; }
  const opt = e.target.closest('[data-opt]');
  if (opt) {
    const pid = opt.closest('[data-pid]').dataset.pid;
    opt.closest('.opts').querySelectorAll('button').forEach((b) => (b.disabled = true));
    try { await api(`/permissions/${pid}`, { method: 'POST', body: JSON.stringify({ option: opt.dataset.opt }) }); cur.asking = false; header(); }
    catch (err) { alert(err.message); opt.closest('.opts').querySelectorAll('button').forEach((b) => (b.disabled = false)); }
    return;
  }
  const a = e.target.closest('[data-a]')?.dataset.a;
  if (!a) return;
  const doneBlock = e.target.closest('.acts')._block;
  const i = blocks.indexOf(doneBlock);
  let start = i; while (start > 0 && blocks[start - 1].ev.type !== 'user') start--;
  const asked = start > 0 ? blocks[start - 1].text : '';
  const said = blocks.slice(start, i).filter((b) => b.ev.type === 'text').map((b) => b.text).join('\n\n');
  if (a === 'copy') { await navigator.clipboard?.writeText(said); e.target.textContent = 'Copied'; }
  if (a === 'claude') openJob(asked, said);
});

function openJob(asked, said) {
  $('#job-title').value = (asked || cur.title).slice(0, 80);
  $('#job-prompt').value =
    `From the Gemini CLI session “${cur.title}” (/studio/gemini/, session ${cur.id}).\n\n` +
    (asked ? `Anthony asked Gemini:\n${asked}\n\n` : '') +
    `Gemini answered:\n${said}\n\nTake it from here in zpkt. Check what Gemini said and did against the repo first.`;
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
$('#gear').onclick = () => {
  if (!cur) { alert('Start a session first: write something below.'); return; }
  const models = state.offers?.models?.length ? state.offers.models : [cur.model];
  const list = models.includes(cur.model) ? models : [cur.model, ...models];
  $('#model').innerHTML = list.map((m) => `<option value="${esc(m)}">${esc(m)}</option>`).join('');
  $('#model').value = cur.model; $('#stitle').value = cur.title;
  $('#cwd').textContent = `Works in ${cur.cwd}`;
  sheet('#set', true);
};
$('#set-x').onclick = () => sheet('#set', false);
$('#set-form').onsubmit = async (e) => {
  e.preventDefault();
  try {
    cur = { ...cur, ...(await api(`/sessions/${cur.id}`, { method: 'PATCH', body: JSON.stringify({ model: $('#model').value, title: $('#stitle').value }) })) };
    sheet('#set', false); header(); refresh().catch(() => {});
  } catch (err) { alert(err.message); }
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
function shrink(file) {    // long edge 1600 px, JPEG
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
$('#new').onclick = () => { document.body.classList.remove('nav'); close(); $('#in').focus(); };
$('#menu').onclick = () => document.body.classList.add('nav');
$('#scrim').onclick = () => document.body.classList.remove('nav');
document.addEventListener('visibilitychange', () => { if (!document.hidden && cur && !following) open(cur.id); });

(async () => {
  try { await refresh(); } catch (e) { $('#thread').innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
  const want = new URLSearchParams(location.search).get('s') || remembered;
  if (want && state.sessions.some((s) => s.id === want)) await open(want); else { header(); paint(); }
})();
