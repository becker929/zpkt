/**
 * Shapes the interface works with.
 *
 * A sound is identified by its BLAKE3 hash. A path is only an alias for a
 * hash, and one sound may have several. The client never sends a path to the
 * server; every route is addressed by hash.
 */

export type SortKey = "name" | "duration" | "size" | "sounding";
export type SortOrder = "asc" | "desc";

/**
 * Whether the view asks for discarded sounds.
 *
 * `false` is the default and the point of discarding: a sound the user does not
 * want stops appearing. `true` is the discard pile, where restore puts things
 * back. `any` is both together.
 */
export type DeletedFilter = "false" | "true" | "any";

/** One row of the list view. */
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
  alias_count: number;
  favorite: boolean;
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

/** One path that resolves to a hash. */
export interface Alias {
  path: string;
  root: string;
  filename: string;
  ext: string;
  mtime: number | null;
}

/** The detail view's sound. */
export interface FileDetail extends FileRow {
  sample_rate: number | null;
  channels: number | null;
  aliases: Alias[];
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
 * Stage 3 fills these in from the `span` table. Stage 2 only carries them
 * through, so the canvas already takes the prop it will need.
 */
export interface Span {
  start_s: number;
  end_s: number;
  label: string;
  confidence?: number | null;
  detail?: string | null;
  method?: string | null;
}

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

/**
 * One path of a duplicated sound, and whether removing it is safe.
 *
 * `deletable` is a warning, not a button. Nothing in this application removes
 * an audio file. A path inside a DAW project bundle is the project's own media:
 * the project reads it from that exact location, and the projects here exist
 * only in the read-only originals, so the damage would be permanent.
 */
export interface DupePath {
  path: string;
  root: string;
  in_bundle: boolean;
  deletable: boolean;
}

/** A hash with more than one alias. */
export interface DupeGroup {
  hash: string;
  filename: string;
  /** Copies counted under the current scoping, not the total number of paths. */
  alias_count: number;
  size_bytes: number;
  wasted_bytes: number;
  /** How many of this sound's paths sit inside a project bundle. */
  bundle_copies: number;
  paths: string[];
  entries: DupePath[];
}

/** A page of duplicate groups with the totals the cleanup view shows. */
export interface DupePage {
  items: DupeGroup[];
  total: number;
  wasted_bytes: number;
  include_bundles: boolean;
  /** Groups the bundle guard withheld, and the bytes they hold. */
  excluded_bundle_groups: number;
  excluded_bundle_bytes: number;
}

export interface Stats {
  files: number;
  aliases: number;
  total_bytes: number;
  wasted_bytes: number;
  duplicate_hashes: number;
  formats: Record<string, number>;
  total_duration_s: number | null;
  /**
   * Hours of actual sound across the index, dead air removed. Null until the
   * server reports it, in which case the header shows wall hours as before.
   */
  total_sounding_s: number | null;
}

/** Filters that define both the list view and the playlist's contents. */
export interface Query {
  q: string;
  ext: string;
  favorite: boolean;
  min_dur: string;
  max_dur: string;
  sort: SortKey;
  order: SortOrder;
  deleted: DeletedFilter;
}

export const EMPTY_QUERY: Query = {
  q: "",
  ext: "",
  favorite: false,
  min_dur: "",
  max_dur: "",
  sort: "name",
  order: "asc",
  deleted: "false",
};

/** One saved list, with the size of what is in it. */
export interface SoundList {
  id: number;
  name: string;
  created_at: string;
  member_count: number;
  duration_s: number;
  /** The same total with dead air removed. Null until the server reports it. */
  sounding_s: number | null;
  size_bytes: number;
}

/** One list and its members, in play order. */
export interface ListDetail extends SoundList {
  items: FileRow[];
}

/**
 * How much of the collection has been dealt with.
 *
 * A sound is triaged when it is starred, discarded, or in at least one list.
 * The three counts overlap, so they do not sum to `triaged`.
 */
export interface TriageCounts {
  total: number;
  triaged: number;
  untriaged: number;
  percent: number;
  starred: number;
  deleted: number;
  listed: number;
  lists: number;
}

/** Every action `POST /api/bulk` accepts. */
export type BulkAction = "star" | "unstar" | "delete" | "restore" | "add_to_list" | "remove_from_list";

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
  list_id: number | null;
  requested: number;
  unique: number;
  matched: number;
  changed: number;
  unchanged: number;
  skipped: number;
}
