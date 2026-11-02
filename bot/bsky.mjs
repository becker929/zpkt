// A small Bluesky client over plain XRPC (fetch): log in with an app password, read mentions, replies and quotes,
// like, post, upload images and video. The session is kept (saveSession) so restarts refresh it instead of logging in
// again: createSession is rate-limited per account. Video goes through the video service, which processes it
// before the post goes out (docs: bsky-docs tutorials/video): a service token for the bot's own PDS, upload,
// then poll the job for the blob.

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export class XrpcError extends Error {
  constructor(nsid, status, body) {
    super(`${nsid}: ${status} ${body?.error ?? ''} ${body?.message ?? ''}`.trim());
    this.status = status;
    this.error = body?.error;
  }
}

export class Bsky {
  /** @param {{service: string, videoService: string, identifier: string, password: string, loadSession?: () => any, saveSession?: (s: any) => void, fetch?: typeof fetch}} o */
  constructor(o) {
    this.service = o.service.replace(/\/$/, '');
    this.videoService = o.videoService.replace(/\/$/, '');
    this.identifier = o.identifier;
    this.password = o.password;
    this.loadSession = o.loadSession ?? (() => null);
    this.saveSession = o.saveSession ?? (() => {});
    this.fetch = o.fetch ?? globalThis.fetch;
    this.s = null; // {did, handle, accessJwt, refreshJwt, pds}
  }

  get did() { return this.s?.did; }
  get handle() { return this.s?.handle; }

  async login() {
    const saved = this.loadSession();
    if (saved?.refreshJwt) {
      this.s = saved;
      try {
        await this.refresh();
        return this.s;
      } catch {
        this.s = null; // the refresh token is gone or revoked: log in again
      }
    }
    if (!this.identifier || !this.password) throw new Error('No Bluesky login: set BSKY_IDENTIFIER and BSKY_APP_PASSWORD (an app password, not the account password)');
    const body = await this.raw(`${this.service}/xrpc/com.atproto.server.createSession`, 'com.atproto.server.createSession', { method: 'POST', json: { identifier: this.identifier, password: this.password } });
    this.adopt(body);
    return this.s;
  }

  adopt(body) {
    const pds = (body.didDoc?.service ?? []).find((s) => s.id === '#atproto_pds' || s.id?.endsWith('#atproto_pds'))?.serviceEndpoint;
    this.s = { did: body.did, handle: body.handle, accessJwt: body.accessJwt, refreshJwt: body.refreshJwt, pds: (pds ?? this.s?.pds ?? this.service).replace(/\/$/, '') };
    this.saveSession(this.s);
  }

  async refresh() {
    const body = await this.raw(`${this.s.pds}/xrpc/com.atproto.server.refreshSession`, 'com.atproto.server.refreshSession', { method: 'POST', token: this.s.refreshJwt });
    this.adopt(body);
  }

  async raw(url, nsid, { method = 'GET', json, bytes, contentType, token, timeoutMs = 30_000 } = {}) {
    const headers = {};
    if (token) headers.authorization = `Bearer ${token}`;
    let body;
    if (json !== undefined) { headers['content-type'] = 'application/json'; body = JSON.stringify(json); }
    if (bytes !== undefined) { headers['content-type'] = contentType; body = bytes; }
    const res = await this.fetch(url, { method, headers, body, signal: AbortSignal.timeout(timeoutMs) });
    const text = await res.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch { data = { message: text.slice(0, 200) }; }
    if (!res.ok) throw new XrpcError(nsid, res.status, data);
    return data;
  }

  /** An authenticated call to the bot's PDS (which proxies app.bsky.* reads to the AppView); refreshes an expired session once. */
  async xrpc(nsid, { method = 'GET', params, json, bytes, contentType, timeoutMs } = {}) {
    if (!this.s) await this.login();
    const qs = params ? '?' + new URLSearchParams(Object.entries(params).flatMap(([k, v]) => (Array.isArray(v) ? v.map((x) => [k, x]) : v === undefined ? [] : [[k, String(v)]]))) : '';
    const go = () => this.raw(`${this.s.pds}/xrpc/${nsid}${qs}`, nsid, { method, json, bytes, contentType, token: this.s.accessJwt, timeoutMs });
    try {
      return await go();
    } catch (e) {
      if (!(e instanceof XrpcError) || !['ExpiredToken', 'InvalidToken'].includes(e.error)) throw e;
      await this.refresh();
      return go();
    }
  }

  getSession() { return this.xrpc('com.atproto.server.getSession'); }

  /** Mentions, replies and quotes, newest first, one page. */
  notifications({ cursor, limit = 50, reasons = ['mention', 'reply', 'quote'] } = {}) {
    return this.xrpc('app.bsky.notification.listNotifications', { params: { limit, cursor, reasons } });
  }

  updateSeen(seenAt) { return this.xrpc('app.bsky.notification.updateSeen', { method: 'POST', json: { seenAt } }); }

  async getPosts(uris) {
    if (!uris.length) return [];
    return (await this.xrpc('app.bsky.feed.getPosts', { params: { uris } })).posts ?? [];
  }

  createRecord(collection, record) {
    return this.xrpc('com.atproto.repo.createRecord', { method: 'POST', json: { repo: this.s.did, collection, record } });
  }

  like(uri, cid) {
    return this.createRecord('app.bsky.feed.like', { $type: 'app.bsky.feed.like', subject: { uri, cid }, createdAt: new Date().toISOString() });
  }

  /** Takes back a like (its record's at:// URI). */
  unlike(likeUri) {
    const rkey = likeUri.split('/').pop();
    return this.xrpc('com.atproto.repo.deleteRecord', { method: 'POST', json: { repo: this.s.did, collection: 'app.bsky.feed.like', rkey } });
  }

  post(record) {
    return this.createRecord('app.bsky.feed.post', { $type: 'app.bsky.feed.post', createdAt: new Date().toISOString(), langs: ['en'], ...record });
  }

  async uploadBlob(bytes, contentType) {
    return (await this.xrpc('com.atproto.repo.uploadBlob', { method: 'POST', bytes, contentType, timeoutMs: 120_000 })).blob;
  }

  async serviceAuth(aud, lxm, seconds = 1800) {
    return (await this.xrpc('com.atproto.server.getServiceAuth', { params: { aud, lxm, exp: Math.floor(Date.now() / 1000) + seconds } })).token;
  }

  /** How many videos the account may still upload today (Bluesky-hosted accounts need a confirmed email to upload any). */
  async videoLimits() {
    const token = await this.serviceAuth(`did:web:${new URL(this.videoService).host}`, 'app.bsky.video.getUploadLimits', 300);
    return this.raw(`${this.videoService}/xrpc/app.bsky.video.getUploadLimits`, 'app.bsky.video.getUploadLimits', { token });
  }

  /** Uploads an MP4 to the video service and waits for the processed blob to land in the bot's repo. */
  async uploadVideo(bytes, name, { timeoutMs = 300_000, pollMs = 1500 } = {}) {
    if (!this.s) await this.login();
    const token = await this.serviceAuth(`did:web:${new URL(this.s.pds).host}`, 'com.atproto.repo.uploadBlob');
    const url = `${this.videoService}/xrpc/app.bsky.video.uploadVideo?${new URLSearchParams({ did: this.s.did, name })}`;
    const res = await this.fetch(url, { method: 'POST', headers: { authorization: `Bearer ${token}`, 'content-type': 'video/mp4', 'content-length': String(bytes.length) }, body: bytes, signal: AbortSignal.timeout(180_000) });
    const first = await res.json().catch(() => ({}));
    // a video the service has seen before comes back as an error that still carries the job (and often the blob)
    let job = first.jobStatus ?? first;
    if (!res.ok && !job.jobId && !job.blob) throw new XrpcError('app.bsky.video.uploadVideo', res.status, first);
    const until = Date.now() + timeoutMs;
    while (!job.blob) {
      if (job.state === 'JOB_STATE_FAILED') throw new Error(`video processing failed: ${job.error ?? ''} ${job.message ?? ''}`.trim());
      if (!job.jobId) throw new Error(`video upload gave no job: ${JSON.stringify(first).slice(0, 200)}`);
      if (Date.now() > until) throw new Error('video processing took too long');
      await sleep(pollMs);
      const s = await this.raw(`${this.videoService}/xrpc/app.bsky.video.getJobStatus?jobId=${encodeURIComponent(job.jobId)}`, 'app.bsky.video.getJobStatus').catch((e) => ({ jobStatus: { ...job, poll_error: e.message } }));
      job = s.jobStatus ?? job;
    }
    return job.blob;
  }
}
