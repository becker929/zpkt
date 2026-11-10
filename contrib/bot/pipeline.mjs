// One request in three stages, each its own function so main.mjs can run them side by side: like() the moment a
// post comes in; acknowledge() it seconds later (the Acker, a quick Claude call, decides piece, revise, chat,
// decline or ignore and writes the reply, told beforehand what the limits allow and which piece the post is under
// or quotes); and handle() accepted music: compose a score, check it in the booth with the composer fixing what
// fails, render it in the booth, send flagged measurements back once, and reply with the video. Everything it talks
// to comes in `ctx`, so tests swap in fakes.
//
// The booth is shared with Anthony and closes itself on a surprise, so handle() has three kinds of "not now":
// closed or full (the request waits in the queue until retry_in_s, and the friend is told once), held (the friend is
// told once that there was a hiccup, and the job is polled until it finishes) and down (the request is tried again
// later). Every version's score is saved before it is sent, with its idempotency key, so a request picked up again
// after a crash asks the booth for the same job instead of composing and rendering a second one.

import Anthropic from '@anthropic-ai/sdk';
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { BoothError } from './booth.mjs';
import { Refused } from './brain.mjs';
import { beforeAck, canMake } from './limits.mjs';
import { postLink, report } from './notify.mjs';
import { clip, graphemes, pieceReply, plainReply, replyRefs, scrub } from './richtext.mjs';

export const SORRY = "Sorry, something went wrong while I was making your piece. I've let my owner know.";
export const BOOTH_SORRY = "Sorry, the booth couldn't make that one. I've let my owner know; try asking for it a different way.";
export const WAITING = "The booth is closed for now, so your piece is waiting its turn. It will follow here when the booth opens.";
export const HELD = "There was a hiccup on my side while making your piece. It's waiting for my owner to look, and will follow here.";
const REFUSED = "I can't make that one, but I'd love to make you something else. Mention me again with another idea!";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** The booth said no for now (closed, queue full): the request waits until `at`. */
export class Waiting extends Error {
  constructor(e) { super(e.message); this.retryIn = e.retryIn; this.code = e.code; this.reason = e.reason; }
}
/** The booth finished a job as failed. retryable: sent again later under a fresh key; otherwise the friend gets a sorry. */
export class BoothFailed extends Error {
  constructor(err = {}) {
    super(`booth job failed at ${err.stage ?? '?'}: ${err.code ?? ''} ${err.message ?? ''}`.trim());
    this.stage = err.stage; this.code = err.code; this.retryable = !!err.retryable;
    this.sorry = this.retryable ? SORRY : BOOTH_SORRY;
  }
}
class BoothDown extends Error {}
class Stopping extends Error {}

/** A failure that trying again later should fix: Claude overloaded, rate limited, erroring or unreachable; the booth
 * unreachable or erroring; a booth job that failed and said it may be sent again. */
export function passing(e) {
  if (e instanceof Anthropic.APIConnectionError) return true;
  if (e?.error?.error?.type === 'overloaded_error' || e?.error?.type === 'overloaded_error') return true;
  if (e instanceof Anthropic.APIError) return e.status === 429 || e.status >= 500;
  if (e instanceof BoothDown || (e instanceof BoothFailed && e.retryable)) return true;
  if (e instanceof BoothError) return e.status >= 500 || e.waits;
  return e?.name === 'TimeoutError' || /fetch failed|ECONNREFUSED|ECONNRESET|socket hang up/i.test(String(e?.message ?? '') + String(e?.cause?.code ?? ''));
}

/** After handle() (or, with stage 'ack', acknowledge()) throws: a passing failure goes back for later, until
 * cfg.retryMinutes (cfg.ackRetryMinutes) runs out; anything else, or the last try, fails the request. Answers 'retry'
 * or 'failed'; after a build fails the caller says sorry (failed() does both). */
export function afterFailure(req, e, { cfg, store, log }, now = Date.now(), stage = 'build') {
  const ack = stage === 'ack';
  const waits = (ack ? cfg.ackRetryMinutes : cfg.retryMinutes) ?? [];
  const row = store.get(req.uri);
  const tries = (ack ? row?.ack_attempts ?? req.ack_attempts : row?.attempts ?? req.attempts) ?? 1;
  if (passing(e) && tries <= waits.length) {
    const minutes = waits[tries - 1];
    store.update(req.uri, { status: ack ? 'new' : 'queued', error: e.message.slice(0, 500), retry_at: now + minutes * 60_000 });
    log('will retry', { uri: req.uri, handle: req.handle, stage, error: e.message.slice(0, 200), in_minutes: minutes, attempt: tries });
    return 'retry';
  }
  store.update(req.uri, { status: 'failed', error: e.message.slice(0, 500) });
  return 'failed';
}

/** handle() threw: retry later, or fail with a sorry under the request and a note to the owner. */
export async function failed(req, e, ctx) {
  ctx.log('failed', { uri: req.uri, handle: req.handle, error: e.message, stack: e.stack?.split('\n').slice(1, 4).join(' | ') });
  if (afterFailure(req, e, ctx) === 'retry') return 'retry';
  const now = ctx.store.get(req.uri);
  if (!now?.reply_uri) {
    const text = e.sorry ?? SORRY;
    try {
      const r = await post(req, ctx, plainReply(text));
      ctx.store.update(req.uri, { reply_uri: r.uri, reply: text });
    } catch (x) { ctx.log('sorry reply failed', { uri: req.uri, error: x.message }); }
  }
  await report(ctx, { title: `Music bot failed for @${req.handle}`, text: `${String(req.text).slice(0, 400)}\n\n${e.message.slice(0, 400)}`, url: postLink(req.uri) });
  return 'failed';
}

/** A threaded reply under the request (to the outbox in a dry run). */
async function post(req, ctx, rt, embed) {
  const record = { text: rt.text, ...(rt.facets.length ? { facets: rt.facets } : {}), reply: replyRefs(req), ...(embed ? { embed } : {}) };
  if (ctx.dryRun) return ctx.outbox(req, record);
  return ctx.bsky.post(record);
}

/** Likes a post once (like_uri remembers it across restarts). Never waits on Claude. True when it liked it now. */
export async function like(req, { bsky, store, dryRun, log }) {
  if (req.like_uri || store.get(req.uri)?.like_uri) return false;
  try {
    const r = dryRun ? { uri: 'dry-run' } : await bsky.like(req.uri, req.cid);
    store.update(req.uri, { like_uri: r.uri });
    log('liked', { uri: req.uri, handle: req.handle, ms_after_post: Date.now() - Date.parse(req.created_at) });
    return true;
  } catch (e) {
    log('like failed', { uri: req.uri, error: e.message });
    return false;
  }
}

/** A declined post: the like (given on sight, before anyone read it) is taken back, and the owner hears about it.
 * like_uri becomes 'unliked', so nothing likes it again. */
export async function unlikeAndReport(req, ctx, reply) {
  const { bsky, store, dryRun, log } = ctx;
  if (req.like_uri && req.like_uri !== 'unliked') {
    try {
      if (!dryRun && req.like_uri.startsWith('at://')) await bsky.unlike(req.like_uri);
      store.update(req.uri, { like_uri: 'unliked' });
      log('unliked', { uri: req.uri, handle: req.handle });
    } catch (e) { log('unlike failed', { uri: req.uri, error: e.message }); }
  }
  await report(ctx, { title: `Music bot declined @${req.handle}`, text: `${String(req.text).slice(0, 500)}\n\nReplied: ${reply ?? '(nothing)'}`, url: postLink(req.uri) });
}

/** Which of the bot's pieces a post is about, from its record: the one it quotes (a remix), the one it replies
 * under, or the newest in its thread (a revision). {parent_key, via} or {}. */
export function parentOf(rec, store) {
  const quoted = rec.embed?.$type === 'app.bsky.embed.recordWithMedia' ? rec.embed.record?.record?.uri : rec.embed?.$type === 'app.bsky.embed.record' ? rec.embed.record?.uri : null;
  if (quoted) {
    const p = store.pieceByPost(quoted);
    if (p) return { parent_key: p.key, via: 'quote' };
  }
  if (rec.reply?.parent?.uri) {
    const p = store.pieceByPost(rec.reply.parent.uri) ?? (rec.reply.root?.uri ? store.latestInThread(rec.reply.root.uri) : null);
    if (p) return { parent_key: p.key, via: 'reply' };
  }
  return {};
}

/** The parent piece as the ack and the composer see it, or null. */
function parentPiece(req, store) {
  if (!req.parent_key) return null;
  const p = store.piece(req.parent_key);
  if (!p) return null;
  return { key: p.key, kind: req.via === 'quote' ? 'remix' : 'revise', title: clip(scrub(p.title ?? ''), 80), version: p.version, handle: p.handle, author: p.author, score: p.score, job_id: p.job_id };
}

const ACK_STATUS = { piece: 'queued', revise: 'queued', chat: 'chatted', decline: 'declined', ignore: 'ignored' };

/** The verbal acknowledgement: what the limits allow, then the Acker's decision and reply, posted under the request.
 * Music it accepted goes in the queue for handle() with the Acker's brief and its kind (piece, revise or remix).
 * `reserved`: music other acks in flight were offered (see canMake). Answers the new status. */
export async function acknowledge(req, ctx, reserved = 0) {
  const { store, acker, log } = ctx;
  const uri = req.uri;
  const g = beforeAck(req, ctx);
  if (g) { store.update(uri, g); log('ack', { uri, handle: req.handle, ...g }); return g.status; }
  store.update(uri, { status: 'acking', ack_attempts: (req.ack_attempts ?? 0) + 1 });
  // a retry after the answer was saved but before it went out keeps that answer (its music already counts)
  let a = req.decision ? { decision: req.decision, brief: req.brief, reply: req.ack } : null;
  let note = null;
  if (!a) {
    const piece = parentPiece(req, store);
    const canPiece = canMake(req, ctx, 'piece', reserved);
    const canRevise = piece?.kind === 'revise' ? canMake(req, ctx, 'revise', reserved) : { ok: false, reason: 'no_piece' };
    try {
      a = await acker.ack({
        handle: req.handle, author: req.author, text: req.text, context: req.context, canPiece, canRevise,
        piece: piece && { kind: piece.kind, title: piece.title, version: piece.version, handle: piece.handle },
        history: store.history(req.author, uri),
        counts: { ...store.chatCounts(req.author, req.day), spentToday: store.spentToday(req.day) },
      });
    } catch (e) {
      if (!(e instanceof Refused)) throw e;
      a = { decision: 'decline', brief: null, reply: REFUSED, cost: e.cost };
    }
    if (a.cost) store.addCost(uri, a.cost);
    if (!ACK_STATUS[a.decision]) { note = `unknown decision ${String(a.decision).slice(0, 40)}`; a = { ...a, decision: 'ignore' }; }
    if (a.decision === 'revise' && piece?.kind !== 'revise') a = { ...a, decision: 'piece' }; // nothing to revise: a new piece
    const kind = a.decision === 'revise' ? 'revise' : a.decision === 'piece' && piece?.kind === 'remix' ? 'remix' : a.decision === 'piece' ? 'piece' : null;
    const can = kind === 'revise' ? canRevise : canPiece;
    // never promise music the limits won't give, whatever the model said
    if (kind && !can.ok) { note = `${kind} not allowed: ${can.reason}`; a = { ...a, decision: 'chat', reply: can.text }; }
    const made = kind && can.ok;
    const reply = a.decision === 'ignore' ? null : a.reply ? clip(scrub(a.reply), 300) || null : null;
    a = { ...a, reply, brief: made ? a.brief || req.text : null };
    store.update(uri, { decision: a.decision, kind: made ? kind : null, parent_key: made && kind !== 'piece' ? piece.key : null, brief: a.brief, ack: a.reply, ack_at: a.reply ? Date.now() : null, note }); // counted as said even if the post fails
  }
  // the reply is a courtesy: if Bluesky won't take it, the decision (and the music) still stands
  if (a.reply && !req.ack_uri) {
    try {
      const r = await post(req, ctx, plainReply(a.reply));
      store.update(uri, { ack_uri: r.uri });
    } catch (e) { log('ack reply failed', { uri, error: e.message }); }
  }
  if (a.decision === 'decline') await unlikeAndReport(store.get(uri) ?? req, ctx, a.reply);
  const status = ACK_STATUS[a.decision];
  store.update(uri, { status, retry_at: null, error: null });
  log('ack', { uri, handle: req.handle, decision: a.decision, kind: store.get(uri)?.kind, status, note, ms_after_post: Date.now() - Date.parse(req.created_at), reply: a.reply?.slice(0, 200) });
  return status;
}

/** What the booth's check says is wrong with a draft, or null when it passes. */
async function problems(score, { booth, log }, uri) {
  if (!score || typeof score !== 'object' || Array.isArray(score)) return { errors: [{ path: '$', code: 'shape', message: 'the answer has no score object' }], warnings: [] };
  let c;
  try {
    c = await booth.check(score);
  } catch (e) {
    if (e instanceof BoothError && e.waits) throw new Waiting(e);
    if (e instanceof BoothError && e.status >= 400 && e.status < 500 && e.status !== 401 && e.status !== 403) return { errors: [{ path: '$', code: e.code ?? 'invalid', message: e.reason ?? e.message }], warnings: [] };
    throw e;
  }
  log('checked', { uri, ok: !!c.ok, errors: c.errors?.length ?? 0, warnings: c.warnings?.length ?? 0, estimate: c.estimate });
  if (c.ok) return null;
  return { errors: c.errors?.length ? c.errors : [{ path: '$', code: 'rejected', message: 'the check did not pass' }], warnings: c.warnings ?? [] };
}

/** A draft, then fixes until the booth's check passes (at most cfg.fixRounds). Answers the passing draft. */
async function checked(first, conv, ctx, uri, spend, counter) {
  let d = first;
  let p = await problems(d.score, ctx, uri);
  while (p && counter.rounds < ctx.cfg.fixRounds) {
    counter.rounds++;
    ctx.log('fix', { uri, errors: p.errors.slice(0, 5).map((e) => `${e.path} ${e.code}`).join('; ') });
    d = await conv.fix('check', p.errors, p.warnings);
    spend(d.cost);
    p = await problems(d.score, ctx, uri);
  }
  if (p) throw new Error(`the score still fails the booth's check after ${counter.rounds} fixes: ${p.errors.slice(0, 3).map((e) => `${e.path} ${e.message}`).join('; ').slice(0, 300)}`);
  return d;
}

/** Sends one version to the booth (the same key always answers the same job) and polls it until it is done. Tells the
 * friend once when it is held. Throws Waiting (closed, full), BoothFailed or BoothDown. */
async function render(row, req, ctx, parentJob) {
  const { cfg, store, booth, log } = ctx;
  const key = row.tries ? `${row.key}~${row.tries}` : row.key;
  const submit = async () => {
    let j;
    try { j = await booth.submit(key, row.score, parentJob); } catch (e) {
      if (e instanceof BoothError && e.waits) throw new Waiting(e);
      throw e;
    }
    store.updatePiece(row.key, { job_id: j.job, state: j.state ?? 'queued' });
    log('submitted', { uri: req.uri, key, job: j.job, state: j.state, position: j.position, eta_s: j.eta_s });
    return j.job;
  };
  let id = row.job_id ?? await submit();
  let downSince = null, heldSince = null;
  for (;;) {
    if (ctx.stopping?.()) throw new Stopping('stopping');
    let j;
    try {
      j = await booth.job(id);
      downSince = null;
    } catch (e) {
      if (e instanceof BoothError && e.status === 404) { log('job gone, sending it again', { uri: req.uri, key, job: id }); id = await submit(); continue; }
      if (e instanceof BoothError && e.status < 500 && !e.waits) throw e;
      downSince ??= Date.now();
      if (Date.now() - downSince > cfg.boothDownMinutes * 60_000) throw new BoothDown(`the booth hasn't answered for ${cfg.boothDownMinutes} minutes: ${e.message}`);
      await sleep(cfg.jobPollSeconds * 1000);
      continue;
    }
    if (j.state !== row.state) { store.updatePiece(row.key, { state: j.state }); row.state = j.state; log('job', { uri: req.uri, job: id, state: j.state, stage: j.stage, position: j.position, eta_s: j.eta_s }); }
    if (j.state === 'done') {
      store.updatePiece(row.key, { measure: j.measure ?? null, error: null });
      return { ...j, job: j.job ?? id };
    }
    if (j.state === 'failed') {
      const f = new BoothFailed(j.error ?? {});
      store.updatePiece(row.key, { error: f.message.slice(0, 500), ...(f.retryable ? { tries: (row.tries ?? 0) + 1, job_id: null, state: 'composed' } : {}) });
      throw f;
    }
    if (j.state === 'held') {
      heldSince ??= Date.now();
      if (!store.get(req.uri)?.held_told) {
        store.update(req.uri, { held_told: 1 });
        try { await post(req, ctx, plainReply(HELD)); } catch (e) { log('held reply failed', { uri: req.uri, error: e.message }); }
        log('held', { uri: req.uri, job: id, stage: j.stage });
      }
      if (Date.now() - heldSince > cfg.heldHours * 3600_000) throw new BoothFailed({ stage: j.stage, code: 'held_too_long', message: `held for over ${cfg.heldHours} h`, retryable: false });
    } else heldSince = null;
    await sleep(cfg.jobPollSeconds * 1000);
  }
}

const safeName = (s) => String(s).replace(/[^A-Za-z0-9._-]+/g, '_').slice(-80);

/** Accepted music (decision piece or revise, kind piece, revise or remix), start to finish. Answers the final status,
 * or 'waiting' when the booth is closed (the request is back in the queue with a retry time). */
export async function handle(req, ctx) {
  const { cfg, store, booth, brain, log } = ctx;
  const uri = req.uri;
  if (req.decision !== 'piece' && req.decision !== 'revise') throw new Error(`not accepted music (decision ${req.decision})`);
  const kind = req.kind ?? 'piece';
  store.update(uri, { status: 'working', attempts: (req.attempts ?? 0) + 1 });
  const spend = (c) => { if (c) store.addCost(uri, c); };
  const finish = (status, fields = {}) => { store.update(uri, { status, retry_at: null, ...fields }); log('request', { uri, handle: req.handle, status, ...fields }); return status; };
  const answer = async (rt, embed) => {
    store.update(uri, { reply: rt.text });
    const r = await post(req, ctx, rt, embed);
    store.update(uri, { reply_uri: r.uri });
    return r;
  };
  if (store.get(uri)?.reply_uri) return finish('done', { note: 'already replied (picked up again after a crash)' });
  const parent = kind === 'piece' ? null : parentPiece(req, store);
  if (kind !== 'piece' && !parent) throw new Error(`the ${kind}'s parent piece ${req.parent_key} is not in bot.db`);
  const version = kind === 'revise' ? parent.version + 1 : 1;
  const key = `${uri}#v${version}`;
  const counter = { rounds: req.rounds ?? 0 };
  let conv = null;

  try {
    // 1. compose and check, unless a crash left this version's score saved (then the booth is asked for the same job)
    let rows = store.piecesOf(uri);
    if (!rows.length) {
      conv = brain.compose({ brief: req.brief || req.text, handle: req.handle, text: req.text, parent: parent && { kind, score: parent.score, title: parent.title, version: parent.version, handle: parent.handle } });
      let d;
      try {
        d = await conv.draft();
        spend(d.cost);
        d = await checked(d, conv, ctx, uri, spend, counter);
      } catch (e) {
        if (!(e instanceof Refused)) throw e;
        spend(e.cost);
        await answer(plainReply(REFUSED));
        return finish('declined', { note: 'the model refused the score' });
      }
      store.addPiece({ key, request_uri: uri, author: req.author, handle: req.handle, day: req.day, kind, version, round: 0, parent_key: parent?.key ?? null, score: d.score, line: d.line, alt: d.alt, root_uri: req.root_uri ?? uri, root_cid: req.root_cid ?? req.cid });
      store.update(uri, { piece_key: key, version, title: String(d.score.title ?? '').slice(0, 200), rounds: counter.rounds });
      rows = store.piecesOf(uri);
    }

    // 2. render it; flagged measurements go back to the composer once, and the better of the two renders is kept
    const first = rows[0];
    const job0 = await render(first, req, ctx, parent?.job_id ?? null);
    let best = first, bestJob = job0;
    const flags = job0.measure?.flags ?? [];
    if (flags.length && cfg.measureRounds > 0) {
      let second = rows[1];
      if (!second && !conv) log('no measure round', { uri, why: 'the composing conversation was lost in a restart' });
      else if (!second && store.rendersToday(req.day) >= cfg.rendersPerDay) log('no measure round', { uri, why: 'renders per day' });
      else if (!second) {
        log('measure flags', { uri, flags });
        try {
          let d = await conv.fix('measure', flags, job0.measure);
          spend(d.cost);
          d = await checked(d, conv, ctx, uri, spend, { rounds: 0 });
          second = store.addPiece({ key: `${key}+1`, request_uri: uri, author: req.author, handle: req.handle, day: req.day, kind, version, round: 1, parent_key: parent?.key ?? null, score: d.score, line: d.line, alt: d.alt, root_uri: req.root_uri ?? uri, root_cid: req.root_cid ?? req.cid });
        } catch (e) {
          if (e instanceof Waiting || passing(e)) throw e;
          log('measure fix failed', { uri, error: e.message }); // the first render stands
        }
      }
      if (second) {
        try {
          const job1 = await render(second, req, ctx, job0.job);
          const flags1 = job1.measure?.flags ?? [];
          log('measure round', { uri, flags_before: flags.length, flags_after: flags1.length });
          if (flags1.length <= flags.length) { best = second; bestJob = job1; }
        } catch (e) {
          if (!(e instanceof BoothFailed)) throw e;
          log('measure round failed, keeping the first render', { uri, error: e.message });
        }
      }
    }
    store.updatePiece(best.key, { kept: 1 });
    if (best !== first) store.updatePiece(first.key, { kept: 0 });

    // 3. the files, then the reply: the video (or the booth's still, if video can't be posted)
    const files = bestJob.files ?? ['video.mp4', 'still.jpg'];
    const base = join(ctx.renders, safeName(`${uri.split('/').pop()}-v${version}${best.round ? `+${best.round}` : ''}`));
    const fetchFile = async (name, ext) => {
      if (!files.includes(name)) return null;
      const buf = await booth.file(bestJob.job, name);
      writeFileSync(`${base}.${ext}`, buf);
      return { path: `${base}.${ext}`, buf };
    };
    const score = best.score;
    const title = clip(scrub(score.title).replace(/["“”]/g, '').replace(/\n/g, ' '), 60) || 'Untitled';
    const url = bestJob.url && /^https:\/\//.test(bestJob.url) ? bestJob.url : cfg.pieceUrl ? cfg.pieceUrl.replace('{job}', encodeURIComponent(bestJob.job)) : null;
    const credit = kind === 'remix' && /^did:[a-z]+:[\w.:%-]+$/.test(parent.author ?? '') ? { title: parent.title || 'a piece', handle: parent.handle, did: parent.author } : null;
    const rt = pieceReply({ line: best.line, title, version, url, credit });
    const alt = clip(scrub(best.alt) || `A video of the piece ${title}: a piano roll of its score with a playhead, ${Math.round(score.bpm ?? 0)} BPM.`, 1000);
    const [w, h] = cfg.video.size;
    const aspectRatio = { width: w, height: h };
    let embed = null;
    let video = null;
    try { video = await fetchFile('video.mp4', 'mp4'); } catch (e) { log('video download failed', { uri, error: e.message }); }
    if (ctx.dryRun) {
      if (video) embed = { $type: 'app.bsky.embed.video', video: { local: video.path }, alt, aspectRatio };
      else { const still = await fetchFile('still.jpg', 'jpg').catch(() => null); if (still) embed = { $type: 'app.bsky.embed.images', images: [{ image: { local: still.path }, alt, aspectRatio }] }; }
    } else {
      try {
        if (!video) throw new Error('the booth gave no video.mp4');
        const lim = await ctx.bsky.videoLimits().catch(() => ({ canUpload: true }));
        if (lim.canUpload === false) throw new Error(`video not allowed: ${lim.message ?? lim.error ?? 'limit'}`);
        embed = { $type: 'app.bsky.embed.video', video: await ctx.bsky.uploadVideo(video.buf, `${safeName(title)}.mp4`), alt, aspectRatio };
      } catch (e) {
        log('video upload failed, posting a still', { uri, error: e.message });
        const still = await fetchFile('still.jpg', 'jpg').catch((x) => { log('still download failed', { uri, error: x.message }); return null; });
        if (still && still.buf.length < 1_000_000) embed = { $type: 'app.bsky.embed.images', images: [{ image: await ctx.bsky.uploadBlob(still.buf, 'image/jpeg'), alt, aspectRatio }] };
      }
    }
    const r = await answer(rt, embed);
    store.updatePiece(best.key, { post_uri: r.uri });
    return finish('done', { title, rounds: counter.rounds, note: `${graphemes(rt.text)} graphemes, ${embed?.$type ?? 'no media'}, ${bestJob.measure?.lufs ?? '?'} LUFS` });
  } catch (e) {
    if (e instanceof Stopping) { store.update(uri, { status: 'queued', attempts: Math.max(0, (store.get(uri)?.attempts ?? 1) - 1) }); return 'stopped'; }
    if (!(e instanceof Waiting)) throw e;
    // closed or full: back in the queue until the booth says, the friend told once (a wait doesn't count as an attempt)
    const s = Math.min(3600, Math.max(5, e.retryIn ?? 300));
    store.update(uri, { status: 'queued', retry_at: Date.now() + s * 1000, attempts: Math.max(0, (store.get(uri)?.attempts ?? 1) - 1), note: `booth ${e.code}: ${String(e.reason ?? '').slice(0, 120)}` });
    log('waiting', { uri, handle: req.handle, code: e.code, reason: e.reason, retry_in_s: s });
    if (!store.get(uri)?.wait_told && s >= cfg.tellWaitSeconds) {
      store.update(uri, { wait_told: 1 });
      try { await post(req, ctx, plainReply(WAITING)); } catch (x) { log('waiting reply failed', { uri, error: x.message }); }
    }
    return 'waiting';
  }
}
