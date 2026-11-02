#!/usr/bin/env node
// zpkt's music bot. Three stages run side by side in this one process:
//   intake: the bot account's notifications every pollSeconds (2 s): mentions, and replies and quotes of its own
//           posts; each new one is liked at once, never waiting on Claude
//   ack:    seconds later, a quick Claude reply (ack.mjs) that knows what the limits allow and which piece the post is
//           under or quotes, threaded under the post; music it accepts joins the queue (a few acks at once, one at a
//           time per person)
//   build:  one request at a time: compose a score with Claude, check it in the booth, render it there (Live, about
//           a minute), send flagged measurements back once, and reply with the video (likes and acks carry on meanwhile)
// Settings, secrets, state and videos live in MUSIC_BOT_HOME (default ~/_agent_scratch/music-bot); see README.md.
//
//   node bot/main.mjs                 run (config.json "dryRun": true by default: reads Bluesky, never writes to it)
//   node bot/main.mjs --once          one poll, its acks and the build queue, then exit
//   node bot/main.mjs --dry-run       never write to Bluesky, whatever config.json says (replies go to outbox/)
//   node bot/main.mjs --live          write to Bluesky, whatever config.json says
//   node bot/main.mjs --booth URL     another booth (a local fake, say)
//   node bot/main.mjs --check         log in everywhere and report (Bluesky, email confirmed, video limit, booth, Claude)
//   node bot/main.mjs --status        recent requests and today's spend
//   node bot/main.mjs --prompt        print the composer's system prompt (reads the booth's guide only)
//   node bot/main.mjs --retry <id>    put a failed request back in line (the post id from its bsky.app link)
//
// Pause it by creating MUSIC_BOT_HOME/PAUSE (it finishes the acks and the build in hand, then reads and starts nothing
// until the file is gone).

import { appendFileSync, existsSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { Acker } from './ack.mjs';
import { Booth } from './booth.mjs';
import { Brain } from './brain.mjs';
import { Bsky } from './bsky.mjs';
import { HOME, ensureHome, loadConfig, loadSecrets, today } from './config.mjs';
import { beforeLike } from './limits.mjs';
import { acknowledge, afterFailure, failed, handle, like, parentOf } from './pipeline.mjs';
import { composeSchema, composeSystem } from './prompts.mjs';
import { Store } from './store.mjs';

const argv = process.argv.slice(2);
const flag = (k) => argv.includes(`--${k}`);
const arg = (k) => { const i = argv.indexOf(`--${k}`); return i < 0 ? undefined : argv[i + 1]; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const cfg = loadConfig({ ...(arg('booth') ? { boothBase: arg('booth') } : {}), ...(flag('dry-run') ? { dryRun: true } : {}), ...(flag('live') ? { dryRun: false } : {}) });
const home = ensureHome(process.env.MUSIC_BOT_HOME || HOME);
const secrets = loadSecrets();
const store = new Store(join(home, 'bot.db'));

function log(event, data = {}) {
  const line = JSON.stringify({ at: new Date().toISOString(), event, ...data });
  console.log(line);
  try { appendFileSync(join(home, 'bot.log'), line + '\n'); } catch { /* the log is a convenience */ }
}

if (flag('status')) {
  const day = today();
  console.log(`today (${day} UTC): ${store.rendersToday(day)} renders, $${store.spentToday(day).toFixed(2)} spent; ${existsSync(join(home, 'PAUSE')) ? 'PAUSED' : 'running'}; ${cfg.dryRun ? 'dry run' : 'live'}`);
  // strangers wrote the text, handles and titles: no control characters (terminal escapes) reach the owner's terminal
  const safe = (v) => String(v ?? '').replace(/[\u0000-\u001f\u007f-\u009f​-‏‪-‮⁦-⁩]/g, '?');
  for (const r of store.recent(Number(arg('n') ?? 15))) console.log(safe(`${r.day} ${String(r.status).padEnd(10)} @${r.handle} ${r.kind ?? ''}${r.version ? ` v${r.version}` : ''} $${(r.cost ?? 0).toFixed(3)} ${r.title ?? ''} ${r.error ? '! ' + String(r.error).slice(0, 80) : ''}| ${String(r.text).replace(/\s+/g, ' ').slice(0, 70)}`));
  process.exit(0);
}

// --retry <rkey>: a failed request goes back in line (music keeps its brief, kind and saved score; anything else is acked again)
if (arg('retry')) {
  const rkey = arg('retry');
  if (!/^[a-z0-9]{6,20}$/.test(rkey)) { console.error('--retry takes the post id from its bsky.app link'); process.exit(2); }
  const r = store.recent(500).find((x) => x.uri.endsWith(`/app.bsky.feed.post/${rkey}`));
  if (!r) { console.error(`no request with post id ${rkey}`); process.exit(1); }
  const music = (r.decision === 'piece' || r.decision === 'revise') && r.brief;
  store.update(r.uri, music ? { status: 'queued', retry_at: null, error: null, attempts: 0, reply_uri: null } : { status: 'new', decision: null, ack: null, retry_at: null, error: null, ack_attempts: 0 });
  console.log(`@${r.handle}: was ${r.status}, now ${music ? `queued (${r.kind}${r.piece_key ? ', its score is kept' : ''})` : 'waiting for its ack'}`);
  process.exit(0);
}

if (!secrets.BOOTH_TOKEN) { console.error(`No BOOTH_TOKEN in ${join(home, 'secrets.json')}: sudo bot/setup-mac.sh --secrets copies it from the Keychain (zpkt-booth-token)`); process.exit(2); }
const booth = new Booth({ base: cfg.boothBase, token: secrets.BOOTH_TOKEN });
const bsky = new Bsky({
  service: cfg.bskyService, videoService: cfg.videoService, identifier: secrets.BSKY_IDENTIFIER, password: secrets.BSKY_APP_PASSWORD,
  loadSession: () => JSON.parse(store.kvGet('bsky_session') ?? 'null'), saveSession: (s) => store.kvSet('bsky_session', JSON.stringify(s)),
});

if (flag('check')) {
  const report = {};
  try {
    const s = await bsky.login();
    const me = await bsky.getSession();
    report.bluesky = { handle: s.handle, did: s.did, pds: s.pds, email_confirmed: me.emailConfirmed ?? null };
    report.video = await bsky.videoLimits().catch((e) => ({ error: e.message }));
  } catch (e) { report.bluesky = { error: e.message }; }
  report.booth = await booth.status().then((s) => ({ base: cfg.boothBase, open: s.open, reason: s.reason, queue: s.queue, live: s.live })).catch((e) => ({ base: cfg.boothBase, error: e.message }));
  report.claude = secrets.ANTHROPIC_API_KEY ? 'key set' : 'ANTHROPIC_API_KEY missing';
  report.mode = cfg.dryRun ? 'dry run' : 'live';
  console.log(JSON.stringify(report, null, 2));
  process.exit(0);
}

/** The booth's guide, waited for: the booth may be starting up (the LaunchAgent restarts us anyway, but gently). */
async function loadGuide() {
  for (let wait = 5; ; wait = Math.min(300, wait * 2)) {
    try {
      const g = await booth.guide();
      if (!g?.schema) throw new Error('the guide has no schema');
      return g;
    } catch (e) {
      if (flag('prompt') || flag('once')) throw e;
      log('no guide yet', { error: e.message, next_in_s: wait });
      await sleep(wait * 1000);
    }
  }
}

if (flag('prompt')) {
  const guide = await loadGuide();
  const text = composeSystem(guide);
  console.log(text);
  console.error(`${text.length} characters, about ${Math.round(text.length / 3.6)} tokens; schema ${JSON.stringify(composeSchema(guide.schema)).length} characters`);
  process.exit(0);
}

// MUSIC_BOT_BRAIN=./test-brain.mjs: a scripted stand-in for Claude (tests, and trying the bot with no API key); its
// scriptedAcker, if it has one, stands in for the Acker too
const stand = process.env.MUSIC_BOT_BRAIN ? await import(new URL(process.env.MUSIC_BOT_BRAIN, `file://${process.cwd()}/`).href) : null;
const scripted = stand ? stand.default() : null;
const scriptedAck = stand?.scriptedAcker ? stand.scriptedAcker() : null;
if ((!scripted || !scriptedAck) && !secrets.ANTHROPIC_API_KEY) { console.error(`No ANTHROPIC_API_KEY (environment, or ${join(home, 'secrets.json')})`); process.exit(2); }
const brain = scripted ?? new Brain({ apiKey: secrets.ANTHROPIC_API_KEY, model: cfg.model, composeEffort: cfg.composeEffort, cacheTtl: cfg.cacheTtl });
const acker = scriptedAck ?? new Acker({ apiKey: secrets.ANTHROPIC_API_KEY, model: cfg.ackModel, booth, cfg, log });
const guide = await loadGuide();
brain.composeSystem = composeSystem(guide);
brain.schema = composeSchema(guide.schema);
const self = (await bsky.login()).did;
const botHandle = bsky.handle;
log('start', { mode: cfg.dryRun ? 'dry run' : 'live', booth: cfg.boothBase, palette: guide.palette, handle: botHandle, compose_prompt_chars: brain.composeSystem.length, open: cfg.open, poll_seconds: cfg.pollSeconds });

let stopping = false;
const ctx = {
  cfg, store, bsky, booth, brain, acker, log, self, dryRun: cfg.dryRun, renders: join(home, 'renders'),
  stopping: () => stopping,
  outbox(req, record) {
    const file = join(home, 'outbox', `${Date.now()}-${req.uri.split('/').pop()}.json`);
    writeFileSync(file, JSON.stringify({ to: `@${req.handle}`, request: req.text, record }, null, 2));
    log('dry run reply', { uri: req.uri, file, text: record.text });
    return { uri: `dry-run:${file}` };
  },
};

const paused = () => existsSync(join(home, 'PAUSE'));
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => { if (stopping) process.exit(1); stopping = true; wake(); log('stopping after the acks in hand; a build waiting on the booth goes back in the queue'); });

// every like and ack runs as a task of its own; settle() waits for them all (--once, and when stopping)
const tasks = new Set();
const task = (p) => { const t = p.catch((e) => log('task error', { error: e.message })).finally(() => tasks.delete(t)); tasks.add(t); return t; };
async function settle() { while (tasks.size) await Promise.allSettled([...tasks]); }

// ---- intake: new posts for the bot, liked at once ----
// listNotifications is one small authenticated GET (150 every 5 minutes at 2 s, far under Bluesky's limits). It is the
// only feed that lists posts for the bot ready made, with blocks and mutes applied.
const quotedUri = (rec) => rec.embed?.$type === 'app.bsky.embed.recordWithMedia' ? rec.embed.record?.record?.uri : rec.embed?.$type === 'app.bsky.embed.record' ? rec.embed.record?.uri : null;
const mine = (uri) => typeof uri === 'string' && uri.startsWith(`at://${self}/`);
const tags = (rec) => (rec.facets ?? []).some((f) => (f.features ?? []).some((x) => x.$type === 'app.bsky.richtext.facet#mention' && x.did === self)) || (botHandle && String(rec.text ?? '').toLowerCase().includes(`@${botHandle.toLowerCase()}`));

/** Is this notification for the bot to answer? Mentions always; replies under its own posts; quotes of its own posts that also mention it. */
function wanted(n) {
  const rec = n.record ?? {};
  if (n.reason === 'mention') return true;
  if (n.reason === 'reply') return mine(rec.reply?.parent?.uri);
  if (n.reason === 'quote') return mine(quotedUri(rec)) && tags(rec);
  return false;
}

const intaking = new Set(); // liked or reading context: not ready for the ack yet
async function poll() {
  let cursor, pages = 0, stop = false;
  do {
    const page = await bsky.notifications({ cursor, limit: cursor ? 50 : 25 });
    for (const n of page.notifications ?? []) {
      if (!['mention', 'reply', 'quote'].includes(n.reason) || n.author?.did === self) continue;
      if (store.has(n.uri) || Date.now() - Date.parse(n.indexedAt) > cfg.maxAgeHours * 3600_000) { stop = true; continue; }
      if (!wanted(n)) continue;
      const rec = n.record ?? {};
      const alts = (rec.embed?.images ?? rec.embed?.media?.images ?? []).map((i) => i.alt).filter(Boolean);
      const context = alts.length ? alts.map((a) => `[image: ${a.slice(0, 300)}]`).join('\n') : null;
      const { parent_key = null, via = null } = parentOf(rec, store);
      if (!store.add({ uri: n.uri, cid: n.cid, author: n.author.did, handle: n.author.handle, text: String(rec.text ?? '').slice(0, 3000), context, root_uri: rec.reply?.root?.uri ?? null, root_cid: rec.reply?.root?.cid ?? null, created_at: rec.createdAt ?? n.indexedAt, seen_at: Date.now(), day: today(), parent_key, via })) continue;
      const req = store.get(n.uri);
      const g = beforeLike(req, ctx);
      if (g) store.update(req.uri, g);
      log('post', { uri: n.uri, reason: n.reason, handle: n.author.handle, text: String(rec.text ?? '').slice(0, 200), parent_key, via, ...g });
      if (g) continue;
      intaking.add(req.uri);
      // the like and the posts around it (context for the ack) in parallel; the ack waits for both
      task(Promise.all([like(req, ctx), around(req, rec)]).finally(() => { intaking.delete(req.uri); pumpAcks(); }));
    }
    cursor = page.cursor;
  } while (cursor && !stop && ++pages < 5);
}

/** The post it replies to and the post it quotes, as context for the ack. */
async function around(req, rec) {
  const uris = [rec.reply?.parent?.uri, quotedUri(rec)].filter(Boolean);
  if (!uris.length) return;
  const posts = await bsky.getPosts(uris).catch(() => []);
  const lines = posts.filter((p) => p?.record?.text).map((p) => `@${p.author?.handle ?? '?'}: ${p.record.text.slice(0, 600)}`);
  if (lines.length) store.update(req.uri, { context: [...lines, req.context].filter(Boolean).join('\n') });
}

// ---- ack: a few at once, never two for one person (so their per-person limits hold) ----
const acking = new Map(); // uri -> author
function pumpAcks() {
  if (stopping || paused()) return;
  for (const r of store.pendingAcks()) {
    if (acking.size >= cfg.ackConcurrency) break;
    if (acking.has(r.uri) || intaking.has(r.uri) || [...acking.values()].includes(r.author)) continue;
    acking.set(r.uri, r.author);
    // every other ack in flight might be offered music: count them against the day's renders
    task(ackOne(r, acking.size - 1).finally(() => { acking.delete(r.uri); pumpAcks(); }));
  }
}

async function ackOne(r, reserved) {
  await like(r, ctx); // a post stored before a crash is liked here
  try {
    if (await acknowledge(store.get(r.uri), ctx, reserved) === 'queued') wake();
  } catch (e) {
    log('ack failed', { uri: r.uri, handle: r.handle, error: e.message, stack: e.stack?.split('\n').slice(1, 4).join(' | ') });
    afterFailure(r, e, ctx, Date.now(), 'ack');
  }
}

// ---- build: one at a time (the booth has one Live) ----
let wakeUp = null;
function wake() { wakeUp?.(); wakeUp = null; }
const nap = (ms) => new Promise((r) => { wakeUp = r; setTimeout(r, ms); });

async function build(r) {
  try {
    const status = await handle(r, ctx);
    if (status === 'waiting') log('booth closed, waiting', { uri: r.uri, until: new Date(store.get(r.uri).retry_at).toISOString() });
  } catch (e) {
    await failed(r, e, ctx);
  }
}

async function builder() {
  while (!stopping) {
    const r = paused() ? null : store.next();
    if (r) await build(r);
    else {
      const at = store.nextRetryAt();
      await nap(at ? Math.max(250, Math.min(5000, at - Date.now())) : 5000);
    }
  }
}

store.recover();
if (flag('once')) {
  await poll().catch((e) => log('poll error', { error: e.message }));
  pumpAcks();
  await settle();
  for (let r; !stopping && !paused() && (r = store.next());) await build(r);
} else {
  const building = builder();
  let backoff = 0;
  while (!stopping) {
    if (!paused()) {
      try {
        await poll();
        backoff = 0;
      } catch (e) {
        backoff = Math.min(60, Math.max(cfg.pollSeconds, backoff * 2)); // Bluesky down: don't hammer it, don't flood the log
        log('poll error', { error: e.message, next_in_s: backoff });
      }
      pumpAcks(); // also picks up acks whose retry time has come
    }
    const until = Date.now() + Math.max(cfg.pollSeconds, backoff) * 1000;
    while (!stopping && Date.now() < until) await sleep(Math.min(250, until - Date.now()));
  }
  wake();
  await building;
}
await settle();
store.close();
log('stopped');
