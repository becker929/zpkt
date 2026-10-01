/**
 * The one place that talks to the server.
 *
 * Every response passes through a normaliser. The backend is written by a
 * separate effort, so field names may differ in small ways (`items` against
 * `files`, a peaks array against parallel min/max arrays). Normalising here
 * means one file changes if the contract drifts, not every component.
 *
 * All URLs are relative. `next.config.mjs` forwards `/api/*` to the FastAPI
 * server, or lets the local mock handlers answer in mock mode.
 */

import type {
  BulkAction,
  BulkResult,
  FileDetail,
  FilePage,
  FileRow,
  Peaks,
  Query,
  Silence,
  SilenceInterval,
  Span,
  Stats,
  SwipeCarried,
  SwipeQueue,
  TriageCounts,
} from "./types";
import { EMPTY_QUERY, MAX_BULK_HASHES, SPAN_METHOD } from "./types";
import { COLUMNS, PLACEMENTS, isOver, regionSchema, soundSetOpen } from "./project";
import type {
  Abandonment,
  Board,
  BoardColumn,
  Collage,
  Column,
  Commit,
  Placement,
  ProjectSummary,
  Region,
} from "./project";
import { MIN_GAP_S, silentSeconds, skippable, soundingSeconds } from "./silence";

/**
 * Extensions the server re-encodes on the way out. Used only as a fallback for
 * a response that predates the `transcoded` field; the server's own answer
 * wins, because it knows which alias it will actually serve.
 */
const TRANSCODED_EXTS = new Set([".aif", ".aiff"]);

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * A write the server refused, with the server's own words for why.
 *
 * `ApiError` carries a status and a URL, which is what a developer needs. This
 * carries `detail`, which is what the user needs: the sentence the server wrote
 * about its own cap, shown unaltered rather than paraphrased by the client.
 */
export class ApiRefusal extends ApiError {
  constructor(
    readonly detail: string,
    status: number,
    /** Present when a column cap is the reason. */
    readonly cap: { column: string; cap: number; count: number } | null,
  ) {
    super(detail, status);
    this.name = "ApiRefusal";
  }
}

async function getJson(url: string, signal?: AbortSignal, fresh = false): Promise<unknown> {
  const res = await fetch(url, {
    signal,
    // Triage state changes under the user's hands. A cached answer would show a
    // counter that disagrees with the row that was just discarded.
    cache: fresh ? "no-store" : "default",
    headers: { accept: "application/json" },
  });
  if (!res.ok) {
    throw new ApiError(`${res.status} ${res.statusText} for ${url}`, res.status);
  }
  return res.json();
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function num(value: unknown, fallback = 0): number {
  const n = typeof value === "string" ? Number(value) : value;
  return typeof n === "number" && Number.isFinite(n) ? n : fallback;
}

function numOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function str(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function strOrNull(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

/** Pull the first key that exists, so small naming differences do not break the view. */
function pick(row: Record<string, unknown>, ...keys: string[]): unknown {
  for (const key of keys) {
    if (row[key] !== undefined && row[key] !== null) return row[key];
  }
  return undefined;
}

function normaliseRow(raw: unknown): FileRow {
  const row = asRecord(raw);
  const path = str(pick(row, "path", "first_path"));
  const filename =
    str(pick(row, "filename", "name")) || path.split("/").pop() || str(row.hash).slice(0, 12);
  let ext = str(pick(row, "ext", "extension"));
  if (!ext) {
    const dot = filename.lastIndexOf(".");
    ext = dot > 0 ? filename.slice(dot) : "";
  }
  return {
    hash: str(row.hash),
    filename,
    ext: ext.toLowerCase(),
    codec: strOrNull(pick(row, "codec", "format")),
    duration_s: numOrNull(pick(row, "duration_s", "duration")),
    // Absent means unmeasured, and `numOrNull` keeps it absent. Coercing it to
    // zero here would print "0:00" against a five minute sound.
    sounding_s: numOrNull(pick(row, "sounding_s", "sounding_duration_s")),
    size_bytes: num(pick(row, "size_bytes", "size", "bytes")),
    deleted: Boolean(pick(row, "deleted", "soft_deleted", "is_deleted")),
    transcoded:
      row.transcoded === undefined
        ? TRANSCODED_EXTS.has(ext.toLowerCase())
        : Boolean(row.transcoded),
  };
}

function queryString(query: Query, limit: number, offset: number): string {
  const params = new URLSearchParams();
  if (query.q.trim()) params.set("q", query.q.trim());
  if (query.ext) params.set("ext", query.ext);
  if (query.min_dur.trim()) params.set("min_dur", query.min_dur.trim());
  if (query.max_dur.trim()) params.set("max_dur", query.max_dur.trim());
  // `false` is the server's default. Sending it anyway would make every cache
  // key differ from the one a link without the parameter produces.
  if (query.deleted && query.deleted !== "false") params.set("deleted", query.deleted);
  params.set("sort", query.sort);
  params.set("order", query.order);
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  return params.toString();
}

/** The list view's key for SWR, and the URL it fetches. */
export function filesUrl(query: Query, limit: number, offset: number): string {
  return `/api/files?${queryString(query, limit, offset)}`;
}

/**
 * Whether the server has refused `sort=sounding`.
 *
 * Sorting by sounding length is part of the same change as the silence route,
 * and a server that has one without the other rejects the parameter outright.
 * Rather than showing an error page for a sort order, fall back to wall
 * duration, which is the nearest thing the server can do, and stop sending it.
 */
let soundingSortMissing = false;

function withoutSoundingSort(url: string): string {
  return url.replace(/([?&]sort=)sounding(\b|$)/, "$1duration");
}

export async function fetchFiles(url: string, signal?: AbortSignal): Promise<FilePage> {
  const target = soundingSortMissing ? withoutSoundingSort(url) : url;
  // Not from the cache: a page fetched again after a discard is being fetched
  // again precisely because the set behind it changed.
  let raw: unknown;
  try {
    raw = await getJson(target, signal, true);
  } catch (err) {
    const refusedSort =
      err instanceof ApiError &&
      (err.status === 422 || err.status === 400) &&
      target.includes("sort=sounding");
    if (!refusedSort) throw err;
    soundingSortMissing = true;
    raw = await getJson(withoutSoundingSort(target), signal, true);
  }
  const body = asRecord(raw);
  const rawItems = pick(body, "items", "files", "results", "rows");
  const items = Array.isArray(rawItems) ? rawItems.map(normaliseRow) : [];
  return {
    items,
    total: num(pick(body, "total", "count", "total_count"), items.length),
    limit: num(pick(body, "limit", "page_size"), items.length),
    offset: num(pick(body, "offset", "skip"), 0),
  };
}

/**
 * One sound.
 *
 * The aliases the server sends are read past. A path is a name for a hash and
 * nothing more; content addressing made the list of them correct rather than
 * interesting, and a detail view full of paths is a detail view that says
 * nothing about the sound.
 */
export async function fetchDetail(hash: string, signal?: AbortSignal): Promise<FileDetail> {
  const body = asRecord(await getJson(`/api/files/${hash}`, signal));
  const base = normaliseRow(body);
  const rawTags = pick(body, "tags");
  return {
    ...base,
    hash: base.hash || hash,
    sample_rate: numOrNull(pick(body, "sample_rate", "samplerate")),
    channels: numOrNull(body.channels),
    tags: Array.isArray(rawTags) ? rawTags.map((t) => str(typeof t === "string" ? t : asRecord(t).name)) : [],
  };
}

/**
 * Peaks are never derived from the audio itself. Files here run to hundreds of
 * megabytes; decoding one in the browser stalls the tab.
 */
export async function fetchPeaks(hash: string, signal?: AbortSignal): Promise<Peaks> {
  const url = `/api/files/${hash}/peaks`;
  const res = await fetch(url, { signal });
  if (!res.ok) throw new ApiError(`${res.status} ${res.statusText} for ${url}`, res.status);

  // The server stores peaks as packed int8 pairs. If it hands them back as
  // bytes rather than JSON, unpack them here.
  const contentType = res.headers.get("content-type") ?? "";
  if (!contentType.includes("json")) {
    const buffer = await res.arrayBuffer();
    return { hash, buckets: Math.floor(buffer.byteLength / 2), pairs: pairsFromInt8(new Int8Array(buffer)) };
  }
  return normalisePeaks(hash, await res.json());
}

function pairsFromInt8(values: Int8Array): Array<[number, number]> {
  const pairs: Array<[number, number]> = [];
  for (let i = 0; i + 1 < values.length; i += 2) pairs.push([values[i], values[i + 1]]);
  return pairs;
}

/** Decode a base64 string of packed int8 pairs. */
function pairsFromBase64(text: string): Array<[number, number]> {
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return pairsFromInt8(new Int8Array(bytes.buffer));
}

export function normalisePeaks(hash: string, body: unknown): Peaks {
  const pairs: Array<[number, number]> = [];

  // A bare array: either pairs, or a flat min,max,min,max stream.
  const root = Array.isArray(body) ? body : pick(asRecord(body), "peaks", "data", "pairs", "values");

  // Packed int8 pairs sent as base64 inside JSON.
  if (typeof root === "string") {
    const record = asRecord(body);
    const decoded = pairsFromBase64(root);
    return { hash: str(record.hash, hash) || hash, buckets: decoded.length, pairs: decoded };
  }

  if (Array.isArray(root)) {
    if (root.length > 0 && Array.isArray(root[0])) {
      for (const item of root as unknown[]) {
        const pair = item as unknown[];
        pairs.push([num(pair[0]), num(pair[1])]);
      }
    } else {
      const flat = root as unknown[];
      for (let i = 0; i + 1 < flat.length; i += 2) {
        pairs.push([num(flat[i]), num(flat[i + 1])]);
      }
    }
  } else {
    // Parallel arrays.
    const record = asRecord(body);
    const mins = pick(record, "min", "mins", "minima");
    const maxs = pick(record, "max", "maxs", "maxima");
    if (Array.isArray(mins) && Array.isArray(maxs)) {
      const n = Math.min(mins.length, maxs.length);
      for (let i = 0; i < n; i += 1) pairs.push([num(mins[i]), num(maxs[i])]);
    }
  }

  const record = asRecord(body);
  return {
    hash: str(record.hash, hash) || hash,
    buckets: num(pick(record, "buckets", "bucket_count"), pairs.length),
    pairs,
  };
}

/** The audio element's source. Hash only; the server resolves it to a path. */
export function streamUrl(hash: string): string {
  return `/api/files/${hash}/stream`;
}

/** A write. Returns the parsed body, or `{}` for a route that answers empty. */
async function send(url: string, method: string, body?: unknown): Promise<Record<string, unknown>> {
  const res = await fetch(url, {
    method,
    headers: body === undefined
      ? { accept: "application/json" }
      : { accept: "application/json", "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError(`${method} ${url} answered ${res.status}`, res.status);
  const text = await res.text();
  if (!text) return {};
  try {
    return asRecord(JSON.parse(text));
  } catch {
    return {};
  }
}

export async function fetchStats(signal?: AbortSignal): Promise<Stats> {
  const body = asRecord(await getJson("/api/stats", signal));
  return {
    files: num(pick(body, "files", "blobs", "unique_files", "file_count")),
    // Bytes actually occupied on disk, which counts every copy.
    total_bytes: num(pick(body, "physical_bytes", "total_bytes", "total_size", "logical_bytes", "size_bytes")),
    total_duration_s: numOrNull(pick(body, "total_duration_s", "duration_s")),
    total_sounding_s: numOrNull(pick(body, "total_sounding_s", "sounding_duration_s", "sounding_s")),
  };
}

/**
 * The spans one classifier found, tinted over the waveform.
 *
 * A method is always named. Every classifier writes into the same table, so
 * asking for all of them at once tints the same second three times over and
 * says nothing about any of them. The default is `SPAN_METHOD`.
 *
 * A missing route is not an error: the waveform simply has no tint.
 */
let spansRouteMissing = false;

/**
 * Spans out of any answer that carries them.
 *
 * Written apart from the route because two answers carry the same list: the
 * spans route, and `GET /api/swipe`, which sends them with the sound so a
 * phone does not ask twice. One normaliser means the swipe view and the detail
 * view read identical spans.
 */
export function normaliseSpans(body: unknown): Span[] {
  const raw = Array.isArray(body) ? body : pick(asRecord(body), "spans", "items");
  if (!Array.isArray(raw)) return [];
  return raw.map((entry) => {
    const row = asRecord(entry);
    return {
      start_s: num(pick(row, "start_s", "start")),
      end_s: num(pick(row, "end_s", "end")),
      label: str(row.label, "other"),
      confidence: numOrNull(row.confidence),
      detail: strOrNull(row.detail),
      method: strOrNull(row.method),
    };
  });
}

export async function fetchSpans(
  hash: string,
  method: string = SPAN_METHOD,
  signal?: AbortSignal,
): Promise<Span[]> {
  if (spansRouteMissing) return [];
  const suffix = `?method=${encodeURIComponent(method)}`;
  try {
    return normaliseSpans(await getJson(`/api/files/${hash}/spans${suffix}`, signal));
  } catch (err) {
    // Before stage 3 the route does not exist. Note that once, then stop
    // asking, so every detail view does not log a 404.
    if (err instanceof ApiError && err.status === 404) {
      spansRouteMissing = true;
      return [];
    }
    throw err;
  }
}

/* Silence ----------------------------------------------------------------- */

/**
 * Whether `/api/files/{hash}/silence` is serving.
 *
 * A 404 means one of two things: the route does not exist yet, or this sound
 * has never been measured. The two are told apart by history. Once any hash
 * has answered, the route plainly exists, so later 404s are unmeasured sounds
 * and asking again for the next one is right. Before that, one 404 is enough
 * to stop asking, so a detail view does not log a 404 per sound.
 */
let silenceRouteMissing = false;
let silenceRouteAnswered = false;

function normaliseInterval(raw: unknown): SilenceInterval | null {
  if (Array.isArray(raw)) {
    const start = num(raw[0], NaN);
    const end = num(raw[1], NaN);
    return Number.isFinite(start) && Number.isFinite(end) ? { start_s: start, end_s: end } : null;
  }
  const row = asRecord(raw);
  const start = numOrNull(pick(row, "start_s", "start", "from"));
  const end = numOrNull(pick(row, "end_s", "end", "to"));
  return start === null || end === null ? null : { start_s: start, end_s: end };
}

/**
 * A silence report out of any answer that carries one.
 *
 * Written apart from the route because two answers carry the same report: the
 * silence route, and `GET /api/swipe`, which sends it with the sound. One
 * normaliser means the swipe view skips exactly what the detail view skips.
 */
export function normaliseSilence(
  hash: string,
  raw: unknown,
  minGap: number = MIN_GAP_S,
): Silence {
  const body = asRecord(raw);
  const rawIntervals = pick(body, "intervals", "items", "silence", "regions");
  const intervals = Array.isArray(rawIntervals)
    ? rawIntervals
        .map(normaliseInterval)
        .filter((interval): interval is SilenceInterval => interval !== null)
    : [];

  const durationS = numOrNull(pick(body, "duration_s", "duration"));
  // The server's own floor may differ from the one asked for, so apply the
  // asked-for floor again here. Filtering an already-filtered list is a
  // no-op; filtering an unfiltered one is the point.
  const gaps = skippable(intervals, minGap, durationS);
  const measured =
    body.measured === undefined
      ? pick(body, "sounding_s", "silent_s", "duration_s", "measured_at") !== undefined
      : Boolean(body.measured);

  return {
    hash: str(body.hash, hash) || hash,
    measured,
    min_gap: num(pick(body, "min_gap", "min_gap_s"), minGap),
    duration_s: durationS,
    sounding_s: numOrNull(pick(body, "sounding_s")) ?? soundingSeconds(durationS, gaps, minGap),
    silent_s: numOrNull(pick(body, "silent_s")) ?? silentSeconds(gaps),
    intervals,
  };
}

/**
 * One sound's dead air, or null when there is nothing measured to say.
 *
 * Null is the honest answer for an unmeasured sound. The caller shows wall
 * duration and does not skip, rather than inventing a sounding length.
 */
export async function fetchSilence(
  hash: string,
  minGap: number = MIN_GAP_S,
  signal?: AbortSignal,
): Promise<Silence | null> {
  if (silenceRouteMissing) return null;
  try {
    const body = await getJson(`/api/files/${hash}/silence?min_gap=${minGap}`, signal);
    silenceRouteAnswered = true;
    return normaliseSilence(hash, body, minGap);
  } catch (err) {
    if (err instanceof ApiError && (err.status === 404 || err.status === 405 || err.status === 501)) {
      if (!silenceRouteAnswered) silenceRouteMissing = true;
      return null;
    }
    throw err;
  }
}

/* Triage ------------------------------------------------------------------ */

/**
 * Discard a sound, or put it back.
 *
 * Soft delete attaches to the hash and hides the sound from the default view.
 * It removes nothing from disk: no route in this application can. Every path
 * that held the bytes still holds them, and restore is the exact inverse.
 */
export async function setDeleted(hash: string, deleted: boolean): Promise<void> {
  await send(`/api/files/${hash}/deleted`, deleted ? "PUT" : "DELETE");
}

/**
 * One action over many hashes, applied in a single transaction.
 *
 * The cap is the server's. Sending more would be refused whole, so the batch
 * is cut here instead, where the interface can say what it did.
 */
export async function bulk(hashes: string[], action: BulkAction): Promise<BulkResult> {
  const capped = hashes.slice(0, MAX_BULK_HASHES);
  const body = await send("/api/bulk", "POST", { hashes: capped, action });
  return {
    action: (str(body.action, action) as BulkAction) || action,
    requested: num(body.requested, capped.length),
    unique: num(body.unique, capped.length),
    matched: num(body.matched, capped.length),
    changed: num(body.changed, capped.length),
    unchanged: num(body.unchanged),
    skipped: num(body.skipped),
  };
}

/**
 * The progress counter: how much of the collection has been answered.
 *
 * A missing route answers null, which is not an error worth showing: the
 * header simply has no counter. The same shape of fallback as `fetchSpans`.
 *
 * The split between taken and discarded is null when the server does not
 * report it. A zero would read as "nothing was taken", which is a claim this
 * is not entitled to make.
 */
export async function fetchTriage(signal?: AbortSignal): Promise<TriageCounts | null> {
  try {
    const body = asRecord(await getJson("/api/triage", signal, true));
    const total = num(pick(body, "total", "blobs", "files"));
    const decided = num(pick(body, "decided", "triaged"));
    const taken = pick(body, "taken", "in_projects", "projected");
    const discarded = pick(body, "discarded", "deleted");
    return {
      total,
      decided,
      undecided: num(pick(body, "undecided", "untriaged"), Math.max(total - decided, 0)),
      percent: num(body.percent, total > 0 ? (decided / total) * 100 : 0),
      taken: taken === undefined ? null : num(taken),
      discarded: discarded === undefined ? null : num(discarded),
    };
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

/* Projects and the board --------------------------------------------------- */

/**
 * Statuses that mean "this route is not being served", as opposed to "this
 * route answered and said no".
 *
 * The project routes are written by a separate effort and do not exist yet. A
 * missing route is not an error to show as a failure, but it is also not an
 * empty board: the interface has to be able to tell "nothing here" apart from
 * "nothing known", and it says so rather than drawing zeroes.
 */
const ABSENT = new Set([404, 405, 501, 502, 503, 504]);

function absent(err: unknown): boolean {
  return err instanceof ApiError && ABSENT.has(err.status);
}

/** A write to a project route, with the refusal body read back out. */
async function sendProject(url: string, method: string, body?: unknown): Promise<Record<string, unknown>> {
  const res = await fetch(url, {
    method,
    headers:
      body === undefined
        ? { accept: "application/json" }
        : { accept: "application/json", "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  const text = await res.text();
  let parsed: Record<string, unknown> = {};
  if (text) {
    try {
      parsed = asRecord(JSON.parse(text));
    } catch {
      parsed = {};
    }
  }

  if (!res.ok) {
    const detail = str(parsed.detail) || `${method} ${url} answered ${res.status}`;
    const cap =
      typeof parsed.cap === "number" && typeof parsed.column === "string"
        ? { column: parsed.column, cap: parsed.cap, count: num(parsed.count) }
        : null;
    throw new ApiRefusal(detail, res.status, cap);
  }
  return parsed;
}

/**
 * The abandonment on a row, or null when the project is on the board.
 *
 * A row that says it was abandoned but cannot say out of which column is read
 * as abandoned all the same, and `from` falls back to the row's own column.
 * Abandoned is the claim that matters here — it is what the caps must not count
 * — and dropping it because one field is missing would put an off-board project
 * back in a column.
 */
function normaliseAbandonment(raw: unknown, column: string): Abandonment | null {
  if (raw === null || raw === undefined || raw === false) return null;
  const row = asRecord(raw);
  const from = str(row.from);
  const fallback = (COLUMNS as readonly string[]).includes(column) ? (column as Column) : "stored";
  return {
    at: str(row.at),
    from: (COLUMNS as readonly string[]).includes(from) ? (from as Column) : fallback,
    reason: str(row.reason),
  };
}

/**
 * One project row, or null when the row cannot be trusted.
 *
 * Null is returned rather than a patched-up object. A row whose `column` is not
 * a column cannot be drawn in a column, and guessing one would put a project
 * somewhere it is not. The caller counts these as unreadable, which is exactly
 * what they are.
 */
function normaliseProjectSummary(raw: unknown): ProjectSummary | null {
  const row = asRecord(raw);
  const id = str(row.id);
  const column = str(row.column);
  if (!id || !(PLACEMENTS as readonly string[]).includes(column)) return null;

  const rawCommits = Array.isArray(row.commits) ? row.commits : [];
  const commits: Commit[] = [];
  for (const entry of rawCommits) {
    const commit = asRecord(entry);
    const at = str(commit.at);
    const digest = str(commit.digest);
    const stage = str(commit.column);
    if (!(COLUMNS as readonly string[]).includes(stage) || !at || !digest) continue;
    commits.push({ column: stage as Column, at, digest });
  }

  const verified = row.sound_set_verified;
  return {
    id,
    name: str(row.name) || id,
    column: column as Placement,
    created_at: str(row.created_at),
    updated_at: str(row.updated_at),
    abandoned: normaliseAbandonment(row.abandoned, column),
    commits,
    sound_count: num(pick(row, "sound_count", "sounds", "count")),
    duration_s: numOrNull(pick(row, "duration_s", "duration")),
    sounding_s: numOrNull(row.sounding_s),
    size_bytes: numOrNull(pick(row, "size_bytes", "size")),
    // Absent means the server did not check. That is not the same as "checked
    // and wrong", and the card must not show a tamper warning for it.
    sound_set_verified: typeof verified === "boolean" ? verified : null,
  };
}

/** A project file that could not be read, and the reason. */
export interface UnreadableProject {
  id: string;
  problem: string;
}

export interface ProjectIndex {
  items: ProjectSummary[];
  unreadable: UnreadableProject[];
}

/**
 * Every project.
 *
 * Null means the route is not being served. The caller says so; it does not
 * draw an empty board, because an empty board and an absent one look the same
 * and mean opposite things.
 */
export async function fetchProjects(signal?: AbortSignal): Promise<ProjectIndex | null> {
  try {
    const body = asRecord(await getJson("/api/projects", signal, true));
    const rawItems = Array.isArray(body) ? body : pick(body, "items", "projects");
    const items: ProjectSummary[] = [];
    const unreadable: UnreadableProject[] = [];

    if (Array.isArray(rawItems)) {
      for (const raw of rawItems) {
        const summary = normaliseProjectSummary(raw);
        if (summary) items.push(summary);
        else {
          const row = asRecord(raw);
          unreadable.push({
            id: str(row.id) || "(no id)",
            problem: "the index sent a row this interface cannot place in a column",
          });
        }
      }
    }

    const rawUnreadable = pick(body, "unreadable", "invalid");
    if (Array.isArray(rawUnreadable)) {
      for (const raw of rawUnreadable) {
        const row = asRecord(raw);
        unreadable.push({
          id: str(row.id) || "(no id)",
          problem: str(pick(row, "problem", "detail", "error"), "does not match the project schema"),
        });
      }
    }

    return { items, unreadable };
  } catch (err) {
    if (absent(err)) return null;
    throw err;
  }
}

/** One project's document and its members as list rows. */
export interface ProjectDetail {
  id: string;
  valid: boolean;
  issues: string[];
  summary: ProjectSummary | null;
  items: FileRow[];
  document: unknown;
  /**
   * The arrangement, or null when nothing has been stamped.
   *
   * Read from the document, or from a `collage` key beside it, and passed
   * through the model. A region the model rejects is dropped rather than
   * drawn: a box the interface cannot describe is a box it cannot play.
   */
  collage: Collage | null;
}

/**
 * The collage out of any answer that carries one.
 *
 * Two answers do: `GET /api/projects/{id}`, inside the document, and
 * `PUT /api/projects/{id}/collage`, which echoes what it wrote. One reader for
 * both, so what the view draws after a save is what it draws after a reload.
 */
export function normaliseCollage(raw: unknown): Collage | null {
  if (raw === null || raw === undefined) return null;
  const record = asRecord(raw);
  const rawRegions = pick(record, "regions", "items");
  if (!Array.isArray(rawRegions)) return null;
  const regions: Region[] = [];
  for (const entry of rawRegions) {
    const parsed = regionSchema.safeParse(entry);
    if (parsed.success) regions.push(parsed.data);
  }
  return { regions };
}

export async function fetchProject(id: string, signal?: AbortSignal): Promise<ProjectDetail | null> {
  try {
    const body = asRecord(await getJson(`/api/projects/${encodeURIComponent(id)}`, signal, true));
    const rawItems = pick(body, "items", "members", "files");
    const rawIssues = Array.isArray(body.issues) ? body.issues : [];
    const document = body.document ?? null;
    return {
      id: str(body.id, id) || id,
      valid: body.valid !== false,
      issues: rawIssues.map((issue) => {
        const row = asRecord(issue);
        const path = str(row.path);
        const message = str(row.message, typeof issue === "string" ? issue : "");
        return path ? `${path}: ${message}` : message;
      }),
      summary: normaliseProjectSummary(pick(body, "summary") ?? body),
      items: Array.isArray(rawItems) ? rawItems.map(normaliseRow) : [],
      document,
      collage: normaliseCollage(pick(body, "collage") ?? asRecord(document).collage),
    };
  } catch (err) {
    if (absent(err)) return null;
    throw err;
  }
}

/* The collage --------------------------------------------------------------- */

/**
 * Whether `PUT /api/projects/{id}/collage` is being served.
 *
 * The route is written by a separate effort. Once it has answered "not here"
 * the view stops sending and says so, rather than logging a 404 per stamp;
 * what was stamped stays on screen and can still be heard.
 */
let collageRouteMissing = false;

export function collageRouteIsMissing(): boolean {
  return collageRouteMissing;
}

/**
 * Write the whole arrangement. Replace, never merge.
 *
 * The description is small — tens of regions — and sending all of it every
 * time means the file on disk is always exactly what is on screen, with no
 * ordering of partial writes to get wrong. Throws `ApiRefusal` when the server
 * rejects a region, with its own words for why. Returns null when the route
 * is not being served.
 */
export async function putCollage(id: string, regions: readonly Region[]): Promise<Collage | null> {
  if (collageRouteMissing) return null;
  try {
    const body = await sendProject(`/api/projects/${encodeURIComponent(id)}/collage`, "PUT", {
      regions,
    });
    return normaliseCollage(pick(body, "collage") ?? body) ?? { regions: [...regions] };
  } catch (err) {
    if (absent(err)) {
      collageRouteMissing = true;
      return null;
    }
    throw err;
  }
}

/**
 * A bounded WAV of one stretch of a source, for the collage to play.
 *
 * The whole file is never sent: sources run to hundreds of megabytes and a
 * region is seconds of one. The server slices and resamples; the client
 * decodes exactly this much and no more.
 */
export function sliceUrl(hash: string, startS: number, endS: number): string {
  const params = new URLSearchParams({ start: String(startS), end: String(endS) });
  return `/api/files/${hash}/slice?${params.toString()}`;
}

/**
 * The board, or null when `/api/board` is not being served.
 *
 * The caps drawn on screen, and the encumbrance threshold projects are marked
 * against, are always the ones in this answer. The client has defaults in
 * `lib/boardConfig.ts`, but those are the mock server's values and the ones
 * recorded in the generated schemas; drawing them here would let the interface
 * show a column as fine while the server refused writes to it, or mark a
 * project the server does not.
 */
export async function fetchBoard(signal?: AbortSignal): Promise<Board | null> {
  try {
    const body = asRecord(await getJson("/api/board", signal, true));
    const rawColumns = pick(body, "columns", "items");
    if (!Array.isArray(rawColumns)) return null;

    const columns: BoardColumn[] = [];
    for (const raw of rawColumns) {
      const row = asRecord(raw);
      const column = str(row.column);
      const cap = numOrNull(row.cap);
      // Zero is a cap, not a missing one: it is how a column says it is closed.
      // Refusing to draw it would hide the tightest setting there is, and the
      // column would read as uncapped while the server refused every write to it.
      if (!(COLUMNS as readonly string[]).includes(column) || cap === null || cap < 0) continue;
      const count = num(row.count);
      columns.push({
        column: column as Column,
        cap,
        count,
        unreadable: num(row.unreadable),
        // The server's reading of its own cap wins. The fallback is only for a
        // server that reports occupancy without saying whether it is over.
        over: typeof row.over === "boolean" ? row.over : isOver(count, cap),
      });
    }
    // A server that serves fewer columns than the model knows about is serving
    // a real board, not a broken one: `enrich` has no view yet and is not a
    // column there. Drawing the two it does report is honest; drawing nothing
    // because a third is missing would hide a board that works. An answer with
    // no readable column at all is a different thing and is treated as absent.
    if (columns.length === 0) return null;

    return {
      columns,
      // The server's threshold, or null when it does not report one. It is not
      // defaulted here: the client having its own number is the thing this
      // field exists to stop.
      encumbrance: numOrNull(body.encumbrance),
      released: num(body.released),
      abandoned: num(body.abandoned),
      unreadable: num(body.unreadable),
    };
  } catch (err) {
    if (absent(err)) return null;
    throw err;
  }
}

/** Create a project in `stored`. Throws `ApiRefusal` when the cap is in the way. */
export async function createProject(name: string, override = false): Promise<ProjectSummary | null> {
  const body = await sendProject("/api/projects", "POST", { name, ...(override ? { override: true } : {}) });
  return normaliseProjectSummary(body);
}

export async function patchProject(
  id: string,
  patch: { name?: string; notes?: string },
): Promise<ProjectSummary | null> {
  return normaliseProjectSummary(await sendProject(`/api/projects/${encodeURIComponent(id)}`, "PATCH", patch));
}

export interface CommitResult {
  summary: ProjectSummary | null;
  commit: Commit | null;
  /** False while the committing column has no view yet and so no real artifact. */
  artifact_real: boolean;
}

/**
 * Freeze this column's artifact and advance.
 *
 * Throws `ApiRefusal`. A 409 carrying `cap` is the downstream column being
 * full, which the caller may retry with `override`. A 422 is not overridable
 * and the caller must say why rather than offering a way through.
 *
 * `expectColumn` is the stage the caller believes it is freezing. Commit is a
 * boundary and each boundary freezes a different artifact, so a request has to
 * name which one it means. Without it a second tab, or a retry after a timeout,
 * presses "freeze the sound set" and freezes the arrangement instead: a stage
 * nobody worked, one-way, with a digest of nothing. The server refuses when the
 * project has already left that stage, and that refusal is not overridable.
 */
export async function commitProject(
  id: string,
  override = false,
  expectColumn?: Column,
): Promise<CommitResult> {
  const body = await sendProject(
    `/api/projects/${encodeURIComponent(id)}/commit`,
    "POST",
    {
      ...(override ? { override: true } : {}),
      ...(expectColumn ? { expect_column: expectColumn } : {}),
    },
  );
  const rawCommit = asRecord(body.commit);
  const stage = str(rawCommit.column);
  return {
    summary: normaliseProjectSummary(pick(body, "summary") ?? body),
    commit: (COLUMNS as readonly string[]).includes(stage)
      ? { column: stage as Column, at: str(rawCommit.at), digest: str(rawCommit.digest) }
      : null,
    artifact_real: body.artifact_real !== false,
  };
}

/**
 * Leave the board without promoting anything.
 *
 * Nothing is frozen, nothing is appended to the chain, and the slot comes back
 * at once. There is no cap in the way of letting something go, so this takes no
 * override: the whole point of it is that commit must not be the only exit, or
 * a project nobody believes in holds its slot until somebody commits something
 * they do not want.
 */
export async function abandonProject(id: string, reason = ""): Promise<ProjectSummary | null> {
  return normaliseProjectSummary(
    await sendProject(`/api/projects/${encodeURIComponent(id)}/abandon`, "POST", { reason }),
  );
}

/**
 * Bring an abandoned project back to the column it left.
 *
 * It takes a slot like anything else, so a full column refuses it with the same
 * 409 and the same override as every other cap refusal. Every commit it had
 * comes back with it.
 */
export async function reviveProject(id: string, override = false): Promise<ProjectSummary | null> {
  return normaliseProjectSummary(
    await sendProject(
      `/api/projects/${encodeURIComponent(id)}/revive`,
      "POST",
      override ? { override: true } : {},
    ),
  );
}

/** Add or remove one sound. Throws `ApiRefusal` with a 409 once frozen. */
export async function setProjectSound(id: string, hash: string, member: boolean): Promise<void> {
  await sendProject(
    `/api/projects/${encodeURIComponent(id)}/sounds/${hash}`,
    member ? "PUT" : "DELETE",
  );
}

export interface ProjectAddResult {
  added: number;
  /** Already in the project, so nothing changed. */
  already: number;
  /** The project stopped accepting sounds part way through. */
  stopped: string | null;
}

/**
 * Put a selection into a project, one route call per hash.
 *
 * There is no bulk route for project membership and this does not invent one:
 * it sends the calls the specification has, a few at a time. Anything the
 * server refuses stops the run immediately and is reported, because the two
 * refusals that matter — the set was frozen in another tab, the project is
 * full — both mean every remaining call would fail the same way. The caller is
 * told how many went in before the stop rather than being told it all worked.
 */
export async function addSoundsToProject(id: string, hashes: string[]): Promise<ProjectAddResult> {
  const capped = hashes.slice(0, MAX_BULK_HASHES);

  // Read the membership once, so the sounds already in the project are not sent
  // at all. The route is idempotent, so sending them would be harmless but
  // would also make the report wrong: every call succeeds, and "added 40" would
  // be printed over a project that gained three.
  let existing = new Set<string>();
  const detail = await fetchProject(id).catch(() => null);
  if (detail) existing = new Set(detail.items.map((row) => row.hash));

  const wanted = capped.filter((hash) => !existing.has(hash));
  const already = capped.length - wanted.length;
  let added = 0;
  let stopped: string | null = null;

  const CONCURRENCY = 6;
  for (let i = 0; i < wanted.length && stopped === null; i += CONCURRENCY) {
    const settled = await Promise.allSettled(
      wanted.slice(i, i + CONCURRENCY).map((hash) => setProjectSound(id, hash, true)),
    );
    for (const outcome of settled) {
      if (outcome.status === "fulfilled") {
        added += 1;
        continue;
      }
      // The two refusals that matter here — the set was frozen in another tab,
      // and the project is full — both mean every remaining call fails the same
      // way. Stop, and report how many went in before the stop.
      const err = outcome.reason;
      stopped = err instanceof ApiRefusal ? err.detail : String(err);
    }
  }

  return { added, already, stopped };
}

/* The swipe queue ---------------------------------------------------------- */

/**
 * Whether `GET /api/swipe` is being served.
 *
 * One absence is enough to stop asking. The derived queue below is the same
 * set worked out from routes that do exist, so nothing is lost by falling back
 * once and staying there for the life of the tab.
 */
let swipeRouteMissing = false;

/** How the queue is read, so a test or a reader can tell the two apart. */
export function swipeRouteIsMissing(): boolean {
  return swipeRouteMissing;
}

/**
 * The sounds in a queue answer, however the server chose to shape it.
 *
 * Two shapes are in use. A batch arrives under `items`; a server that hands
 * over one sound at a time puts it under `sound`. Both are read, because the
 * view consumes the queue one sound at a time either way and the difference is
 * only how often it has to ask.
 */
function normaliseQueueItems(body: unknown): FileRow[] {
  const record = asRecord(body);
  const raw = Array.isArray(body) ? body : pick(record, "items", "files", "results", "queue");
  if (Array.isArray(raw)) return raw.map(normaliseRow).filter((row) => row.hash !== "");
  const single = pick(record, "sound", "item", "next");
  if (single === undefined || single === null) return [];
  const row = normaliseRow(single);
  return row.hash === "" ? [] : [row];
}

/**
 * What the answer carried about the sound at the head of it.
 *
 * The route sends the sound's silence and its spans alongside the sound, so a
 * phone spends one round trip on a sound rather than three. A field the answer
 * did not carry stays null and the view fetches it the long way; nothing here
 * invents a measurement.
 */
function carriedWith(head: FileRow | null, record: Record<string, unknown>): SwipeCarried | null {
  if (!head) return null;
  const rawSilence = pick(record, "silence");
  const rawSpans = pick(record, "spans");
  if (rawSilence === undefined && rawSpans === undefined) return null;
  return {
    hash: head.hash,
    silence: rawSilence === undefined ? null : normaliseSilence(head.hash, rawSilence, MIN_GAP_S),
    spans: rawSpans === undefined ? null : normaliseSpans(rawSpans),
  };
}

/**
 * The next undecided sounds, and how many are left.
 *
 * Undecided means the sound has neither been taken into a project nor
 * discarded. There is no third state to be in, because there is no third
 * action.
 *
 * Two ways to get it, and the answer says which was used. `GET /api/swipe` is
 * the route that answers it directly. When that route is not being served, the
 * same queue is worked out here: every undiscarded sound, less the hashes that
 * are already in a project. Both are real. Neither invents a count — when
 * nothing can be read at all this returns null and the view says so.
 */
export async function fetchSwipeQueue(limit = 24, signal?: AbortSignal): Promise<SwipeQueue | null> {
  if (!swipeRouteMissing) {
    try {
      const body = await getJson(`/api/swipe?limit=${limit}`, signal, true);
      const items = normaliseQueueItems(body);
      const record = asRecord(body);
      return {
        items,
        remaining: num(pick(record, "remaining", "undecided", "total"), items.length),
        source: "route",
        carried: carriedWith(items[0] ?? null, record),
        project: normaliseProjectSummary(record.project),
      };
    } catch (err) {
      if (!absent(err)) throw err;
      swipeRouteMissing = true;
    }
  }
  return deriveSwipeQueue(limit, signal);
}

/**
 * The queue, worked out from `/api/files` and `/api/projects`.
 *
 * Always read from offset 0. Every sound this hands over gets answered before
 * the next one arrives — that is what having no third action means — so a
 * taken sound leaves this filter by joining a project and a discarded one
 * leaves it by being discarded. The top of the set is therefore always fresh,
 * and no offset arithmetic can skip a sound.
 */
async function deriveSwipeQueue(limit: number, signal?: AbortSignal): Promise<SwipeQueue | null> {
  const index = await fetchProjects(signal).catch(() => null);
  const taken = new Set<string>();
  if (index) {
    const details = await Promise.all(
      index.items.map((project) => fetchProject(project.id, signal).catch(() => null)),
    );
    for (const detail of details) {
      for (const row of detail?.items ?? []) taken.add(row.hash);
    }
  }

  // Ask for enough rows that a page made entirely of already-taken sounds
  // still yields something. A project holds tens of sounds, not hundreds.
  const page = await fetchFiles(
    filesUrl({ ...EMPTY_QUERY, deleted: "false" }, Math.max(limit + taken.size, limit), 0),
    signal,
  );
  const items = page.items.filter((row) => !taken.has(row.hash)).slice(0, limit);

  // Every taken sound is undiscarded, so it is inside this total. Subtracting
  // the ones we resolved is exact, not an estimate.
  const takenInSet = page.total === 0 ? 0 : taken.size;
  return {
    items,
    remaining: Math.max(page.total - takenInSet, items.length),
    source: "derived",
    // Nothing came with these sounds: they were assembled out of a list. The
    // view fetches each sound's silence and spans as it always did.
    carried: null,
    project: currentProject(index?.items ?? null),
  };
}

/**
 * The project on the bench, or null when there is not one.
 *
 * `stored` holds one uncommitted project, and there is no picking which
 * project a sound goes into because there is only ever one there. When a board
 * running a looser cap holds several, the most recently started one is the
 * bench: it is the one whose sounds are being chosen right now.
 */
export function currentProject(projects: readonly ProjectSummary[] | null): ProjectSummary | null {
  if (!projects) return null;
  const open = projects.filter(soundSetOpen);
  if (open.length === 0) return null;
  return open.reduce((newest, project) => (project.created_at > newest.created_at ? project : newest));
}
