// The booth as the bot uses it: lib/booth's HTTP service on loopback (127.0.0.1:8794), as Anthony, in front of
// Live. JSON in and out, every request with the bot's token (Bearer zb1_...). The booth takes a score and nothing
// else (docs/bluesky-bot.md, "The one rule"), so this client only ever sends scores, keys and job ids.
//
// Errors are {error, message} with a stable code. Two of them mean "not now" rather than "no": 503 closed (the
// booth is shut, outside its hours, or Live is busy) and 429 queue_full; both carry or imply a wait, and BoothError
// .waits is true for them. Anything else is an answer the caller has to deal with.

const JOB_ID = /^[a-z0-9]{6,32}$/; // the booth's own ids are [a-z0-9]{12}; nothing else goes into a URL
export const FILES = ['render.m4a', 'video.mp4', 'still.jpg', 'score.json', 'measure.json'];

export class BoothError extends Error {
  constructor(what, status, body) {
    super(`booth ${what}: ${status} ${body?.error ?? ''} ${body?.message ?? body?.reason ?? ''}`.trim());
    this.status = status;
    this.code = body?.error ?? null;
    this.reason = body?.reason ?? body?.message ?? null;
    this.retryIn = Number.isFinite(body?.retry_in_s) ? body.retry_in_s : null;
  }

  /** Closed or full: the request should wait and try again, not fail. */
  get waits() { return (this.status === 503 && this.code === 'closed') || (this.status === 429 && this.code === 'queue_full'); }
}

export class Booth {
  /** @param {{base: string, token: string, fetch?: typeof fetch, timeoutMs?: number}} o */
  constructor(o) {
    this.base = o.base.replace(/\/$/, '');
    this.token = o.token || '';
    this.fetch = o.fetch ?? globalThis.fetch;
    this.timeoutMs = o.timeoutMs ?? 30_000;
    if (!this.token) throw new Error('No booth token: copy it into secrets.json as BOOTH_TOKEN (setup-mac.sh --secrets)');
  }

  async req(method, path, { json, raw = false, timeoutMs = this.timeoutMs, ok = [200] } = {}) {
    const headers = { authorization: `Bearer ${this.token}` };
    if (json !== undefined) headers['content-type'] = 'application/json';
    const res = await this.fetch(`${this.base}${path}`, { method, headers, body: json === undefined ? undefined : JSON.stringify(json), signal: AbortSignal.timeout(timeoutMs) });
    if (raw && res.ok) return Buffer.from(await res.arrayBuffer());
    const text = await res.text();
    let data;
    try { data = text ? JSON.parse(text) : {}; } catch { data = { error: 'bad_response', message: text.slice(0, 200) }; }
    if (!ok.includes(res.status)) throw new BoothError(`${method} ${path}`, res.status, data);
    return data;
  }

  /** The palette as the composer sees it, the score's JSON Schema, the rules, examples and limits. */
  guide() { return this.req('GET', '/v1/guide'); }

  /** Free: schema, palette, ranges and cost. Saves nothing, never touches Live. */
  check(score) { return this.req('POST', '/v1/check', { json: { score } }); }

  /** Queues a render. `key` is the bot's idempotency key: the same key always answers the same job. */
  submit(key, score, parent = null) {
    return this.req('POST', '/v1/jobs', { json: { key, score, ...(parent ? { parent } : {}), want: { video: { size: [1080, 1920] }, stems: false } }, ok: [200, 201, 202] });
  }

  async job(id) { return this.req('GET', `/v1/jobs/${jobId(id)}`); }

  async cancel(id) { return this.req('DELETE', `/v1/jobs/${jobId(id)}`, { ok: [200, 202, 204] }); }

  /** One of the job's files, as a Buffer. */
  async file(id, name) {
    if (!FILES.includes(name)) throw new Error(`not a booth file: ${String(name).slice(0, 40)}`);
    return this.req('GET', `/v1/jobs/${jobId(id)}/files/${name}`, { raw: true, timeoutMs: 120_000 });
  }

  status() { return this.req('GET', '/v1/status'); }
}

function jobId(id) {
  if (!JOB_ID.test(String(id))) throw new Error(`not a booth job id: ${String(id).slice(0, 40)}`);
  return id;
}
