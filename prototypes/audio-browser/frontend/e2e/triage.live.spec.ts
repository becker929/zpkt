/**
 * Answering sounds against the real index on port 3100.
 *
 * The fixture cannot show that the interface and the FastAPI server agree:
 * field names, the meaning of `deleted=`, whether the swipe queue is served at
 * all. This does.
 *
 * These tests write, which nothing else in the live project does. Everything
 * they write, they undo: one sound discarded and restored, and at most one
 * sound put into a project and taken back out. `afterEach` checks it and puts
 * back anything left. The data is the user's, and a collection's worth of
 * decisions is not reproducible.
 */

import { expect, test, type Page } from "@playwright/test";

import { api, waitForRows } from "./helpers";

/** A search wide enough to hit most of the collection. */
const WIDE = "/search?q=a";

/**
 * Wait until the swipe view has said something.
 *
 * It has three answers and they arrive after a request: a sound, nothing left
 * to answer, or a queue it cannot read. Reading the page before one of them
 * lands would skip a test for a reason that is only timing.
 */
async function settled(page: Page): Promise<void> {
  await expect(
    page
      .getByTestId("swipe-card")
      .or(page.getByTestId("swipe-done"))
      .or(page.getByTestId("swipe-absent"))
      .or(page.getByTestId("swipe-error")),
  ).toBeVisible();
}

/**
 * What each sound this run touched looked like before it was touched.
 *
 * The state is remembered, not assumed. Two thirds of this collection has
 * already been discarded by the user, so a cleanup that restored everything it
 * had a hash for would quietly undo their decisions — and a decision undone by
 * a test is indistinguishable from one they never made.
 */
const wasDeleted = new Map<string, boolean>();
const taken = new Set<string>();
let bench: string | null = null;

/** Remember a sound's discard state before changing it. */
async function remember(page: Page, hash: string): Promise<void> {
  if (wasDeleted.has(hash)) return;
  const state = await api(page, `/api/files/${hash}`);
  wasDeleted.set(hash, state.deleted === true);
}

test.afterEach(async ({ page }) => {
  for (const [hash, before] of wasDeleted) {
    await page.request.fetch(`/api/files/${hash}/deleted`, { method: before ? "PUT" : "DELETE" });
    const state = await api(page, `/api/files/${hash}`);
    expect(state.deleted, `a test left ${hash} in the wrong state`).toBe(before);
  }
  wasDeleted.clear();

  for (const hash of taken) {
    if (bench) await page.request.delete(`/api/projects/${bench}/sounds/${hash}`);
  }
  taken.clear();
});

test("the header counter reads the real collection", async ({ page }) => {
  const response = await page.request.get("/api/triage");
  test.skip(!response.ok(), "the triage route is not being served");
  const counts = (await response.json()) as Record<string, number>;

  await page.goto("/");
  const counter = page.getByTestId("triage-counter");
  await expect(counter).toBeVisible();
  await expect(counter).toHaveAttribute("data-total", String(counts.total));
  await expect(counter).toHaveAttribute("data-decided", String(counts.decided ?? counts.triaged));

  // The same numbers the server reports, not a client-side estimate.
  expect(Number(counts.total)).toBeGreaterThan(500);
});

test("discarding a real sound hides it and restores exactly", async ({ page }) => {
  // A sound that has not already been discarded, found by asking the server
  // rather than by hoping one is near the top of a search. Two thirds of this
  // collection has been discarded, and a discarded row offers restore.
  const undecided = await api(page, "/api/files?deleted=false&limit=1&sort=name");
  const sound = (undecided.items as Array<{ hash: string; filename: string }>)[0];
  expect(sound, "every sound in the collection is already discarded").toBeTruthy();

  await page.goto(`/search?q=${encodeURIComponent(sound.filename)}`);
  await waitForRows(page);

  const row = page.locator(`[data-testid="row"][data-hash="${sound.hash}"]`);
  await expect(row).toBeVisible();
  const hash = sound.hash;
  await remember(page, hash);
  expect(wasDeleted.get(hash), "the server offered a sound that was already discarded").toBe(false);

  await row.getByTestId("discard-row").click();
  await expect(page.getByTestId("undo-bar")).toBeVisible();

  // The sound is in the discard pile. Asked about by hash, not looked for in a
  // page of the pile: this collection has thousands of discards and the newest
  // one need not be on the first page of them.
  await expect.poll(async () => (await api(page, `/api/files/${hash}`)).deleted).toBe(true);

  // Nothing left the disk: the bytes still stream and the waveform still draws.
  const stream = await page.request.get(`/api/files/${hash}/stream`, { headers: { range: "bytes=0-99" } });
  expect(stream.status()).toBeLessThan(400);
  expect((await page.request.get(`/api/files/${hash}/peaks`)).ok()).toBe(true);

  await page.getByTestId("undo").click();
  await expect.poll(async () => (await api(page, `/api/files/${hash}`)).deleted).toBe(false);
});

test("the swipe view answers a real sound, both ways", async ({ page }) => {
  await page.goto("/");
  await settled(page);

  test.skip(await page.getByTestId("swipe-absent").isVisible(), "the queue cannot be read here");
  test.skip(await page.getByTestId("swipe-done").isVisible(), "nothing is undecided");

  // Discard, then take it straight back. One write, one reversal.
  const first = await page.getByTestId("swipe").getAttribute("data-hash");
  expect(first).toBeTruthy();
  await remember(page, first!);
  await page.getByTestId("swipe-discard").click();
  await expect.poll(async () => (await api(page, `/api/files/${first}`)).deleted).toBe(true);
  await page.getByTestId("swipe-undo").click();
  await expect.poll(async () => (await api(page, `/api/files/${first}`)).deleted).toBe(false);

  // Taking is not checked here. The bench is one of the user's real project
  // files, and taking a sound into it and back out rewrites that file even
  // when the sound set ends up the same. Live tests read real projects and
  // never write them (`live-guard.ts` fails the run if one does); taking is
  // covered against the mock server in `swipe.mock.spec.ts`.
});
