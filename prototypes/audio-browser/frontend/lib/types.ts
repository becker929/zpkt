/**
 * Shapes the interface works with.
 *
 * A sound is identified by its BLAKE3 hash. A path is only an alias for a
 * hash, and one sound may have several. The client never sends a path to the
 * server; every route is addressed by hash.
 *
 * There is no favourite here, and no list. A star means "decide later", and a
 * triage lane must not offer that. The only decisions a sound can carry are
 * the two the swipe view makes: it was taken into a project, or it was
 * discarded.
 */

import type { ProjectSummary } from "./project";

/**
 * How a set of sounds is ordered.
 *
 * Size is not here. Nobody chooses a sound because of how many bytes it is,
 * and neither is the number of paths it has: content addressing made those
 * correct rather than interesting.
 */
export type SortKey = "name" | "duration" | "sounding";
export type SortOrder = "asc" | "desc";

/**
 * Whether the view asks for discarded sounds.
 *
 * `false` is the default and the point of discarding: a sound the user does not
 * want stops appearing. `true` is the discard pile, where restore puts things
 * back. `any` is both together.
 */
export type DeletedFilter = "false" | "true" | "any";

/** One row of a list of sounds. */
export interface FileRow {
  hash: string;
  filename: string;
  ext: string;
  codec: string | null;
  duration_s: number | null;
  /**
   * Wall duration minus silence of 2 seconds or more.
   *
   * Null when the server has not measured this sound, or has not started
   * sending the field at all. Null is not zero: a row with no measurement
   * shows its wall duration rather than a length of 0:00 that would be a lie.
   */
  sounding_s: number | null;
  size_bytes: number;
  /**
   * The user discarded this sound.
   *
   * It says nothing about the filesystem. Every path still holds the bytes;
   * the flag only means the list hides the sound unless it is asked for.
   */
  deleted: boolean;
  /**
   * The server re-encodes this format on the way out, so the response carries
   * no byte offsets and the browser cannot seek in it. AIF is the case here.
   * The interface says so rather than letting a click on the waveform do
   * nothing.
   */
  transcoded: boolean;
}

/** The detail view's sound. */
export interface FileDetail extends FileRow {
  sample_rate: number | null;
  channels: number | null;
  tags: string[];
}

/** A page of list results. */
export interface FilePage {
  items: FileRow[];
  total: number;
  limit: number;
  offset: number;
}

/**
 * Waveform peaks: one [minimum, maximum] pair per bucket, each in -128..127.
 * The server stores them as int8 pairs, so this is a direct unpacking.
 */
export interface Peaks {
  hash: string;
  buckets: number;
  pairs: Array<[number, number]>;
}

/**
 * A labelled region of a sound, drawn as a tint over the waveform.
 *
 * Every classifier writes into one table, so a sound can carry three opinions
 * at once. The interface asks for one method at a time; see `SPAN_METHOD`.
 */
export interface Span {
  start_s: number;
  end_s: number;
  label: string;
  confidence?: number | null;
  detail?: string | null;
  method?: string | null;
}

/**
 * The classifier whose spans are drawn.
 *
 * The bakeoff put YAMNet and an unrelated model in agreement 82.9% of the
 * time, while CLAP agreed with neither. Tinting all three over each other says
 * nothing, so one is asked for by name and that one is YAMNet.
 */
export const SPAN_METHOD = "yamnet";

/** One measured stretch below the silence threshold. */
export interface SilenceInterval {
  start_s: number;
  end_s: number;
}

/**
 * Everything known about one sound's dead air.
 *
 * `intervals` arrives already filtered to `min_gap`; the client filters again
 * with the same floor, so a server that sends everything down to 0.4 seconds
 * and a server that pre-filters both work.
 *
 * `measured` is false when the sound has no measurement yet. That is different
 * from a measured sound with no silence, and the interface must not confuse
 * the two: one has nothing to say, the other has said there is no dead air.
 */
export interface Silence {
  hash: string;
  measured: boolean;
  min_gap: number;
  duration_s: number | null;
  sounding_s: number | null;
  silent_s: number;
  intervals: SilenceInterval[];
}

export interface Stats {
  files: number;
  total_bytes: number;
  total_duration_s: number | null;
  /**
   * Hours of actual sound across the index, dead air removed. Null until the
   * server reports it, in which case the header shows wall hours as before.
   */
  total_sounding_s: number | null;
}

/** Filters that define a set of sounds. */
export interface Query {
  q: string;
  ext: string;
  min_dur: string;
  max_dur: string;
  sort: SortKey;
  order: SortOrder;
  deleted: DeletedFilter;
}

export const EMPTY_QUERY: Query = {
  q: "",
  ext: "",
  min_dur: "",
  max_dur: "",
  sort: "name",
  order: "asc",
  deleted: "false",
};

/**
 * How much of the collection has been answered.
 *
 * A sound is decided when it has been taken into a project or discarded. There
 * is no third state, because there is no third action.
 */
export interface TriageCounts {
  total: number;
  decided: number;
  undecided: number;
  percent: number;
  /**
   * The split, when the server reports it. Null means it did not, and the
   * interface says nothing rather than printing a zero it made up.
   */
  taken: number | null;
  discarded: number | null;
}

/**
 * Where a swipe queue came from.
 *
 * `route` is `GET /api/swipe`. `derived` is the same queue worked out from the
 * routes that do exist — every undiscarded sound, less the ones already in a
 * project — for a server that does not serve the queue yet. Both are real; the
 * view says which, because a queue the client assembled can lag a queue the
 * server would have built.
 */
export type SwipeSource = "route" | "derived";

/**
 * What the queue answer carried about the sound at the head of it.
 *
 * `GET /api/swipe` sends the sound, its measured dead air and its spans
 * together, so a phone spends one request on a sound instead of three. Each
 * field is null when the answer did not carry it, and the view falls back to
 * the route that serves it on its own.
 *
 * It describes the head sound and no other. `hash` is here so a caller can say
 * which sound it belongs to: a buffer that has had answered sounds filtered
 * out of it can have a different sound in front, and that sound's silence is
 * not this one's.
 */
export interface SwipeCarried {
  hash: string;
  silence: Silence | null;
  spans: Span[] | null;
}

/** A batch of undecided sounds, and how many are left behind them. */
export interface SwipeQueue {
  items: FileRow[];
  /** Sounds still undecided, this batch included. */
  remaining: number;
  source: SwipeSource;
  /** What came with the head sound, or null when nothing did. */
  carried: SwipeCarried | null;
  /**
   * The project a "take it" would put the sound into, as the server named it.
   *
   * Null when the answer did not carry one, which is either a server that does
   * not send it or a bench with nothing on it. The view falls back to working
   * the bench out from the project index, which is the same answer by a longer
   * road.
   */
  project: ProjectSummary | null;
}

/** Every action `POST /api/bulk` accepts. */
export type BulkAction = "delete" | "restore";

/**
 * The cap on one bulk request, matching the server's.
 *
 * The selection bar refuses to send more than this rather than letting the
 * server reject a batch the user has already committed to.
 */
export const MAX_BULK_HASHES = 1000;

/** Counts from one bulk action. The server applies it whole or not at all. */
export interface BulkResult {
  action: BulkAction;
  requested: number;
  unique: number;
  matched: number;
  changed: number;
  unchanged: number;
  skipped: number;
}
