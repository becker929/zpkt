/**
 * Phone-sized pictures of the silence surfaces.
 *
 * Skipped unless `SCREENSHOTS=1`, so a normal run does not rewrite the images.
 * Take them with:
 *
 *     SCREENSHOTS=1 npm run test:e2e:mobile
 *
 * Mock mode only, and nothing here writes anything: it plays a sound, opens a
 * detail page, and takes pictures.
 */

import { expect, test, type Page } from "@playwright/test";

import { api, waitForRows } from "./helpers";

const SHOT_DIR = "screenshots";

test.skip(process.env.SCREENSHOTS !== "1", "set SCREENSHOTS=1 to rewrite the images");

interface Interval {
  start_s: number;
  end_s: number;
}

/** The first row of the filter with several measured gaps, and its index. */
async function withGaps(page: Page, filter: string): Promise<{ hash: string; index: number }> {
  const body = await api(page, `/api/files?${filter}&limit=20`);
  const items = body.items as Array<{ hash: string }>;
  for (let i = 0; i < items.length; i += 1) {
    const silence = await api(page, `/api/files/${items[i].hash}/silence`);
    if ((silence.intervals as Interval[]).length >= 2) return { hash: items[i].hash, index: i };
  }
  throw new Error("no fixture row with gaps");
}

test("silence surfaces at phone size", async ({ page }) => {
  // Reached through the search view: nothing lists the undecided collection.
  const filter = "q=a&ext=.wav&min_dur=60&sort=name";
  const { hash, index } = await withGaps(page, filter);

  await page.goto(`/search?${filter}`);
  await waitForRows(page);
  await page.screenshot({ path: `${SHOT_DIR}/phone-silence-search.png` });

  await page.locator(`[data-index="${index}"]`).tap();
  await expect(page.getByTestId("player-bar")).toHaveAttribute("data-hash", hash);
  // Let the peaks and the measurement land, or the picture is of an empty box.
  await expect
    .poll(async () => Number(await page.getByTestId("player-bar").getByTestId("waveform").getAttribute("data-buckets")))
    .toBeGreaterThan(0);
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${SHOT_DIR}/phone-silence-player.png` });

  await page.getByTestId("player-bar").locator("a").first().tap();
  await expect(page.getByTestId("detail")).toBeVisible();
  await expect
    .poll(async () => Number(await page.getByTestId("detail").getByTestId("waveform").getAttribute("data-buckets")))
    .toBeGreaterThan(0);
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${SHOT_DIR}/phone-silence-detail.png` });
});
