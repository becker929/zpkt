/** Shared helpers for the browser tests. */

import { expect, type Locator, type Page } from "@playwright/test";

/** A stream URL names a hash and nothing else. */
export const STREAM_URL = /\/api\/files\/[0-9a-f]{64}\/stream$/;

/**
 * Wait until React has taken the page over.
 *
 * Typing into a field before hydration is a race the test loses: the keystroke
 * lands on plain HTML, and when React arrives it resets the controlled input to
 * its own empty state. The header's collection totals are filled in by an
 * effect, so text there is proof that effects are running.
 */
export async function waitForHydration(page: Page): Promise<void> {
  await expect(page.getByTestId("topbar-stats")).not.toHaveText("…");
}

/** Wait until the list view has real rows in it, not placeholders. */
export async function waitForRows(page: Page): Promise<void> {
  await expect(page.getByTestId("scroller")).toBeVisible();
  await expect
    .poll(async () => page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').count(), {
      message: "the list never rendered a row with a hash",
    })
    .toBeGreaterThan(0);
}

/** How many rows the whole filtered set has, read from the scroller's height. */
export async function renderedRowCount(page: Page): Promise<number> {
  return page.getByTestId("row").count();
}

/**
 * How many pixels the canvas actually painted.
 *
 * The waveform is drawn, not laid out, so an element that exists proves
 * nothing. This reads the bitmap back and counts pixels that are not
 * transparent.
 */
export async function paintedPixels(waveform: Locator): Promise<number> {
  return waveform.locator("canvas").evaluate((node) => {
    const canvas = node as HTMLCanvasElement;
    const ctx = canvas.getContext("2d");
    if (!ctx || canvas.width === 0 || canvas.height === 0) return 0;
    const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height);
    let painted = 0;
    for (let i = 3; i < data.length; i += 4) {
      if (data[i] !== 0) painted += 1;
    }
    return painted;
  });
}

/**
 * Hold a thumb on an element long enough to start a selection.
 *
 * `tap` is too short by design: the interface has to tell a tap that plays
 * apart from a press that picks. This is a real touch sequence, down, wait, up,
 * because on a phone there is no checkbox column to click until a selection has
 * already started.
 */
export async function longPress(page: Page, selector: string): Promise<void> {
  const target = page.locator(selector).first();
  const box = await target.boundingBox();
  expect(box, `no box for ${selector}`).not.toBeNull();
  const clientX = box!.x + box!.width * 0.4;
  const clientY = box!.y + box!.height / 2;
  await target.dispatchEvent("pointerdown", { pointerType: "touch", clientX, clientY, bubbles: true });
  await page.waitForTimeout(700);
  await target.dispatchEvent("pointerup", { pointerType: "touch", clientX, clientY, bubbles: true });
}

/** Read JSON from the API through the page's own origin. */
export async function api(page: Page, path: string): Promise<Record<string, unknown>> {
  const response = await page.request.get(path);
  expect(response.ok(), `${path} answered ${response.status()}`).toBe(true);
  return (await response.json()) as Record<string, unknown>;
}
