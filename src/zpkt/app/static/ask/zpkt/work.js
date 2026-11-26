// The work model: what an agent's events mean, as plain data. No DOM, so it runs in tests.
//
// A turn is made of steps (runs of tool calls between pieces of text), subagents (lanes) and one todo list per
// agent. Every summary here is a template built from the level below it, never from raw output, so a line can
// always be traced to a child that can be opened. Problems (errors) are counted at every level and never hidden.

const base = (p) => String(p || '').split(/[\\/]/).filter(Boolean).pop() || '';
const first = (s, n = 60) => { const l = String(s || '').trim().split('\n')[0]; return l.length > n ? l.slice(0, n - 1) + '…' : l; };
const plural = (n, one, many = one + 's') => `${n} ${n === 1 ? one : many}`;

const KIND = [
  ['topic', /^update_topic$/i],
  ['todo', /^(todowrite|todo_write|write_todos|update_todos)$/i],
  ['agent', /^(task|agent|delegate_to_agent|subagent|codebase_investigator)$/i],
  ['run', /^(bash|run_shell_command|shell|execute)$/i],
  ['read', /^(read|read_file|read_many_files|notebookread|list_directory|ls)$/i],
  ['edit', /^(edit|multiedit|write|write_file|replace|notebookedit)$/i],
  ['search', /^(grep|glob|search_file_content|toolsearch|google_web_search|websearch)$/i],
  ['fetch', /^(webfetch|web_fetch)$/i],
];

/** Which family a tool call belongs to: todo, agent, run, read, edit, search, fetch or other. */
export function toolKind(name, params = {}) {
  for (const [k, re] of KIND) if (re.test(name || '')) return k;
  if (typeof params.subagent_type === 'string' || typeof params.agent_name === 'string') return 'agent';
  return 'other';
}

/** One tool call as verb + object, e.g. "ran ears analyze", "read spec.js". Template only: it cannot misstate the call. */
export function toolLine(name, params = {}) {
  const p = params || {};
  switch (toolKind(name, p)) {
    case 'run': return `ran ${first(p.command || p.cmd, 70)}`;
    case 'read': return `read ${base(p.file_path || p.absolute_path || p.path || p.dir_path) || first(p.pattern)}`;
    case 'edit': return `edited ${base(p.file_path || p.absolute_path || p.path)}`;
    case 'search': return `searched ${first(p.pattern || p.query, 50)}`;
    case 'fetch': return `fetched ${first(p.url || p.prompt, 50)}`;
    default: {
      // The app's own tools, in the person's words rather than by their ids (propose_option: only in older chats).
      const app = String(name || '').match(/(?:^|[^a-z])(make_page|read_state|read_measurement|change_live|propose_live|propose_option)(?![a-z_])/i)?.[1].toLowerCase();
      if (app === 'make_page') { const t = p.spec?.title || p.page?.title || p.title; return `${p.spec?.id ? 'changed' : 'made'} a surface${typeof t === 'string' && t ? ': ' + first(t, 50) : ''}`; }
      if (app === 'read_state') return 'looked at the desk';
      if (app === 'read_measurement') return 'read the last measurement';
      if (app === 'change_live') return `changed Live${typeof p.why === 'string' && p.why ? ': ' + first(p.why, 50) : ''}`;
      if (app === 'propose_live') return `asked to change Live${typeof p.why === 'string' && p.why ? ': ' + first(p.why, 50) : ''}`;   // it runs only after the person's tap
      if (app === 'propose_option') return `made a suggestion${typeof p.title === 'string' && p.title ? ': ' + first(p.title, 50) : ''}`;
      const v = ['command', 'file_path', 'path', 'pattern', 'url', 'query', 'prompt'].map((k) => p[k]).find((x) => typeof x === 'string')
        ?? Object.values(p).find((x) => typeof x === 'string');
      return `${name}${v ? ' ' + first(v, 50) : ''}`;
    }
  }
}

const NOUN = { run: ['Ran', 'command'], read: ['Read', 'file'], edit: ['Edited', 'file'], search: ['Searched', 'time'], fetch: ['Fetched', 'page'], other: ['Used', 'tool'] };

/** A step's line, built from its tool calls: "Read 3 files, ran 1 command (1 error)". */
export function stepSummary(tools) {
  if (!tools.length) return 'No tool calls';
  let text;
  if (tools.length === 1) text = toolLine(tools[0].name, tools[0].params).replace(/^./, (c) => c.toUpperCase());
  else {
    const counts = new Map();
    for (const t of tools) { const k = NOUN[t.kind] ? t.kind : 'other'; counts.set(k, (counts.get(k) || 0) + 1); }
    text = [...counts].map(([k, n], i) => { const [verb, noun] = NOUN[k]; return `${i ? verb.toLowerCase() : verb} ${plural(n, noun)}`; }).join(', ');
  }
  const bad = tools.filter((t) => t.status === 'error').length;
  return bad ? `${text} (${plural(bad, 'error')})` : text;
}

/** The turn's counts, shown inside its opened work view: "4 steps · 11 tool calls · 1 failed and was retried". */
export function traceLine({ steps, tools, problems, agents = 0 }) {
  const parts = [plural(steps, 'step'), plural(tools, 'tool call')];
  if (agents) parts.push(plural(agents, 'subagent'));
  if (problems) parts.push(`${problems} failed`);
  return parts.join(' · ');
}

/** Todo items from either engine's todo tool: [{ text, status: 'pending' | 'current' | 'done' }]. */
export function todosFrom(params = {}) {
  const list = Array.isArray(params.todos) ? params.todos : Array.isArray(params.items) ? params.items : [];
  return list.slice(0, 50).map((t) => {
    const text = first(typeof t === 'string' ? t : t?.content ?? t?.description ?? t?.text ?? t?.title ?? '', 120);
    const s = String(t?.status || '').toLowerCase();
    return { text, status: /^(completed|done|complete)$/.test(s) ? 'done' : /^(in_progress|in-progress|active|current)$/.test(s) ? 'current' : 'pending' };
  }).filter((t) => t.text);
}

/** The collapsed todo bar: { count: "2 / 5", text: "Tune kick", done: bool }. */
export function todoBar(todos) {
  const n = todos.length;
  const done = todos.filter((t) => t.status === 'done').length;
  const cur = todos.findIndex((t) => t.status === 'current');
  if (!n) return { count: '', text: '', done: false };
  if (cur >= 0) return { count: `${cur + 1} / ${n}`, text: todos[cur].text, done: false };
  if (done === n) return { count: `${n} / ${n}`, text: 'All done', done: true };
  return { count: `${done} / ${n}`, text: todos.find((t) => t.status === 'pending')?.text || '', done: false };
}

/** A subagent's name and brief from its launching tool call. */
export function agentInfo(name, params = {}) {
  const p = params || {};
  const title = first(p.description || p.agent_name || p.subagent_type || p.name || name, 48);
  const brief = String(p.prompt || p.task || p.objective || p.query || p.description || '').trim();
  const label = first((p.description || p.agent_name || p.subagent_type || name).toString().toLowerCase(), 14);
  return { title, brief, label };
}

/** Gemini CLI's own chapter marker (update_topic): what it is about to do, in its words. */
export function topicFrom(params = {}) {
  const p = params || {};
  return { title: first(p.title, 80), intent: first(p.strategic_intent || p.intent, 160), summary: first(p.summary, 240) };
}

/** A step never grows past this many tool calls: a long run becomes several steps, each with its own line. */
export const STEP_MAX = 6;

/** A command's output that says it failed: `hands` errors and guards, a Python traceback, a nonzero exit code. */
export const FAILED_RUN = /^(ERROR|GUARD):|^Traceback \(most recent call last\)|Exit Code: [1-9]|WARNING: the render is silent/m;
// What the CLI prints on every start; it says nothing about the turn.
const LOG_NOISE = /YOLO mode is enabled|^\s*$/;

/**
 * Folds a session's events into turns. Used by the page event by event (apply), and by tests in one go.
 * Events carry `parent` (a tool id) when they happened inside a subagent.
 */
export function createWork() {
  const W = { turns: [], turn: null, agents: new Map(), tools: new Map(), last: '' };

  const newStep = (owner) => {
    const s = { tools: [], open: true, summary: '', topic: owner.topic || '', logs: owner.logs?.splice(0) || [] };
    owner.steps.push(s); owner.step = s; return s;
  };
  const ownerOf = (e) => (e.parent && W.agents.get(e.parent)) || W.turn;
  const closeStep = (owner) => { if (owner?.step) { owner.step.open = false; owner.step.summary = stepSummary(owner.step.tools); owner.step = null; } };

  /** Returns what changed, so the page knows what to draw: { kind, ... } or null. */
  W.apply = (e) => {
    switch (e.type) {
      case 'prompt':
        W.turn = { seq: e.seq, since: e.t || 0, steps: [], step: null, agents: [], todos: [], logs: [], topic: '', running: true, problems: 0, toolCount: 0, status: null };
        W.turns.push(W.turn);
        W.last = '';   // the previous turn's last call is not what this one is doing
        return { kind: 'turn', turn: W.turn };
      case 'message': {
        const owner = ownerOf(e);
        if (!owner || e.role === 'user') return null;
        if (e.parent) { owner.text = (owner.text || '') + (e.content || ''); return { kind: 'agent', agent: owner }; }
        if ((e.content || '').trim()) { const had = owner.step; closeStep(owner); return { kind: 'text', closed: had || null }; }
        return { kind: 'text', closed: null };
      }
      case 'tool_use': {
        const owner = ownerOf(e);
        if (!owner) return null;
        const kind = toolKind(e.tool_name, e.parameters);
        const turn = W.turn;
        if (kind === 'topic') {
          const t = topicFrom(e.parameters);
          const closed = owner.step;
          closeStep(owner);
          owner.topic = t.intent || t.title || owner.topic || '';
          W.tools.set(e.tool_id, { kind, owner });
          return { kind: 'topic', owner, closed };
        }
        if (kind === 'todo') { owner.todos = todosFrom(e.parameters); W.tools.set(e.tool_id, { kind, owner }); return { kind: 'todos', owner }; }
        if (kind === 'agent') {
          closeStep(owner);
          const a = { id: e.tool_id, ...agentInfo(e.tool_name, e.parameters), status: 'running', report: '', text: '', steps: [], step: null, todos: [], toolCount: 0, problems: 0, parent: owner };
          W.agents.set(a.id, a); turn?.agents.push(a); W.tools.set(e.tool_id, { kind, agent: a });
          return { kind: 'agent-new', agent: a };
        }
        const t = { id: e.tool_id, name: e.tool_name, params: e.parameters || {}, kind, status: 'running', line: toolLine(e.tool_name, e.parameters), start: e.t };
        W.last = t.line;
        let closed = null;
        if (owner.step && owner.step.tools.length >= STEP_MAX) { closed = owner.step; closeStep(owner); }
        const isNew = !owner.step;
        const step = owner.step || newStep(owner);
        step.tools.push(t); owner.toolCount++;
        if (e.parent && turn) turn.toolCount++;
        W.tools.set(e.tool_id, { kind, tool: t, step, owner });
        return { kind: 'tool', tool: t, step, owner, isNew, closed };
      }
      case 'tool_result': {
        const r = W.tools.get(e.tool_id);
        if (!r) return null;
        let bad = e.status === 'error';
        const out = e.output ?? e.error?.message ?? e.error ?? '';
        if (r.kind === 'agent') {
          r.agent.status = bad ? 'failed' : 'done';
          r.agent.report = typeof out === 'string' ? out : JSON.stringify(out);
          closeStep(r.agent);
          if (bad && W.turn) W.turn.problems++;
          return { kind: 'agent', agent: r.agent, finished: true };
        }
        if (r.kind === 'todo' || r.kind === 'topic') return null;
        r.tool.output = typeof out === 'string' ? out : JSON.stringify(out, null, 2);
        // Gemini CLI reports a shell command as a success whatever it printed; a command that says it failed failed.
        if (!bad && r.tool.kind === 'run' && FAILED_RUN.test(r.tool.output)) bad = true;
        r.tool.status = bad ? 'error' : 'ok';
        if (r.tool.start && e.t) r.tool.ms = e.t - r.tool.start;
        if (!r.step.open) r.step.summary = stepSummary(r.step.tools);
        if (bad) { r.owner.problems++; if (r.owner !== W.turn && W.turn) W.turn.problems++; }
        return { ...r, kind: 'tool-done' };
      }
      // What the CLI printed beside its events: kept with the step it was printed during.
      case 'log': {
        const turn = W.turn;
        if (!turn || LOG_NOISE.test(e.text || '')) return { kind: 'log', step: null, turn: null };
        const step = turn.running ? turn.step : null;
        (step ? step.logs : turn.logs).push(String(e.text));
        return { kind: 'log', step, turn };
      }
      case 'result':
      case 'run_end': {
        const turn = W.turn;
        if (!turn || !turn.running) return null;
        closeStep(turn);
        turn.running = false;
        turn.status = e.type === 'result' ? e.status : e.code || e.error ? 'error' : e.signal ? 'stopped' : 'success';
        for (const a of turn.agents) if (a.status === 'running') { a.status = 'stopped'; closeStep(a); }
        // A tool call the run ended without answering is not running any more.
        for (const o of [turn, ...turn.agents]) for (const s of o.steps) for (const t of s.tools) if (t.status === 'running') t.status = 'none';
        turn.trace = traceLine({ steps: turn.steps.length, tools: turn.toolCount, problems: turn.problems, agents: turn.agents.length });
        return { kind: 'turn-end', turn };
      }
      // A model-written purpose line for a step, subagent or turn (lib/summaries.mjs), or its withdrawal.
      case 'summary': {
        const turn = W.turns.find((t) => t.seq === e.turn);
        if (!turn) return null;
        if (e.error) { turn.summaryError = e.error; return { kind: 'summary', turn }; }
        const set = (o) => { if (e.wrong) { o.purpose = ''; o.purposeWrong = true; } else if (!o.purposeWrong) o.purpose = String(e.line || ''); };
        if (e.level === 'turn') { set(turn); return { kind: 'summary', turn }; }
        if (e.level === 'agent') { const a = turn.agents.find((x) => x.id === e.ref); if (!a) return null; set(a); return { kind: 'summary', agent: a }; }
        for (const o of [turn, ...turn.agents]) for (const s of o.steps) if (s.tools[0]?.id === e.ref) { set(s); return { kind: 'summary', step: s, owner: o }; }
        return null;
      }
      default: return null;
    }
  };
  /** The most recent action, for the top of the chat: the live tool call, or what the last turn was for. */
  W.current = () => { const t = W.turn; return !t ? '' : t.running ? W.last || t.topic || '' : t.purpose || ''; };   // a raw command is not what a finished turn was for
  return W;
}
