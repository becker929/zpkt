/**
 * Phone-sized pictures of every triage surface.
 *
 * Skipped unless `SCREENSHOTS=1`, so a normal run does not rewrite the images.
 * Take them with:
 *
 *     SCREENSHOTS=1 npm run test:e2e:mobile
 *
 * Everything written here is put back at the end: the mock server keeps its
 * triage state in memory and the next run has to start from the same fixture.
 */

import { expect, test, type Page } from "@playwright/test";

import { waitForRows } from "./helpers";

const SHOT_DIR = "screenshots";
const LIST_NAME = "keepers";

test.skip(process.env.SCREENSHOTS !== "1", "set SCREENSHOTS=1 to rewrite the images");

async function longPress(page: Page, selector: string): Promise<void> {
  const target = page.locator(selector).first();
  const box = await target.boundingBox();
  const at = { pointerType: "touch", clientX: box!.x + 40, clientY: box!.y + box!.height / 2, bubbles: true };
  await target.dispatchEvent("pointerdown", at);
  await page.waitForTimeout(700);
  await target.dispatchEvent("pointerup", at);
}

async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: `${SHOT_DIR}/${name}.png` });
}

test("triage surfaces at phone size", async ({ page }) => {
  // A sound playing, so the player bar is in every picture: the bars below it
  // must never be the reason it cannot be reached.
  await page.goto("/?sort=name&order=asc");
  await waitForRows(page);
  await page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first().tap();
  await expect(page.getByTestId("player-bar")).toBeVisible();

  // 1. A selection made by long press, with the bulk bar under it.
  await longPress(page, '[data-testid="row"][data-hash]:not([data-hash=""])');
  await page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').nth(2).tap();
  await page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').nth(3).tap();
  await expect(page.getByTestId("selection-bar")).toBeVisible();
  await shot(page, "phone-selection");

  // 2. The sheet that files a selection into a list.
  await page.getByTestId("bulk-list").tap();
  await expect(page.getByTestId("list-sheet")).toBeVisible();
  // Wait for the lists themselves, or the picture is of the word "loading".
  await expect(page.getByTestId("sheet-list").first()).toBeVisible();
  await shot(page, "phone-list-sheet");
  await page.getByTestId("sheet-close").tap();

  // 3. A discard, with the undo strip that follows it.
  await page.getByTestId("bulk-discard").tap();
  await expect(page.getByTestId("undo-bar")).toBeVisible();
  // The rows settle a moment after the count does. Wait for both, so the
  // picture shows the list as it is, not mid-refetch.
  await expect(page.getByTestId("result-count")).toHaveText("3,448 sounds");
  await expect(page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first()).toBeVisible();
  await shot(page, "phone-undo");

  // 4. The discard pile, where restore puts things back.
  await page.goto("/?deleted=true");
  await waitForRows(page);
  await shot(page, "phone-discarded");

  // Put those sounds back before anything else is pictured.
  const discarded = await page.request.get("/api/files?deleted=true&limit=1000");
  const hashes = ((await discarded.json()) as { items: Array<{ hash: string }> }).items.map((f) => f.hash);
  if (hashes.length > 0) await page.request.post("/api/bulk", { data: { hashes, action: "restore" } });

  // 5. The lists view. One list is made here so the picture shows two.
  const existing = await page.request.get("/api/lists");
  const lists = ((await existing.json()) as { items: Array<{ id: number; name: string }> }).items;
  const mine = lists.find((l) => l.name === LIST_NAME);
  let madeId = mine?.id ?? null;
  if (madeId === null) {
    const created = await page.request.post("/api/lists", { data: { name: LIST_NAME } });
    madeId = ((await created.json()) as { id: number }).id;
    const rows = await page.request.get("/api/files?limit=3&sort=duration&order=desc");
    const picked = ((await rows.json()) as { items: Array<{ hash: string }> }).items.map((f) => f.hash);
    await page.request.post("/api/bulk", { data: { hashes: picked, action: "add_to_list", list_id: madeId } });
  }

  // KNOWN FLAKE: this `goto` is sometimes rejected because a `router.replace`
  // from the discarded filter is still in flight. Ruled out: a redundant
  // replace to the same URL, and slow first-compile of the route in dev.
  // Not yet found. It affects this screenshot-only spec, never the suite.
  await page.goto("/lists");
  await expect(page.getByTestId("list-card").first()).toBeVisible();
  await shot(page, "phone-lists");

  // 6. One list, playing as a queue.
  await page.locator(`[data-testid="list-card"][data-list-id="${madeId}"] [data-testid="list-link"]`).tap();
  await expect(page.getByTestId("list-row").first()).toBeVisible();
  await page.getByTestId("list-play-all").tap();
  await expect(page.getByTestId("player-bar")).toBeVisible();
  await shot(page, "phone-list-playing-queue");

  // Leave the fixture as it was found.
  await page.request.delete(`/api/lists/${madeId}`);
});
