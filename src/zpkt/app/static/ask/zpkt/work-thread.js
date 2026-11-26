// The thread's work parts: steps (a collapsed row per run of tool calls), plain tool-call rows, subagent
// cards, and the one-line trace a finished turn collapses under. Elements are built here; work.js says what they mean.
import { stepSummary } from './work.js';
import { enter, bump } from './juice.js';

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const el = (html) => { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstChild; };
const CHEV = '<svg class="wk-chev" viewBox="0 0 10 10" width="10" height="10" aria-hidden="true"><path d="M3 1.5l4 3.5-4 3.5z" fill="currentColor"/></svg>';
const clip = (s, n) => (s.length > n ? s.slice(0, n) + '\n…' : s);

/** A plain tool-call row: one monospace line; opens to its raw input and output. */
export function toolRow(t, slot = 'el') {   // slot: where on the tool this row is kept (the drawer keeps its own)
  const d = el(`<details class="wk-tool"><summary><span class="wk-line"></span><span class="wk-r"></span></summary><pre class="out"></pre></details>`);
  d.querySelector('.wk-line').textContent = t.line;
  d.querySelector('pre').textContent = JSON.stringify(t.params, null, 2);
  t[slot] = d;
  paintTool(t, slot);
  return d;
}
export function paintTool(t, slot = 'el') {
  const d = t[slot]; if (!d) return;
  const r = d.querySelector('.wk-r');
  r.textContent = t.status === 'running' ? 'running' : t.status === 'none' ? 'no result' : `${t.status === 'error' ? 'error' : 'ok'}${t.ms ? ` · ${(t.ms / 1000).toFixed(1)} s` : ''}`;
  d.classList.toggle('bad', t.status === 'error');
  if (t.output && !d.querySelector('.wk-out')) { const p = el('<pre class="out wk-out"></pre>'); p.textContent = clip(t.output, 20000); d.append(p); }
}

/** A step: a row that is open while it runs and closes to its summary. A step with a problem stays in view, raised. */
export function stepEl(step, title) {
  const d = el(`<details class="wk-step" open><summary>${CHEV}<span class="wk-t"><span class="wk-title"></span><span class="wk-fact"></span></span><span class="wk-r">running</span></summary><div class="wk-rows"></div></details>`);
  d.querySelector('.wk-title').textContent = title || step.topic || 'Working';
  step.el = d;
  enter(d);
  return d;
}
export function paintStep(step, title) {
  const d = step.el; if (!d) return;
  const bad = step.tools.some((t) => t.status === 'error');
  const n = step.tools.length;
  // Closed: the purpose line leads when there is one, with the template line (the facts) under it.
  const purpose = !step.open && step.purpose;
  d.querySelector('.wk-title').textContent = step.open ? (title || step.topic || stepSummary(step.tools)) : purpose || step.summary;
  d.querySelector('.wk-fact').textContent = purpose ? step.summary : '';
  mark(d.querySelector('.wk-title'), purpose && { level: 'step', ref: step.tools[0]?.id });
  d.querySelector(':scope > summary .wk-r').textContent = step.open ? 'running' : `${n} tool call${n === 1 ? '' : 's'}`;
  if (!step.open && d.open && !d.dataset.closed) { d.dataset.closed = '1'; d.open = false; bump(d, 1.02); }
  d.classList.toggle('bad', bad);   // a problem stays in view (it is never folded away), but it is drawn plainly
}

/** What the CLI printed during a step (or a whole turn): one quiet row among the tool calls. */
export function logRow(lines) {
  const d = el('<details class="wk-tool wk-log"><summary><span class="wk-line"></span><span class="wk-r"></span></summary><pre class="out"></pre></details>');
  paintLog(d, lines);
  return d;
}
export function paintLog(d, lines) {
  d.querySelector('.wk-line').textContent = `CLI log: ${lines[lines.length - 1] || ''}`;
  d.querySelector('.wk-r').textContent = `${lines.length} line${lines.length === 1 ? '' : 's'}`;
  d.querySelector('pre').textContent = clip(lines.join('\n'), 20000);
}
export function paintLogs(step) {
  if (!step.el || !step.logs?.length) return;
  if (!step.logEl) { step.logEl = logRow(step.logs); step.el.querySelector('.wk-rows').append(step.logEl); }
  else paintLog(step.logEl, step.logs);
}

/** A subagent's card in the thread: brief first, then report. Opens the drawer. */
export function agentCard(a) {
  const d = el(`<section class="wk-agent" data-agent="${esc(a.id)}"><div class="wk-face">
    <h4><span class="wk-name"></span><span class="wk-status"></span></h4>
    <div class="wk-gist"></div>
    <div class="wk-lab">Brief</div><div class="wk-brief"></div>
    <div class="wk-lab wk-rl">Report</div><div class="wk-report"></div>
    <button type="button" class="wk-open" data-open-agent="${esc(a.id)}">Open</button></div></section>`);
  d.querySelector('.wk-name').textContent = a.title;
  d.querySelector('.wk-brief').textContent = a.brief || '(no brief given)';
  a.el = d;
  paintAgent(a);
  enter(d);
  return d;
}
export function paintAgent(a) {
  const d = a.el; if (!d) return;
  const was = d.dataset.status;
  d.dataset.status = a.status;
  d.querySelector('.wk-status').textContent = { running: 'running', done: 'done', failed: 'failed', stopped: 'stopped' }[a.status] || a.status;
  const rep = d.querySelector('.wk-report');
  if (a.status === 'running') { rep.textContent = `Working · ${a.toolCount} tool call${a.toolCount === 1 ? '' : 's'} so far`; rep.classList.add('wk-dim'); }
  else { rep.textContent = a.report.trim() || (a.status === 'stopped' ? 'Stopped before it reported.' : '(empty report)'); rep.classList.remove('wk-dim'); }
  d.querySelector('.wk-rl').textContent = a.status === 'failed' ? 'Failed' : 'Report';
  const g = d.querySelector('.wk-gist'); g.textContent = a.purpose || ''; g.hidden = !a.purpose;
  mark(g, a.purpose && { level: 'agent', ref: a.id });
  if (a.status === 'done' && was === 'running') bump(d, 1.03);
}

/**
 * A finished turn: everything between the prompt and the final answer folds under one quiet row, "Details".
 * Counts of steps and tool calls, and errors the agent recovered from, are inside it: a reader of the answer does
 * not need them. A turn that failed says so itself, in a sentence (the page). Stays out of the fold: subagent
 * cards, and text that holds a page link or a control panel.
 */
export function foldTurn(thread, turn) {
  const users = thread.querySelectorAll(':scope > .m.user');
  const start = users[users.length - 1];
  if (!start) return null;
  const after = [];
  for (let n = start.nextElementSibling; n; n = n.nextElementSibling) after.push(n);
  const texts = after.filter((n) => n.matches('.m.model'));
  const answer = texts[texts.length - 1];
  const fold = after.filter((n) => n.matches('.wk-step') || (n.matches('.m.model') && n !== answer && !n.querySelector('a[href*="#page="], .oldpanel')));
  if (!turn.steps.length && !turn.agents.length) return null;
  const d = el(`<details class="wk-trace"><summary><span class="wk-t"><span class="wk-traceline"></span></span></summary><div class="wk-folded"><p class="wk-counts"></p></div></details>`);
  start.after(d);
  d.querySelector('.wk-folded').append(...fold);
  if (turn.logs?.length) d.querySelector('.wk-folded').append(logRow(turn.logs));   // printed outside any step
  turn.traceEl = d;
  paintTrace(turn);
  return d;
}
/** The row a turn's work folds under: what the turn was for when a purpose line exists, else "Details". The counts are inside. */
export function paintTrace(turn) {
  const d = turn.traceEl; if (!d) return;
  d.querySelector('.wk-traceline').textContent = turn.purpose || 'Details';
  d.querySelector('.wk-counts').textContent = turn.trace;
  mark(d.querySelector('.wk-traceline'), turn.purpose && { level: 'turn', ref: 'turn' });
  let n = d.querySelector('.wk-nosum');
  if (turn.summaryError && !n) { n = el('<p class="wk-nosum"></p>'); d.querySelector('.wk-counts').after(n); }
  if (n) n.textContent = turn.summaryError ? `No summaries for this turn: ${turn.summaryError}` : '';
}
// A model-written line carries what it summarizes, so a long press can mark it wrong (work-ui.js).
function mark(node, p) {
  if (!node) return;
  if (p) { node.dataset.purpose = p.level; node.dataset.ref = p.ref ?? ''; node.title = 'Written by a model from the rows below. Long press if it is wrong.'; }
  else { delete node.dataset.purpose; delete node.dataset.ref; node.removeAttribute('title'); }
}

/** Where compaction happened. */
export function compactMark() {
  return el('<div class="wk-memory">Memory compacted here: the agent now works from a summary of what came before.</div>');
}
