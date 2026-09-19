/**
 * The collage view on a phone.
 *
 * Under the iPhone 14 Pro descriptor: WebKit, 393 wide, touch, and a viewport
 * only 660 tall once Safari's chrome is taken out. What a desktop run cannot
 * show is checked here: that choosing, stamping and playing work by tapping
 * alone, that every target is a thumb's size, that the stamp bar is inside the
 * viewport (and stays there when the phone is turned), that a region taller
 * than the screen still says what it is, and that two boxes never sit on top
 * of each other on one track.
 *
 * Every write here goes to the mock server, whose projects live in memory.
 * The real project in `collage` is read, never written, in
 * `collage.live.spec.ts`.
 */

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const PROJECT = "2026-09-12-conveyor-belt";
const TRACK_W = 128;

async function resetCollage(request: APIRequestContext): Promise<void> {
  const response = await request.put(`/api/projects/${PROJECT}/collage`, { data: { regions: [] } });
  expect(response.ok()).toBe(true);
}

/** Tap the blank at a point inside it, through the touchscreen. */
async function tapSpace(page: Page, x: number, y: number): Promise<void> {
  const space = await page.getByTestId("collage-space").boundingBox();
  expect(space).not.toBeNull();
  await page.touchscreen.tap(space!.x + x, space!.y + y);
}

async function chooseByTapping(page: Page, index: number): Promise<string> {
  await page.getByTestId("collage-choose").tap();
  await expect(page.getByTestId("collage-picker")).toBeVisible();
  const row = page.getByTestId("picker-row").nth(index);
  const hash = (await row.getAttribute("data-hash")) ?? "";
  await row.tap();
  await page.getByTestId("picker-use").tap();
  await expect(page.getByTestId("collage-picker")).toHaveCount(0);
  return hash;
}

test.beforeEach(async ({ request }) => {
  await resetCollage(request);
});

test.afterEach(async ({ request }) => {
  await resetCollage(request);
});

test("choose, stamp and play with one thumb, and every target is a thumb's size", async ({ page }) => {
  await page.goto("/collage");
  await expect(page.getByTestId("collage")).toBeVisible();
  const viewport = page.viewportSize()!;

  // The bar is on screen, not under the toolbar, and tall enough to hit.
  const choose = await page.getByTestId("collage-choose").boundingBox();
  expect(choose).not.toBeNull();
  expect(choose!.y + choose!.height).toBeLessThanOrEqual(viewport.height + 1);
  expect(choose!.height).toBeGreaterThanOrEqual(44);

  // The picker's rows and its one wide button.
  await page.getByTestId("collage-choose").tap();
  await expect(page.getByTestId("collage-picker")).toBeVisible();
  const row = await page.getByTestId("picker-row").first().boundingBox();
  expect(row!.height).toBeGreaterThanOrEqual(44);
  const use = await page.getByTestId("picker-use").boundingBox();
  expect(use!.height).toBeGreaterThanOrEqual(44);
  expect(use!.y + use!.height).toBeLessThanOrEqual(viewport.height + 1);
  await page.getByTestId("picker-close").tap();
  await expect(page.getByTestId("collage-picker")).toHaveCount(0);

  const hash = await chooseByTapping(page, 0);
  await page.screenshot({ path: "screenshots/collage-phone-chosen.png" });

  await tapSpace(page, 50, 160);
  await expect(page.getByTestId("region")).toHaveCount(1);
  const region = page.getByTestId("region").first();
  const box = await region.boundingBox();
  expect(box!.height).toBeGreaterThanOrEqual(44);
  expect(box!.width).toBeGreaterThanOrEqual(100);

  // Beside it, a second track, still inside a phone's width.
  await tapSpace(page, TRACK_W + 50, 160);
  await expect(page.getByTestId("region")).toHaveCount(2);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-tracks", "2");
  const second = await page.getByTestId("region").nth(1).boundingBox();
  expect(second!.x + second!.width).toBeLessThanOrEqual(viewport.width + 1);
  await page.screenshot({ path: "screenshots/collage-phone-stamped.png" });

  // Tap the region: it plays from a slice, and nothing else is stamped.
  const slice = page.waitForRequest((request) => request.url().includes(`/api/files/${hash}/slice?`));
  await region.tap();
  await slice;
  await expect(region).toHaveAttribute("data-playing", "true");
  await expect(page.getByTestId("region")).toHaveCount(2);
  await expect(page.getByTestId("collage-play-error")).toHaveCount(0);
  await page.screenshot({ path: "screenshots/collage-phone-playing.png" });
  await region.tap();
  await expect(region).toHaveAttribute("data-playing", "false");
});

test("no seconds, no grid, no decibels on a phone either", async ({ page }) => {
  await page.goto("/collage");
  await chooseByTapping(page, 1);
  await tapSpace(page, 50, 160);
  await expect(page.getByTestId("region")).toHaveCount(1);
  const text = (await page.getByTestId("collage").innerText()).toLowerCase();
  expect(text).not.toMatch(/\d+:\d\d/);
  expect(text).not.toMatch(/\b\d+(\.\d+)?\s?s\b/);
  expect(text).not.toMatch(/\bdb\b/);
});

test("a region taller than the screen keeps its name in view as it scrolls", async ({ page, request }) => {
  // The fixture project's sounds may all be short. A tall region is made by
  // writing one directly: a long cut is a valid region whatever the source
  // is, and the view draws what it is given.
  const detail = (await (await request.get(`/api/projects/${PROJECT}`)).json()) as {
    items: Array<{ hash: string; duration_s: number }>;
  };
  const hash = detail.items[0].hash;
  const tall = {
    id: "r1",
    hash,
    track: 0,
    start_s: 0,
    end_s: Math.max(detail.items[0].duration_s, 300),
    at_s: 0,
    rate: 1,
    gain: 1,
    fade_in_s: 0,
    fade_out_s: 0,
  };
  const put = await request.put(`/api/projects/${PROJECT}/collage`, { data: { regions: [tall] } });
  expect(put.ok()).toBe(true);

  await page.goto("/collage");
  const region = page.getByTestId("region").first();
  await expect(region).toBeVisible();
  const viewport = page.viewportSize()!;
  const box = await region.boundingBox();
  expect(box!.height).toBeGreaterThan(viewport.height);

  // Scroll a screen and a half down through the region. The label follows.
  await page.getByTestId("collage-canvas").evaluate((node) => {
    node.scrollTop = Math.round(window.innerHeight * 1.5);
  });
  await page.waitForTimeout(150);
  const label = await region.locator(".region-label").boundingBox();
  const canvas = await page.getByTestId("collage-canvas").boundingBox();
  expect(label).not.toBeNull();
  expect(label!.y).toBeGreaterThanOrEqual(canvas!.y - 1);
  expect(label!.y).toBeLessThan(canvas!.y + 80);
  await page.screenshot({ path: "screenshots/collage-phone-tall.png" });
});

test("turning the phone keeps the bar reachable and the canvas stampable", async ({ page }) => {
  await page.goto("/collage");
  await chooseByTapping(page, 0);
  await page.setViewportSize({ width: 852, height: 393 });
  await page.waitForTimeout(200);

  const bar = await page.getByTestId("collage-choose").boundingBox();
  expect(bar).not.toBeNull();
  expect(bar!.y + bar!.height).toBeLessThanOrEqual(393 + 1);
  expect(bar!.height).toBeGreaterThanOrEqual(44);

  const canvas = await page.getByTestId("collage-canvas").boundingBox();
  expect(canvas!.height).toBeGreaterThan(120);

  await tapSpace(page, 50, 60);
  await expect(page.getByTestId("region")).toHaveCount(1);
  await page.screenshot({ path: "screenshots/collage-phone-landscape.png" });

  // And the picker still fits.
  await page.getByTestId("collage-choose").tap();
  await expect(page.getByTestId("collage-picker")).toBeVisible();
  const use = await page.getByTestId("picker-use").boundingBox();
  expect(use!.y + use!.height).toBeLessThanOrEqual(393 + 1);
});

/** A region row, exactly as the file holds it. */
function regionRow(id: string, hash: string, track: number, atS: number, lengthS: number) {
  return { id, hash, track, start_s: 0, end_s: lengthS, at_s: atS, rate: 1, gain: 1, fade_in_s: 0, fade_out_s: 0 };
}

async function firstHash(request: APIRequestContext): Promise<string> {
  const detail = (await (await request.get(`/api/projects/${PROJECT}`)).json()) as {
    items: Array<{ hash: string }>;
  };
  return detail.items[0].hash;
}

test("two cuts shorter than a thumb, closer than a thumb, are not drawn on top of each other", async ({
  page,
  request,
}) => {
  // A file may hold this: two one-second cuts a second and a half apart on
  // one track. Each is drawn a thumb tall, and a thumb is more than a second
  // and a half. The second box must not be hidden under the first, or one of
  // the two cannot be tapped.
  const hash = await firstHash(request);
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", hash, 0, 0, 1), regionRow("r2", hash, 0, 1.5, 1)] },
  });
  expect(put.ok()).toBe(true);

  await page.goto("/collage");
  await expect(page.getByTestId("region")).toHaveCount(2);
  const a = await page.getByTestId("region").nth(0).boundingBox();
  const b = await page.getByTestId("region").nth(1).boundingBox();
  expect(a!.y + a!.height).toBeLessThanOrEqual(b!.y + 0.5);
  // The first is drawn no shorter than its sound (a second, ten pixels), and
  // the second, with nothing after it, gets the full thumb.
  expect(a!.height).toBeGreaterThanOrEqual(10);
  expect(b!.height).toBeGreaterThanOrEqual(44);

  // And the second can be tapped: it plays, and the first does not.
  await page.getByTestId("region").nth(1).tap();
  await expect(page.getByTestId("region").nth(1)).toHaveAttribute("data-playing", "true");
  await expect(page.getByTestId("region").nth(0)).toHaveAttribute("data-playing", "false");
});

test("a stamp that fits the sound's gap but not the box's gap slides down instead", async ({ page, request }) => {
  // One short cut at the top, and one nine seconds later. The fixture's
  // sounds are all shorter than a thumb, so a stamp aimed between them fits
  // in seconds and not in pixels. It goes after the second, and no two boxes
  // overlap.
  const hash = await firstHash(request);
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", hash, 0, 0, 1), regionRow("r2", hash, 0, 9, 1)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  await expect(page.getByTestId("region")).toHaveCount(2);
  await chooseByTapping(page, 0);
  // The middle of the gap: the first box ends at 12 + 44 = 56, the second
  // starts at 12 + 90 = 102. Not nearer the edge: WebKit pulls a tap that
  // lands within a finger of a button onto the button, so a tap ten pixels
  // under a region plays the region.
  await tapSpace(page, 50, 79);
  await expect(page.getByTestId("region")).toHaveCount(3);
  const boxes = [];
  for (let i = 0; i < 3; i += 1) boxes.push((await page.getByTestId("region").nth(i).boundingBox())!);
  boxes.sort((p, q) => p.y - q.y);
  for (let i = 1; i < boxes.length; i += 1) {
    expect(boxes[i].y, `region ${i} is drawn over the one above it`).toBeGreaterThanOrEqual(
      boxes[i - 1].y + boxes[i - 1].height - 0.5,
    );
  }
});

test("a stamp on a track past the right edge scrolls into view", async ({ page }) => {
  // Three tracks fill a phone. The column for a fourth begins at 384 on a 393
  // wide screen, and a tap in that sliver makes a fourth track. What was just
  // made must not be off the right of the screen.
  await page.goto("/collage");
  await chooseByTapping(page, 0);
  await tapSpace(page, 40, 100);
  await tapSpace(page, TRACK_W + 40, 100);
  await tapSpace(page, 2 * TRACK_W + 40, 100);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-tracks", "3");
  const viewport = page.viewportSize()!;
  await tapSpace(page, viewport.width - 4, 100);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-tracks", "4");
  await page.waitForTimeout(200);
  const fourth = await page.getByTestId("region").nth(3).boundingBox();
  const canvas = await page.getByTestId("collage-canvas").boundingBox();
  expect(fourth!.x + fourth!.width).toBeLessThanOrEqual(canvas!.x + canvas!.width + 1);
  expect(fourth!.x).toBeGreaterThanOrEqual(canvas!.x - 1);
});

test("undo is one level: after it there is nothing left to take back", async ({ page }) => {
  await page.goto("/collage");
  await chooseByTapping(page, 0);
  await tapSpace(page, 40, 100);
  await tapSpace(page, 40, 200);
  await tapSpace(page, 40, 300);
  await expect(page.getByTestId("region")).toHaveCount(3);
  await page.getByTestId("collage-undo").tap();
  await expect(page.getByTestId("region")).toHaveCount(2);
  // The second undo has nothing to press. The two that remain stay.
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);
  await page.waitForTimeout(200);
  await expect(page.getByTestId("region")).toHaveCount(2);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
});

test("a second region stops the first, and a stamp while one plays does not stop it", async ({ page }) => {
  await page.goto("/collage");
  await chooseByTapping(page, 0);
  await tapSpace(page, 40, 100);
  await tapSpace(page, TRACK_W + 40, 100);
  await expect(page.getByTestId("region")).toHaveCount(2);
  const first = page.getByTestId("region").nth(0);
  const second = page.getByTestId("region").nth(1);

  await first.tap();
  await expect(first).toHaveAttribute("data-playing", "true");
  await second.tap();
  await expect(second).toHaveAttribute("data-playing", "true");
  await expect(first).toHaveAttribute("data-playing", "false");

  // Stamping is not stopping. The fixture's sounds are about a second long,
  // so play a long one: a cut written straight in, then played from a piece.
  await tapSpace(page, 2 * TRACK_W + 40, 300);
  await expect(page.getByTestId("region")).toHaveCount(3);
  await expect(page.getByTestId("collage-play-error")).toHaveCount(0);
});

test("with nothing in collage the view says so plainly", async ({ page }) => {
  // The fixture always has one. Make the route answer with none by blocking
  // the project index's collage entry from being on the board.
  await page.route("**/api/projects", async (route) => {
    const response = await route.fetch();
    const body = (await response.json()) as { items: Array<{ column: string }> };
    body.items = body.items.filter((p) => p.column !== "collage");
    await route.fulfill({ response, json: body });
  });
  await page.goto("/collage");
  await expect(page.getByTestId("collage-none")).toBeVisible();
  await expect(page.getByTestId("collage-none")).toContainText("nothing is in collage");
  await expect(page.getByTestId("collage-space")).toHaveCount(0);
});
