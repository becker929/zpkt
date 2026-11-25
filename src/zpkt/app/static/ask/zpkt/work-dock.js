// The pinned stack above the composer: one todo bar for the agent (collapsed to a single bar by default) and the
// strip of running subagents. The strip stays chips and labels; it must not grow into a dashboard.
import { todoBar } from './work.js';
import { bump, burst } from './juice.js';

const el = (html) => { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstChild; };
const TICK = '<svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true"><path d="M2 6.5l2.6 2.6L10 3.5" fill="none" stroke="currentColor" stroke-width="2"/></svg>';
const CHEV = '<svg class="wk-chev" viewBox="0 0 10 10" width="10" height="10" aria-hidden="true"><path d="M3 1.5l4 3.5-4 3.5z" fill="currentColor"/></svg>';

/** A todo bar. `onStop` adds the stop square (main agent only). */
export function createTodo(host, { onStop = null, key = 'main' } = {}) {
  const root = el(`<div class="wk-todo" hidden><div class="wk-bar"><button type="button" class="wk-toggle" aria-expanded="false"><span class="wk-count"></span><span class="wk-cur"></span>${CHEV}</button>${onStop ? '<button type="button" class="wk-stop" aria-label="Stop the agent"><i></i></button>' : ''}</div><ul hidden></ul></div>`);
  host.append(root);
  const list = root.querySelector('ul'), toggle = root.querySelector('.wk-toggle');
  let open = false, last = [], lastCount = '';
  try { open = localStorage.getItem(`wk.todo.${key}`) === '1'; } catch {}
  const setOpen = (o) => { open = o; list.hidden = !o || !last.length; toggle.setAttribute('aria-expanded', String(o)); root.classList.toggle('open', o && !!last.length); try { localStorage.setItem(`wk.todo.${key}`, o ? '1' : '0'); } catch {} };
  toggle.onclick = () => { setOpen(!open); bump(toggle, 1.02); };
  if (onStop) root.querySelector('.wk-stop').onclick = (e) => { bump(e.currentTarget, 1.25); onStop(); };

  /**
   * todos: [{ text, status }], running: is the agent working.
   * now: when the agent keeps no todo list, what to show instead: { text, items: [{ text, status }] } (its steps so far).
   */
  function render(todos, running, now = null) {
    const own = todos.length > 0;
    const bar = own ? todoBar(todos) : { count: '', text: now?.text || '', done: false };
    if (!own) todos = running ? now?.items || [] : [];
    root.hidden = !running && (!own || bar.done);
    root.classList.toggle('wk-none', !todos.length);   // nothing to open: no arrow
    toggle.disabled = !todos.length;
    root.querySelector('.wk-count').textContent = bar.count;
    root.querySelector('.wk-cur').textContent = bar.text || (running ? 'Working' : '');
    if (onStop) root.querySelector('.wk-stop').hidden = !running;
    list.innerHTML = '';
    todos.forEach((t, i) => {
      const li = el(`<li class="${t.status}"><span class="wk-box">${t.status === 'done' ? TICK : ''}</span><span></span></li>`);
      li.lastChild.textContent = t.text;
      list.append(li);
      if (own && t.status === 'done' && last[i] && last[i].status !== 'done' && last[i].text === t.text) { bump(li, 1.05); burst(root.querySelector('.wk-count'), 8); }
    });
    if (bar.count !== lastCount && lastCount) bump(root.querySelector('.wk-count'), 1.3);
    if (own && bar.done && last.length && !todoBar(last).done) burst(root, 22);
    lastCount = bar.count; last = todos.map((t) => ({ ...t }));
    if (open && !own && todos.length) list.scrollTop = list.scrollHeight;   // steps: the newest is at the bottom
    setOpen(open);
  }
  return { render, el: root };
}

/** The strip: one chip per running subagent; a failed one is raised until the next turn. */
export function createStrip(host, { onOpen }) {
  const root = el('<div class="wk-strip" hidden></div>');
  host.append(root);
  const seen = new Map();
  function render(agents) {
    const show = agents.filter((a) => a.status === 'running' || a.status === 'failed');
    root.hidden = !show.length;
    root.innerHTML = '';
    for (const a of show) {
      const b = el('<button type="button" class="wk-chip"><span></span></button>');
      b.firstChild.textContent = a.label;
      b.title = a.title;
      b.onclick = () => onOpen(a.id);
      b.classList.toggle('wk-failed', a.status === 'failed');
      seen.set(a.id, a.status);
      root.append(b);
    }
  }
  return { render };
}
