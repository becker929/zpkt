// Claude as the composer: one conversation per version (high effort), which carries on while the booth's check
// sends problems back and, once, while the render's measurements do. It answers in a fixed JSON shape (structured
// outputs): the score in the booth's own schema, a line for the reply and alt text. Every call's cost is counted
// from its usage. The Acker (ack.mjs) is the other Claude call.

import Anthropic from '@anthropic-ai/sdk';
import { FIX, composeUser } from './prompts.mjs';

// $ per million tokens. Cache writes cost 1.25x input for the 5-minute TTL, 2x for the hour.
const PRICES = {
  'claude-opus-5-5': { input: 4, output: 20, read: 0.2 },
  'claude-sonnet-5-5': { input: 2, output: 10, read: 0.2 },
  'claude-haiku-5-5': { input: 0.1, output: 0.5, read: 0.01 },
};

export function costOf(model, u) {
  const p = PRICES[model] ?? PRICES['claude-opus-5-5'];
  const write = u.cache_creation?.ephemeral_1h_input_tokens !== undefined
    ? (u.cache_creation.ephemeral_5m_input_tokens ?? 0) * 1.25 + u.cache_creation.ephemeral_1h_input_tokens * 2
    : (u.cache_creation_input_tokens ?? 0) * 1.25;
  return ((u.input_tokens ?? 0) * p.input + write * p.input + (u.cache_read_input_tokens ?? 0) * p.read + (u.output_tokens ?? 0) * p.output) / 1e6;
}

export class Refused extends Error {}

export class Brain {
  /** @param {{apiKey?: string, model: string, composeEffort: string, cacheTtl: string, client?: any}} o */
  constructor(o) {
    this.o = o;
    this.client = o.client ?? new Anthropic({ apiKey: o.apiKey, maxRetries: 4 });
    this.composeSystem = ''; // prompts.composeSystem(guide), set at start-up
    this.schema = null; // prompts.composeSchema(guide.schema), set at start-up
    this.fallbacks = true; // server-side fallback on a refusal, until the API says no
  }

  /** One structured call; answers {data, cost, content}. Throws Refused when the whole chain declines. */
  async ask({ system, messages, effort, schema, maxTokens, cache }) {
    const ttl = this.o.cacheTtl === '1h' ? { ttl: '1h' } : {};
    const req = {
      model: this.o.model,
      max_tokens: maxTokens,
      system: cache ? [{ type: 'text', text: system, cache_control: { type: 'ephemeral', ...ttl } }] : system,
      ...(cache ? { cache_control: { type: 'ephemeral', ...ttl } } : {}), // the growing fix conversation, too
      messages,
      output_config: { effort, format: { type: 'json_schema', schema } },
    };
    let msg;
    try {
      msg = this.fallbacks
        ? await this.client.beta.messages.stream({ ...req, betas: ['server-side-fallback-2026-07-01'], fallbacks: 'default' }).finalMessage()
        : await this.client.messages.stream(req).finalMessage();
    } catch (e) {
      if (!(this.fallbacks && e instanceof Anthropic.BadRequestError && /fallback/i.test(e.message))) throw e;
      this.fallbacks = false;
      msg = await this.client.messages.stream(req).finalMessage();
    }
    const cost = costOf(this.o.model, msg.usage ?? {});
    if (msg.stop_reason === 'refusal') throw Object.assign(new Refused(msg.stop_details?.explanation ?? 'refused'), { cost });
    if (msg.stop_reason === 'max_tokens') throw Object.assign(new Error('the answer ran out of room (max_tokens)'), { cost });
    const text = msg.content.filter((b) => b.type === 'text').map((b) => b.text).join('');
    let data;
    try { data = JSON.parse(text); } catch { throw Object.assign(new Error(`answer was not JSON: ${text.slice(0, 120)}`), { cost }); }
    return { data, cost, content: msg.content };
  }

  /** A composing conversation: draft() for the first score, fix(kind, ...) to send back a problem and get the next.
   * `parent` ({kind: revise | remix, score, title, version, handle}) is the score a revision or remix starts from. */
  compose({ brief, handle, text, parent }) {
    if (!this.composeSystem || !this.schema) throw new Error('the composer has no guide yet (composeSystem and schema)');
    const messages = [{ role: 'user', content: composeUser({ brief, handle, text, parent }) }];
    const turn = async () => {
      const r = await this.ask({ system: this.composeSystem, messages, effort: this.o.composeEffort, schema: this.schema, maxTokens: 64000, cache: true });
      messages.push({ role: 'assistant', content: r.content });
      return { score: r.data.score, line: r.data.line, alt: r.data.alt, cost: r.cost };
    };
    return {
      draft: turn,
      fix: (kind, ...args) => { messages.push({ role: 'user', content: FIX[kind](...args) }); return turn(); },
      messages,
    };
  }
}
