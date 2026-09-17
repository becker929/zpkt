/**
 * Fixture collection for mock mode.
 *
 * Mock mode exists so the interface can be built and driven before the FastAPI
 * server answers on port 8090. The numbers match the real index: 3,451 unique
 * sounds, 8,277 aliases, about 75 hours. Everything here is generated from a
 * seeded pseudo-random number generator, so the data is the same on every
 * reload and screenshots are reproducible.
 *
 * This module runs on the server only. It is imported by the route handlers
 * under `app/api/`.
 */

import { createHash } from "node:crypto";

import { COLUMN_CAP } from "./boardConfig";
import { isBundlePath } from "./paths";
import {
  COLUMNS,
  MAX_PROJECT_SOUNDS,
  SCHEMA_VERSION,
  checkProject,
  commitArtifact,
  describeIssues,
  isColumn,
  isOver,
  manifestInput,
  nextPlacement,
  onBoard,
  projectId,
  slotHolder,
  soundSetOpen,
  storedCommit,
  uniqueProjectId,
} from "./project";
import type {
  Board,
  Column,
  Commit,
  ProjectDocument,
  ProjectSound,
  ProjectSummary,
} from "./project";
import { MIN_GAP_S, silentSeconds, skippable, soundingSeconds } from "./silence";
import type { Alias, BulkAction, DupeGroup, FileRow, Query, SilenceInterval, SortKey } from "./types";

export const MOCK_ENABLED = process.env.NEXT_PUBLIC_MOCK === "1";

const FILE_COUNT = 3451;
const BUCKETS = 1000;

/** Small deterministic generator. Same seed, same collection, every time. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const FOLDERS = [
  "sounds - spoken",
  "sounds - foley",
  "music - previous demos",
  "dj - sets",
  "samples - drums",
  "field recordings",
];

const NOUNS = [
  "mouth snare",
  "kick",
  "hat",
  "room tone",
  "vocal take",
  "guitar loop",
  "modular patch",
  "rain",
  "subway",
  "bass sketch",
  "techno idea",
  "voice memo",
  "clap",
  "ride cymbal",
  "tape hiss",
  "synth drone",
  "market ambience",
  "door slam",
  "conversation",
  "808 sub",
];

/**
 * Session words and task words for the long filenames.
 *
 * Half the real collection is named the way a session is named:
 * `banana-pancake_2023-12-05_investigate-rumble_0-kick.wav`. Those names are
 * sixty characters long and they carry the whole meaning of a row, so the
 * fixture has to contain them. A fixture of ten-character names would let a
 * column two characters wide look fine.
 */
const SESSIONS = [
  "banana-pancake",
  "wet-cardboard",
  "iron-lung",
  "slow-tape",
  "north-window",
  "blue-radio",
  "paper-engine",
];

const TASKS = [
  "investigate-rumble",
  "fix-the-low-end",
  "second-pass",
  "reamp-test",
  "before-the-chorus",
  "mono-check",
];

/**
 * The name of fixture sound `i`.
 *
 * Every value comes from the index, never from the seeded stream, so adding
 * this did not shift a single duration, alias count or duplicate group.
 */
function mockFilename(i: number, noun: string, ext: string): string {
  const nn = String(i % 97).padStart(2, "0");
  if (i % 2 === 1) return `${noun} ${nn}${ext}`;
  const month = String(1 + (i % 12)).padStart(2, "0");
  const day = String(1 + (i % 28)).padStart(2, "0");
  const stamp = `20${23 + (i % 3)}-${month}-${day}`;
  const session = SESSIONS[i % SESSIONS.length];
  const task = TASKS[Math.floor(i / 2) % TASKS.length];
  return `${session}_${stamp}_${task}_${nn}-${noun.replace(/ /g, "-")}${ext}`;
}

const EXTS: Array<[string, string, number]> = [
  [".wav", "pcm_s24le", 6583],
  [".aif", "pcm_s16be", 1180],
  [".mp3", "mp3", 450],
  [".m4a", "aac", 60],
  [".flac", "flac", 2],
  [".aiff", "pcm_s16be", 2],
];

interface MockFile extends FileRow {
  sample_rate: number;
  channels: number;
  aliases: Alias[];
  tags: string[];
  seed: number;
  /**
   * Every measured gap, down to 0.4 seconds, exactly as the `silence_interval`
   * table holds them. The floor is applied when they are read, not here.
   */
  silence: SilenceInterval[];
}

function hexHash(index: number): string {
  const rand = mulberry32(index * 2654435761 + 7);
  let out = "";
  while (out.length < 64) out += Math.floor(rand() * 16).toString(16);
  return out.slice(0, 64);
}

function pickExt(r: number): [string, string] {
  const total = EXTS.reduce((sum, [, , n]) => sum + n, 0);
  let target = r * total;
  for (const [ext, codec, n] of EXTS) {
    target -= n;
    if (target <= 0) return [ext, codec];
  }
  return [".wav", "pcm_s24le"];
}

/**
 * Where the dead air is in fixture sound `i`.
 *
 * Shaped like the real measurement: about two thirds of sounds carry some
 * silence, most of it leading and trailing on takes and stems, with long empty
 * stretches inside anything over a minute. Gaps shorter than the 2 second floor
 * are included deliberately, because the client filters at read time and that
 * filtering needs something to bite on.
 *
 * Every value comes from the file's own seed, so the fixture is the same on
 * every reload and a screenshot of a tinted waveform is reproducible.
 */
function buildSilence(seed: number, duration: number): SilenceInterval[] {
  if (duration < 1) return [];
  const rand = mulberry32(seed * 61 + 13);
  // A third of the collection plays wall to wall. Those rows prove the
  // interface says nothing when there is nothing to say.
  if (rand() < 0.34) return [];

  const round = (n: number) => Number(n.toFixed(3));
  const out: SilenceInterval[] = [];
  let cursor = 0;

  // Leading silence. On a take of any length this is the commonest case by far.
  const lead = duration >= 8 ? 2.5 + rand() * Math.min(duration * 0.18, 25) : 0.4 + rand() * 0.9;
  if (lead < duration * 0.9) {
    out.push({ start_s: 0, end_s: round(lead) });
    cursor = lead;
  }

  // Long empty stretches inside a bounce. Both the number of them and their
  // length grow with the file, because that is where the collection's dead air
  // actually is: an hour-long mix with one four second gap is not what the
  // measurement found.
  if (duration > 60) {
    const gaps = 1 + Math.floor(rand() * 3 + Math.min(duration / 280, 9));
    for (let g = 0; g < gaps; g += 1) {
      const start = cursor + 4 + rand() * ((duration - cursor) / (gaps + 1));
      const length = rand() < 0.3 ? 0.4 + rand() : 3 + rand() * Math.min(duration * 0.1, 420);
      const end = Math.min(start + length, duration - 1);
      if (start >= duration || end - start < 0.4) break;
      out.push({ start_s: round(start), end_s: round(end) });
      cursor = end;
    }
  }

  // Trailing silence: the recorder kept running after the sound stopped.
  if (duration >= 8 && rand() < 0.75) {
    const tail = 2.5 + rand() * Math.min(duration * 0.15, 20);
    const start = Math.max(cursor + 1, duration - tail);
    if (duration - start >= 2.0) out.push({ start_s: round(start), end_s: round(duration) });
  }

  // Sorted and apart, which is how ffmpeg reports them.
  return skippable(out, 0.4, duration);
}

function buildCollection(): MockFile[] {
  const files: MockFile[] = [];
  for (let i = 0; i < FILE_COUNT; i += 1) {
    const rand = mulberry32(i + 1);
    const [ext, codec] = pickExt(rand());
    const noun = NOUNS[Math.floor(rand() * NOUNS.length)];
    const filename = mockFilename(i, noun, ext);

    // A long tail of short one-shots plus a few long DJ mixes, which is what
    // the real collection looks like.
    const roll = rand();
    const duration =
      roll < 0.55
        ? 0.1 + rand() * 3
        : roll < 0.92
          ? 4 + rand() * 60
          : roll < 0.985
            ? 60 + rand() * 300
            : 900 + rand() * 3600;

    const sampleRate = ext === ".mp3" || ext === ".m4a" ? 44100 : [44100, 48000, 96000][Math.floor(rand() * 3)];
    const channels = rand() < 0.35 ? 1 : 2;
    const bytesPerSecond = ext === ".mp3" ? 40000 : ext === ".m4a" ? 32000 : (sampleRate * channels * 3);

    // Roughly 2.4 aliases per hash on average, matching 8,277 over 3,451.
    const aliasCount = roll < 0.4 ? 1 : roll < 0.8 ? 2 : roll < 0.95 ? 3 : 5;
    // A tenth of the multi-alias sounds are a project's recorded media, stored
    // once per Logic bundle. The real collection has 867 such paths and they
    // are the case the cleanup view must never offer for deletion, so the
    // fixture has to contain them.
    const inBundle = aliasCount > 1 && i % 10 === 3;
    const aliases: Alias[] = [];
    for (let a = 0; a < aliasCount; a += 1) {
      const folder = FOLDERS[Math.floor(rand() * FOLDERS.length)];
      const root = inBundle ? "compost" : a === 0 ? "compost" : rand() < 0.6 ? "audio-library" : "compost";
      const where = inBundle
        ? `${folder}/song ${a + 1}.logicx/Media/Audio Files/`
        : `${folder}/${a > 0 ? `bounce ${a}/` : ""}`;
      aliases.push({
        path: `/Users/anthonybecker/_tmsmsm/daw-library/${root}/${where}${filename}`,
        root,
        filename,
        ext,
        mtime: 1600000000 + Math.floor(rand() * 200000000),
      });
    }

    const durationS = Number(duration.toFixed(6));
    const silence = buildSilence(i + 1, durationS);

    files.push({
      hash: hexHash(i),
      filename,
      ext,
      codec,
      duration_s: durationS,
      sounding_s: soundingSeconds(durationS, silence, MIN_GAP_S),
      silence,
      size_bytes: Math.round(duration * bytesPerSecond) + 44,
      alias_count: aliasCount,
      favorite: i % 37 === 0,
      deleted: false,
      // AIF goes through ffmpeg on the way out, so its stream cannot be seeked.
      transcoded: ext === ".aif" || ext === ".aiff",
      sample_rate: sampleRate,
      channels,
      aliases,
      tags: i % 11 === 0 ? ["keep"] : [],
      seed: i + 1,
    });
  }
  return files;
}

/**
 * Everything the fixture remembers, kept on `globalThis`.
 *
 * The development server compiles each route the first time it is asked for,
 * and a route compiled later gets its own instance of this module. State held
 * in a module variable would then be per-route: a list created through
 * `/api/lists` would not exist for `/api/lists/{id}`. One object on the global
 * survives both that and hot reloading.
 */
interface MockState {
  collection: MockFile[] | null;
  lists: Map<number, MockList>;
  nextListId: number;
  seeded: boolean;
  /**
   * The projects directory. Keyed by filename stem, holding documents exactly
   * as they would be on disk: unvalidated, because one of the things the board
   * has to survive is a file somebody edited by hand.
   */
  projects: Map<string, unknown>;
  projectsSeeded: boolean;
}

interface MockList {
  id: number;
  name: string;
  created_at: string;
  /** Hashes in play order. */
  members: string[];
}

const globalState = globalThis as typeof globalThis & { __audioBrowserMock?: MockState };

function state(): MockState {
  if (!globalState.__audioBrowserMock) {
    globalState.__audioBrowserMock = {
      collection: null,
      lists: new Map(),
      nextListId: 1,
      seeded: false,
      projects: new Map(),
      projectsSeeded: false,
    };
  }
  return globalState.__audioBrowserMock;
}

export function mockFiles(): MockFile[] {
  const store = state();
  if (store.collection === null) store.collection = buildCollection();
  return store.collection;
}

export function mockFile(hash: string): MockFile | undefined {
  return mockFiles().find((f) => f.hash === hash);
}

/** Favourite state lives in module memory. It resets when the dev server restarts. */
export function setMockFavorite(hash: string, favorite: boolean): boolean {
  const file = mockFile(hash);
  if (!file) return false;
  file.favorite = favorite;
  return true;
}

const SORTERS: Record<SortKey, (a: MockFile, b: MockFile) => number> = {
  name: (a, b) => a.filename.localeCompare(b.filename),
  duration: (a, b) => (a.duration_s ?? 0) - (b.duration_s ?? 0),
  size: (a, b) => a.size_bytes - b.size_bytes,
  // An unmeasured sound sorts by the only length it has. It is not zero.
  sounding: (a, b) =>
    (a.sounding_s ?? a.duration_s ?? 0) - (b.sounding_s ?? b.duration_s ?? 0),
};

export function mockQuery(query: Query): MockFile[] {
  const needle = query.q.trim().toLowerCase();
  const minDur = query.min_dur === "" ? null : Number(query.min_dur);
  const maxDur = query.max_dur === "" ? null : Number(query.max_dur);
  const wantDeleted = query.deleted ?? "false";

  const out = mockFiles().filter((f) => {
    // Discarded sounds are hidden unless asked for. That is the whole point of
    // discarding one.
    if (wantDeleted === "false" && f.deleted) return false;
    if (wantDeleted === "true" && !f.deleted) return false;
    if (needle && !f.filename.toLowerCase().includes(needle)) return false;
    if (query.ext && f.ext !== query.ext) return false;
    if (query.favorite && !f.favorite) return false;
    const d = f.duration_s ?? 0;
    if (minDur !== null && Number.isFinite(minDur) && d < minDur) return false;
    if (maxDur !== null && Number.isFinite(maxDur) && d > maxDur) return false;
    return true;
  });

  out.sort(SORTERS[query.sort] ?? SORTERS.name);
  if (query.order === "desc") out.reverse();
  return out;
}

/**
 * Peaks in the server's own format: one int8 minimum and maximum per bucket.
 * The shape mirrors what the real `/peaks` route returns.
 */
export function mockPeaks(file: MockFile): Array<[number, number]> {
  const rand = mulberry32(file.seed * 31 + 5);
  const pairs: Array<[number, number]> = [];
  const hits = 1 + Math.floor(rand() * 6);
  const duration = file.duration_s ?? 0;
  // Peaks and the silence measurement describe the same audio, so a bucket
  // inside a measured gap has to be flat. A tinted region over a full-height
  // waveform would look like a bug in the tint.
  const quiet = (t: number) =>
    duration > 0 && file.silence.some((s) => t * duration >= s.start_s && t * duration < s.end_s);

  for (let i = 0; i < BUCKETS; i += 1) {
    const t = i / BUCKETS;
    if (quiet(t)) {
      pairs.push([-1, 1]);
      // Pull on the generator exactly as often as the sounding branch does, so
      // where the silence falls does not shift the rest of the shape.
      rand();
      rand();
      continue;
    }
    // A few transients with exponential decay, plus a noise floor.
    let envelope = 0.06;
    for (let h = 0; h < hits; h += 1) {
      const at = (h + 0.5) / hits;
      if (t >= at - 0.01) envelope = Math.max(envelope, Math.exp(-(t - at) * (8 + hits * 4)));
    }
    const amp = Math.min(1, envelope * (0.55 + rand() * 0.45));
    const hi = Math.round(amp * 120);
    const lo = -Math.round(amp * 120 * (0.7 + rand() * 0.3));
    pairs.push([lo, hi]);
  }
  return pairs;
}

/**
 * Synthetic WAV audio, generated as it is sent.
 *
 * The audio runs the full length the index claims, because a transport that
 * disagrees with its own metadata hides real bugs: seeking to 80% of a
 * 40-minute sound must land at 32 minutes, not at the end of a truncated clip.
 * Nothing is held in memory: the stream produces a chunk at a time, so a
 * 55-minute file costs a few kilobytes of server memory no matter how much of
 * it the browser pulls.
 */
const MOCK_SAMPLE_RATE = 22050;
const MOCK_HEADER_BYTES = 44;
const MOCK_CHUNK_FRAMES = 16384;

export function mockWavFrames(file: MockFile): number {
  return Math.floor(MOCK_SAMPLE_RATE * Math.max(file.duration_s ?? 1, 0.5));
}

export function mockWavLength(file: MockFile): number {
  return MOCK_HEADER_BYTES + mockWavFrames(file) * 2;
}

function mockWavHeader(file: MockFile): Buffer {
  const dataLength = mockWavFrames(file) * 2;
  const header = Buffer.alloc(MOCK_HEADER_BYTES);
  header.write("RIFF", 0);
  header.writeUInt32LE(36 + dataLength, 4);
  header.write("WAVE", 8);
  header.write("fmt ", 12);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20); // PCM
  header.writeUInt16LE(1, 22); // mono
  header.writeUInt32LE(MOCK_SAMPLE_RATE, 24);
  header.writeUInt32LE(MOCK_SAMPLE_RATE * 2, 28);
  header.writeUInt16LE(2, 32);
  header.writeUInt16LE(16, 34);
  header.write("data", 36);
  header.writeUInt32LE(dataLength, 40);
  return header;
}

/** Bytes `start` to `end` inclusive of the file, produced lazily. */
export function mockWavStream(file: MockFile, start: number, end: number): ReadableStream<Uint8Array> {
  const rand = mulberry32(file.seed);
  const base = 110 * Math.pow(2, Math.floor(rand() * 12) / 12);
  const header = mockWavHeader(file);
  let cursor = start;

  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (cursor > end) {
        controller.close();
        return;
      }
      if (cursor < MOCK_HEADER_BYTES) {
        const stop = Math.min(end, MOCK_HEADER_BYTES - 1);
        controller.enqueue(new Uint8Array(header.subarray(cursor, stop + 1)));
        cursor = stop + 1;
        return;
      }
      const firstFrame = Math.floor((cursor - MOCK_HEADER_BYTES) / 2);
      const lastFrame = Math.floor((end - MOCK_HEADER_BYTES) / 2);
      const frames = Math.min(MOCK_CHUNK_FRAMES, lastFrame - firstFrame + 1);
      const buffer = Buffer.alloc(frames * 2);
      for (let i = 0; i < frames; i += 1) {
        const t = (firstFrame + i) / MOCK_SAMPLE_RATE;
        const env = Math.exp(-((t % 1.0) * 4));
        const value =
          Math.sin(2 * Math.PI * base * t) * env * 0.4 + Math.sin(2 * Math.PI * base * 2.01 * t) * env * 0.15;
        buffer.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(value * 32767))), i * 2);
      }
      // A range may start mid-frame, so trim to the exact requested byte.
      const skip = (cursor - MOCK_HEADER_BYTES) % 2;
      controller.enqueue(new Uint8Array(buffer.subarray(skip)));
      cursor += buffer.length - skip;
    },
  });
}

/**
 * Mock-only demonstration spans, so the stage 3 overlay can be seen working
 * before stage 3 exists. Real spans come from the `span` table.
 */
export function mockSpans(file: MockFile): Array<{ start_s: number; end_s: number; label: string; method: string }> {
  if (parseInt(file.hash[0], 16) % 2 === 1) return [];
  const duration = file.duration_s ?? 0;
  if (duration < 1) return [];
  const labels = ["speech", "music", "other"];
  const rand = mulberry32(file.seed * 17 + 3);
  const spans = [];
  let t = 0;
  while (t < duration) {
    const length = Math.max(0.5, (0.08 + rand() * 0.2) * duration);
    const end = Math.min(duration, t + length);
    spans.push({
      start_s: Number(t.toFixed(3)),
      end_s: Number(end.toFixed(3)),
      label: labels[Math.floor(rand() * labels.length)],
      method: "yamnet",
    });
    t = end;
  }
  return spans;
}

/**
 * Mock `GET /api/files/{hash}/silence`.
 *
 * The fixture holds every gap down to 0.4 seconds, as the real table does, and
 * this filters to the requested floor. `sounding_s` is always computed at the
 * same floor as the intervals that are returned, so the two agree.
 */
export function mockSilence(file: MockFile, minGap: number) {
  const duration = file.duration_s ?? 0;
  const intervals = skippable(file.silence, minGap, duration);
  return {
    hash: file.hash,
    measured: true,
    min_gap: minGap,
    duration_s: file.duration_s,
    sounding_s: soundingSeconds(file.duration_s, intervals, minGap),
    silent_s: Number(silentSeconds(intervals).toFixed(3)),
    intervals: intervals.map((i) => ({ start_s: i.start_s, end_s: i.end_s })),
  };
}

function toDupeGroup(f: MockFile, copies: number): DupeGroup {
  const entries = f.aliases.map((a) => ({
    path: a.path,
    root: a.root,
    in_bundle: isBundlePath(a.path),
    deletable: !isBundlePath(a.path),
  }));
  return {
    hash: f.hash,
    filename: f.filename,
    alias_count: copies,
    size_bytes: f.size_bytes,
    wasted_bytes: f.size_bytes * (copies - 1),
    bundle_copies: entries.filter((e) => e.in_bundle).length,
    paths: entries.map((e) => e.path),
    entries,
  };
}

/**
 * Mock `/api/dupes`, scoped the way the real route is.
 *
 * Copies inside a project bundle are left out unless asked for, because they
 * are a project's own media and cannot be removed. The result reports how many
 * groups and bytes that left out.
 */
export function mockDupes(
  limit: number,
  includeBundles: boolean,
): {
  items: DupeGroup[];
  total: number;
  wasted_bytes: number;
  excluded_bundle_groups: number;
  excluded_bundle_bytes: number;
} {
  /** Copies that count under the current scoping, per file. */
  const counted = (f: MockFile) =>
    includeBundles ? f.alias_count : f.aliases.filter((a) => !isBundlePath(a.path)).length;

  const all = mockFiles().filter((f) => f.alias_count > 1);
  const kept = all.filter((f) => counted(f) > 1);
  const items = kept
    .slice()
    .sort((a, b) => b.size_bytes * (counted(b) - 1) - a.size_bytes * (counted(a) - 1))
    .slice(0, limit)
    .map((f) => toDupeGroup(f, counted(f)));

  const wasted = kept.reduce((sum, f) => sum + f.size_bytes * (counted(f) - 1), 0);
  const everything = all.reduce((sum, f) => sum + f.size_bytes * (f.alias_count - 1), 0);
  return {
    items,
    total: kept.length,
    wasted_bytes: wasted,
    excluded_bundle_groups: includeBundles ? 0 : all.length - kept.length,
    excluded_bundle_bytes: includeBundles ? 0 : everything - wasted,
  };
}

export function mockStats() {
  const files = mockFiles();
  const formats: Record<string, number> = {};
  let totalBytes = 0;
  let wasted = 0;
  let aliases = 0;
  let duration = 0;
  let sounding = 0;
  let dupes = 0;
  for (const f of files) {
    formats[f.ext] = (formats[f.ext] ?? 0) + 1;
    totalBytes += f.size_bytes * f.alias_count;
    wasted += f.size_bytes * (f.alias_count - 1);
    aliases += f.alias_count;
    duration += f.duration_s ?? 0;
    // An unmeasured sound contributes its wall length, because the alternative
    // is contributing nothing and under-reporting the work left to do.
    sounding += f.sounding_s ?? f.duration_s ?? 0;
    if (f.alias_count > 1) dupes += 1;
  }
  return {
    files: files.length,
    aliases,
    total_bytes: totalBytes,
    wasted_bytes: wasted,
    duplicate_hashes: dupes,
    formats,
    total_duration_s: duration,
    total_sounding_s: sounding,
  };
}

/* Triage ------------------------------------------------------------------ */

/**
 * Soft deletes and lists in mock mode.
 *
 * All of it lives in module memory and resets when the dev server restarts, in
 * the same way favourites already do. Soft delete here does exactly what it
 * does against the real index: it marks a hash and nothing else. No mock route
 * touches a file, because no real route may either.
 */

const MOCK_EPOCH = "2026-01-01T00:00:00Z";

function listStore(): Map<number, MockList> {
  const store = state();
  if (!store.seeded) {
    store.seeded = true;
    // One seeded list, so the lists view has something in it on a cold server
    // and a screenshot of it is reproducible.
    const members = mockFiles().slice(5, 9).map((f) => f.hash);
    store.lists.set(store.nextListId, {
      id: store.nextListId,
      name: "warm-up set",
      created_at: MOCK_EPOCH,
      members,
    });
    store.nextListId += 1;
  }
  return store.lists;
}

/** The row shape `/api/files` and `/api/lists/{id}` both return. */
export function mockSummary(f: MockFile) {
  return {
    hash: f.hash,
    filename: f.filename,
    ext: f.ext,
    path: f.aliases[0]?.path ?? "",
    root: f.aliases[0]?.root ?? "",
    codec: f.codec,
    duration_s: f.duration_s,
    sounding_s: f.sounding_s,
    size_bytes: f.size_bytes,
    sample_rate: f.sample_rate,
    channels: f.channels,
    alias_count: f.alias_count,
    favorite: f.favorite,
    deleted: f.deleted,
    has_peaks: true,
    transcoded: f.transcoded,
  };
}

export function setMockDeleted(hash: string, deleted: boolean): boolean {
  const file = mockFile(hash);
  if (!file) return false;
  file.deleted = deleted;
  return true;
}

export function mockDeletedState(hash: string) {
  const file = mockFile(hash);
  if (!file) return null;
  return {
    hash,
    deleted: file.deleted,
    deleted_at: file.deleted ? MOCK_EPOCH : null,
    note: null,
    alias_count: file.alias_count,
  };
}

function listSummary(list: MockList) {
  let duration = 0;
  let sounding = 0;
  let size = 0;
  for (const hash of list.members) {
    const file = mockFile(hash);
    if (!file) continue;
    duration += file.duration_s ?? 0;
    sounding += file.sounding_s ?? file.duration_s ?? 0;
    size += file.size_bytes;
  }
  return {
    id: list.id,
    name: list.name,
    created_at: list.created_at,
    member_count: list.members.length,
    duration_s: Number(duration.toFixed(3)),
    sounding_s: Number(sounding.toFixed(3)),
    size_bytes: size,
  };
}

export function mockLists() {
  const items = [...listStore().values()].map(listSummary);
  return { total: items.length, items };
}

export function mockListDetail(id: number, limit: number, offset: number) {
  const list = listStore().get(id);
  if (!list) return null;
  const rows = list.members
    .map((hash) => mockFile(hash))
    .filter((f): f is MockFile => f !== undefined)
    .slice(offset, offset + limit)
    .map(mockSummary);
  return { ...listSummary(list), limit, offset, items: rows };
}

/** The lists one sound is in, named just enough to link to them. */
export function mockListsOf(hash: string) {
  return [...listStore().values()]
    .filter((list) => list.members.includes(hash))
    .map((list) => ({ id: list.id, name: list.name }));
}

export function mockCreateList(name: string) {
  const trimmed = name.trim();
  const store = listStore();
  for (const list of store.values()) {
    // The name is unique in the schema, so creating a duplicate is a conflict,
    // not a second list.
    if (list.name === trimmed) return null;
  }
  const id = state().nextListId;
  const list: MockList = { id, name: trimmed, created_at: MOCK_EPOCH, members: [] };
  store.set(id, list);
  state().nextListId += 1;
  return listSummary(list);
}

export function mockRenameList(id: number, name: string) {
  const list = listStore().get(id);
  if (!list) return null;
  list.name = name.trim();
  return listSummary(list);
}

export function mockDeleteList(id: number) {
  const list = listStore().get(id);
  if (!list) return null;
  listStore().delete(id);
  return { id, name: list.name, removed_members: list.members.length };
}

export function mockSetMember(listId: number, hash: string, member: boolean) {
  const list = listStore().get(listId);
  if (!list || !mockFile(hash)) return null;
  const at = list.members.indexOf(hash);
  if (member && at === -1) list.members.push(hash);
  if (!member && at !== -1) list.members.splice(at, 1);
  const now = list.members.indexOf(hash);
  return {
    list_id: listId,
    hash,
    member: now !== -1,
    position: now === -1 ? null : now,
    added_at: now === -1 ? null : MOCK_EPOCH,
    member_count: list.members.length,
  };
}

/**
 * One action over many hashes.
 *
 * The real route runs this in a single transaction. Nothing here is
 * asynchronous, so the mock is atomic for free; what it has to match is the
 * counting, because that is what the interface reports back to the user.
 */
export function mockBulk(hashes: string[], action: BulkAction, listId?: number | null) {
  const unique = [...new Set(hashes)];
  const list = listId === undefined || listId === null ? null : listStore().get(listId) ?? null;
  if ((action === "add_to_list" || action === "remove_from_list") && list === null) return null;

  let matched = 0;
  let changed = 0;
  let unchanged = 0;

  for (const hash of unique) {
    const file = mockFile(hash);
    if (!file) continue;
    matched += 1;

    if (action === "star" || action === "unstar") {
      const wanted = action === "star";
      if (file.favorite === wanted) unchanged += 1;
      else {
        file.favorite = wanted;
        changed += 1;
      }
      continue;
    }

    if (action === "delete" || action === "restore") {
      const wanted = action === "delete";
      if (file.deleted === wanted) unchanged += 1;
      else {
        file.deleted = wanted;
        changed += 1;
      }
      continue;
    }

    const at = list!.members.indexOf(hash);
    if (action === "add_to_list") {
      if (at !== -1) unchanged += 1;
      else {
        list!.members.push(hash);
        changed += 1;
      }
    } else {
      if (at === -1) unchanged += 1;
      else {
        list!.members.splice(at, 1);
        changed += 1;
      }
    }
  }

  return {
    action,
    list_id: listId ?? null,
    requested: hashes.length,
    unique: unique.length,
    matched,
    changed,
    unchanged,
    skipped: unique.length - matched,
  };
}

/** Triaged over total: starred, discarded, or in at least one list. */
export function mockTriage() {
  const listed = new Set<string>();
  for (const list of listStore().values()) for (const hash of list.members) listed.add(hash);

  const files = mockFiles();
  let starred = 0;
  let deleted = 0;
  let triaged = 0;
  for (const f of files) {
    if (f.favorite) starred += 1;
    if (f.deleted) deleted += 1;
    if (f.favorite || f.deleted || listed.has(f.hash)) triaged += 1;
  }
  const total = files.length;
  return {
    total,
    triaged,
    untriaged: total - triaged,
    percent: total === 0 ? 0 : Number(((triaged / total) * 100).toFixed(2)),
    starred,
    deleted,
    listed: listed.size,
    lists: listStore().size,
  };
}

/* Projects and the board --------------------------------------------------- */

/**
 * Projects in mock mode.
 *
 * The real thing is a directory of JSON files with SQLite as a cache. Here the
 * directory is a map on `globalThis`, and it holds documents exactly as they
 * would be on disk: unvalidated, because one of the things the board has to
 * cope with is a file somebody edited by hand. Every read validates.
 *
 * The digests are SHA-256, not BLAKE3. Node has SHA-256 and no BLAKE3, and
 * inventing 64 hex characters would be worse than using a real hash of the
 * right input. The input is the one the model fixes, so the chain behaves
 * correctly; only the algorithm differs, and the interface says so wherever a
 * digest is shown while mock mode is on.
 */

function projectStore(): Map<string, unknown> {
  const store = state();
  if (!store.projectsSeeded) {
    store.projectsSeeded = true;
    for (const doc of seedProjects()) {
      store.projects.set((doc as { id: string }).id, doc);
    }
  }
  return store.projects;
}

/** SHA-256 of a stage's artifact, standing in for BLAKE3 while mocking. */
function mockDigest(input: string): string {
  return createHash("sha256").update(input, "utf8").digest("hex");
}

function mockSound(hash: string, addedAt: string): ProjectSound {
  return { hash, added_at: addedAt, role: null, note: "" };
}

/**
 * The fixture board.
 *
 * One project per column, so every column starts inside a cap of 3 and a test
 * has room to push exactly one of them over. Several are deliberately awkward:
 * `slag-heap` was edited after its sound set was frozen, `dead-end` was
 * abandoned out of `collage` and holds no slot, `hand-edited-by-mistake` names
 * no column anybody can read, and `chain-out-of-order` is nonsense that still
 * says which column it is sitting in and so still holds that slot. All of them
 * are cases the board has to show rather than hide.
 */
function seedProjects(): unknown[] {
  const hashes = mockFiles().map((f) => f.hash);
  const at = (day: number, hour: number) =>
    `2026-09-${String(day).padStart(2, "0")}T${String(hour).padStart(2, "0")}:00:00Z`;

  const stored = {
    schema_version: SCHEMA_VERSION,
    id: "2026-09-16-rust-and-rebar",
    name: "rust and rebar",
    column: "stored",
    created_at: at(16, 21),
    updated_at: at(16, 22),
    notes: "kick first. everything else answers to it.",
    abandoned: null,
    commits: [],
    sounds: [hashes[10], hashes[11], hashes[12]].map((h) => mockSound(h, at(16, 21))),
  };

  const collageMembers = [hashes[20], hashes[21]];
  const collage = {
    schema_version: SCHEMA_VERSION,
    id: "2026-09-12-conveyor-belt",
    name: "conveyor belt",
    column: "collage",
    created_at: at(12, 9),
    updated_at: at(13, 11),
    notes: "",
    abandoned: null,
    commits: [
      { column: "stored", at: at(13, 11), digest: mockDigest(manifestInput(collageMembers)) },
    ],
    sounds: collageMembers.map((h) => mockSound(h, at(12, 9))),
  };

  // Frozen over three sounds, and the file now holds four. The digest no longer
  // matches, which is the whole reason the digest is there.
  const frozenOver = [hashes[30], hashes[31], hashes[32]];
  const enrich = {
    schema_version: SCHEMA_VERSION,
    id: "2026-09-08-slag-heap",
    name: "slag heap",
    column: "enrich",
    created_at: at(8, 14),
    updated_at: at(11, 18),
    notes: "",
    abandoned: null,
    commits: [
      { column: "stored", at: at(9, 10), digest: mockDigest(manifestInput(frozenOver)) },
      { column: "collage", at: at(11, 18), digest: mockDigest("collage\0x") },
    ],
    sounds: [...frozenOver, hashes[33]].map((h) => mockSound(h, at(8, 14))),
  };

  const releasedMembers = [hashes[40], hashes[41]];
  const released = {
    schema_version: SCHEMA_VERSION,
    id: "2026-08-30-first-light",
    name: "first light",
    column: "released",
    created_at: "2026-08-30T12:00:00Z",
    updated_at: "2026-09-05T12:00:00Z",
    notes: "",
    abandoned: null,
    commits: [
      { column: "stored", at: "2026-09-01T12:00:00Z", digest: mockDigest(manifestInput(releasedMembers)) },
      { column: "collage", at: "2026-09-03T12:00:00Z", digest: mockDigest("collage\0y") },
      { column: "enrich", at: "2026-09-05T12:00:00Z", digest: mockDigest("enrich\0y") },
    ],
    sounds: releasedMembers.map((h) => mockSound(h, "2026-08-30T12:00:00Z")),
  };

  // Abandoned out of `collage`, so it is off the board and holds no slot there.
  // Its `stored` commit is untouched: reviving it brings back a project whose
  // sound set is still frozen, which is what makes abandoning cheap enough to
  // use.
  const abandonedMembers = [hashes[60], hashes[61]];
  const abandoned = {
    schema_version: SCHEMA_VERSION,
    id: "2026-09-05-dead-end",
    name: "dead end",
    column: "collage",
    created_at: at(5, 10),
    updated_at: at(7, 16),
    notes: "",
    abandoned: { at: at(7, 16), from: "collage", reason: "the kick never sat right." },
    commits: [
      { column: "stored", at: at(6, 12), digest: mockDigest(manifestInput(abandonedMembers)) },
    ],
    sounds: abandonedMembers.map((h) => mockSound(h, at(5, 10))),
  };

  // Not a project. `mixdown` is not a column, so this file cannot be placed and
  // holds no slot: there is no column to hold it in.
  const brokenColumn = {
    schema_version: 1,
    id: "hand-edited-by-mistake",
    name: "hand edited by mistake",
    column: "mixdown",
    created_at: "2026-09-14T12:00:00Z",
    updated_at: "2026-09-14T12:00:00Z",
    notes: "",
    abandoned: null,
    commits: [],
    sounds: [],
  };

  // Also not a project. The chain names `collage` before `stored` and then
  // names `collage` twice, so there is no order of events this file could have
  // come from. The schema rejects it outright, which is the point of writing
  // the chain as fixed branches rather than as a rule the app remembers to
  // apply.
  //
  // It still says it is in `enrich`, so it still holds a slot there. A file
  // nobody can read is a job to do, not a slot given back.
  const brokenChain = {
    schema_version: 1,
    id: "chain-out-of-order",
    name: "chain out of order",
    column: "enrich",
    created_at: "2026-09-14T12:00:00Z",
    updated_at: "2026-09-14T12:00:00Z",
    notes: "",
    abandoned: null,
    commits: [
      { column: "collage", at: "2026-09-14T13:00:00Z", digest: mockDigest("a") },
      { column: "collage", at: "2026-09-14T14:00:00Z", digest: mockDigest("b") },
    ],
    sounds: [hashes[50]].map((h) => mockSound(h, at(14, 12))),
  };

  return [stored, collage, enrich, released, abandoned, brokenColumn, brokenChain];
}

/** The key a document is filed under, even when the document is nonsense. */
function storedId(key: string, raw: unknown): string {
  const id = (raw as { id?: unknown } | null)?.id;
  return typeof id === "string" ? id : key;
}

export interface MockUnreadable {
  id: string;
  problem: string;
  /**
   * The column this file is still holding a slot in, or null when it does not
   * even say which column it is in.
   */
  column: Column | null;
}

function measures(sounds: readonly ProjectSound[]) {
  let duration = 0;
  let sounding = 0;
  let size = 0;
  let known = 0;
  for (const sound of sounds) {
    const file = mockFile(sound.hash);
    if (!file) continue;
    known += 1;
    duration += file.duration_s ?? 0;
    sounding += file.sounding_s ?? file.duration_s ?? 0;
    size += file.size_bytes;
  }
  // Nothing resolved, so there is nothing measured to report. Null, not zero.
  if (known === 0) return { duration_s: null, sounding_s: null, size_bytes: null };
  return {
    duration_s: Number(duration.toFixed(3)),
    sounding_s: Number(sounding.toFixed(3)),
    size_bytes: size,
  };
}

/**
 * Whether the member hashes still hash to what the `stored` commit froze.
 *
 * Null when nothing has been frozen yet, so the interface can tell "not checked"
 * apart from "checked and wrong".
 */
function verifySoundSet(project: ProjectDocument): boolean | null {
  const frozen = storedCommit(project.commits);
  if (!frozen) return null;
  return mockDigest(manifestInput(project.sounds.map((s) => s.hash))) === frozen.digest;
}

function summarise(project: ProjectDocument): ProjectSummary {
  return {
    id: project.id,
    name: project.name,
    column: project.column,
    created_at: project.created_at,
    updated_at: project.updated_at,
    abandoned: project.abandoned,
    commits: [...project.commits],
    sound_count: project.sounds.length,
    ...measures(project.sounds),
    sound_set_verified: verifySoundSet(project),
  };
}

/** Every readable project, plus the files that could not be read. */
export function mockProjects(): { items: ProjectSummary[]; unreadable: MockUnreadable[]; total: number } {
  const items: ProjectSummary[] = [];
  const unreadable: MockUnreadable[] = [];
  for (const [key, raw] of projectStore()) {
    const checked = checkProject(raw);
    if (checked.ok) items.push(summarise(checked.project));
    else {
      unreadable.push({
        id: storedId(key, raw),
        problem: describeIssues(checked.issues),
        column: slotHolder(raw),
      });
    }
  }
  items.sort((a, b) => (a.created_at === b.created_at ? a.id.localeCompare(b.id) : b.created_at.localeCompare(a.created_at)));
  unreadable.sort((a, b) => a.id.localeCompare(b.id));
  return { items, unreadable, total: items.length };
}

function readProject(id: string): ProjectDocument | null {
  const raw = projectStore().get(id);
  if (raw === undefined) return null;
  const checked = checkProject(raw);
  return checked.ok ? checked.project : null;
}

/**
 * How many slots one column is holding.
 *
 * Three kinds of file are counted and one kind is not. A readable project in
 * this column counts. A file that does not match the schema but still says it
 * is in this column counts too, because a slot is held by the file being there
 * and not by the file being correct: skipping it would mean one junk key in one
 * document freed a slot, and that is a way past the cap that needs no override
 * and leaves no trace. Released and abandoned projects hold nothing.
 */
function occupancy(column: Column): number {
  let count = 0;
  for (const raw of projectStore().values()) {
    const checked = checkProject(raw);
    if (checked.ok) {
      if (checked.project.column === column && onBoard(checked.project)) count += 1;
    } else if (slotHolder(raw) === column) {
      count += 1;
    }
  }
  return count;
}

export function mockBoard(): Board {
  const { items, unreadable } = mockProjects();
  return {
    columns: COLUMNS.map((column) => {
      const held = unreadable.filter((entry) => entry.column === column).length;
      const count = items.filter((p) => p.column === column && onBoard(p)).length + held;
      return { column, cap: COLUMN_CAP, count, unreadable: held, over: isOver(count, COLUMN_CAP) };
    }),
    released: items.filter((p) => p.column === "released").length,
    abandoned: items.filter((p) => p.abandoned !== null).length,
    unreadable: unreadable.length,
  };
}

/** One project: the document itself, and its members as list rows. */
export function mockProjectDetail(id: string) {
  const raw = projectStore().get(id);
  if (raw === undefined) return null;
  const checked = checkProject(raw);
  if (!checked.ok) {
    return { id: storedId(id, raw), valid: false as const, issues: checked.issues, document: raw };
  }
  const project = checked.project;
  return {
    id: project.id,
    valid: true as const,
    document: project,
    summary: summarise(project),
    // Members that no longer resolve to a sound are dropped from the rows but
    // still counted in `sound_count`, so the card can say the two differ rather
    // than quietly showing fewer.
    items: project.sounds
      .map((sound) => mockFile(sound.hash))
      .filter((f): f is MockFile => f !== undefined)
      .map(mockSummary),
  };
}

/** An instant the documents will accept: UTC, to the second. */
function nowInstant(): string {
  return `${new Date().toISOString().slice(0, 19)}Z`;
}

/** What a route answers when a cap stands in the way. */
export interface MockCapRefusal {
  refusal: "cap";
  column: Column;
  cap: number;
  count: number;
}

export type MockProjectResult<T> =
  | { ok: true; value: T }
  | { ok: false; status: number; detail: string; cap?: MockCapRefusal };

function capRefusal(column: Column): MockCapRefusal | null {
  const count = occupancy(column);
  if (count < COLUMN_CAP) return null;
  return { refusal: "cap", column, cap: COLUMN_CAP, count };
}

/**
 * How a refusal reads.
 *
 * A cap of 0 means the column is closed, and "collage holds 0 of 0" is not what
 * that is. The override is still offered either way: a closed column is
 * friction like every other cap, not a wall.
 */
function capDetail(refusal: MockCapRefusal, advice: string): string {
  return refusal.cap === 0
    ? `${refusal.column} is closed: its cap is 0. ${advice}`
    : `${refusal.column} holds ${refusal.count} of ${refusal.cap}. ${advice}`;
}

export function mockCreateProject(name: string, override: boolean): MockProjectResult<ProjectSummary> {
  const created = nowInstant();
  const refusal = override ? null : capRefusal("stored");
  if (refusal) {
    return {
      ok: false,
      status: 409,
      detail: capDetail(refusal, "finish one before starting another, or send override."),
      cap: refusal,
    };
  }

  const id = uniqueProjectId(projectId(name, created), projectStore().keys());
  const document: ProjectDocument = {
    schema_version: SCHEMA_VERSION,
    id,
    name,
    column: "stored",
    created_at: created,
    updated_at: created,
    notes: "",
    abandoned: null,
    commits: [],
    sounds: [],
  };
  const checked = checkProject(document);
  if (!checked.ok) {
    return { ok: false, status: 422, detail: describeIssues(checked.issues) };
  }
  projectStore().set(id, document);
  return { ok: true, value: summarise(checked.project) };
}

/**
 * Rename or re-note a project.
 *
 * `column` is not a field this route writes. A project advances by committing,
 * which is what records the digest and what the cap gates; moving it with a
 * PATCH would be a way around both. `abandoned` is not a field this route
 * writes either, for the same reason: it is what frees a slot, so it goes
 * through its own route where the board can be told about it.
 */
export function mockPatchProject(
  id: string,
  patch: { name?: string; notes?: string; column?: unknown },
): MockProjectResult<ProjectSummary> {
  const project = readProject(id);
  if (!project) return { ok: false, status: 404, detail: "no such project" };
  if (patch.column !== undefined) {
    return {
      ok: false,
      status: 409,
      detail: "a project advances by committing, which is what records the digest. this route does not move one.",
    };
  }

  const next = {
    ...project,
    name: patch.name ?? project.name,
    notes: patch.notes ?? project.notes,
    updated_at: nowInstant(),
  };
  const checked = checkProject(next);
  if (!checked.ok) return { ok: false, status: 422, detail: describeIssues(checked.issues) };
  projectStore().set(id, checked.project);
  return { ok: true, value: summarise(checked.project) };
}

/**
 * Freeze this column's artifact and advance.
 *
 * Three ways this does not go through: the project is already released, its
 * sound set is empty and there is nothing to freeze, or the next column is at
 * its cap. Only the last of those is overridable, because only the last is a
 * discipline rather than a nonsense.
 */
export function mockCommitProject(
  id: string,
  override: boolean,
  expectColumn?: string,
): MockProjectResult<{ summary: ProjectSummary; commit: Commit; artifact_real: boolean }> {
  const project = readProject(id);
  if (!project) return { ok: false, status: 404, detail: "no such project" };
  if (!isColumn(project.column)) {
    return { ok: false, status: 409, detail: "this project is released. there is nothing left to freeze." };
  }
  // Committing is how a project advances, and an abandoned one is not in the
  // race. Reviving it first is the way back, and that is where the cap is paid.
  if (project.abandoned !== null) {
    return {
      ok: false,
      status: 409,
      detail: `"${project.name}" was abandoned at ${project.abandoned.at}. revive it before committing it.`,
    };
  }

  // The caller names the stage it means to freeze. Commit is one-way and each
  // boundary freezes a different artifact, so a request that was aimed at
  // `stored` must not be applied to `collage` because a second tab, or a retry
  // after a timeout, got there first. Not overridable: there is no reading of
  // "yes, freeze a stage I did not ask about" that is a decision rather than an
  // accident.
  if (expectColumn !== undefined && expectColumn !== project.column) {
    return {
      ok: false,
      status: 409,
      detail: `this asked to freeze ${expectColumn}, and "${project.name}" is already in ${project.column}. somewhere else committed it first. nothing was frozen twice.`,
    };
  }

  const column = project.column;
  if (column === "stored" && project.sounds.length === 0) {
    return {
      ok: false,
      status: 422,
      detail: "a project with no sounds has nothing to freeze. put something in it first.",
    };
  }

  const target = nextPlacement(column);
  if (isColumn(target) && !override) {
    const refusal = capRefusal(target);
    if (refusal) {
      return {
        ok: false,
        status: 409,
        detail: `${target} holds ${refusal.count} of ${refusal.cap}. finish something in ${target} before sending more into it, or send override.`,
        cap: refusal,
      };
    }
  }

  const artifact = commitArtifact(project, column);
  const commit: Commit = { column, at: nowInstant(), digest: mockDigest(artifact.input) };
  const next = {
    ...project,
    column: target,
    commits: [...project.commits, commit],
    updated_at: commit.at,
  };
  const checked = checkProject(next);
  if (!checked.ok) return { ok: false, status: 500, detail: describeIssues(checked.issues) };
  projectStore().set(id, checked.project);
  return {
    ok: true,
    value: { summary: summarise(checked.project), commit, artifact_real: artifact.real },
  };
}

/**
 * Leave the board without promoting anything.
 *
 * Nothing is frozen and nothing is appended to `commits`. That is the whole
 * difference from commit: this is the cheap exit, and it is cheap because it
 * can be undone. The slot comes back at once.
 *
 * Refused for a released project, which is already off the board, and for one
 * that is already abandoned. Neither is overridable, because neither is a
 * discipline; both are asking for something that has already happened.
 */
export function mockAbandonProject(id: string, reason: string): MockProjectResult<ProjectSummary> {
  const project = readProject(id);
  if (!project) return { ok: false, status: 404, detail: "no such project" };
  if (!isColumn(project.column)) {
    return { ok: false, status: 409, detail: "this project is released. it is already off the board." };
  }
  if (project.abandoned !== null) {
    return {
      ok: false,
      status: 409,
      detail: `"${project.name}" was already abandoned at ${project.abandoned.at}.`,
    };
  }

  const at = nowInstant();
  const next = {
    ...project,
    abandoned: { at, from: project.column, reason },
    updated_at: at,
  };
  const checked = checkProject(next);
  if (!checked.ok) return { ok: false, status: 500, detail: describeIssues(checked.issues) };
  projectStore().set(id, checked.project);
  return { ok: true, value: summarise(checked.project) };
}

/**
 * Bring an abandoned project back to the column it left.
 *
 * It takes a slot like anything else, so a full column refuses it with the same
 * 409 and the same override as every other cap refusal. That cost is the point:
 * reviving something is starting it again, and starting something has a price.
 *
 * Every commit it had is still there. The project comes back exactly as it went
 * away, one field lighter.
 */
export function mockReviveProject(id: string, override: boolean): MockProjectResult<ProjectSummary> {
  const project = readProject(id);
  if (!project) return { ok: false, status: 404, detail: "no such project" };
  if (project.abandoned === null) {
    return { ok: false, status: 409, detail: `"${project.name}" is not abandoned. it is on the board.` };
  }

  const back = project.abandoned.from;
  if (!override) {
    const refusal = capRefusal(back);
    if (refusal) {
      return {
        ok: false,
        status: 409,
        detail: capDetail(
          refusal,
          `reviving "${project.name}" takes a slot there. finish something in ${back} first, or send override.`,
        ),
        cap: refusal,
      };
    }
  }

  const next = { ...project, abandoned: null, updated_at: nowInstant() };
  const checked = checkProject(next);
  if (!checked.ok) return { ok: false, status: 500, detail: describeIssues(checked.issues) };
  projectStore().set(id, checked.project);
  return { ok: true, value: summarise(checked.project) };
}

/** Add or remove one sound. Refused outright once the sound set is frozen. */
export function mockSetProjectSound(
  id: string,
  hash: string,
  member: boolean,
): MockProjectResult<ProjectSummary> {
  const project = readProject(id);
  if (!project) return { ok: false, status: 404, detail: "no such project" };
  if (!soundSetOpen(project)) {
    const frozen = storedCommit(project.commits);
    return {
      ok: false,
      status: 409,
      detail: frozen
        ? `the sound set of "${project.name}" was frozen at ${frozen.at}. it can never gain or lose a sound.`
        : `"${project.name}" is in ${project.column}, past the column where sounds are assigned.`,
    };
  }
  if (member && !mockFile(hash)) {
    return { ok: false, status: 404, detail: "no sound with that hash" };
  }

  const at = project.sounds.findIndex((sound) => sound.hash === hash);
  if (member && at === -1 && project.sounds.length >= MAX_PROJECT_SOUNDS) {
    return {
      ok: false,
      status: 409,
      detail: `a project holds at most ${MAX_PROJECT_SOUNDS} sounds.`,
    };
  }

  const sounds = project.sounds.slice();
  if (member && at === -1) sounds.push(mockSound(hash, nowInstant()));
  if (!member && at !== -1) sounds.splice(at, 1);

  const checked = checkProject({ ...project, sounds, updated_at: nowInstant() });
  if (!checked.ok) return { ok: false, status: 422, detail: describeIssues(checked.issues) };
  projectStore().set(id, checked.project);
  return { ok: true, value: summarise(checked.project) };
}

/**
 * Remove a project file.
 *
 * Mock only, and no part of the interface calls it. The specification has no
 * such route, and the way a project leaves the board is by being finished. It
 * exists so the browser tests can put the fixture directory back the way they
 * found it: the mock server keeps its state in memory and is reused between
 * runs, so a test that left four projects behind would push the next run over
 * the cap before it started.
 */
export function mockDeleteProject(id: string): boolean {
  return projectStore().delete(id);
}
