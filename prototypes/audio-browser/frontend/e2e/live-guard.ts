/**
 * The projects directory, fingerprinted.
 *
 * The live project runs against the real stack, and the real stack keeps the
 * user's real projects as files in `audio-browser/projects/`. HW011 is one of
 * them. A live test may read those files through the API — open the project,
 * list its sounds, preview one, fetch a slice — but it may never write one.
 * Every write a test needs goes to the mock server, whose projects live in
 * memory and are gone when it stops.
 *
 * "Never" is checked, not promised. `live-guard.setup.ts` takes this
 * fingerprint before the first live test and `live-guard.teardown.ts` takes it
 * again after the last one; the run fails loudly if any byte of any project
 * file moved. A test that writes and then "cleans up" still fails, because
 * cleaning up rewrites `updated_at` and the file is not what it was.
 */

import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";

/** Where the real projects live. Relative to `frontend/`. */
export const PROJECTS_DIR = resolve(process.env.E2E_PROJECTS_DIR ?? join(__dirname, "..", "..", "projects"));

/** Where the fingerprint taken before the run is kept for the check after it. */
export const FINGERPRINT_FILE = resolve(__dirname, "..", "test-results", "live-guard.json");

/** The user's first real project. Named so the failure can say so. */
export const HW011 = "2026-09-19-hw011.json";

export type Fingerprint = Record<string, string>;

/** SHA-256 of every `*.json` in the projects directory, keyed by filename. */
export function fingerprint(dir: string = PROJECTS_DIR): Fingerprint {
  if (!existsSync(dir)) return {};
  const out: Fingerprint = {};
  for (const name of readdirSync(dir).sort()) {
    if (!name.endsWith(".json")) continue;
    out[name] = createHash("sha256").update(readFileSync(join(dir, name))).digest("hex");
  }
  return out;
}

/** Every way `after` differs from `before`, in words. Empty when nothing moved. */
export function differences(before: Fingerprint, after: Fingerprint): string[] {
  const out: string[] = [];
  for (const name of Object.keys(before)) {
    if (!(name in after)) out.push(`${name} was deleted`);
    else if (after[name] !== before[name]) out.push(`${name} was rewritten (${before[name].slice(0, 12)}… → ${after[name].slice(0, 12)}…)`);
  }
  for (const name of Object.keys(after)) {
    if (!(name in before)) out.push(`${name} was created`);
  }
  return out;
}
