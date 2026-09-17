/**
 * Phone-sized pictures of every surface that is left.
 *
 * Skipped unless `SCREENSHOTS=1`, so a normal run does not rewrite the images.
 * Take them with:
 *
 *     SCREENSHOTS=1 npm run test:e2e:mobile
 *
 * Everything written here is put back at the end: the mock server keeps its
 * state in memory and the next run has to start from the same fixture.
 */

import { expect, test, type Page } from "@playwright/test";

import { waitForRows } from "./helpers";

const SHOT_DIR = "screenshots";

/** A view with rows in it. Nothing lists the undecided collection any more. */
const ROWS = "/search?q=kick";

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

/**
 * Go to a view, and go again if the development server got there first.
 *
 * Next's hot-reload client cannot complete its handshake under WebKit, so it
 * falls back to reloading the page. A reload that lands mid-navigation
 * cancels it. Nothing about the application is being tested here, so the
 * answer is to ask again.
 */
async function open(page: Page, url: string): Promise<void> {
  for (let attempt = 0; attempt < 4; attempt += 1) {
    await page.goto(url).catch(() => undefined);
    if (new URL(page.url()).pathname + new URL(page.url()).search === url) return;
    await page.waitForTimeout(500);
  }
  throw new Error(`could not settle on ${url}; it is now ${page.url()}`);
}

test("every surface at phone size", async ({ page }) => {
  // 1. The swipe view: one sound, the bench above it, two answers under it.
  await open(page, "/");
  await expect(page.getByTestId("swipe-card")).toBeVisible();
  // Wait for the waveform, or the picture is of an empty box.
  await expect
    .poll(async () =>
      Number(await page.getByTestId("swipe-card").getByTestId("waveform").getAttribute("data-buckets")),
    )
    .toBeGreaterThan(0);
  await shot(page, "phone-swipe");

  // 2. The record of what was taken, and which project it went into.
  await open(page, "/decided");
  // The taken list opens one request per project, and in development the first
  // of them compiles the route. Longer than the default, and only here.
  await expect(page.locator('[data-testid="row"]').first()).toBeVisible({ timeout: 40_000 });
  await shot(page, "phone-decided-taken");

  // 3. The discard pile, where restore puts things back.
  const rows = await page.request.get("/api/swipe?limit=3");
  const hashes = ((await rows.json()) as { items: Array<{ hash: string }> }).items.map((f) => f.hash);
  await page.request.post("/api/bulk", { data: { hashes, action: "delete" } });
  await page.reload();
  await page.getByTestId("filter-discarded").tap();
  await expect(page.locator('[data-testid="row"]').first()).toBeVisible();
  await shot(page, "phone-decided-discarded");

  // 4. Search, and a selection made by long press with the bulk bar under it.
  await open(page, ROWS);
  await waitForRows(page);
  await page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first().tap();
  await expect(page.getByTestId("player-bar")).toBeVisible();
  await shot(page, "phone-search");

  await longPress(page, '[data-testid="row"][data-hash]:not([data-hash=""])');
  await page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').nth(2).tap();
  await expect(page.getByTestId("selection-bar")).toBeVisible();
  await shot(page, "phone-selection");
  await page.getByTestId("selection-clear").tap();

  // 6. The card mid-drag, saying what letting go would do. Last, because a
  //    half-finished gesture is a state to photograph and not one to navigate
  //    out of.
  await open(page, "/");
  await expect(page.getByTestId("swipe-card")).toBeVisible();
  const card = page.getByTestId("swipe-card");
  const box = await card.boundingBox();
  const y = box!.y + box!.height / 2;
  const from = box!.x + box!.width * 0.7;
  await card.dispatchEvent("pointerdown", { pointerType: "touch", clientX: from, clientY: y, bubbles: true });
  for (const dx of [20, 60, 110]) {
    await card.dispatchEvent("pointermove", {
      pointerType: "touch",
      clientX: from - dx,
      clientY: y,
      bubbles: true,
    });
  }
  await expect(card).toHaveAttribute("data-intent", "discard");
  await shot(page, "phone-swipe-dragging");
  // Back to rest, so nothing is answered by taking a picture of it.
  await card.dispatchEvent("pointercancel", { pointerType: "touch", clientX: from, clientY: y, bubbles: true });

  // Leave the fixture as it was found.
  const discarded = await page.request.get("/api/files?deleted=true&limit=1000");
  const back = ((await discarded.json()) as { items: Array<{ hash: string }> }).items.map((f) => f.hash);
  if (back.length > 0) await page.request.post("/api/bulk", { data: { hashes: back, action: "restore" } });
});
