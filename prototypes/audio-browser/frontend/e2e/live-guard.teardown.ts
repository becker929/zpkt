/**
 * After the live tests: the real projects directory must be byte for byte what
 * it was before them.
 *
 * This runs whether the live tests passed or failed. A difference here is not
 * a flaky test; it is a test that wrote to the user's real work, and the whole
 * run fails so it cannot be missed. See `live-guard.ts`.
 */

import { existsSync, readFileSync } from "node:fs";

import { expect, test as teardown } from "@playwright/test";

import { FINGERPRINT_FILE, HW011, differences, fingerprint, type Fingerprint } from "./live-guard";

teardown("no live test rewrote a real project file", async () => {
  expect(
    existsSync(FINGERPRINT_FILE),
    `no fingerprint at ${FINGERPRINT_FILE}: the live guard setup did not run before the live tests`,
  ).toBe(true);
  const saved = JSON.parse(readFileSync(FINGERPRINT_FILE, "utf8")) as { dir: string; files: Fingerprint };
  const after = fingerprint(saved.dir);
  const moved = differences(saved.files, after);
  const touchedHw011 = moved.some((line) => line.startsWith(HW011));
  expect(
    moved,
    [
      `a live test wrote to the real projects directory (${saved.dir}).`,
      touchedHw011 ? `${HW011} is the user's real work and must never be written by a test.` : "",
      "live tests may read a real project; every write belongs to the mock server.",
      ...moved.map((line) => `  - ${line}`),
    ]
      .filter(Boolean)
      .join("\n"),
  ).toEqual([]);
});
