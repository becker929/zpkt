// Entry point for agent work in the page (index.html's inline script uses window.Work).
//   init({ thread, dock, drawer, onStop })   once
//   reset()                                 a session is (re)opened
//   apply(e, { replaying })                 every session event; returns true when it drew the event itself
//   settle()                                after the replay
//   route(agentId | null)                   open or close the subagent drawer (the page owns the URL)
import { createWork } from './work.js';
import { toolRow, paintTool, stepEl, paintStep, paintLogs, logRow, agentCard, paintAgent, foldTurn, paintTrace, compactMark } from './work-thread.js';
import { createTodo, createStrip } from './work-dock.js';
import { createDrawer } from './work-drawer.js';
import { setQuiet, burst, bump } from './juice.js';

let W = createWork();
let ui = null;
let openAgent = null;
let running = false;

const mainTodos = () => W.turn?.todos || [];
const curTitle = () => mainTodos().find((t) => t.status === 'current')?.text || '';

// With no todo list from the agent, the bar shows what it said it is doing and opens to its steps so far.
function nowDoing() {
  const t = W.turn;
  if (!t) return null;
  const items = t.steps.map((s) => ({ text: s.open ? W.last || s.topic || 'Working' : s.purpose || s.summary, status: s.open ? 'current' : 'done' }));
  return { text: t.topic || W.last || '', items };
}
function refreshDock() {
  if (!ui) return;
  ui.todo.render(mainTodos(), running, nowDoing());
  ui.strip.render(W.turn?.agents || []);
  refreshDrawer();
}
function refreshDrawer() {
  if (!ui) return;
  const a = openAgent && W.agents.get(openAgent);
  document.body.classList.toggle('wk-drawer-open', !!a);
  ui.drawerHost.hidden = !a;
  if (a) ui.drawer.draw(a, mainTodos(), running); else ui.drawer.clear();
}

function apply(e, { replaying = false } = {}) {
  if (!ui) return false;
  setQuiet(replaying);
  if (e.type === 'compact') { ui.thread.append(compactMark()); return true; }
  if (e.type === 'state') { running = !!e.running; refreshDock(); return true; }
  const c = W.apply(e);
  if (e.type === 'prompt') running = e.engine !== 'instant';   // the fast path is done in a second or two: no Working bar to flash
  if (e.type === 'run_end') running = false;
  if (!c) { if (e.type === 'prompt' || e.type === 'run_end') refreshDock(); return e.type === 'tool_use' || e.type === 'tool_result' || !!e.parent; }
  switch (c.kind) {
    case 'turn': refreshDock(); return false;
    case 'text': if (c.closed) paintStep(c.closed); return false;                     // the page draws the text itself
    case 'todos': refreshDock(); if (c.owner.step) paintStep(c.owner.step, curTitle()); return true;
    case 'topic': if (c.closed) paintStep(c.closed); if (c.owner === W.turn) refreshDock(); return true;
    case 'log': if (c.step) paintLogs(c.step); return true;   // lines outside a step wait for the next one, or the turn's end
    case 'tool':
      if (c.owner === W.turn) {
        if (c.closed) paintStep(c.closed);
        if (c.isNew) { ui.thread.append(stepEl(c.step, curTitle())); paintLogs(c.step); }
        c.step.el.querySelector('.wk-rows').append(toolRow(c.tool));
        paintStep(c.step, curTitle());
        if (!mainTodos().length) refreshDock();
      } else { paintAgent(c.owner); refreshDrawer(); }
      return true;
    case 'tool-done':
      if (c.owner === W.turn) { paintTool(c.tool); paintStep(c.step, curTitle()); }
      else { paintAgent(c.owner); refreshDrawer(); }
      return true;
    case 'agent-new':
      if (c.agent.parent === W.turn) { const prev = W.turn.steps[W.turn.steps.length - 1]; if (prev) paintStep(prev); ui.thread.append(agentCard(c.agent)); }
      refreshDock();
      return true;
    case 'agent': paintAgent(c.agent); if (c.finished) refreshDock(); else refreshDrawer(); return true;
    case 'turn-end': {
      for (const s of c.turn.steps) { paintStep(s); for (const t of s.tools) paintTool(t); }
      for (const a of c.turn.agents) paintAgent(a);
      const fold = foldTurn(ui.thread, c.turn);
      if (!fold && c.turn.logs.length) ui.thread.append(logRow(c.turn.logs));           // a run that printed and did nothing else
      if (fold && c.turn.status === 'success' && !c.turn.problems) { bump(fold, 1.02); burst(fold.querySelector('.wk-traceline'), 18); }
      refreshDock();
      return false;                                                                    // the page still shows stats or errors
    }
    case 'summary':
      if (c.step) { if (c.owner === W.turns.find((t) => t.steps.includes(c.step))) paintStep(c.step); refreshDrawer(); if (running && !mainTodos().length) refreshDock(); }
      if (c.agent) { paintAgent(c.agent); refreshDrawer(); }
      if (c.turn) paintTrace(c.turn);
      return true;
    default: return false;
  }
}

// Long press (or right-click) on a model-written line marks it wrong; the server stores that and the line goes.
function watchWrong(root, onWrong) {
  let timer = null, fired = false;
  const target = (e) => e.target.closest?.('[data-purpose]');
  const fire = (n) => {
    fired = true;
    const turn = W.turns.find((t) => t.traceEl?.contains(n) || t.steps.some((s) => s.el?.contains(n)) || t.agents.some((a) => a.el?.contains(n)));
    if (turn) onWrong({ level: n.dataset.purpose, ref: n.dataset.ref, turn: turn.seq });
  };
  root.addEventListener('pointerdown', (e) => { const n = target(e); fired = false; clearTimeout(timer); if (n) timer = setTimeout(() => fire(n), 650); });
  for (const t of ['pointerup', 'pointercancel', 'pointermove']) root.addEventListener(t, (e) => { if (t !== 'pointermove' || Math.abs(e.movementX) + Math.abs(e.movementY) > 6) clearTimeout(timer); });
  root.addEventListener('contextmenu', (e) => { const n = target(e); if (n) { e.preventDefault(); clearTimeout(timer); if (!fired) fire(n); } });
  root.addEventListener('click', (e) => { if (fired) { fired = false; e.preventDefault(); e.stopPropagation(); } }, true);   // the press must not also open the row
}

window.Work = {
  init({ thread, dock, drawer, onStop, onRoute, onWrong }) {
    ui = { thread, drawerHost: drawer, onRoute };
    ui.todo = createTodo(dock, { onStop });
    ui.strip = createStrip(dock, { onOpen: (id) => onRoute(id) });
    ui.drawer = createDrawer(drawer, { onClose: () => onRoute(null) });
    thread.addEventListener('click', (e) => { const b = e.target.closest('[data-open-agent]'); if (b) onRoute(b.dataset.openAgent); });
    if (onWrong) watchWrong(thread, onWrong);
  },
  reset() { W = createWork(); running = false; openAgent = null; refreshDock(); },
  apply,
  settle() { setQuiet(false); refreshDock(); },
  setRunning(r) { if (running !== !!r) { running = !!r; refreshDock(); } },
  route(id) { openAgent = id || null; refreshDrawer(); },
  hasAgent: (id) => W.agents.has(id),
  current: () => W.current(),
  /** The last lines the CLI printed in this turn, for the note under a run that failed. */
  /** The first line of the last command in this turn that failed, or ''. */
  lastFailure: () => { const t = W.turn; const bad = t ? t.steps.flatMap((s) => s.tools).filter((x) => x.status === 'error') : [];
    return bad.length ? String(bad[bad.length - 1].output || '').split('\n').find((l) => l.trim()) || '' : ''; },
  lastLog: (n = 6) => { const t = W.turn; return t ? [...t.steps.flatMap((s) => s.logs), ...t.logs].slice(-n) : []; },
};
window.dispatchEvent(new Event('work-ready'));
