/**
 * The caps.
 *
 * How many projects one column may hold, and how many sounds one project holds
 * before it is marked encumbered. Both are friction rather than restriction:
 * going past either is possible, visible, and stays visible.
 *
 * How many projects one column may hold. Turning it down is the point: 2, or 1,
 * are reasonable settings and this is the one line to change.
 *
 * At 1 the board is at its most honest. One thing in `stored`, one in
 * `collage`, one in `enrich`, and the only way to start another is to finish the
 * one in front of you.
 *
 * `NEXT_PUBLIC_COLUMN_CAP` overrides it without an edit, which is how the
 * browser tests exercise a cap of 1 against the same source.
 */
const DEFAULT_COLUMN_CAP = 3;

/**
 * What a cap that cannot be read falls back to.
 *
 * It is the tightest setting, not the default, and that direction is the whole
 * decision. Somebody who edits this value is almost always turning it down; a
 * typo in that edit must not hand them the loosest board in the application
 * while looking exactly like the board they asked for. Erring tight is
 * uncomfortable and obvious, and `CAP_PROBLEM` says on every view what happened
 * and how to fix it. Erring loose is comfortable, silent, and the opposite of
 * what was asked for.
 *
 * Nothing is blocked by it. A cap of 1 still takes an override, as every cap
 * does: friction, not restriction.
 */
const FALLBACK_COLUMN_CAP = 1;

export interface CapConfig {
  /** The cap in force. */
  cap: number;
  /** What `NEXT_PUBLIC_COLUMN_CAP` was set to, or null when it was not set. */
  raw: string | null;
  /** Null when the setting was readable. A sentence for the interface when it was not. */
  problem: string | null;
}

/**
 * Read the configured cap.
 *
 * A whole number of zero or more is taken as it stands. **Zero is a legitimate
 * setting and means the column is closed**: nothing new goes into it without an
 * explicit override, and a column that already holds something reads as over
 * its limit the moment the board is drawn. It is the honest way to say "not
 * this stage, not now" — mothballing `enrich` while a batch of material goes
 * through `stored` — and it needs no new concept, because a closed column is
 * just the cap doing what the cap already does.
 *
 * Anything else — a fraction, a negative number, a word — is a mistake, not a
 * setting. It is refused rather than rounded, the board falls back to the
 * tightest cap, and the interface says so until it is fixed.
 */
function readCap(): CapConfig {
  const raw = process.env.NEXT_PUBLIC_COLUMN_CAP;
  if (raw === undefined || raw.trim() === "") {
    return { cap: DEFAULT_COLUMN_CAP, raw: null, problem: null };
  }

  const parsed = Number(raw);
  if (Number.isInteger(parsed) && parsed >= 0) return { cap: parsed, raw, problem: null };

  return {
    cap: FALLBACK_COLUMN_CAP,
    raw,
    problem:
      `NEXT_PUBLIC_COLUMN_CAP is set to “${raw}”, which is not a whole number of slots. ` +
      `Every column is running at ${FALLBACK_COLUMN_CAP} until that is fixed. A cap nobody can ` +
      `read tightens rather than loosens: a typo while turning the cap down must not quietly ` +
      `hand back the loosest board there is.`,
  };
}

export const CAP_CONFIG: CapConfig = readCap();

/**
 * The cap the mock server serves and the value recorded in the generated
 * schemas.
 *
 * The interface never uses this to draw a column. It draws the cap that
 * `GET /api/board` reports, because the server is the one enforcing it, and a
 * client that drew its own idea of the cap could show a column as fine while
 * the server was refusing writes to it.
 */
export const COLUMN_CAP = CAP_CONFIG.cap;

/**
 * The sentence to put on screen when the setting could not be read, or null.
 *
 * `NEXT_PUBLIC_COLUMN_CAP` is inlined when the code is compiled, so the server
 * and the browser read the same value here and the banner cannot differ between
 * them during hydration.
 */
export const CAP_PROBLEM: string | null = CAP_CONFIG.problem;

/**
 * How many sounds a project holds before it is marked encumbered.
 *
 * A hard techno track is a kick, a rumble, a few percussive textures, two or
 * three atmospheres and some impacts. Past sixteen you are collecting rather
 * than building, and the project says so every time it is on screen.
 *
 * This is a mark, not a limit. Adding still works; the mark stays until the
 * count comes back down. `NEXT_PUBLIC_ENCUMBERED_AT` overrides it without an
 * edit, in the same way `NEXT_PUBLIC_COLUMN_CAP` overrides the cap above.
 */
const DEFAULT_ENCUMBERED_AT = 16;

function readEncumberedAt(): number {
  const raw = process.env.NEXT_PUBLIC_ENCUMBERED_AT;
  if (raw === undefined || raw.trim() === "") return DEFAULT_ENCUMBERED_AT;
  const parsed = Number(raw);
  // A threshold nobody can read falls back to the written default rather than
  // to zero. Zero would mark every project the moment it held one sound, which
  // would make the mark mean nothing.
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : DEFAULT_ENCUMBERED_AT;
}

export const ENCUMBERED_AT: number = readEncumberedAt();

/** True once a project holds more material than a track needs. */
export function isEncumbered(soundCount: number): boolean {
  return soundCount > ENCUMBERED_AT;
}
