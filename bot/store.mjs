// The bot's memory, in node:sqlite. Two tables:
//
// requests: every post it has seen and what became of it. A post is liked as it comes in (like_uri, so a restart
// never likes it twice), then moves new -> acking -> chatted | declined | ignored, or, when the ack accepted music
// (decision piece or revise), queued -> working -> done | declined | failed. A request put back after a passing
// failure (Claude overloaded, the booth closed or down) waits in the queue until its retry_at. `kind` is what the
// music is: piece (new), revise (the next version of parent_key) or remix (a new piece starting from parent_key).
// wait_told and held_told remember that the friend has been told once.
//
// pieces: every version the bot sent to the booth, one row per job: the booth key (`<request uri>#v<version>`, plus
// `+<n>` for a render-side revision; `~<tries>` is added when the booth asked for a retryable failure to be sent
// again), the score JSON, the composer's line and alt text, the parent's key, the job id, its state and measurements, and,
// for the version that was posted, the reply's post uri (post_uri). A friend replying under that post, or quoting
// it, finds the piece through post_uri; a reply elsewhere in the thread finds the thread's latest piece.

import { DatabaseSync } from 'node:sqlite';

const COLUMNS = ['cid', 'author', 'handle', 'text', 'context', 'root_uri', 'root_cid', 'created_at', 'seen_at', 'day', 'status', 'decision', 'note', 'brief', 'kind', 'via', 'parent_key', 'version', 'piece_key', 'title', 'reply_uri', 'reply', 'cost', 'rounds', 'attempts', 'error', 'retry_at', 'updated_at', 'like_uri', 'ack', 'ack_uri', 'ack_at', 'ack_attempts', 'wait_told', 'held_told'];
const PIECE_COLUMNS = ['request_uri', 'author', 'handle', 'day', 'kind', 'version', 'round', 'parent_key', 'score', 'title', 'line', 'alt', 'tries', 'job_id', 'state', 'measure', 'error', 'post_uri', 'root_uri', 'root_cid', 'kept', 'created_at', 'updated_at'];

export class Store {
  constructor(path) {
    this.db = new DatabaseSync(path);
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS requests (
        uri TEXT PRIMARY KEY, cid TEXT, author TEXT, handle TEXT, text TEXT, context TEXT,
        root_uri TEXT, root_cid TEXT, created_at TEXT, seen_at INTEGER, day TEXT,
        status TEXT, decision TEXT, note TEXT, brief TEXT, kind TEXT, via TEXT, parent_key TEXT, version INTEGER,
        piece_key TEXT, title TEXT, reply_uri TEXT, reply TEXT, cost REAL DEFAULT 0, rounds INTEGER DEFAULT 0,
        attempts INTEGER DEFAULT 0, error TEXT, retry_at INTEGER, updated_at INTEGER, like_uri TEXT,
        ack TEXT, ack_uri TEXT, ack_at INTEGER, ack_attempts INTEGER DEFAULT 0, wait_told INTEGER DEFAULT 0, held_told INTEGER DEFAULT 0);
      CREATE INDEX IF NOT EXISTS requests_status ON requests (status, seen_at);
      CREATE INDEX IF NOT EXISTS requests_author ON requests (author, day);
      CREATE TABLE IF NOT EXISTS pieces (
        key TEXT PRIMARY KEY, request_uri TEXT, author TEXT, handle TEXT, day TEXT, kind TEXT, version INTEGER,
        round INTEGER DEFAULT 0, parent_key TEXT, score TEXT, title TEXT, line TEXT, alt TEXT, tries INTEGER DEFAULT 0, job_id TEXT, state TEXT, measure TEXT,
        error TEXT, post_uri TEXT, root_uri TEXT, root_cid TEXT, kept INTEGER DEFAULT 0, created_at INTEGER, updated_at INTEGER);
      CREATE INDEX IF NOT EXISTS pieces_post ON pieces (post_uri);
      CREATE INDEX IF NOT EXISTS pieces_root ON pieces (root_uri, created_at);
      CREATE INDEX IF NOT EXISTS pieces_request ON pieces (request_uri, round);
      CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
    `);
  }

  has(uri) {
    return !!this.db.prepare('SELECT 1 FROM requests WHERE uri = ?').get(uri);
  }

  get(uri) {
    return this.db.prepare('SELECT * FROM requests WHERE uri = ?').get(uri) ?? null;
  }

  add(r) {
    return this.db.prepare('INSERT OR IGNORE INTO requests (uri, cid, author, handle, text, context, root_uri, root_cid, created_at, seen_at, day, status, via, parent_key, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)')
      .run(r.uri, r.cid, r.author, r.handle, r.text, r.context ?? null, r.root_uri ?? null, r.root_cid ?? null, r.created_at, r.seen_at, r.day, r.status ?? 'new', r.via ?? null, r.parent_key ?? null, Date.now()).changes > 0;
  }

  update(uri, fields) {
    const keys = Object.keys(fields).filter((k) => COLUMNS.includes(k));
    if (!keys.length) return;
    this.db.prepare(`UPDATE requests SET ${keys.map((k) => `${k} = ?`).join(', ')}, updated_at = ? WHERE uri = ?`).run(...keys.map((k) => fields[k] ?? null), Date.now(), uri);
  }

  addCost(uri, usd) {
    this.db.prepare('UPDATE requests SET cost = cost + ? WHERE uri = ?').run(usd, uri);
  }

  /** The oldest accepted request waiting its turn (one put back for a retry waits until its time). */
  next(now = Date.now()) {
    return this.db.prepare("SELECT * FROM requests WHERE status = 'queued' AND decision IN ('piece', 'revise') AND (retry_at IS NULL OR retry_at <= ?) ORDER BY seen_at, uri LIMIT 1").get(now) ?? null;
  }

  /** When the next queued request may start (null when none is waiting): the builder naps until then. */
  nextRetryAt() {
    return this.db.prepare("SELECT MIN(COALESCE(retry_at, 0)) AS t FROM requests WHERE status = 'queued' AND decision IN ('piece', 'revise')").get().t ?? null;
  }

  /** Posts waiting for their ack, oldest first (one put back for a retry waits until its time). */
  pendingAcks(now = Date.now(), limit = 20) {
    return this.db.prepare("SELECT * FROM requests WHERE status = 'new' AND (retry_at IS NULL OR retry_at <= ?) ORDER BY seen_at, uri LIMIT ?").all(now, limit);
  }

  /** Requests a crash left half done go back where they were: music to the queue (at most twice, then it fails; its
   * score and booth key are kept, so the same job is asked for again), acks to be acked again. */
  recover() {
    this.db.prepare("UPDATE requests SET status = 'failed', error = 'gave up after a crash' WHERE status = 'working' AND attempts >= 3").run();
    this.db.prepare("UPDATE requests SET status = 'queued' WHERE status = 'working'").run();
    this.db.prepare("UPDATE requests SET status = 'new' WHERE status = 'acking'").run();
  }

  /** This person's recent requests, newest first, for the ack (not counting `except`, the one being acked). */
  history(author, except, limit = 10) {
    return this.db.prepare("SELECT day, status, kind, version, title, text FROM requests WHERE author = ? AND uri != ? AND status != 'skipped' ORDER BY seen_at DESC, uri LIMIT ?").all(author, except ?? '', limit);
  }

  /** Chat replies so far (every chat or decline the ack answered with words): from this person today, and from anyone
   * in the last hour. The Acker's own rate limits read these. */
  chatCounts(author, day, now = Date.now()) {
    const mine = this.db.prepare("SELECT COUNT(*) AS n FROM requests WHERE author = ? AND day = ? AND ack IS NOT NULL AND decision IN ('chat', 'decline')").get(author, day).n;
    const hour = this.db.prepare("SELECT COUNT(*) AS n FROM requests WHERE ack_at >= ? AND ack IS NOT NULL AND decision IN ('chat', 'decline')").get(now - 3600_000).n;
    return { chatRepliesFromAuthorToday: mine, chatRepliesThisHour: hour };
  }

  /** New pieces and remixes this person asked for today that the bot set out to make. */
  piecesFor(author, day) {
    return this.db.prepare("SELECT COUNT(*) AS n FROM requests WHERE author = ? AND day = ? AND decision IN ('piece', 'revise') AND kind IN ('piece', 'remix')").get(author, day).n;
  }

  revisionsFor(author, day) {
    return this.db.prepare("SELECT COUNT(*) AS n FROM requests WHERE author = ? AND day = ? AND decision IN ('piece', 'revise') AND kind = 'revise'").get(author, day).n;
  }

  /** Booth jobs today, render-side revisions included, plus accepted requests not yet sent (each will be at least one). */
  rendersToday(day) {
    const sent = this.db.prepare('SELECT COUNT(*) AS n FROM pieces WHERE day = ?').get(day).n;
    const waiting = this.db.prepare("SELECT COUNT(*) AS n FROM requests WHERE day = ? AND decision IN ('piece', 'revise') AND status IN ('queued', 'working') AND piece_key IS NULL").get(day).n;
    return sent + waiting;
  }

  mentionsFrom(author, day) {
    return this.db.prepare('SELECT COUNT(*) AS n FROM requests WHERE author = ? AND day = ?').get(author, day).n;
  }

  spentToday(day) {
    return this.db.prepare('SELECT COALESCE(SUM(cost), 0) AS usd FROM requests WHERE day = ?').get(day).usd;
  }

  recent(limit = 20) {
    return this.db.prepare('SELECT * FROM requests ORDER BY seen_at DESC, uri LIMIT ?').all(limit);
  }

  // ---- pieces ----

  addPiece(p) {
    const now = Date.now();
    this.db.prepare('INSERT OR IGNORE INTO pieces (key, request_uri, author, handle, day, kind, version, round, parent_key, score, title, line, alt, root_uri, root_cid, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)')
      .run(p.key, p.request_uri, p.author, p.handle, p.day, p.kind, p.version, p.round ?? 0, p.parent_key ?? null, JSON.stringify(p.score), String(p.score?.title ?? '').slice(0, 200) || null, p.line ?? null, p.alt ?? null, p.root_uri ?? null, p.root_cid ?? null, 'composed', now, now);
    return this.piece(p.key);
  }

  updatePiece(key, fields) {
    const keys = Object.keys(fields).filter((k) => PIECE_COLUMNS.includes(k));
    if (!keys.length) return;
    const v = (k) => (k === 'measure' || k === 'score') && fields[k] !== null && typeof fields[k] === 'object' ? JSON.stringify(fields[k]) : fields[k] ?? null;
    this.db.prepare(`UPDATE pieces SET ${keys.map((k) => `${k} = ?`).join(', ')}, updated_at = ? WHERE key = ?`).run(...keys.map(v), Date.now(), key);
  }

  piece(key) {
    return parse(this.db.prepare('SELECT * FROM pieces WHERE key = ?').get(key));
  }

  /** A request's jobs, first render first. */
  piecesOf(uri) {
    return this.db.prepare('SELECT * FROM pieces WHERE request_uri = ? ORDER BY round').all(uri).map(parse);
  }

  /** The posted version a post is (the bot's reply carrying it), or null. */
  pieceByPost(postUri) {
    return parse(this.db.prepare('SELECT * FROM pieces WHERE post_uri = ? AND kept = 1').get(postUri));
  }

  /** The newest posted version in a thread, or null. */
  latestInThread(rootUri) {
    return parse(this.db.prepare('SELECT * FROM pieces WHERE root_uri = ? AND kept = 1 AND post_uri IS NOT NULL ORDER BY created_at DESC, version DESC LIMIT 1').get(rootUri));
  }

  kvGet(k) {
    return this.db.prepare('SELECT v FROM kv WHERE k = ?').get(k)?.v ?? null;
  }

  kvSet(k, v) {
    if (v === null) this.db.prepare('DELETE FROM kv WHERE k = ?').run(k);
    else this.db.prepare('INSERT OR REPLACE INTO kv (k, v) VALUES (?, ?)').run(k, v);
  }

  close() {
    this.db.close();
  }
}

function parse(row) {
  if (!row) return null;
  return { ...row, score: row.score ? JSON.parse(row.score) : null, measure: row.measure ? JSON.parse(row.measure) : null };
}
