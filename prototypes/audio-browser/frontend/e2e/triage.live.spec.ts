/**
 * Triage against the real index on port 3100.
 *
 * The fixture cannot show that the interface and the FastAPI server agree:
 * field names, the shape of a list, the meaning of `deleted=`. This does.
 *
 * These tests write, which nothing else in the live project does. Everything
 * they write, they undo: one list, made and removed, and one sound discarded
 * and restored. `afterEach` checks it and puts back anything left. The data is
 * the user's, and 3,451 sounds of triage decisions are not reproducible.
 */

import { expect, test, type Page } from "@playwright/test";

import { api, waitForRows } from "./helpers";

/** The list this file makes. Any leftover with this name is removed first. */
const LIST_NAME = "e2e temporary list";

async function removeTestLists(page: Page): Promise<void> {
  const body = await api(page, "/api/lists");
  for (const list of body.items as Array<{ id: number; name: string }>) {
    if (list.name === LIST_NAME) await page.request.delete(`/api/lists/${list.id}`);
  }
}

/** Discarded sounds this run left behind. The user's own discards are not touched. */
const discarded = new Set<string>();

test.afterEach(async ({ page }) => {
  for (const hash of discarded) {
    await page.request.delete(`/api/files/${hash}/deleted`);
    const state = await api(page, `/api/files/${hash}`);
    expect(state.deleted, `a test left ${hash} discarded`).toBe(false);
  }
  discarded.clear();
  await removeTestLists(page);
});

test("the header counter reads the real collection", async ({ page }) => {
  const counts = await api(page, "/api/triage");
  await page.goto("/");
  const counter = page.getByTestId("triage-counter");
  await expect(counter).toBeVisible();
  await expect(counter).toHaveAttribute("data-total", String(counts.total));
  await expect(counter).toHaveAttribute("data-triaged", String(counts.triaged));

  // The same numbers the server reports, not a client-side estimate.
  expect(Number(counts.total)).toBeGreaterThan(3000);
});

test("discarding a real sound hides it and restores exactly", async ({ page }) => {
  await page.goto("/?sort=size&order=asc");
  await waitForRows(page);

  const before = Number((await api(page, "/api/files?limit=1")).total);
  const row = page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first();
  const hash = await row.getAttribute("data-hash");
  expect(hash).toBeTruthy();
  discarded.add(hash!);

  await row.getByTestId("discard-row").click();
  await expect(page.getByTestId("undo-bar")).toBeVisible();
  await expect(page.locator(`[data-testid="row"][data-hash="${hash}"]`)).toHaveCount(0);

  // The default list is one shorter, and the sound is in the discard pile.
  await expect.poll(async () => Number((await api(page, "/api/files?limit=1")).total)).toBe(before - 1);
  const pile = await api(page, "/api/files?deleted=true&limit=1000");
  expect((pile.items as Array<{ hash: string }>).map((f) => f.hash)).toContain(hash);

  // Nothing left the disk: the bytes still stream and the waveform still draws.
  const stream = await page.request.get(`/api/files/${hash}/stream`, { headers: { range: "bytes=0-99" } });
  expect(stream.status()).toBeLessThan(400);
  expect((await page.request.get(`/api/files/${hash}/peaks`)).ok()).toBe(true);

  await page.getByTestId("undo").click();
  await expect.poll(async () => Number((await api(page, "/api/files?limit=1")).total)).toBe(before);
  discarded.delete(hash!);

  const restored = await api(page, `/api/files/${hash}`);
  expect(restored.deleted).toBe(false);
});

test("a list made from a real selection plays as a queue", async ({ page }) => {
  await removeTestLists(page);

  await page.goto("/?sort=duration&order=asc");
  await waitForRows(page);

  const rows = page.locator('[data-testid="row"][data-hash]:not([data-hash=""])');
  const hashes: string[] = [];
  for (let i = 0; i < 2; i += 1) {
    const hash = await rows.nth(i).getAttribute("data-hash");
    if (hash) hashes.push(hash);
    await rows.nth(i).getByTestId("row-select").click();
  }
  expect(hashes).toHaveLength(2);

  await page.getByTestId("bulk-list").click();
  await page.getByTestId("new-list-name").fill(LIST_NAME);
  await page.getByTestId("new-list-create").click();
  await expect(page.getByTestId("undo-bar")).toContainText("added 2 sounds to the list");

  await page.goto("/lists");
  const card = page.locator(`[data-testid="list-card"]:has-text("${LIST_NAME}")`);
  await expect(card).toBeVisible();
  await card.getByTestId("list-link").click();
  await expect(page.getByTestId("list-row")).toHaveCount(2);

  await page.getByTestId("list-play-all").click();
  await expect(page.getByTestId("player-bar")).toHaveAttribute("data-hash", hashes[0]);
  await page.getByTestId("next").click();
  await expect(page.getByTestId("player-bar")).toHaveAttribute("data-hash", hashes[1]);

  // The stream is addressed by hash, as everything here is.
  const src = await page.getByTestId("audio").evaluate((node) => (node as HTMLAudioElement).src);
  expect(new URL(src).pathname).toMatch(/\/api\/files\/[0-9a-f]{64}\/stream$/);

  // Removing the list leaves both sounds exactly as they were.
  await removeTestLists(page);
  for (const hash of hashes) {
    const detail = await api(page, `/api/files/${hash}`);
    expect(detail.deleted).toBe(false);
  }
});
