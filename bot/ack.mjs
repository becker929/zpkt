// The acknowledgement: right after the like, one fast Haiku call that decides what to do with a post and writes
// the first reply. Music it can make gets "making it, a video will follow" (and a brief for the composer): a new
// piece, or the next version when the post is under one of the bot's pieces. Anything else addressed to the bot
// gets a chatbot answer from a model that knows what the bot is, its limits and models, and can look up two things
// with read-only tools: this person's past requests and whether the booth is open. Nothing about the computer the
// bot runs on is in the prompt or reachable by a tool.
//
// Chat is rate limited (per person per day, and for everyone per hour), generously on purpose. Past a limit a
// would-be chat gets no model-written answer: at exactly the person's daily limit one canned "out of chat" line
// (the caller counts it as a chat reply, so it is said once), otherwise nothing. Music requests are still decided.

import Anthropic from '@anthropic-ai/sdk';
import { costOf } from './brain.mjs';
import { ACK_SCHEMA, ACK_TEXT, ackSystem, ackUser } from './prompts.mjs';
import { clip, scrub } from './richtext.mjs';

export const ACK_DEFAULTS = { ackModel: 'claude-haiku-5-5', chatPerUserPerDay: 20, chatPerHour: 120 };

export const REPLY_LIMIT = 280;
const TOOL_ROUNDS = 3; // model turns that may call tools; the turn after is told to answer
const TOOL_TIMEOUT_MS = 5000;
const LIST_MAX = 10;

export const ACK_TOOLS = [
  {
    name: 'my_history',
    description: "This person's past requests to the bot, newest first (day, outcome, kind, title and version).",
    input_schema: { type: 'object', additionalProperties: false, properties: {} },
  },
  {
    name: 'booth_status',
    description: 'Whether the booth that makes the music is open right now, and how many pieces are waiting in its queue.',
    input_schema: { type: 'object', additionalProperties: false, properties: {} },
  },
];

function withTimeout(p, ms) {
  let timer;
  return Promise.race([p, new Promise((_, rej) => { timer = setTimeout(() => rej(new Error('the booth did not answer in time')), ms); })]).finally(() => clearTimeout(timer));
}

export class Acker {
  /** @param {{apiKey?: string, model?: string, client?: any, booth?: any, cfg?: any, log?: (event: string, data?: object) => void}} o */
  constructor({ apiKey, model, client, booth, cfg = {}, log } = {}) {
    this.cfg = { ...ACK_DEFAULTS, ...cfg };
    this.model = model ?? this.cfg.ackModel;
    this.client = client ?? new Anthropic({ apiKey, maxRetries: 2, timeout: 30_000 });
    this.booth = booth;
    this.log = log ?? (() => {});
    this.system = ackSystem({ composeModel: this.cfg.model, ackModel: this.model, piecesPerUserPerDay: this.cfg.piecesPerUserPerDay ?? 2, revisionsPerUserPerDay: this.cfg.revisionsPerUserPerDay ?? 6, chatPerUserPerDay: this.cfg.chatPerUserPerDay });
  }

  /** The chat limits: null, or 'canned' (say ACK_TEXT.outOfChat once) or 'silent'. */
  chatLimited(counts = {}) {
    const mine = counts.chatRepliesFromAuthorToday ?? 0;
    if ((counts.chatRepliesThisHour ?? 0) >= this.cfg.chatPerHour) return 'silent';
    if (mine > this.cfg.chatPerUserPerDay) return 'silent';
    if (mine === this.cfg.chatPerUserPerDay) return 'canned';
    return null;
  }

  async ack(input) {
    const { handle, text, context, canPiece = { ok: false }, canRevise = { ok: false }, piece = null, history = [], counts = {} } = input;
    const limited = this.chatLimited(counts);
    const anything = canPiece.ok || (piece?.kind === 'revise' && canRevise.ok);
    // Out of chat and no music to make: nothing the model could say would be posted.
    if (limited && !anything) {
      this.log('ack_skipped', { why: 'chat limit and no music', limited });
      return { decision: 'ignore', brief: null, reply: null, cost: 0, why: 'chat limit' };
    }
    const req = {
      model: this.model,
      max_tokens: 4000,
      system: [{ type: 'text', text: this.system, cache_control: { type: 'ephemeral' } }],
      tools: ACK_TOOLS,
      tool_choice: { type: limited ? 'none' : 'auto' }, // out of chat: decide only, no lookups
      output_config: { effort: this.cfg.ackEffort ?? 'low', format: { type: 'json_schema', schema: ACK_SCHEMA } },
      messages: [{ role: 'user', content: ackUser({ handle, text, context, canPiece, canRevise, piece, historyCount: history.length }) }],
    };
    let cost = 0;
    let msg;
    const tools = [];
    for (let round = 0; ; round++) {
      if (round >= TOOL_ROUNDS) req.tool_choice = { type: 'none' };
      msg = await this.client.messages.create(req);
      cost += costOf(this.model, msg.usage ?? {});
      if (msg.stop_reason !== 'tool_use') break;
      const uses = msg.content.filter((b) => b.type === 'tool_use');
      req.messages = [...req.messages, { role: 'assistant', content: msg.content }];
      const results = await Promise.all(uses.map(async (u) => {
        const t0 = Date.now();
        try {
          const out = await withTimeout(this.runTool(u.name, u.input ?? {}, input), TOOL_TIMEOUT_MS);
          tools.push(u.name);
          this.log('ack_tool', { name: u.name, ms: Date.now() - t0 });
          return { type: 'tool_result', tool_use_id: u.id, content: JSON.stringify(out).slice(0, 2000) };
        } catch (e) {
          this.log('ack_tool', { name: u.name, ms: Date.now() - t0, error: e.message });
          return { type: 'tool_result', tool_use_id: u.id, content: String(e.message).slice(0, 200), is_error: true };
        }
      }));
      req.messages.push({ role: 'user', content: results });
    }
    if (msg.stop_reason === 'refusal') return { decision: 'ignore', brief: null, reply: null, cost, why: 'refused' };
    if (msg.stop_reason === 'max_tokens') throw Object.assign(new Error('the acknowledgement ran out of room (max_tokens)'), { cost });
    const raw = msg.content.filter((b) => b.type === 'text').map((b) => b.text).join('');
    let data;
    try { data = JSON.parse(raw); } catch { throw Object.assign(new Error(`acknowledgement was not JSON: ${raw.slice(0, 120)}`), { cost }); }
    return { ...this.shape(data, { canPiece, canRevise, piece, limited, text }), cost, tools };
  }

  /** The model's answer made safe: limits applied, replies scrubbed and clipped, empty strings as null. A revise with
   * no piece to revise is a new piece; music the limits don't allow becomes a chat in the bot's own words. */
  shape(data, { canPiece, canRevise, piece, limited, text = '' }) {
    let decision = ['piece', 'revise', 'chat', 'decline', 'ignore'].includes(data.decision) ? data.decision : 'ignore';
    let reply = clip(scrub(data.reply ?? ''), REPLY_LIMIT) || null;
    const brief = String(data.brief ?? '').replace(/[\u0000-\u0009\u000b-\u001f\u007f]/g, '').trim() || null;
    const why = String(data.why ?? '').slice(0, 200);
    if (decision === 'revise' && piece?.kind !== 'revise') decision = 'piece';
    const allowedNow = decision === 'revise' ? canRevise : canPiece;
    if ((decision === 'piece' || decision === 'revise') && !allowedNow.ok) {
      decision = 'chat'; // the model forgot bot_state: say why it can't, in the bot's own words
      reply = clip(scrub(allowedNow.text || ACK_TEXT.cantMake), REPLY_LIMIT);
    }
    if (decision === 'piece' || decision === 'revise') {
      return { decision, brief: brief ?? `${decision === 'revise' ? 'The next version, as this post asks' : 'A piece for this request'}: ${String(text).slice(0, 500)}`, reply: reply ?? (decision === 'revise' ? ACK_TEXT.revising : ACK_TEXT.making), why };
    }
    if (limited && decision !== 'ignore') {
      // out of chat: no model-written words; one canned line at the person's limit, else silence
      return limited === 'canned' && decision === 'chat' ? { decision: 'chat', brief: null, reply: ACK_TEXT.outOfChat, why: `${why} (out of chat)` } : { decision: 'ignore', brief: null, reply: null, why: `${why} (chat limit)` };
    }
    if (decision === 'ignore' || !reply) return { decision: 'ignore', brief: null, reply: null, why };
    return { decision, brief: null, reply, why };
  }

  /** The tools. Read-only: the history the caller passed in, and the booth's open/queue (nothing else of its status). */
  async runTool(name, args, input) {
    if (name === 'my_history') {
      return { requests: (input.history ?? []).slice(0, LIST_MAX).map((h) => ({ day: h.day, status: h.status, kind: h.kind ?? undefined, title: h.title ?? undefined, version: h.version ?? undefined, asked: clip(String(h.text ?? ''), 120) })) };
    }
    if (name === 'booth_status') {
      if (!this.booth) return { error: 'unknown' };
      const s = await this.booth.status();
      return { open: !!s.open, waiting: Number(s.queue?.length ?? s.queue ?? 0) || 0 };
    }
    throw new Error(`unknown tool ${name}`);
  }
}
