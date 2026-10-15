// Feedback for the artist agent (docs/artist-agent.md): a thumbs up on the left edge and a thumbs down on the right,
// on every view, always there. A press is stored at once, with what was on screen and what had just played (the
// caller's `context()`); only then does a quick question come up in a small chat by the thumb, which can be
// answered or let go. A press that can't reach the harness waits in this browser and is sent with the next one.
//
//   mountFeedback({ context: () => ({ view, ... }) }) -> { destroy() }
import { haptic, onTap } from '../concepts/model.js';

const API = '/studio/api/artist/';
const QUEUE = 'artist:queue';
const SVG = 'http://www.w3.org/2000/svg';
const THUMB = 'M7 10v10H4V10zM7 10l4-7c1.4 0 2.3 1.1 2 2.5L12.4 9H18a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 16.8 20H7';

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
}
function thumb() {
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
  const p = document.createElementNS(SVG, 'path'); p.setAttribute('d', THUMB);
  svg.append(p);
  return svg;
}

async function post(path, body) {
  const r = await fetch(API + path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), keepalive: true,
  });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}
const queued = () => { try { return JSON.parse(localStorage.getItem(QUEUE)) || []; } catch { return []; } };
function setQueued(list) { try { localStorage.setItem(QUEUE, JSON.stringify(list.slice(-200))); } catch { /* this visit only */ } }
async function flush() {
  const list = queued();
  if (!list.length) return;
  const left = [];
  for (const ev of list) { try { await post('feedback', ev); } catch { left.push(ev); } }
  setQueued(left);
}

/** The press itself: stored first, everything else after. Resolves with the stored id, or null if it was queued. */
export async function press(vote, ctx) {
  const ev = { vote, view: ctx.view ?? 'unknown', context: ctx, client_ts: Date.now() };
  try {
    const { id } = await post('feedback', ev);
    flush();
    return id;
  } catch {
    setQueued([...queued(), ev]);
    return null;
  }
}

export function mountFeedback({ context = () => ({ view: 'page' }) } = {}) {
  const root = h('div', { class: 'fb', 'aria-label': 'Feedback for the artist' });
  const up = h('button', { type: 'button', class: 'fb-thumb up', 'aria-label': 'I like this' }, thumb());
  const down = h('button', { type: 'button', class: 'fb-thumb down', 'aria-label': "I don't like this" }, thumb());
  const pop = h('section', { class: 'fb-pop', role: 'dialog', 'aria-label': 'A quick question', 'aria-hidden': 'true' });
  root.append(up, down, pop);
  document.body.append(root);
  let open = null;                     // the feedback the pop-over is about

  async function go(vote, btn) {
    haptic(true);
    btn.classList.remove('hit'); void btn.offsetWidth; btn.classList.add('hit');
    const ctx = context();
    const id = await press(vote, ctx);
    ask(vote, id, ctx);
  }

  function close() {
    open = null;
    pop.classList.remove('show'); pop.setAttribute('aria-hidden', 'true');
  }

  async function ask(vote, id, ctx) {
    open = id ?? `local-${Date.now()}`;
    const mine = open;
    pop.className = `fb-pop show ${vote}`;
    pop.setAttribute('aria-hidden', 'false');
    const log = h('div', { class: 'fb-log' });
    const agent = h('p', { class: 'fb-msg agent typing' }, h('i'), h('i'), h('i'));
    log.append(h('p', { class: 'fb-msg you', text: vote === 'up' ? 'Liked' : 'Not for me' }), agent);
    const x = h('button', { type: 'button', class: 'fb-x', 'aria-label': 'Close' }, '×');
    pop.replaceChildren(h('header', {}, h('b', { text: 'Quick question' }), x), log);
    onTap(x, close);
    let q = null;
    if (id) { try { q = await post(`feedback/${id}/question`, {}); } catch { q = null; } }
    if (open !== mine) return;
    q ??= { question: vote === 'up' ? 'What landed?' : 'What was off?', choices: ['The sound', 'The shake', 'The map', 'Something else'], by: 'rules' };
    agent.classList.remove('typing');
    agent.textContent = q.question;
    const field = h('input', { type: 'text', class: 'fb-text', placeholder: 'Or say it in a few words', enterkeyhint: 'send' });
    const send = h('button', { type: 'button', class: 'fb-send' }, 'Send');
    const chips = h('div', { class: 'fb-chips' }, (q.choices ?? []).map((c) => {
      const b = h('button', { type: 'button', class: 'fb-chip', text: c });
      onTap(b, () => answer(c, ''));
      return b;
    }));
    const skip = h('button', { type: 'button', class: 'fb-skip', text: 'Skip' });
    onTap(skip, close);
    onTap(send, () => answer(null, field.value.trim()));
    field.addEventListener('keydown', (e) => { if (e.key === 'Enter') answer(null, field.value.trim()); });
    pop.append(chips, h('div', { class: 'fb-say' }, field, send), skip);

    async function answer(choice, text) {
      if (!choice && !text) return;
      haptic();
      log.append(h('p', { class: 'fb-msg you', text: choice ?? text }));
      chips.remove(); pop.querySelector('.fb-say')?.remove(); skip.remove();
      if (id) { try { await post(`feedback/${id}/answer`, { choice, text }); } catch { /* the press is kept either way */ } }
      log.append(h('p', { class: 'fb-msg agent', text: 'Noted. Thank you.' }));
      setTimeout(() => { if (open === mine) close(); }, 1300);
    }
  }

  onTap(up, () => go('up', up));
  onTap(down, () => go('down', down));
  flush();
  return { destroy: () => root.remove(), close };
}
