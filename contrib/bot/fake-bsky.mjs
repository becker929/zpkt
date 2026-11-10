// A stand-in for Bluesky in tests (the room bot's, with replies and quotes): one local HTTP server playing the bot's
// PDS (sessions, notifications, records, blobs, service tokens) and the video service (upload, job status, limits).
// It records every write so tests can read what the bot would have posted. Access tokens can be made to expire, and
// video can be made to fail.

import { createServer } from 'node:http';

export async function fakeBluesky({ handle = 'tunes.test', password = 'app-pass' } = {}) {
  const st = {
    did: 'did:plc:musicbottest', handle, password,
    mentions: [], posts: new Map(), records: [], blobs: [], calls: [],
    access: '', refresh: '', sessions: 0, refreshes: 0, n: 0,
    failVideo: false, noVideo: false, expireNext: false,
  };
  const tokens = () => { st.n++; st.access = `acc-${st.n}`; st.refresh = `ref-${st.n}`; };
  let base = '';
  const session = () => ({ did: st.did, handle: st.handle, accessJwt: st.access, refreshJwt: st.refresh, didDoc: { id: st.did, service: [{ id: '#atproto_pds', type: 'AtprotoPersonalDataServer', serviceEndpoint: base }] }, emailConfirmed: true });
  const blob = (bytes, mimeType) => { const b = { $type: 'blob', ref: { $link: `bafyblob${st.blobs.length}` }, mimeType, size: bytes.length }; st.blobs.push({ ...b, bytes }); return b; };
  const read = (req) => new Promise((r) => { const parts = []; req.on('data', (d) => parts.push(d)); req.on('end', () => r(Buffer.concat(parts))); });

  const server = createServer(async (req, res) => {
    const url = new URL(req.url, base);
    const nsid = url.pathname.replace('/xrpc/', '');
    const auth = (req.headers.authorization ?? '').replace(/^Bearer /, '');
    const body = await read(req);
    const json = () => { try { return JSON.parse(body.toString() || '{}'); } catch { return {}; } };
    const send = (code, data) => { res.writeHead(code, { 'content-type': 'application/json' }); res.end(JSON.stringify(data)); };
    st.calls.push(nsid);
    const needAccess = () => {
      if (st.expireNext) { st.expireNext = false; st.access = 'expired'; }
      if (auth !== st.access) { send(400, { error: 'ExpiredToken', message: 'Token has expired' }); return false; }
      return true;
    };
    switch (nsid) {
      case 'com.atproto.server.createSession': {
        const b = json();
        if (b.password !== st.password || (b.identifier !== st.handle && b.identifier !== st.did)) return send(401, { error: 'AuthenticationRequired', message: 'Invalid identifier or password' });
        st.sessions++; tokens(); return send(200, session());
      }
      case 'com.atproto.server.refreshSession':
        if (auth !== st.refresh) return send(400, { error: 'ExpiredToken', message: 'refresh token gone' });
        st.refreshes++; tokens(); return send(200, session());
      case 'com.atproto.server.getSession':
        return needAccess() && send(200, { did: st.did, handle: st.handle, emailConfirmed: true });
      case 'app.bsky.notification.listNotifications':
        return needAccess() && send(200, { notifications: st.mentions });
      case 'app.bsky.notification.updateSeen':
        return needAccess() && send(200, {});
      case 'app.bsky.feed.getPosts':
        return needAccess() && send(200, { posts: url.searchParams.getAll('uris').map((u) => st.posts.get(u)).filter(Boolean) });
      case 'com.atproto.repo.createRecord': {
        if (!needAccess()) return;
        const b = json();
        const uri = `at://${st.did}/${b.collection}/rkey${st.records.length}`;
        st.records.push({ uri, ...b, at: Date.now() }); // at: when it arrived, for timing likes and replies
        const cid = `bafyrec${st.records.length}`;
        if (b.collection === 'app.bsky.feed.post') st.posts.set(uri, { uri, cid, author: { did: st.did, handle: st.handle }, record: b.record });
        return send(200, { uri, cid });
      }
      case 'com.atproto.repo.deleteRecord': {
        if (!needAccess()) return;
        const b = json();
        const i = st.records.findIndex((r) => r.collection === b.collection && r.uri.endsWith(`/${b.rkey}`));
        if (i >= 0) st.records.splice(i, 1);
        return send(200, {});
      }
      case 'com.atproto.repo.uploadBlob':
        return needAccess() && send(200, { blob: blob(body, req.headers['content-type']) });
      case 'com.atproto.server.getServiceAuth':
        return needAccess() && send(200, { token: `svc|${url.searchParams.get('aud')}|${url.searchParams.get('lxm')}` });
      case 'app.bsky.video.getUploadLimits':
        return send(auth.startsWith('svc|') ? 200 : 401, { canUpload: !st.noVideo, remainingDailyVideos: st.noVideo ? 0 : 20, message: st.noVideo ? 'no video today' : undefined });
      case 'app.bsky.video.uploadVideo': {
        const [, aud, lxm] = auth.split('|');
        if (aud !== `did:web:${new URL(base).host}` || lxm !== 'com.atproto.repo.uploadBlob') return send(401, { error: 'BadServiceToken', message: `aud ${aud} lxm ${lxm}` });
        if (url.searchParams.get('did') !== st.did) return send(400, { error: 'BadDid' });
        st.video = { bytes: body.length, name: url.searchParams.get('name'), type: req.headers['content-type'] };
        st.job = st.failVideo ? { jobId: 'job1', did: st.did, state: 'JOB_STATE_FAILED', error: 'transcode_failed', message: 'could not transcode' } : { jobId: 'job1', did: st.did, state: 'JOB_STATE_CREATED' };
        st.pendingBlob = blob(body, 'video/mp4');
        return send(200, st.job);
      }
      case 'app.bsky.video.getJobStatus':
        return send(200, { jobStatus: st.failVideo ? st.job : { jobId: 'job1', did: st.did, state: 'JOB_STATE_COMPLETED', blob: st.pendingBlob } });
      default:
        return send(404, { error: 'MethodNotImplemented', message: nsid });
    }
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  base = `http://127.0.0.1:${server.address().port}`;

  /** A notification for the bot, as listNotifications gives it: a mention (tagging the bot), or a reply or quote of
   * one of its posts (reason 'reply' or 'quote'; `tag: false` leaves the bot's @mention out of the text's facets). */
  function mention({ handle: h, text, reply, embed, ageMinutes = 1, n = st.mentions.length, reason = 'mention', tag = reason === 'mention' }) {
    const did = `did:plc:${h.replace(/\W/g, '')}`;
    const uri = `at://${did}/app.bsky.feed.post/m${n}`;
    const at = new Date(Date.now() - ageMinutes * 60_000).toISOString();
    const record = { $type: 'app.bsky.feed.post', text, createdAt: at, ...(reply ? { reply } : {}), ...(embed ? { embed } : {}), facets: tag ? [{ index: { byteStart: 0, byteEnd: handle.length + 1 }, features: [{ $type: 'app.bsky.richtext.facet#mention', did: st.did }] }] : [] };
    const note = { uri, cid: `bafym${n}`, author: { did, handle: h }, reason, record, indexedAt: at, isRead: false };
    st.mentions.unshift(note);
    st.posts.set(uri, { uri, cid: note.cid, author: note.author, record });
    return note;
  }

  return { url: base, state: st, mention, posts: () => st.records.filter((r) => r.collection === 'app.bsky.feed.post'), likes: () => st.records.filter((r) => r.collection === 'app.bsky.feed.like'), close: () => new Promise((r) => server.close(r)) };
}
