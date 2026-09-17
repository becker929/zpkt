/**
 * What a sound's set of paths means.
 *
 * A hash is the identity of a sound and a path is only a name for it, so the
 * same bytes reached by several paths is normal. What is *not* uniform is what
 * that repetition costs, and the three cases are easy to confuse:
 *
 * - The same sound once under each root. `audio-library/` is a deliberate
 *   working copy of `compost/`, so work never touches the originals. This is
 *   the intended state. Calling it waste would advise deleting the safety copy.
 * - The same sound twice inside one root, in ordinary folders. Real
 *   redundancy: keeping one frees the rest.
 * - The same sound in several Logic project bundles. Each project reads its own
 *   copy from that exact path, and the projects here exist only in the
 *   read-only originals, so no copy can go.
 *
 * Nothing in this application deletes audio. These functions decide what the
 * interface *says*, which is the part that can still mislead.
 */

import type { Alias } from "./types";

/** Directory suffixes that mark a DAW project bundle. */
const BUNDLE_SUFFIXES = [".logicx/"];

/**
 * True when a path sits inside a DAW project bundle.
 *
 * The test is on a directory component, so `Song.logicx/Media/take.wav` matches
 * and a file merely named `mix.logicx.wav` does not.
 */
export function isBundlePath(path: string): boolean {
  const lower = path.toLowerCase();
  return BUNDLE_SUFFIXES.some((suffix) => lower.includes(suffix));
}

/** How many times this sound repeats inside a single root. */
export function copiesWithinOneRoot(aliases: Alias[]): number {
  const perRoot = new Map<string, number>();
  for (const alias of aliases) {
    perRoot.set(alias.root, (perRoot.get(alias.root) ?? 0) + 1);
  }
  return Math.max(0, ...perRoot.values());
}

/** What the detail view's paths panel should say. One of four cases. */
export type PathsVerdict =
  | { kind: "reclaimable"; copies: number; freedBytes: number }
  | { kind: "bundle"; copies: number }
  | { kind: "mirror"; roots: number }
  | { kind: "single" };

export function pathsVerdict(aliases: Alias[], sizeBytes: number): PathsVerdict {
  // Bundle copies are weighed first and separately, because a sound can be
  // both: twice in ordinary folders and once more inside a project. Only the
  // ordinary copies are reclaimable.
  const loose = aliases.filter((alias) => !isBundlePath(alias.path));
  const looseCopies = copiesWithinOneRoot(loose);
  if (looseCopies > 1) {
    return {
      kind: "reclaimable",
      copies: looseCopies,
      freedBytes: sizeBytes * (looseCopies - 1),
    };
  }

  const copies = copiesWithinOneRoot(aliases);
  if (copies > 1) return { kind: "bundle", copies };
  if (aliases.length > 1) {
    return { kind: "mirror", roots: new Set(aliases.map((a) => a.root)).size };
  }
  return { kind: "single" };
}
