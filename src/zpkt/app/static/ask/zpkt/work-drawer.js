// The subagent drawer: one subagent in full. Beside the chat on a wide screen (the parent stays visible); a
// full-screen sheet on a phone, with the parent's line pinned on top. Read-only: anything that needs the user goes
// through the main thread, and control panels never appear here.
import { todoBar } from './work.js';
import { toolRow, paintTool } from './work-thread.js';
import { createTodo } from './work-dock.js';

const el = (html) => { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstChild; };
const CHEV = '<svg class="wk-chev" viewBox="0 0 10 10" width="10" height="10" aria-hidden="true"><path d="M3 1.5l4 3.5-4 3.5z" fill="currentColor"/></svg>';
const BACK = '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M9.5 3L4.5 8l5 5M5 8h8" fill="none" stroke="currentColor" stroke-width="2"/></svg>';

export function createDrawer(host, { onClose }) {
  host.innerHTML = '';
  const root = el(`<div class="wk-drawer">
    <button type="button" class="wk-parent" aria-label="Back to the main thread">${BACK}<span></span></button>
    <div class="wk-dbody"></div>
    <div class="wk-dfoot"><div class="wk-dtodo"></div><p class="wk-ro">Read-only. Answer in the main thread.</p></div></div>`);
  host.append(root);
  const body = root.querySelector('.wk-dbody');
  const todo = createTodo(root.querySelector('.wk-dtodo'), { key: 'agent' });
  root.querySelector('.wk-parent').onclick = onClose;
  let shown = null;

  function draw(a, parentTodos, parentRunning) {
    const bar = todoBar(parentTodos);
    root.querySelector('.wk-parent span').textContent = ['Main', bar.count, bar.text || (parentRunning ? 'working' : '')].filter(Boolean).join(' · ');
    if (shown !== a) {
      shown = a;
      body.innerHTML = '';
      body.append(el('<h3><span class="wk-name"></span><span class="wk-status"></span></h3>'), el('<div class="wk-lab">Brief</div>'), el('<div class="wk-brief"></div>'),
        el('<div class="wk-dsteps"></div>'), el('<div class="wk-dtext"></div>'), el('<div class="wk-lab wk-rl">Report</div>'), el('<div class="wk-report"></div>'));
      body.querySelector('.wk-name').textContent = a.title;
      body.querySelector('.wk-brief').textContent = a.brief || '(no brief given)';
    }
    body.querySelector('.wk-status').textContent = a.status;
    const steps = body.querySelector('.wk-dsteps');
    a.steps.forEach((s, i) => {
      let d = steps.children[i];
      if (!d) { d = el(`<details class="wk-step"><summary>${CHEV}<span class="wk-title"></span><span class="wk-r"></span></summary><div class="wk-rows"></div></details>`); steps.append(d); d.open = true; }
      const rows = d.querySelector('.wk-rows');
      s.tools.forEach((t, k) => {
        if (!rows.children[k]) rows.append(toolRow(t, 'del'));
        paintTool(t, 'del');
      });
      d.querySelector('.wk-title').textContent = s.open ? 'Working' : s.purpose || s.summary;
      d.querySelector(':scope > summary .wk-r').textContent = s.open ? 'running' : `${s.tools.length} tool call${s.tools.length === 1 ? '' : 's'}`;
      if (!s.open && !d.dataset.closed) { d.dataset.closed = '1'; d.open = false; }
      d.classList.toggle('bad', s.tools.some((t) => t.status === 'error'));
    });
    body.querySelector('.wk-dtext').textContent = a.status === 'running' ? a.text.trim().slice(-1200) : '';
    const rep = body.querySelector('.wk-report');
    const failed = a.status === 'failed';
    rep.textContent = a.status === 'running' ? `Working · ${a.toolCount} tool calls so far` : a.report.trim() || '(empty report)';
    rep.classList.toggle('wk-dim', a.status === 'running');
    rep.classList.toggle('wk-failed', failed);
    body.querySelector('.wk-rl').textContent = failed ? 'Failed' : 'Report';
    todo.render(a.todos, a.status === 'running');
  }
  return { draw, clear() { shown = null; body.innerHTML = ''; } };
}
