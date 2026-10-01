/**
 * Silence: what counts as a gap, how long a sound really sounds, and where the
 * player should jump to.
 *
 * Pure functions only. Nothing here touches the audio element, the network, or
 * React. The player and the waveform both read from this, so the rule about
 * what is skippable is written once.
 *
 * The server measures every gap down to 0.4 seconds and hands them all over.
 * The floor is applied here, at read time, so it is a setting rather than a
 * property of the data.
 */

import type { SilenceInterval } from "./types";

/**
 * The shortest gap worth skipping, in seconds.
 *
 * Measured over the whole collection, a 2 second floor recovers 10.4 of the
 * 11.5 available hours. Going down to 0.4 seconds buys 1.1 hours more and
 * jumps over musical rests and the gap between two drum hits, so the player
 * would jitter. Two seconds never lands inside a phrase.
 */
export const MIN_GAP_S = 2.0;

/**
 * How far sounding and wall duration must differ before both are shown.
 *
 * Under this, the two numbers say the same thing and printing both is noise.
 * Over it, the difference is itself the information: a five minute file with
 * forty seconds of sound is a stem that barely plays.
 */
export const WALL_GAP_S = 3.0;

/** Land just inside the sound, so the skip does not re-trigger on its own edge. */
export const SKIP_NUDGE_S = 0.02;

/**
 * A gap ending this close to the end is the end.
 *
 * Wall duration comes from ffprobe and the audio element disagrees with it by
 * a frame or two, so an exact comparison would never match.
 */
export const TAIL_S = 0.4;

/** Sorted, clamped, non-overlapping, and longer than the floor. */
export function skippable(
  intervals: readonly SilenceInterval[],
  minGap: number = MIN_GAP_S,
  durationS?: number | null,
): SilenceInterval[] {
  const limit = durationS && durationS > 0 ? durationS : null;
  const clamped: SilenceInterval[] = [];
  for (const interval of intervals) {
    const start = Math.max(0, interval.start_s);
    const end = limit === null ? interval.end_s : Math.min(interval.end_s, limit);
    if (end - start >= minGap) clamped.push({ start_s: start, end_s: end });
  }
  clamped.sort((a, b) => a.start_s - b.start_s);

  // ffmpeg reports gaps in order and apart, but a later measurement pass or a
  // hand-written row could overlap. Merging keeps the arithmetic honest.
  const merged: SilenceInterval[] = [];
  for (const interval of clamped) {
    const last = merged[merged.length - 1];
    if (last && interval.start_s <= last.end_s) {
      if (interval.end_s > last.end_s) last.end_s = interval.end_s;
      continue;
    }
    merged.push({ ...interval });
  }
  return merged;
}

/** Total seconds inside the given gaps. Assumes `skippable` has run. */
export function silentSeconds(intervals: readonly SilenceInterval[]): number {
  let total = 0;
  for (const interval of intervals) total += Math.max(0, interval.end_s - interval.start_s);
  return total;
}

/**
 * Wall duration minus every gap of at least `minGap`.
 *
 * Returns null when the wall duration is unknown, because a sounding duration
 * derived from nothing is worse than no number at all.
 */
export function soundingSeconds(
  durationS: number | null | undefined,
  intervals: readonly SilenceInterval[],
  minGap: number = MIN_GAP_S,
): number | null {
  if (durationS === null || durationS === undefined || !Number.isFinite(durationS)) return null;
  const gaps = skippable(intervals, minGap, durationS);
  return Math.max(0, durationS - silentSeconds(gaps));
}

/** The gap containing `t`, or null. Assumes `skippable` has run. */
export function intervalAt(
  intervals: readonly SilenceInterval[],
  t: number,
): SilenceInterval | null {
  for (const interval of intervals) {
    if (t >= interval.start_s && t < interval.end_s) return interval;
    // Sorted, so nothing further along can contain an earlier time.
    if (interval.start_s > t) break;
  }
  return null;
}

/** True when this gap runs to the end of the sound, so there is nothing after it. */
export function isTrailing(
  interval: SilenceInterval,
  durationS: number | null | undefined,
): boolean {
  if (durationS === null || durationS === undefined || !Number.isFinite(durationS) || durationS <= 0) {
    return false;
  }
  return interval.end_s >= durationS - TAIL_S;
}

/** True when both numbers are known and far enough apart to be worth printing. */
export function differsMeaningfully(
  soundingS: number | null | undefined,
  wallS: number | null | undefined,
): boolean {
  if (soundingS === null || soundingS === undefined) return false;
  if (wallS === null || wallS === undefined) return false;
  if (!Number.isFinite(soundingS) || !Number.isFinite(wallS)) return false;
  return wallS - soundingS >= WALL_GAP_S;
}

/** What the player should do at time `t`. Null means carry on playing. */
export type SkipDecision =
  | { kind: "seek"; to: number; interval: SilenceInterval }
  | { kind: "end"; interval: SilenceInterval };

/**
 * Decide whether to jump, given where the playhead is.
 *
 * `excused` is a gap the user scrubbed into on purpose. An explicit seek is an
 * instruction, and the skipper does not argue with it: while the playhead is
 * inside that gap, nothing happens. This is the whole difference between a
 * player that saves ten hours and one that cannot be used.
 */
export function decideSkip(options: {
  t: number;
  intervals: readonly SilenceInterval[];
  durationS: number | null | undefined;
  excused?: SilenceInterval | null;
}): SkipDecision | null {
  const here = intervalAt(options.intervals, options.t);
  if (!here) return null;
  const excused = options.excused;
  if (excused && excused.start_s === here.start_s && excused.end_s === here.end_s) return null;
  if (isTrailing(here, options.durationS)) return { kind: "end", interval: here };
  return { kind: "seek", to: here.end_s + SKIP_NUDGE_S, interval: here };
}
