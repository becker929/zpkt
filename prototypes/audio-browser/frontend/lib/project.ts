/**
 * The project model. One definition, two languages.
 *
 * Zod is the source of truth. `npm run schema` emits JSON Schema from these
 * declarations into `audio-browser/schemas/`, and Python validates project
 * files against that generated file with `jsonschema`. Neither language keeps a
 * second hand-written copy.
 *
 * A project is a real JSON file in `audio-browser/projects/`, one file per
 * project, named after its `id`. The file is the truth. SQLite indexes the
 * files so the board can be drawn without reading all of them, but the index is
 * a cache: if the two disagree, the files win.
 *
 * Everything here is pure. No fetching, no clock, no randomness. The effectful
 * parts live in `lib/api.ts` and the route handlers, so both languages can
 * share the rules without sharing a runtime.
 */

import { z } from "zod";

/** Bumped when the document shape changes in a way old files do not satisfy. */
export const SCHEMA_VERSION = 1;

/**
 * The most sounds one project may hold.
 *
 * A hard industrial techno track is assembled from tens of sounds, not
 * thousands. The cap exists so a runaway bulk add cannot write a document the
 * board then has to read on every draw.
 */
export const MAX_PROJECT_SOUNDS = 512;

export const MAX_NAME_LENGTH = 120;

/* Columns and the one place that is not a column --------------------------- */

/**
 * The board. Three columns, in order.
 *
 * Every column has its own commit, and each commit freezes that column's own
 * artifact. Commit is not a column; it is the interface at a column's edge.
 */
export const COLUMNS = ["stored", "collage", "enrich"] as const;
export type Column = (typeof COLUMNS)[number];

/**
 * Where a project sits. The three columns, plus `released`.
 *
 * A project leaving `enrich` is released. It is off the board and occupies no
 * slot anywhere, which is what makes finishing something the way to get room to
 * start another.
 */
export const PLACEMENTS = [...COLUMNS, "released"] as const;
export type Placement = (typeof PLACEMENTS)[number];

/** What happens in each column, and what committing out of it freezes. */
export const COLUMN_WORK: Record<Column, string> = {
  stored: "assign sounds from the library",
  collage: "cut, move, balance",
  enrich: "effects",
};

export const COLUMN_FREEZES: Record<Column, string> = {
  stored: "the sound set",
  collage: "the arrangement",
  enrich: "the treatment",
};

export const columnSchema = z.enum(COLUMNS);
export const placementSchema = z.enum(PLACEMENTS);

/** Where a project goes when this column commits. `enrich` commits to release. */
export function nextPlacement(column: Column): Placement {
  const at = COLUMNS.indexOf(column);
  return at === COLUMNS.length - 1 ? "released" : COLUMNS[at + 1];
}

/** The columns a placement still has ahead of it, in order. */
export function isColumn(placement: Placement): placement is Column {
  return placement !== "released";
}

/* Field shapes ------------------------------------------------------------- */

/**
 * End of string, written so that Python reads it the way JavaScript does.
 *
 * Every pattern below is copied verbatim into the generated JSON Schema, and
 * Python's `jsonschema` applies it with `re.search`, where `$` also matches just
 * before a trailing newline. `"a".repeat(64) + "\n"` therefore passes `^[0-9a-f]
 * {64}$` in Python while Zod rejects it, and the two languages stop agreeing
 * about the same file. A negative lookahead for any character means the same
 * thing in both.
 */
const END = "(?![\\s\\S])";

/** A BLAKE3 content hash, lower case hex. A sound is never addressed by path. */
export const hashSchema = z
  .string()
  .regex(new RegExp(`^[0-9a-f]{64}${END}`), "a hash is 64 lower-case hex characters");

/** The BLAKE3 of a stage's artifact. Same shape as a hash, different meaning. */
export const digestSchema = z
  .string()
  .regex(new RegExp(`^[0-9a-f]{64}${END}`), "a digest is 64 lower-case hex characters");

/**
 * An instant in UTC, as `2026-09-16T21:04:00Z`. Local times are refused.
 *
 * The pattern is not redundant with `.datetime()`. Zod's check becomes
 * `"format": "date-time"` in the emitted JSON Schema, and `format` is advisory:
 * `jsonschema` ignores it unless a format checker is installed, and RFC 3339
 * allows an offset even then. The pattern is what actually holds the line at
 * UTC on the Python side, so that two timestamps can be ordered by comparing
 * the strings.
 *
 * The fields are range-bounded rather than four loose pairs of digits. `\d{2}`
 * would let `2026-99-99T99:99:99Z` through the generated schema, which Zod
 * rejects, and a chain of instants that are not times cannot be put in order by
 * anything. February the thirtieth still gets past both; a regular expression is
 * the wrong tool for the length of a month.
 */
export const instantSchema = z
  .string()
  .datetime({ offset: false })
  .regex(
    new RegExp(
      `^\\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\\d|3[01])T(?:[01]\\d|2[0-3]):[0-5]\\d:[0-5]\\d(?:\\.\\d+)?Z${END}`,
    ),
    "an instant is ISO 8601 in UTC, ending in Z",
  );

/**
 * The slug that is both the `id` and the filename.
 *
 * Lower case, digits and single hyphens. It has to survive being a filename on
 * a case-insensitive filesystem, so nothing here may differ only by case.
 */
export const slugSchema = z
  .string()
  .min(1)
  .max(100)
  .regex(
    new RegExp(`^[a-z0-9]+(?:-[a-z0-9]+)*${END}`),
    "a slug is lower-case words joined by single hyphens",
  );

/**
 * A display name: one line, no leading or trailing whitespace.
 *
 * Names are not unique. Two projects may both be called "rust and rebar"; they
 * are told apart by their `id`, which is unique because it is a filename.
 */
export const nameSchema = z
  .string()
  .min(1)
  .max(MAX_NAME_LENGTH)
  .regex(
    new RegExp(`^\\S(?:.*\\S)?${END}`),
    "a name is one line with no leading or trailing space",
  );

/**
 * When a project left the board without being promoted, and what it left.
 *
 * `from` is the column it was in. It repeats `column`, which the document keeps
 * so revive knows where to put the project back; `checkProject` refuses a file
 * where the two disagree, so the repetition cannot rot.
 *
 * This is a separate field and never a value of `column`. Overloading `column`
 * would collapse the four branches below into one and take the commit chain's
 * invariant with it: "abandoned" carries no information about which stages were
 * frozen, so a chain of any length would have to be allowed against it.
 */
export const abandonmentSchema = z
  .object({
    at: instantSchema,
    from: columnSchema,
    reason: z.string().max(2000),
  })
  .strict();

export type Abandonment = z.infer<typeof abandonmentSchema>;

/**
 * One sound in a project.
 *
 * `role` is a free slot for the later columns: `kick`, `rumble`, `texture`. It
 * is null until something sets it, and no column may widen this schema to suit
 * itself.
 */
export const projectSoundSchema = z
  .object({
    hash: hashSchema,
    added_at: instantSchema,
    role: z.string().min(1).max(40).nullable(),
    note: z.string().max(2000),
  })
  .strict();

export type ProjectSound = z.infer<typeof projectSoundSchema>;

/** One entry in the chain: which stage was frozen, when, and what it froze. */
function commitEntrySchema<C extends Column>(column: C) {
  return z
    .object({
      column: z.literal(column),
      at: instantSchema,
      digest: digestSchema,
    })
    .strict();
}

/** The chain entry for any stage, for consumers that do not care which. */
export const anyCommitSchema = z
  .object({ column: columnSchema, at: instantSchema, digest: digestSchema })
  .strict();

export type Commit = z.infer<typeof anyCommitSchema>;

/** The fields every project has, wherever it sits. */
const commonFields = {
  schema_version: z.literal(SCHEMA_VERSION),
  id: slugSchema,
  name: nameSchema,
  created_at: instantSchema,
  updated_at: instantSchema,
  notes: z.string().max(10_000),
  /**
   * Non-null means off the board, holding no slot. Cleared by revive.
   *
   * Abandoning appends nothing to `commits`, so a revived project comes back
   * with exactly the stages it had frozen before.
   */
  abandoned: abandonmentSchema.nullable(),
  sounds: z.array(projectSoundSchema).max(MAX_PROJECT_SOUNDS),
};

/**
 * The four documents, one per placement.
 *
 * `commits` is append only and is exactly the stages already passed, in board
 * order. Writing that as four fixed-length branches rather than as a cross-field
 * rule is what lets the emitted JSON Schema carry the invariant: a `.refine()`
 * is dropped on the way out, and Python would then validate something weaker
 * than this file says. Out of order, repeated, or missing entries are all
 * rejected by the generated schema, not only by TypeScript.
 *
 * It also means one thing can never happen: a project cannot sit in `collage`
 * without a `stored` commit, so "the sound set is frozen from `collage`
 * onwards" is a property of the format rather than a rule the app promises.
 *
 * Abandoning is a separate nullable field and not a fifth branch, because being
 * off the board says nothing about which stages were frozen. A project
 * abandoned out of `collage` is still a `collage` document, chain and all, and
 * reviving it is clearing one field rather than rebuilding a chain.
 */
const storedProjectSchema = z
  .object({
    ...commonFields,
    column: z.literal("stored"),
    // An empty array, written as a capped array rather than as `z.tuple([])`:
    // an empty tuple emits `"items": []`, which draft 7 rejects as a schema.
    commits: z.array(anyCommitSchema).max(0),
  })
  .strict();

const collageProjectSchema = z
  .object({
    ...commonFields,
    column: z.literal("collage"),
    commits: z.tuple([commitEntrySchema("stored")]),
  })
  .strict();

const enrichProjectSchema = z
  .object({
    ...commonFields,
    column: z.literal("enrich"),
    commits: z.tuple([commitEntrySchema("stored"), commitEntrySchema("collage")]),
  })
  .strict();

const releasedProjectSchema = z
  .object({
    ...commonFields,
    column: z.literal("released"),
    // A released project is already off the board and holds no slot. There is
    // nothing for abandoning to free and nothing for revive to put back, so the
    // format does not let a file claim both at once.
    abandoned: z.null(),
    commits: z.tuple([
      commitEntrySchema("stored"),
      commitEntrySchema("collage"),
      commitEntrySchema("enrich"),
    ]),
  })
  .strict();

export const projectDocumentSchema = z.discriminatedUnion("column", [
  storedProjectSchema,
  collageProjectSchema,
  enrichProjectSchema,
  releasedProjectSchema,
]);

export type ProjectDocument = z.infer<typeof projectDocumentSchema>;

/* What a commit freezes ---------------------------------------------------- */

/**
 * The exact bytes a stage digests, and whether that artifact is real yet.
 *
 * `stored` owns the sound set, and its artifact is the one the specification
 * fixes: the member hashes, deduplicated, sorted, and joined by newline with no
 * trailing newline. Both languages must agree on it byte for byte or the freeze
 * is not checkable, which is why it is a function and not a sentence in a
 * document.
 *
 * `collage` and `enrich` own an arrangement and a treatment, and neither view
 * exists yet. Their artifact is therefore a placeholder: deterministic and
 * different for every project, so two commits never collide, but `real` is
 * false and the interface says so rather than presenting a digest of nothing as
 * a digest of something. When those views land, this is the one function that
 * changes.
 */
export function commitArtifact(
  project: Pick<ProjectDocument, "id" | "sounds">,
  column: Column,
): { input: string; real: boolean } {
  const manifest = manifestInput(project.sounds.map((sound) => sound.hash));
  if (column === "stored") return { input: manifest, real: true };
  return { input: `${column} ${project.id} ${manifest}`, real: false };
}

/**
 * Exactly what `stored` hashes: member hashes, deduplicated, sorted, joined by
 * newline, no trailing newline.
 */
export function manifestInput(hashes: readonly string[]): string {
  return [...new Set(hashes)].sort().join("\n");
}

/* The index's view of a project ------------------------------------------- */

/**
 * One row of `GET /api/projects`: enough to draw a card without opening the
 * file.
 *
 * Every measure may be absent, and absent is null rather than zero. A length of
 * 0:00 against a project holding four minutes of audio is a lie, and the board
 * would rather say nothing.
 */
export const projectSummarySchema = z
  .object({
    id: slugSchema,
    name: nameSchema,
    column: placementSchema,
    created_at: instantSchema,
    updated_at: instantSchema,
    /** Non-null means off the board. The card draws it; the caps do not count it. */
    abandoned: abandonmentSchema.nullable(),
    commits: z.array(anyCommitSchema),
    sound_count: z.number().int().nonnegative(),
    duration_s: z.number().nonnegative().nullable(),
    sounding_s: z.number().nonnegative().nullable(),
    size_bytes: z.number().nonnegative().nullable(),
    /**
     * Whether the member hashes still hash to the digest frozen by the `stored`
     * commit.
     *
     * Null means the server did not check, or there is nothing to check yet.
     * False means the file was edited after the freeze, which is exactly the
     * thing the digest exists to make visible.
     */
    sound_set_verified: z.boolean().nullable(),
  })
  .strict();

export type ProjectSummary = z.infer<typeof projectSummarySchema>;

/** The `stored` commit, if the sound set has been frozen. */
export function storedCommit(commits: readonly Commit[]): Commit | null {
  return commits.find((commit) => commit.column === "stored") ?? null;
}

/**
 * Whether this project is in play: in a column, and not abandoned.
 *
 * This is the one test the caps use. A released project and an abandoned one
 * are both off the board and both hold no slot, which is what makes finishing
 * something — or letting it go — the way to get room to start another.
 */
export function onBoard(project: Pick<ProjectSummary, "column" | "abandoned">): boolean {
  return isColumn(project.column) && project.abandoned === null;
}

/**
 * Whether this project can still gain or lose a sound.
 *
 * Three conditions, all checked: it is in `stored`, it is on the board, and no
 * `stored` commit exists. Any one alone would be enough in a consistent file,
 * and checking all three is what makes a hand-edited file fail closed.
 */
export function soundSetOpen(
  project: Pick<ProjectSummary, "column" | "commits" | "abandoned">,
): boolean {
  return project.column === "stored" && project.abandoned === null && storedCommit(project.commits) === null;
}

/* The board ---------------------------------------------------------------- */

/**
 * One column of `GET /api/board`.
 *
 * `over` is the server's own reading of its own cap, carried explicitly so the
 * client never has to decide what counts as over.
 */
export const boardColumnSchema = z
  .object({
    column: columnSchema,
    /**
     * Slots in this column. Zero is a real setting and means the column is
     * closed: nothing may be put into it without an explicit override, and a
     * column that already holds something reads as over its limit at once.
     */
    cap: z.number().int().nonnegative(),
    count: z.number().int().nonnegative(),
    /**
     * How many of `count` are files that could not be read.
     *
     * A file whose `column` can be read still holds the slot it is sitting in,
     * even when the rest of it is nonsense. Skipping it would let one junk key
     * free a slot, which is a cap bypass that needs no override.
     */
    unreadable: z.number().int().nonnegative(),
    over: z.boolean(),
  })
  .strict();

export type BoardColumn = z.infer<typeof boardColumnSchema>;

export const boardSchema = z
  .object({
    /**
     * The columns the server is serving, in board order.
     *
     * Not fixed at three. A column exists on the board when there is a view
     * for it: `enrich` has none yet, so a server may serve two. What the board
     * must never do is draw a column the server did not report — an occupancy
     * that came from nowhere is worse than a column that is not there.
     */
    columns: z.array(boardColumnSchema).min(1).max(COLUMNS.length),
    /** Released projects. Off the board; they occupy no slot and have no cap. */
    released: z.number().int().nonnegative(),
    /** Abandoned projects. Off the board too, and revivable. */
    abandoned: z.number().int().nonnegative(),
    /**
     * Project files that do not match this schema, wherever they sit.
     *
     * One whose `column` can still be read holds its slot and is counted in
     * that column as well. One whose column cannot be read is counted here
     * only, because a file that cannot be placed cannot be put in a column.
     */
    unreadable: z.number().int().nonnegative(),
  })
  .strict();

export type Board = z.infer<typeof boardSchema>;

/** Over its limit. At a cap of 0 anything at all is over it. */
export function isOver(count: number, cap: number): boolean {
  return count > cap;
}

/**
 * The column an unreadable file is still holding a slot in, if any.
 *
 * `occupancy` cannot ask the schema about a file the schema rejects, so it asks
 * this instead: the one field the cap needs is `column`, and it is readable on
 * its own. A file naming a column holds a slot there until somebody fixes it. A
 * file whose column is `released`, missing, or not a column holds nothing,
 * because there is no column to hold it in.
 *
 * A file that says it was abandoned is taken at its word and holds nothing.
 * That is not a way round the cap: abandoning is a supported move that frees a
 * slot anyway, and it is reversible.
 */
export function slotHolder(raw: unknown): Column | null {
  const row = raw as { column?: unknown; abandoned?: unknown } | null | undefined;
  const column = typeof row?.column === "string" ? row.column : null;
  if (column === null || !(COLUMNS as readonly string[]).includes(column)) return null;
  if (row?.abandoned !== null && row?.abandoned !== undefined) return null;
  return column as Column;
}

/* Identity ----------------------------------------------------------------- */

/**
 * Letters that have a Latin reading but that `NFKD` does not take apart.
 *
 * `NFKD` splits `é` into `e` plus a combining mark, so accented Latin survives
 * the strip below on its own. It does nothing for a different script, and it
 * does nothing for a letter that is one character rather than a letter plus a
 * mark. Both are handled here, letter by letter, so that a Cyrillic or Greek
 * name keeps its sound in the id instead of losing everything but its digits.
 *
 * Keys are lower case, because the name is lower cased before the lookup.
 */
const TRANSLITERATED: Readonly<Record<string, string>> = {
  // Cyrillic, in the reading English uses for it.
  а: "a", б: "b", в: "v", г: "g", ґ: "g", д: "d", е: "e", ё: "e", є: "ye",
  ж: "zh", з: "z", и: "i", і: "i", ї: "yi", й: "i", к: "k", л: "l", м: "m",
  н: "n", о: "o", п: "p", р: "r", с: "s", т: "t", у: "u", ф: "f", х: "kh",
  ц: "ts", ч: "ch", ш: "sh", щ: "shch", ъ: "", ы: "y", ь: "", э: "e",
  ю: "yu", я: "ya",
  // Greek.
  α: "a", β: "v", γ: "g", δ: "d", ε: "e", ζ: "z", η: "i", θ: "th", ι: "i",
  κ: "k", λ: "l", μ: "m", ν: "n", ξ: "x", ο: "o", π: "p", ρ: "r", σ: "s",
  ς: "s", τ: "t", υ: "y", φ: "f", χ: "ch", ψ: "ps", ω: "o",
  // Latin letters that are one character and not a letter plus a mark.
  ß: "ss", æ: "ae", œ: "oe", ø: "o", å: "aa", đ: "d", ð: "d", þ: "th", ł: "l",
};

/**
 * The name with every script this knows read into Latin letters.
 *
 * The combining marks `NFKD` leaves behind are removed rather than replaced.
 * `slugify` turns any run of characters it cannot use into a hyphen, so a mark
 * left in place would cut the word it belongs to in two: `béton` decomposes to
 * `b`, `e`, an acute accent, `t`, `o`, `n`, and the accent would make that
 * `be-ton`. Dropping the mark is what makes the id read as the word does.
 */
function transliterate(name: string): string {
  let out = "";
  for (const character of name.normalize("NFKD").toLowerCase().replace(/\p{M}/gu, "")) {
    out += TRANSLITERATED[character] ?? character;
  }
  return out;
}

/**
 * A slug built from the code points of a name that has no Latin reading at all.
 *
 * `🔥🔥🔥` is not transliterable, and calling it `project` would make the id say
 * nothing about the project. This names the characters themselves: `u1f525`.
 * It is derived only from the name, so it is the same every time, and two
 * different names cannot land on it by accident.
 *
 * Repeats are dropped and the first four distinct characters are enough; the
 * date in front and `uniqueProjectId` behind settle anything that still meets.
 */
function codePointSlug(name: string): string {
  const tokens: string[] = [];
  for (const character of name) {
    const code = character.codePointAt(0);
    // Spaces and control characters name nothing.
    if (code === undefined || code <= 0x20) continue;
    // Nor do the invisible characters that only change how the one before them
    // is drawn: a variation selector after an emoji would put `ufe0f` in the id
    // and say nothing about the project.
    if (/[\p{M}\p{Cf}]/u.test(character)) continue;
    const token = `u${code.toString(16)}`;
    if (!tokens.includes(token)) tokens.push(token);
    if (tokens.length === 4) break;
  }
  return tokens.join("-");
}

/**
 * The name reduced to slug characters.
 *
 * Three steps, in order, each one a fallback for the last: read the name into
 * Latin letters, then name its characters by their code points, then give up
 * and call it `project`. The slug is a filename, so it cannot be nothing; a
 * meaningless one is nearly as bad, so `техно 909` becomes `tekhno-909` rather
 * than `909`, and `🔥🔥🔥` becomes `u1f525` rather than `project`.
 */
export function slugify(name: string): string {
  const latin = transliterate(name)
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80)
    .replace(/-+$/g, "");
  if (latin) return latin;
  return codePointSlug(name) || "project";
}

/**
 * The id a new project would take: the day it was made, then its name.
 *
 * Two projects made on one day with one name produce one id, which is a
 * collision and not a merge. `uniqueProjectId` resolves it.
 */
export function projectId(name: string, createdAt: string): string {
  return `${createdAt.slice(0, 10)}-${slugify(name)}`;
}

/**
 * The first free id in the family `base`, `base-2`, `base-3`, …
 *
 * Duplicate names are allowed; duplicate files are not. The caller passes every
 * id already on disk.
 */
export function uniqueProjectId(base: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  if (!used.has(base)) return base;
  for (let n = 2; n < 1000; n += 1) {
    const candidate = `${base}-${n}`;
    if (!used.has(candidate)) return candidate;
  }
  throw new Error(`no free id in the family "${base}"`);
}

/* Validation --------------------------------------------------------------- */

/** Hashes that appear more than once in a document's `sounds`. */
export function duplicateHashes(sounds: readonly { hash: string }[]): string[] {
  const seen = new Set<string>();
  const twice = new Set<string>();
  for (const sound of sounds) {
    if (seen.has(sound.hash)) twice.add(sound.hash);
    seen.add(sound.hash);
  }
  return [...twice];
}

/** A problem with a document, in the shape `safeParse` reports. */
export interface ProjectIssue {
  path: string;
  message: string;
}

export type ProjectCheck =
  | { ok: true; project: ProjectDocument }
  | { ok: false; issues: ProjectIssue[] };

/**
 * Validate a document, including the rules JSON Schema cannot carry.
 *
 * Draft 7 can say "unique items" but not "unique by one key", and it cannot
 * compare two fields, so membership uniqueness and the ordering of timestamps
 * are checked here, along with the two fields an abandonment has to agree with.
 * Anything that reads a project file has to run both: the schema alone is
 * necessary, not sufficient. The Python side must mirror every check below
 * after `jsonschema` passes.
 */
export function checkProject(raw: unknown): ProjectCheck {
  const parsed = projectDocumentSchema.safeParse(raw);
  if (!parsed.success) {
    return {
      ok: false,
      issues: parsed.error.issues.map((issue) => ({
        path: issue.path.join(".") || "(root)",
        message: issue.message,
      })),
    };
  }

  const project = parsed.data;
  const issues: ProjectIssue[] = [];

  const twice = duplicateHashes(project.sounds);
  if (twice.length > 0) {
    issues.push({
      path: "sounds",
      message: `membership is a set: ${twice.length} hash${twice.length === 1 ? "" : "es"} appear more than once`,
    });
  }

  if (project.updated_at < project.created_at) {
    issues.push({ path: "updated_at", message: "updated_at is before created_at" });
  }

  // The chain is append only, so its instants never go backwards and never
  // predate the project itself. ISO 8601 in UTC sorts lexically, so string
  // comparison is the right comparison and needs no date parsing.
  let previous = project.created_at;
  project.commits.forEach((commit, index) => {
    if (commit.at < previous) {
      issues.push({
        path: `commits.${index}.at`,
        message: `the ${commit.column} commit is dated before the entry above it`,
      });
    }
    previous = commit.at;
  });

  // `abandoned.from` is the column revive puts the project back into, and
  // `column` is where the board says it was. Draft 7 cannot compare two fields,
  // so a file where they disagree is caught here. Letting it through would mean
  // revive and the board disagreed about the same project.
  if (project.abandoned !== null) {
    if (project.abandoned.from !== project.column) {
      issues.push({
        path: "abandoned.from",
        message: `it was abandoned out of ${project.abandoned.from} but the file says it is in ${project.column}`,
      });
    }
    if (project.abandoned.at < previous) {
      issues.push({
        path: "abandoned.at",
        message: "it was abandoned before the last thing that happened to it",
      });
    }
  }

  return issues.length === 0 ? { ok: true, project } : { ok: false, issues };
}

/** A one-line reading of what is wrong with a file, for the interface. */
export function describeIssues(issues: readonly ProjectIssue[]): string {
  return issues.map((issue) => `${issue.path}: ${issue.message}`).join("; ");
}
