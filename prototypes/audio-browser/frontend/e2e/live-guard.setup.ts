/**
 * Before the live tests: fingerprint the real projects directory.
 *
 * The `live` project depends on this one, so no live test can run without the
 * fingerprint having been taken. See `live-guard.ts` for the rule this holds.
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

import { test as setup } from "@playwright/test";

import { FINGERPRINT_FILE, HW011, PROJECTS_DIR, fingerprint } from "./live-guard";

setup("fingerprint the real projects before any live test runs", async () => {
  const before = fingerprint();
  mkdirSync(dirname(FINGERPRINT_FILE), { recursive: true });
  writeFileSync(FINGERPRINT_FILE, JSON.stringify({ dir: PROJECTS_DIR, files: before }, null, 2));
  const names = Object.keys(before);
  // eslint-disable-next-line no-console
  console.log(
    `live guard: ${names.length} project file${names.length === 1 ? "" : "s"} in ${PROJECTS_DIR}` +
      (before[HW011] ? `; ${HW011} is ${before[HW011].slice(0, 12)}…` : ""),
  );
});
