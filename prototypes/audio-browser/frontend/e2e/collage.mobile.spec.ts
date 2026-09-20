/**
 * The collage view on a phone.
 *
 * Under the iPhone 14 Pro descriptor: WebKit, 393 wide, touch, and a viewport
 * only 660 tall once Safari's chrome is taken out. What a desktop run cannot
 * show is checked here: that choosing, stamping, playing and selecting a
 * handle work by tapping alone, that every target is a thumb's size, that the
 * stamp bar is inside the viewport (and stays there when the phone is
 * turned), that a region taller than the screen still says what it is, and
 * that two boxes never sit on top of each other on one track.
 *
 * A drag is a sequence of touch moves, and Playwright's touchscreen can only
 * tap. The drags here are pointer events with `pointerType: "touch"`,
 * dispatched at the handle. That exercises the view's own handling of a
 * touch drag: capture, the preview, the scroll at the edge, the one write on
 * release, and the cancel on rotation. It does not exercise WebKit's own
 * decision to hand the touch to the page rather than to the scroller, which
 * `touch-action: none` on the selected handle asks for and which only a real
 * finger can confirm.
 *
 * Every write here goes to the mock server, whose projects live in memory.
 * The real project in `collage` is read, never written, in
 * `collage.live.spec.ts`.
 */

import { expect, test, type APIRequestContext, type Locator, type Page } from "@playwright/test";

const PROJECT = "2026-09-12-conveyor-belt";
const TRACK_W = 128;
const PX_PER_S = 10;
const TOP_PAD = 56;

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

/** A region row, exactly as the file holds it. */
function regionRow(id: string, hash: string, track: number, atS: number, lengthS: number, rate = 1) {
  return { id, hash, track, start_s: 0, end_s: lengthS, at_s: atS, rate, gain: 1, fade_in_s: 0, fade_out_s: 0 };
}

async function firstSound(request: APIRequestContext): Promise<{ hash: string; duration_s: number }> {
  const detail = (await (await request.get(`/api/projects/${PROJECT}`)).json()) as {
    items: Array<{ hash: string; duration_s: number }>;
  };
  return detail.items[0];
}

async function regionsOnServer(request: APIRequestContext) {
  const detail = (await (await request.get(`/api/projects/${PROJECT}`)).json()) as {
    document: { collage?: { regions?: Array<{ id: string; start_s: number; end_s: number; at_s: number }> } | null };
  };
  return detail.document.collage?.regions ?? [];
}

function handle(page: Page, regionId: string, end: "start" | "end"): Locator {
  return page.locator(`[data-testid="handle"][data-region-id="${regionId}"][data-end="${end}"]`);
}

function region(page: Page, regionId: string): Locator {
  return page.locator(`[data-testid="region"][data-region-id="${regionId}"]`);
}

/**
 * Take a region up with one tap on its grab, through the touchscreen.
 *
 * The grab is the region's hit area: its box when the box is a thumb tall,
 * and a thumb's height reaching out from a shorter box. The tap also plays
 * the region; that is what a tap on a region does.
 */
async function takeUp(page: Page, regionId: string): Promise<void> {
  const target = region(page, regionId);
  const box = (await target.boundingBox())!;
  await target.tap({ position: { x: TRACK_W / 2, y: Math.min(box.height / 2, 30) } });
  await expect(target).toHaveAttribute("data-selected", "true");
}

/**
 * One touch pointer event at a point, dispatched on the handle.
 *
 * `pointerId` is the thumb it belongs to. A phone has more than one, and the
 * second is how a gesture gets interfered with, so tests that need two say so.
 */
async function touch(
  target: Locator,
  type: string,
  clientX: number,
  clientY: number,
  pointerId = 7,
): Promise<void> {
  await target.dispatchEvent(type, {
    pointerType: "touch",
    pointerId,
    isPrimary: pointerId === 7,
    clientX,
    clientY,
    bubbles: true,
    cancelable: true,
  });
}

/** A thumb on a selected handle, moved by `dy` in steps, then lifted. */
async function thumbDrag(page: Page, target: Locator, dy: number, lift = true): Promise<{ x: number; y: number }> {
  const box = (await target.boundingBox())!;
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await touch(target, "pointerdown", x, y);
  const steps = 6;
  for (let i = 1; i <= steps; i += 1) {
    await touch(target, "pointermove", x, y + (dy * i) / steps);
    await page.waitForTimeout(16);
  }
  if (lift) await touch(target, "pointerup", x, y + dy);
  return { x, y: y + dy };
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
  const first = page.getByTestId("region").first();
  const box = await first.boundingBox();
  // The box is the sound's true length, about a second here. The grab is
  // what a thumb reaches for: a thumb tall, reaching out from the box. No
  // handles yet; nothing is taken up.
  expect(box!.height).toBeGreaterThanOrEqual(5);
  expect(box!.height).toBeLessThan(44);
  expect(box!.width).toBeGreaterThanOrEqual(100);
  const grab = (await first.getByTestId("region-grab").boundingBox())!;
  expect(grab.height).toBeGreaterThanOrEqual(44);
  expect(grab.width).toBeGreaterThanOrEqual(44);
  await expect(page.getByTestId("handle")).toHaveCount(0);

  // Beside it, a second track, still inside a phone's width.
  await tapSpace(page, TRACK_W + 50, 160);
  await expect(page.getByTestId("region")).toHaveCount(2);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-tracks", "2");
  const second = await page.getByTestId("region").nth(1).boundingBox();
  expect(second!.x + second!.width).toBeLessThanOrEqual(viewport.width + 1);
  await page.screenshot({ path: "screenshots/collage-phone-stamped.png" });

  // Tap the region: it plays from a slice, it is taken up, and nothing else
  // is stamped. Taken up, it has a handle at each end, a thumb in both
  // directions.
  const slice = page.waitForRequest((request) => request.url().includes(`/api/files/${hash}/slice?`));
  await page.touchscreen.tap(grab.x + grab.width / 2, grab.y + grab.height / 2);
  await slice;
  await expect(first).toHaveAttribute("data-playing", "true");
  await expect(first).toHaveAttribute("data-selected", "true");
  await expect(page.getByTestId("region")).toHaveCount(2);
  await expect(page.getByTestId("collage-play-error")).toHaveCount(0);
  for (const end of ["start", "end"] as const) {
    const h = (await handle(page, "r1", end).boundingBox())!;
    expect(h.height, `${end} handle`).toBeGreaterThanOrEqual(44);
    expect(h.width, `${end} handle`).toBeGreaterThanOrEqual(44);
  }
  await page.screenshot({ path: "screenshots/collage-phone-playing.png" });
  await page.touchscreen.tap(grab.x + grab.width / 2, grab.y + grab.height / 2);
  await expect(first).toHaveAttribute("data-playing", "false");
  await expect(first).toHaveAttribute("data-selected", "true");
});

test("no seconds, no grid, no decibels on a phone either, and no hours in the header", async ({ page }) => {
  await page.goto("/collage");
  await chooseByTapping(page, 1);
  await tapSpace(page, 50, 160);
  await expect(page.getByTestId("region")).toHaveCount(1);
  const text = (await page.getByTestId("collage").innerText()).toLowerCase();
  expect(text).not.toMatch(/\d+:\d\d/);
  expect(text).not.toMatch(/\b\d+(\.\d+)?\s?s\b/);
  expect(text).not.toMatch(/\bdb\b/);
  await expect(page.getByTestId("topbar-stats")).toHaveAttribute("data-hours", "hidden");
});

test("a region taller than the screen keeps its name in view as it scrolls, and shows its sound", async ({ page, request }) => {
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
  await expect.poll(async () => Number(await region.getByTestId("region-wave").getAttribute("data-buckets"))).toBe(1000);

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

test("two short cuts half a second apart: no pile, each is a thumb to take up, and the one taken up has full handles", async ({
  page,
  request,
}) => {
  // Two one-second cuts a second and a half apart on one track: ten pixels
  // each, five apart. This is the seam every snip makes. Before the fix the
  // facing handles piled up twenty-two pixels thin, a region's own two
  // handles overlapped each other, and a real touch at a region's centre
  // selected a handle instead of playing the region.
  const { hash } = await firstSound(request);
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", hash, 0, 0, 1), regionRow("r2", hash, 0, 1.5, 1)] },
  });
  expect(put.ok()).toBe(true);

  await page.goto("/collage");
  await expect(page.getByTestId("region")).toHaveCount(2);
  const a = (await region(page, "r1").boundingBox())!;
  const b = (await region(page, "r2").boundingBox())!;
  expect(a.y + a.height).toBeLessThanOrEqual(b.y + 0.5);
  expect(a.height).toBeCloseTo(10, 0);
  expect(b.height).toBeCloseTo(10, 0);

  // Nothing is taken up, so there are no handles to pile. Each region has a
  // grab: a thumb tall where there is room, and never across the middle of
  // the gap, so the two never overlap.
  await expect(page.getByTestId("handle")).toHaveCount(0);
  const ga = (await region(page, "r1").getByTestId("region-grab").boundingBox())!;
  const gb = (await region(page, "r2").getByTestId("region-grab").boundingBox())!;
  expect(gb.height).toBeGreaterThanOrEqual(44);
  expect(ga.height).toBeGreaterThanOrEqual(40);
  expect(ga.y + ga.height).toBeLessThanOrEqual(gb.y + 0.5);
  expect(ga.width).toBeGreaterThanOrEqual(44);

  // A real touch at the centre of the second box plays the second region and
  // takes it up: two full handles, one above and one below, not overlapping.
  const slice = page.waitForRequest((r) => r.url().includes(`/api/files/${hash}/slice?`));
  await page.touchscreen.tap(b.x + b.width / 2, b.y + b.height / 2);
  await slice;
  await expect(region(page, "r2")).toHaveAttribute("data-playing", "true");
  await expect(region(page, "r2")).toHaveAttribute("data-selected", "true");
  await expect(page.getByTestId("handle")).toHaveCount(2);
  const hs = (await handle(page, "r2", "start").boundingBox())!;
  const he = (await handle(page, "r2", "end").boundingBox())!;
  expect(hs.height).toBeGreaterThanOrEqual(44);
  expect(he.height).toBeGreaterThanOrEqual(44);
  expect(hs.width).toBeGreaterThanOrEqual(44);
  expect(Math.abs(hs.y + hs.height - b.y)).toBeLessThanOrEqual(2);
  expect(Math.abs(he.y - (b.y + b.height))).toBeLessThanOrEqual(2);
  expect(hs.y + hs.height).toBeLessThanOrEqual(he.y + 0.5);
  await page.screenshot({ path: "screenshots/collage-phone-close-handles.png" });

  // The first region is under the second's top handle now. Its flank is
  // still its own: a touch there takes the first up instead, and the
  // second's handles go away.
  await page.touchscreen.tap(a.x + 12, a.y + a.height / 2);
  await expect(region(page, "r1")).toHaveAttribute("data-selected", "true");
  await expect(region(page, "r2")).toHaveAttribute("data-selected", "false");
  await expect(region(page, "r2")).toHaveAttribute("data-playing", "false");
  await expect(handle(page, "r2", "start")).toHaveCount(0);
  await expect(handle(page, "r1", "end")).toHaveCount(1);

  // A thumb on the first's bottom handle drags it, straight away, up into
  // the region: a trim, one write. The two boxes are still apart.
  await thumbDrag(page, handle(page, "r1", "end"), -4);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  const stored = await regionsOnServer(request);
  expect(stored[0].end_s).toBeCloseTo(0.6, 2);
  expect(stored[1].at_s).toBe(1.5);
  const a2 = (await region(page, "r1").boundingBox())!;
  expect(a2.y + a2.height).toBeLessThanOrEqual(b.y + 0.5);

  // A tap on the blank lets go. Nothing is stamped: no sound is chosen, and
  // the picker does not open over a tap that was only letting go.
  await tapSpace(page, 50, 400);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "");
  await expect(page.getByTestId("region")).toHaveCount(2);
  await expect(page.getByTestId("collage-picker")).toHaveCount(0);
  await expect(page.getByTestId("handle")).toHaveCount(0);
});

test("a tap on a region survives being slow, a tap that moves is not a tap, and a tap on the seam does not misfire", async ({
  page,
  request,
}) => {
  // WebKit delivers a tap's `click` at a point of its own choosing. Taps are
  // read from the pointer events instead, so what is checked here is that
  // reading: a thumb that rests before lifting is still a tap; a thumb that
  // travels is a scroll and plays nothing; a thumb that lands on the seam
  // between a region and its handle and lifts on the other side does
  // neither thing.
  const sound = await firstSound(request);
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", sound.hash, 0, 0, sound.duration_s, 0.05)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  const target = region(page, "r1");
  const box = (await target.boundingBox())!;
  const x = box.x + box.width / 2;
  const y = box.y + 60;

  // Slow: down, a long rest, up.
  await touch(target, "pointerdown", x, y);
  await page.waitForTimeout(900);
  await touch(target, "pointerup", x, y);
  await expect(target).toHaveAttribute("data-playing", "true");
  await expect(target).toHaveAttribute("data-selected", "true");
  await touch(target, "pointerdown", x, y);
  await touch(target, "pointerup", x, y);
  await expect(target).toHaveAttribute("data-playing", "false");

  // A little travel is still a tap; more is not.
  await touch(target, "pointerdown", x, y);
  await touch(target, "pointermove", x + 3, y + 4);
  await touch(target, "pointerup", x + 3, y + 4);
  await expect(target).toHaveAttribute("data-playing", "true");
  await touch(target, "pointerdown", x, y);
  await touch(target, "pointermove", x, y + 12);
  await touch(target, "pointerup", x, y + 24);
  await expect(target).toHaveAttribute("data-playing", "true");
  // And a pan, which WebKit ends with a cancel, plays nothing.
  await touch(target, "pointerdown", x, y);
  await touch(target, "pointercancel", x, y);
  await expect(target).toHaveAttribute("data-playing", "true");

  // The seam. Down on the end handle, up on the box: the handle's drag ends
  // where the thumb lifted, having moved by the travel; nothing plays.
  const he = (await handle(page, "r1", "end").boundingBox())!;
  const hx = he.x + he.width / 2;
  let writes = 0;
  page.on("request", (r) => {
    if (r.method() === "PUT" && r.url().includes("/collage")) writes += 1;
  });
  await touch(handle(page, "r1", "end"), "pointerdown", hx, he.y + 2);
  await touch(handle(page, "r1", "end"), "pointermove", hx, he.y - 20);
  await touch(handle(page, "r1", "end"), "pointerup", hx, he.y - 20);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(writes).toBe(1);
  await expect(target).toHaveAttribute("data-playing", "false");
  const [stored] = await regionsOnServer(request);
  // Twenty-two pixels up at a twentieth speed is a tenth of a second and a
  // bit of source, off the end.
  expect(stored.end_s).toBeCloseTo(sound.duration_s - 0.11, 2);
  // Down on the box, up on the handle: neither a tap nor a drag.
  await touch(target, "pointerdown", x, box.y + box.height - 4);
  await touch(target, "pointerup", x, box.y + box.height + 30);
  await page.waitForTimeout(200);
  expect(writes).toBe(1);
  await expect(target).toHaveAttribute("data-playing", "false");
});

test("the loop a phone lives in: stamp, listen, stamp again; the second stamp is not a dead tap", async ({ page }) => {
  await page.goto("/collage");
  await chooseByTapping(page, 0);
  await tapSpace(page, 40, 100);
  await expect(page.getByTestId("region")).toHaveCount(1);
  // Listen: the region is taken up.
  await takeUp(page, "r1");
  await expect(region(page, "r1")).toHaveAttribute("data-playing", "true");
  await expect(page.getByTestId("handle")).toHaveCount(2);
  // Stamp again, on the blank well below. One tap: it lands, and the first
  // region is put down.
  await tapSpace(page, 40, 400);
  await expect(page.getByTestId("region")).toHaveCount(2);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "");
  await expect(page.getByTestId("handle")).toHaveCount(0);
  // Listening was not interrupted by stamping.
  await expect(region(page, "r1")).toHaveAttribute("data-playing", "true");
});

test("a fifteen-minute region draws under the backing-store cap, top and bottom, and scrolls", async ({
  page,
  request,
}) => {
  // The longest sound in HW011 is nearly fifteen minutes and would be
  // stamped whole: nine thousand pixels. The region's canvas is capped at
  // 8192 device pixels tall; it must still draw, at both ends, rather than
  // come up blank the way an oversized canvas does on a phone.
  const sound = await firstSound(request);
  const rate = sound.duration_s / 900;
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", sound.hash, 0, 0, sound.duration_s, rate)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  const target = region(page, "r1");
  await expect(target).toBeVisible();
  expect((await target.boundingBox())!.height).toBeCloseTo(9000, -1);
  const wave = target.getByTestId("region-wave");
  await expect.poll(async () => Number(await wave.getAttribute("data-buckets"))).toBe(1000);
  const backing = await wave.evaluate((node) => {
    const c = node as HTMLCanvasElement;
    return { width: c.width, height: c.height };
  });
  expect(backing.height).toBeLessThanOrEqual(8192);
  expect(backing.height).toBeGreaterThan(4000);
  const painted = await wave.evaluate((node) => {
    const c = node as HTMLCanvasElement;
    const ctx = c.getContext("2d")!;
    const count = (y0: number, h: number) => {
      const { data } = ctx.getImageData(0, y0, c.width, h);
      let n = 0;
      for (let i = 3; i < data.length; i += 4) if (data[i] !== 0) n += 1;
      return n;
    };
    return { top: count(0, 200), bottom: count(c.height - 200, 200) };
  });
  expect(painted.top).toBeGreaterThan(400);
  expect(painted.bottom).toBeGreaterThan(400);

  // Taken up, its end handle is nine thousand pixels down. Scrolled there,
  // the handle is on screen and a thumb tall; the label still says what the
  // region is; and the handle, not the blank, is what refuses to scroll.
  await takeUp(page, "r1");
  const end = handle(page, "r1", "end");
  await end.scrollIntoViewIfNeeded();
  await page.waitForTimeout(150);
  const canvas = (await page.getByTestId("collage-canvas").boundingBox())!;
  const he = (await end.boundingBox())!;
  expect(he.y).toBeGreaterThanOrEqual(canvas.y - 1);
  expect(he.y + he.height).toBeLessThanOrEqual(canvas.y + canvas.height + 1);
  expect(he.height).toBeGreaterThanOrEqual(44);
  expect(await page.getByTestId("collage-canvas").evaluate((node) => node.scrollTop)).toBeGreaterThan(8000);
  const label = await target.locator(".region-label").boundingBox();
  expect(label!.y).toBeGreaterThanOrEqual(canvas.y - 1);
  expect(await end.evaluate((node) => getComputedStyle(node).touchAction)).toBe("none");
  expect(await page.getByTestId("collage-space").evaluate((node) => getComputedStyle(node).touchAction)).toBe(
    "manipulation",
  );
});

test("a stamp between two cuts lands in the gap at true length, and no two boxes overlap", async ({ page, request }) => {
  // One short cut at the top, and one nine seconds later. A stamp aimed at
  // the flank of the gap, beside the handles, lands there. Nothing pads it.
  const { hash } = await firstSound(request);
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", hash, 0, 0, 1), regionRow("r2", hash, 0, 9, 1)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  await expect(page.getByTestId("region")).toHaveCount(2);
  await chooseByTapping(page, 0);
  await tapSpace(page, 12, TOP_PAD + 4 * PX_PER_S);
  await expect(page.getByTestId("region")).toHaveCount(3);
  const stored = await regionsOnServer(request);
  expect(stored[2].at_s).toBeCloseTo(4, 0);
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

test("undo is a stack and the button says how deep it is", async ({ page }) => {
  await page.goto("/collage");
  await chooseByTapping(page, 0);
  await tapSpace(page, 40, 100);
  await tapSpace(page, 40, 200);
  await tapSpace(page, 40, 300);
  await expect(page.getByTestId("region")).toHaveCount(3);
  const undo = page.getByTestId("collage-undo");
  await expect(undo).toHaveAttribute("data-depth", "3");
  expect((await undo.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await undo.tap();
  await expect(page.getByTestId("region")).toHaveCount(2);
  await expect(undo).toHaveAttribute("data-depth", "2");
  await undo.tap();
  await undo.tap();
  await expect(page.getByTestId("region")).toHaveCount(0);
  // Nothing left to press.
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);
  await page.waitForTimeout(200);
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

  // Stamping is not stopping.
  await tapSpace(page, 2 * TRACK_W + 40, 300);
  await expect(page.getByTestId("region")).toHaveCount(3);
  await expect(page.getByTestId("collage-play-error")).toHaveCount(0);
});

/* Trim ----------------------------------------------------------------------- */

test("trim with one thumb: tap the end handle, then drag it; one write; the box tells the truth", async ({
  page,
  request,
}) => {
  const sound = await firstSound(request);
  const rate = 0.05;
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", sound.hash, 0, 0, sound.duration_s, rate)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  const target = region(page, "r1");
  const before = (await target.boundingBox())!;
  expect(before.height).toBeCloseTo((sound.duration_s / rate) * PX_PER_S, 0);

  // Tap the region to take it up. The handle is a thumb wide and tall, and
  // a tap on it selects it.
  await takeUp(page, "r1");
  const end = handle(page, "r1", "end");
  await end.scrollIntoViewIfNeeded();
  await end.tap();
  await expect(end).toHaveAttribute("data-selected", "true");
  const hb = (await end.boundingBox())!;
  expect(hb.height).toBeGreaterThanOrEqual(44);
  expect(hb.width).toBeGreaterThanOrEqual(44);
  await page.screenshot({ path: "screenshots/collage-phone-selected.png" });

  // Drag it up eighty pixels: the cut is shown before it is made.
  let writes = 0;
  page.on("request", (r) => {
    if (r.method() === "PUT" && r.url().includes("/collage")) writes += 1;
  });
  await thumbDrag(page, end, -80, false);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-dragging", "true");
  const cut = (await page.getByTestId("region-cut").boundingBox())!;
  expect(cut.height).toBeCloseTo(80, 0);
  await page.screenshot({ path: "screenshots/collage-phone-trimming.png" });
  expect(writes).toBe(0);
  await touch(end, "pointerup", hb.x + hb.width / 2, hb.y + hb.height / 2 - 80);

  await expect(page.getByTestId("collage")).toHaveAttribute("data-dragging", "false");
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(writes).toBe(1);
  const [stored] = await regionsOnServer(request);
  expect(stored.end_s).toBeCloseTo(sound.duration_s - 0.4, 2);
  expect(stored.at_s).toBe(0);
  const after = (await target.boundingBox())!;
  expect(after.y).toBeCloseTo(before.y, 0);
  expect(after.height).toBeCloseTo(before.height - 80, 0);
  await page.screenshot({ path: "screenshots/collage-phone-trimmed.png" });
});

test("a drag held at the bottom of the screen scrolls the canvas under the thumb", async ({ page, request }) => {
  // A source stamped whole is taller than a phone. Its end handle starts
  // off screen; dragging the start handle down to the screen's edge carries
  // on down through the region.
  const sound = await firstSound(request);
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", sound.hash, 0, 0, sound.duration_s, 0.005)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  expect((await region(page, "r1").boundingBox())!.height).toBeGreaterThan(2000);

  await takeUp(page, "r1");
  const start = handle(page, "r1", "start");
  await start.tap();
  await expect(start).toHaveAttribute("data-selected", "true");
  const canvas = page.getByTestId("collage-canvas");
  const canvasBox = (await canvas.boundingBox())!;
  const hb = (await start.boundingBox())!;
  const x = hb.x + hb.width / 2;
  const y = hb.y + hb.height / 2;
  await touch(start, "pointerdown", x, y);
  // Down to the canvas's bottom edge, and hold.
  const edge = canvasBox.y + canvasBox.height - 20;
  await touch(start, "pointermove", x, edge);
  await page.waitForTimeout(400);
  const scrolled = await canvas.evaluate((node) => node.scrollTop);
  expect(scrolled).toBeGreaterThan(50);
  // The cut grows as the canvas scrolls: the thumb has not moved, but the
  // region has, under it.
  const cut = (await page.getByTestId("region-cut").boundingBox())!;
  expect(cut.height).toBeGreaterThan(edge - y + 50);
  await touch(start, "pointerup", x, edge);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  const [stored] = await regionsOnServer(request);
  expect(stored.start_s).toBeGreaterThan(0);
  expect(stored.at_s).toBe(0);
});

test("turning the phone mid-drag lets go without writing anything", async ({ page, request }) => {
  const sound = await firstSound(request);
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", sound.hash, 0, 0, sound.duration_s, 0.05)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  await takeUp(page, "r1");
  const end = handle(page, "r1", "end");
  await end.scrollIntoViewIfNeeded();

  let writes = 0;
  page.on("request", (r) => {
    if (r.method() === "PUT" && r.url().includes("/collage")) writes += 1;
  });
  await thumbDrag(page, end, -60, false);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-dragging", "true");
  await expect(end).toHaveAttribute("data-selected", "true");
  await page.setViewportSize({ width: 852, height: 393 });
  await expect(page.getByTestId("collage")).toHaveAttribute("data-dragging", "false");
  await page.waitForTimeout(300);
  expect(writes).toBe(0);
  const [stored] = await regionsOnServer(request);
  expect(stored.end_s).toBeCloseTo(sound.duration_s, 3);
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);
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

/* Snip ----------------------------------------------------------------------- */

/**
 * A snip drag on a phone is a thumb on a region's grab: the same touch
 * pointer events as a trim drag, dispatched at the grab, which is where a
 * snip begins. As with trim, this exercises the view's handling of the
 * touch and not WebKit's decision to hand it to the page, which
 * `touch-action: none` on the grab in snip mode asks for.
 */

/** A region's grab, the centre strip of its box, where a thumb takes it. */
function grabOf(page: Page, regionId: string): Locator {
  return region(page, regionId).getByTestId("region-grab");
}

/** A thumb down on a region's grab at `fromY` below the box's top, moved to `toY`, and lifted unless told not to. */
async function thumbSnip(page: Page, regionId: string, fromY: number, toY: number, lift = true) {
  const target = grabOf(page, regionId);
  const box = (await region(page, regionId).boundingBox())!;
  const x = box.x + box.width / 2;
  await touch(target, "pointerdown", x, box.y + fromY);
  const steps = 6;
  for (let i = 1; i <= steps; i += 1) {
    await touch(target, "pointermove", x, box.y + fromY + ((toY - fromY) * i) / steps);
    await page.waitForTimeout(16);
  }
  if (lift) await touch(target, "pointerup", x, box.y + toY);
  return { x, y: box.y + toY, box };
}

test("snip on a phone: a thumb-sized button in the bar, the handles go while it is on, and the grab stops scrolling", async ({
  page,
  request,
}) => {
  const sound = await firstSound(request);
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", sound.hash, 0, 0, sound.duration_s, 0.05)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  const viewport = page.viewportSize()!;
  const button = page.getByTestId("collage-snip");
  const bb = (await button.boundingBox())!;
  expect(bb.height).toBeGreaterThanOrEqual(44);
  expect(bb.width).toBeGreaterThanOrEqual(44);
  expect(bb.y + bb.height).toBeLessThanOrEqual(viewport.height + 1);

  await takeUp(page, "r1");
  await expect(page.getByTestId("handle")).toHaveCount(2);
  const grab = grabOf(page, "r1");
  expect(await grab.evaluate((node) => getComputedStyle(node).touchAction)).not.toBe("none");

  await button.tap();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "snip");
  await expect(page.getByTestId("handle")).toHaveCount(0);
  const modeBox = (await page.getByTestId("collage-mode").boundingBox())!;
  expect(modeBox.height).toBeGreaterThanOrEqual(44);
  expect(modeBox.y + modeBox.height).toBeLessThanOrEqual(viewport.height + 1);
  await expect(page.getByTestId("collage-mode")).toContainText("snip is on");
  expect(await grab.evaluate((node) => getComputedStyle(node).touchAction)).toBe("none");
  const text = (await page.getByTestId("collage").innerText()).toLowerCase();
  expect(text).not.toMatch(/\d+:\d\d/);
  expect(text).not.toMatch(/\b\d+(\.\d+)?\s?s\b/);
  await page.screenshot({ path: "screenshots/collage-phone-snip-on.png" });

  // The statement in the bar puts trim back, and the grab scrolls again.
  await page.getByTestId("collage-mode").tap();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  await expect(page.getByTestId("handle")).toHaveCount(2);
  expect(await grab.evaluate((node) => getComputedStyle(node).touchAction)).not.toBe("none");
});

test("a thumb snip on a phone: the stripes paint as it goes, one write, two regions, and both trim at the seam", async ({
  page,
  request,
}) => {
  const { hash } = await firstSound(request);
  // Three seconds of source at a tenth speed: three hundred pixels.
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [{ ...regionRow("r1", hash, 0, 0, 3, 0.1) }] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  const before = (await region(page, "r1").boundingBox())!;
  await page.getByTestId("collage-snip").tap();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "snip");

  let writes = 0;
  page.on("request", (r) => {
    if (r.method() === "PUT" && r.url().includes("/collage")) writes += 1;
  });
  // Sixty to a hundred pixels down: six tenths of a second to one second
  // of source. The first half stays inside the fixture's sound, so it can
  // be trimmed afterwards without meeting the sound's end.
  const { x, y } = await thumbSnip(page, "r1", 60, 100, false);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-snipping", "true");
  const band = (await page.getByTestId("region-snip").boundingBox())!;
  expect(Math.abs(band.y - (before.y + 60))).toBeLessThanOrEqual(2);
  expect(band.height).toBeCloseTo(40, 0);
  expect(band.width).toBeGreaterThanOrEqual(100);
  expect(writes).toBe(0);
  await page.screenshot({ path: "screenshots/collage-phone-snipping.png" });
  await touch(grabOf(page, "r1"), "pointerup", x, y);

  await expect(page.getByTestId("collage")).toHaveAttribute("data-snipping", "false");
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(writes).toBe(1);
  await expect(page.getByTestId("region")).toHaveCount(2);
  let stored = await regionsOnServer(request);
  expect(stored[0]).toMatchObject({ id: "r1", at_s: 0, start_s: 0 });
  expect(stored[0].end_s).toBeCloseTo(0.6, 2);
  expect(stored[1].id).toBe("r2");
  expect(stored[1].start_s).toBeCloseTo(1.0, 2);
  expect(stored[1].at_s).toBeCloseTo(10, 2);

  // Trim is back, the first half is up with its handles, and the seam is
  // clean: two grabs that do not overlap, a full handle between them.
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "r1");
  await expect(page.getByTestId("handle")).toHaveCount(2);
  const ga = (await grabOf(page, "r1").boundingBox())!;
  const gb = (await grabOf(page, "r2").boundingBox())!;
  expect(ga.y + ga.height).toBeLessThanOrEqual(gb.y + 0.5);
  const he = (await handle(page, "r1", "end").boundingBox())!;
  expect(he.height).toBeGreaterThanOrEqual(44);
  await page.screenshot({ path: "screenshots/collage-phone-snipped.png" });

  // The first half's inner edge, dragged down: a trim, stopping short of
  // the second half.
  await thumbDrag(page, handle(page, "r1", "end"), 10);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  stored = await regionsOnServer(request);
  expect(stored[0].end_s).toBeCloseTo(0.7, 2);
  expect(stored[1].start_s).toBeCloseTo(1.0, 2);

  // The second half, taken up by a real touch on its box, and its inner
  // edge dragged down. It keeps its place.
  const b = (await region(page, "r2").boundingBox())!;
  await page.touchscreen.tap(b.x + b.width / 2, b.y + 40);
  await expect(region(page, "r2")).toHaveAttribute("data-selected", "true");
  await expect(handle(page, "r1", "end")).toHaveCount(0);
  await thumbDrag(page, handle(page, "r2", "start"), 20);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  stored = await regionsOnServer(request);
  expect(stored[1].start_s).toBeCloseTo(1.2, 2);
  expect(stored[1].at_s).toBeCloseTo(10, 2);
  expect(writes).toBe(3);
});

test("in snip mode a thumb that barely moves is a tap: it plays, and nothing is cut", async ({ page, request }) => {
  const sound = await firstSound(request);
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", sound.hash, 0, 0, sound.duration_s, 0.1)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  await page.getByTestId("collage-snip").tap();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "snip");
  let writes = 0;
  page.on("request", (r) => {
    if (r.method() === "PUT" && r.url().includes("/collage")) writes += 1;
  });
  await thumbSnip(page, "r1", 30, 34);
  await expect(region(page, "r1")).toHaveAttribute("data-playing", "true");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "snip");
  await page.waitForTimeout(200);
  expect(writes).toBe(0);
  await expect(page.getByTestId("region")).toHaveCount(1);
  await expect(page.getByTestId("region-snip")).toHaveCount(0);
});

test("turning the phone mid-snip, or a second finger on the button, lets go without writing", async ({ page, request }) => {
  const { hash } = await firstSound(request);
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", hash, 0, 0, 3, 0.1)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  await page.getByTestId("collage-snip").tap();
  let writes = 0;
  page.on("request", (r) => {
    if (r.method() === "PUT" && r.url().includes("/collage")) writes += 1;
  });

  // Mid-snip, the other finger presses the button: the mode changes, the
  // stripes go, and the first finger lifting afterwards cuts nothing.
  let held = await thumbSnip(page, "r1", 100, 150, false);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-snipping", "true");
  await page.getByTestId("collage-snip").tap();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-snipping", "false");
  await touch(grabOf(page, "r1"), "pointerup", held.x, held.y);
  await page.waitForTimeout(200);
  expect(writes).toBe(0);
  await expect(page.getByTestId("region")).toHaveCount(1);

  // Mid-snip, the phone turns.
  await page.getByTestId("collage-snip").tap();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "snip");
  held = await thumbSnip(page, "r1", 100, 150, false);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-snipping", "true");
  await page.setViewportSize({ width: 852, height: 393 });
  await expect(page.getByTestId("collage")).toHaveAttribute("data-snipping", "false");
  await touch(grabOf(page, "r1"), "pointerup", held.x, held.y);
  await page.waitForTimeout(300);
  expect(writes).toBe(0);
  await expect(page.getByTestId("region")).toHaveCount(1);
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);
  const [stored] = await regionsOnServer(request);
  expect(stored).toMatchObject({ start_s: 0, end_s: 3 });
});

test("a thumb across a one-second cut takes the whole of it, the stripes having covered it; its neighbour is untouched; undo brings it back", async ({
  page,
  request,
}) => {
  // The seam bullet two fixed, in snip mode: two one-second cuts, ten
  // pixels each. Any thumb's travel across the first leaves less than a
  // quarter of a second on each side, so the whole of it goes.
  const { hash } = await firstSound(request);
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", hash, 0, 0, 1), regionRow("r2", hash, 0, 1.5, 1)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  await page.getByTestId("collage-snip").tap();
  const box = (await region(page, "r1").boundingBox())!;
  await thumbSnip(page, "r1", 0.5, 9.5, false);
  const band = (await page.getByTestId("region-snip").boundingBox())!;
  expect(Math.abs(band.y - box.y)).toBeLessThanOrEqual(2);
  expect(band.height).toBeCloseTo(box.height, 0);
  await expect(page.getByTestId("region-snip")).toHaveAttribute("data-whole", "true");
  await expect(page.getByTestId("collage-mode")).toContainText("hold still to take the whole region out");
  await page.screenshot({ path: "screenshots/collage-phone-snip-whole.png" });
  // Held still: the band fills and arms, the bar turns amber and says a lift
  // takes it. Then the lift.
  await expect(page.getByTestId("region-snip")).toHaveAttribute("data-armed", "true");
  await expect(page.getByTestId("collage-mode")).toContainText("let go to take the whole region out");
  await page.screenshot({ path: "screenshots/collage-phone-snip-armed.png" });
  await touch(grabOf(page, "r1"), "pointerup", box.x + box.width / 2, box.y + 9.5);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  await expect(page.getByTestId("region")).toHaveCount(1);
  let stored = await regionsOnServer(request);
  expect(stored).toHaveLength(1);
  expect(stored[0]).toMatchObject({ id: "r2", at_s: 1.5, start_s: 0, end_s: 1 });
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");

  await page.getByTestId("collage-undo").tap();
  await expect(page.getByTestId("region")).toHaveCount(2);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  stored = await regionsOnServer(request);
  expect(stored[0]).toMatchObject({ id: "r1", at_s: 0, start_s: 0, end_s: 1 });
});

test("a thumb that sweeps through a short region in snip mode takes nothing; the hint says what would; undo never had to", async ({
  page,
  request,
}) => {
  // The grab of a one-second region is a thumb tall around a ten-pixel box,
  // and in snip mode it does not scroll. A thumb that lands on it meaning
  // to scroll paints the whole box amber under itself and sweeps on. Before
  // the hold, that lift removed the region, with nothing seen; the only way
  // back was undo, which a reload empties.
  const { hash } = await firstSound(request);
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", hash, 0, 0, 1), regionRow("r2", hash, 0, 1.5, 1)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  await page.getByTestId("collage-snip").tap();
  let writes = 0;
  page.on("request", (r) => {
    if (r.method() === "PUT" && r.url().includes("/collage")) writes += 1;
  });

  // Down from the grab's reach above the box, through it and on down the
  // track, lifting as it goes. The band was whole the whole way.
  const grab = (await grabOf(page, "r1").boundingBox())!;
  const box = (await region(page, "r1").boundingBox())!;
  expect(grab.y).toBeLessThan(box.y - 10);
  await thumbSnip(page, "r1", grab.y - box.y + 4, 140, false);
  await expect(page.getByTestId("region-snip")).toHaveAttribute("data-whole", "true");
  await expect(page.getByTestId("region-snip")).toHaveAttribute("data-armed", "false");
  await touch(grabOf(page, "r1"), "pointerup", box.x + box.width / 2, box.y + 140);
  await page.waitForTimeout(300);
  expect(writes).toBe(0);
  await expect(page.getByTestId("region")).toHaveCount(2);
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "snip");
  const hint = page.getByTestId("collage-hint");
  await expect(hint).toContainText("hold still");
  const hb = (await hint.boundingBox())!;
  const viewport = page.viewportSize()!;
  expect(hb.y + hb.height).toBeLessThanOrEqual(viewport.height + 1);
  const text = (await page.getByTestId("collage").innerText()).toLowerCase();
  expect(text).not.toMatch(/\d+:\d\d/);
  expect(text).not.toMatch(/\b\d+(\.\d+)?\s?(s|ms|db)\b/);
  await page.screenshot({ path: "screenshots/collage-phone-snip-swept.png" });

  // Reload: both cuts are still there. Nothing needed undoing.
  await page.reload();
  await expect(page.getByTestId("region")).toHaveCount(2);
  const stored = await regionsOnServer(request);
  expect(stored.map((r) => r.id)).toEqual(["r1", "r2"]);
});

/* Stretch -------------------------------------------------------------------- */

/**
 * A stretch drag on a phone is a thumb on the one handle that shows in
 * stretch mode: the same touch pointer events as a trim drag, dispatched at
 * the handle. As with trim, this exercises the view's handling of the touch
 * and not WebKit's decision to hand it to the page, which `touch-action:
 * none` on the handle asks for.
 */

async function storedRates(request: APIRequestContext) {
  const detail = (await (await request.get(`/api/projects/${PROJECT}`)).json()) as {
    document: { collage?: { regions?: Array<{ id: string; start_s: number; end_s: number; at_s: number; rate: number }> } | null };
  };
  return detail.document.collage?.regions ?? [];
}

test("stretch with one thumb: take up, tap a handle, tap stretch; one handle; drag; one write; the bar says so and shows no number", async ({
  page,
  request,
}) => {
  const { hash } = await firstSound(request);
  // Four seconds of source at full speed, ten collage seconds in: forty
  // pixels, with room above it for the start to move up into.
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", hash, 0, 10, 4)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  const viewport = page.viewportSize()!;
  const button = page.getByTestId("collage-stretch");
  const bb = (await button.boundingBox())!;
  expect(bb.height).toBeGreaterThanOrEqual(44);
  expect(bb.width).toBeGreaterThanOrEqual(44);
  expect(bb.y + bb.height).toBeLessThanOrEqual(viewport.height + 1);
  await expect(button).toBeDisabled();

  // The user's own order: tap the region, tap a handle, then the button.
  await takeUp(page, "r1");
  await expect(button).toBeDisabled();
  const end = handle(page, "r1", "end");
  await end.tap();
  await expect(end).toHaveAttribute("data-selected", "true");
  await expect(button).toBeEnabled();
  await button.tap();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "stretch");
  await expect(page.getByTestId("handle")).toHaveCount(1);
  await expect(end).toHaveAttribute("data-kind", "stretch");
  expect((await end.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  expect(await end.evaluate((node) => getComputedStyle(node).touchAction)).toBe("none");
  const modeBox = (await page.getByTestId("collage-mode").boundingBox())!;
  expect(modeBox.height).toBeGreaterThanOrEqual(44);
  expect(modeBox.y + modeBox.height).toBeLessThanOrEqual(viewport.height + 1);
  await expect(page.getByTestId("collage-mode")).toContainText("stretch is on");
  await page.screenshot({ path: "screenshots/collage-phone-stretch-on.png" });

  // Down forty: the outline says the box is about to be twice as long, and
  // nothing is written until the lift.
  let writes = 0;
  page.on("request", (r) => {
    if (r.method() === "PUT" && r.url().includes("/collage")) writes += 1;
  });
  const before = (await region(page, "r1").boundingBox())!;
  const held = await thumbDrag(page, end, 40, false);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-dragging", "true");
  const more = (await page.getByTestId("region-more").boundingBox())!;
  expect(more.height).toBeCloseTo(40, 0);
  expect(Math.abs(more.y - (before.y + before.height))).toBeLessThanOrEqual(2);
  expect(writes).toBe(0);
  let text = (await page.getByTestId("collage").innerText()).toLowerCase();
  expect(text).not.toMatch(/\d+(\.\d+)?\s?(x|×)\b/);
  expect(text).not.toMatch(/\b\d+(\.\d+)?\s?(s|ms|db|%)\b/);
  await page.screenshot({ path: "screenshots/collage-phone-stretching.png" });
  await touch(end, "pointerup", held.x, held.y);

  await expect(page.getByTestId("collage")).toHaveAttribute("data-dragging", "false");
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(writes).toBe(1);
  let stored = await storedRates(request);
  expect(stored[0].rate).toBeCloseTo(0.5, 6);
  expect(stored[0]).toMatchObject({ start_s: 0, end_s: 4, at_s: 10 });
  const after = (await region(page, "r1").boundingBox())!;
  expect(after.y).toBeCloseTo(before.y, 0);
  expect(after.height).toBeCloseTo(80, 0);
  // The stretch is over: trim is back with both handles, the handle still
  // selected, and nothing anywhere says the rate.
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  await expect(page.getByTestId("handle")).toHaveCount(2);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "r1:end");
  text = (await page.getByTestId("collage").innerText()).toLowerCase();
  expect(text).not.toMatch(/\d+(\.\d+)?\s?(x|×)\b/);
  const spoken = await page.getByTestId("collage").evaluate((node) =>
    Array.from(node.querySelectorAll("[aria-label], [title]"))
      .map((el) => `${el.getAttribute("aria-label") ?? ""} ${el.getAttribute("title") ?? ""}`)
      .join("\n")
      .toLowerCase(),
  );
  expect(spoken).not.toMatch(/\d+(\.\d+)?\s?(x|×)\b/);
  expect(spoken).not.toMatch(/\b\d+(\.\d+)?\s?(s|sec|seconds?|ms|db)\b/);
  await page.screenshot({ path: "screenshots/collage-phone-stretched.png" });

  // The start handle, the same way: up forty, the bottom stays put, and the
  // region begins earlier.
  const start = handle(page, "r1", "start");
  await start.tap();
  await expect(start).toHaveAttribute("data-selected", "true");
  await button.tap();
  await expect(page.getByTestId("handle")).toHaveCount(1);
  await expect(handle(page, "r1", "end")).toHaveCount(0);
  const bottom = after.y + after.height;
  await thumbDrag(page, start, -40);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(writes).toBe(2);
  stored = await storedRates(request);
  expect(stored[0].rate).toBeCloseTo(1 / 3, 6);
  expect(stored[0].at_s).toBeCloseTo(6, 3);
  expect(stored[0]).toMatchObject({ start_s: 0, end_s: 4 });
  const last = (await region(page, "r1").boundingBox())!;
  expect(last.y + last.height).toBeCloseTo(bottom, 0);
  expect(last.y).toBeCloseTo(after.y - 40, 0);
});

test("a fifteen-minute source at a quarter speed is an hour tall: it draws under the backing-store cap at both ends, and its end is reachable", async ({
  page,
  request,
}) => {
  // The longest sound in HW011 stamped whole and slowed to the bound is
  // nine hundred seconds of source over thirty-six thousand pixels. The
  // fixture's sound is a second long, so the same height is reached with a
  // rate far below the bound; the view draws the cut it is given over the
  // height the rate gives it either way, and what is checked is that a
  // canvas this tall still draws at both ends rather than coming up blank.
  const sound = await firstSound(request);
  const rate = sound.duration_s / 3600;
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", sound.hash, 0, 0, sound.duration_s, rate)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  const target = region(page, "r1");
  await expect(target).toBeVisible();
  expect((await target.boundingBox())!.height).toBeCloseTo(36000, -1);
  const wave = target.getByTestId("region-wave");
  await expect.poll(async () => Number(await wave.getAttribute("data-buckets"))).toBe(1000);
  const backing = await wave.evaluate((node) => {
    const c = node as HTMLCanvasElement;
    return { width: c.width, height: c.height };
  });
  expect(backing.height).toBeLessThanOrEqual(8192);
  expect(backing.height).toBeGreaterThan(8000);
  expect(backing.width).toBeGreaterThanOrEqual(16);
  const painted = await wave.evaluate((node) => {
    const c = node as HTMLCanvasElement;
    const ctx = c.getContext("2d")!;
    const count = (y0: number, h: number) => {
      const { data } = ctx.getImageData(0, y0, c.width, h);
      let n = 0;
      for (let i = 3; i < data.length; i += 4) if (data[i] !== 0) n += 1;
      return n;
    };
    return { top: count(0, 200), bottom: count(c.height - 200, 200) };
  });
  expect(painted.top).toBeGreaterThan(200);
  expect(painted.bottom).toBeGreaterThan(200);

  // Taken up, the end handle is an hour down. Scrolled there, it is on
  // screen and a thumb tall, and the label still says what the region is.
  await takeUp(page, "r1");
  const end = handle(page, "r1", "end");
  await end.scrollIntoViewIfNeeded();
  await page.waitForTimeout(150);
  const canvas = (await page.getByTestId("collage-canvas").boundingBox())!;
  const he = (await end.boundingBox())!;
  expect(he.y).toBeGreaterThanOrEqual(canvas.y - 1);
  expect(he.y + he.height).toBeLessThanOrEqual(canvas.y + canvas.height + 1);
  expect(he.height).toBeGreaterThanOrEqual(44);
  expect(await page.getByTestId("collage-canvas").evaluate((node) => node.scrollTop)).toBeGreaterThan(35000);
  const label = await target.locator(".region-label").boundingBox();
  expect(label!.y).toBeGreaterThanOrEqual(canvas.y - 1);

  // Already past the slow bound, a stretch down changes nothing and writes
  // nothing; the bar says it is as slow as it goes.
  await end.tap();
  await page.getByTestId("collage-stretch").tap();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "stretch");
  let writes = 0;
  page.on("request", (r) => {
    if (r.method() === "PUT" && r.url().includes("/collage")) writes += 1;
  });
  const held = await thumbDrag(page, end, 60, false);
  await expect(page.getByTestId("collage-mode")).toHaveAttribute("data-bound", "slow");
  await touch(end, "pointerup", held.x, held.y);
  await page.waitForTimeout(300);
  expect(writes).toBe(0);
  expect((await storedRates(request))[0].rate).toBe(rate);
});

test("turning the phone mid-stretch lets go without writing anything", async ({ page, request }) => {
  const { hash } = await firstSound(request);
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", hash, 0, 0, 4)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  await takeUp(page, "r1");
  const end = handle(page, "r1", "end");
  await end.tap();
  await page.getByTestId("collage-stretch").tap();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "stretch");

  let writes = 0;
  page.on("request", (r) => {
    if (r.method() === "PUT" && r.url().includes("/collage")) writes += 1;
  });
  await thumbDrag(page, end, 60, false);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-dragging", "true");
  await page.setViewportSize({ width: 852, height: 393 });
  await expect(page.getByTestId("collage")).toHaveAttribute("data-dragging", "false");
  await page.waitForTimeout(300);
  expect(writes).toBe(0);
  expect((await storedRates(request))[0].rate).toBe(1);
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);
  // The handle was not let go of, so stretch is still on, and the button
  // is still on screen to turn it off.
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "stretch");
  const bb = (await page.getByTestId("collage-stretch").boundingBox())!;
  expect(bb.y + bb.height).toBeLessThanOrEqual(393 + 1);
});

test("choosing an end costs material: a tap on a handle that slides five pixels trims the cut", async ({
  page,
  request,
}) => {
  // Pinned, not endorsed. Choosing an end is the first step of every stretch
  // — tap the region, tap a handle, tap stretch — and a handle drags from
  // its first pixel by design ("two short cuts half a second apart" turns a
  // four-pixel drag into a trim on purpose, on a ten-pixel region). So the
  // thumb travel of an ordinary tap is a trim: five pixels here takes half a
  // second of source off the cut and pushes a step onto undo, before the
  // stretch it was setting up has begun. A tap slop on handles would end
  // this and would take the deliberate four-pixel trim with it. That is a
  // decision for Anthony; this test says what it costs today.
  const { hash, duration_s } = await firstSound(request);
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", hash, 0, 0, duration_s)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  await takeUp(page, "r1");

  const end = handle(page, "r1", "end");
  const box = (await end.boundingBox())!;
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await touch(end, "pointerdown", x, y);
  for (const step of [1, 2, 4, 5]) {
    await touch(end, "pointermove", x + 1, y - step);
    await page.waitForTimeout(16);
  }
  await touch(end, "pointerup", x + 1, y - 5);

  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  await expect(end).toHaveAttribute("data-selected", "true");
  await expect(page.getByTestId("collage-undo")).toHaveAttribute("data-depth", "1");
  const [stored] = await regionsOnServer(request);
  expect(stored.end_s).toBeCloseTo(duration_s - 0.5, 2);
  // Undo is the whole of the remedy, and it is one tap away.
  await page.getByTestId("collage-undo").tap();
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);
  expect((await regionsOnServer(request))[0].end_s).toBeCloseTo(duration_s, 3);
});

/* Playing the piece ---------------------------------------------------------- */

/** How far down the blank the playhead is, in canvas pixels. */
async function playheadAt(page: Page): Promise<number> {
  const space = (await page.getByTestId("collage-space").boundingBox())!;
  const line = (await page.getByTestId("collage-playhead").boundingBox())!;
  return line.y - space.y;
}

test("play the whole piece with one thumb: the transport is a thumb, the line moves down, stop silences it", async ({
  page,
  request,
}) => {
  const { hash } = await firstSound(request);
  // Three regions on three tracks, slowed so the piece lasts long enough to
  // watch. The second begins while the first is still sounding.
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: {
      regions: [
        regionRow("r1", hash, 0, 0, 0.4, 0.02),
        regionRow("r2", hash, 1, 3, 0.5, 0.02),
        regionRow("r3", hash, 2, 0, 0.3, 0.02),
      ],
    },
  });
  expect(put.ok()).toBe(true);

  await page.goto("/collage");
  const viewport = page.viewportSize()!;
  const play = page.getByTestId("collage-play");
  const bb = (await play.boundingBox())!;
  expect(bb.height).toBeGreaterThanOrEqual(44);
  expect(bb.width).toBeGreaterThanOrEqual(44);
  expect(bb.y + bb.height).toBeLessThanOrEqual(viewport.height + 1);
  await expect(page.getByTestId("collage-playhead")).toHaveCount(0);

  // The tap is the user gesture iOS insists on before any audio starts.
  await play.tap();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing", { timeout: 20_000 });
  await expect(page.getByTestId("collage-play-error")).toHaveCount(0);
  await expect(play).toContainText("stop");
  const line = page.getByTestId("collage-playhead");
  await expect(line).toBeVisible();
  const lb = (await line.boundingBox())!;
  expect(lb.height).toBeLessThanOrEqual(4);
  expect(lb.width).toBeGreaterThanOrEqual(TRACK_W);
  await page.screenshot({ path: "screenshots/collage-phone-playing-piece.png" });

  // It moves down at the piece's own rate: ten pixels a second.
  const first = await playheadAt(page);
  await page.waitForTimeout(2000);
  const second = await playheadAt(page);
  expect(second - first).toBeGreaterThan(14);
  expect(second - first).toBeLessThan(26);
  expect(first).toBeGreaterThanOrEqual(TOP_PAD - 2);

  // Nothing on the screen reads as a time, a rate or a level.
  const text = (await page.getByTestId("collage").innerText()).toLowerCase();
  expect(text).not.toMatch(/\d+:\d\d/);
  expect(text).not.toMatch(/\b\d+(\.\d+)?\s?(s|sec|seconds?|ms|db|bpm|%)\b/);

  // A tap on a region while the piece plays takes it up and does not start a
  // second thing sounding under it.
  await takeUp(page, "r1");
  await expect(region(page, "r1")).toHaveAttribute("data-playing", "false");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");

  await play.tap();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "idle");
  await expect(page.getByTestId("collage-playhead")).toHaveCount(0);
  await expect(play).toContainText("play");
});

test("turning the phone mid-play keeps the piece sounding, and the line keeps its place", async ({ page, request }) => {
  const { hash } = await firstSound(request);
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", hash, 0, 0, 0.5, 0.02)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  await page.getByTestId("collage-play").tap();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing", { timeout: 20_000 });
  await page.waitForTimeout(1000);
  const before = await playheadAt(page);

  // Rotating ends a drag, because the thumb is no longer where the handle
  // was. It does not end the piece: nothing about the music depends on which
  // way the phone is held.
  await page.setViewportSize({ width: 852, height: 393 });
  await page.waitForTimeout(500);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  const after = await playheadAt(page);
  expect(after).toBeGreaterThanOrEqual(before);
  expect(after - before).toBeLessThan(30);
  const bar = (await page.getByTestId("collage-play").boundingBox())!;
  expect(bar.y + bar.height).toBeLessThanOrEqual(393 + 1);
  expect(bar.height).toBeGreaterThanOrEqual(44);
  await page.screenshot({ path: "screenshots/collage-phone-playing-landscape.png" });
  await page.getByTestId("collage-play").tap();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "idle");
});

test("a piece taller than the phone offers a way back to the line, and never moves the canvas itself", async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);
  const { hash } = await firstSound(request);
  // Eight tenths of a second at a hundredth speed: eighty seconds of piece,
  // eight hundred pixels, more than twice the height of the canvas. HW011 is
  // twenty-one thousand pixels, where the line is gone inside a minute.
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", hash, 0, 0, 0.8, 0.01)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  await expect(page.getByTestId("collage-follow")).toHaveCount(0);

  await page.getByTestId("collage-play").tap();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing", { timeout: 20_000 });
  await expect(page.getByTestId("collage-follow")).toHaveCount(0);

  // A thumb scrolls down through the piece to work on something later. The
  // line is left behind, and the offer to go back to it appears.
  const canvas = page.getByTestId("collage-canvas");
  await canvas.evaluate((node) => {
    node.scrollTop = 500;
  });
  const follow = page.getByTestId("collage-follow");
  await expect(follow).toBeVisible();
  await expect(follow).toContainText("the playhead is above");

  // A thumb's target, on the screen, and clear of the bar it would otherwise
  // hide under.
  const viewport = page.viewportSize()!;
  const bb = (await follow.boundingBox())!;
  const bar = (await page.getByTestId("collage-play").boundingBox())!;
  expect(bb.height).toBeGreaterThanOrEqual(44);
  expect(bb.width).toBeGreaterThanOrEqual(44);
  expect(bb.y + bb.height).toBeLessThanOrEqual(viewport.height + 1);
  expect(bb.y + bb.height, "the way back sits over the bar").toBeLessThanOrEqual(bar.y + 1);
  await page.screenshot({ path: "screenshots/collage-phone-follow.png" });

  // The canvas did not move on its own while the offer stood: a canvas that
  // chased the line would take a region out from under a trimming thumb.
  await page.waitForTimeout(1500);
  expect(await canvas.evaluate((node) => node.scrollTop)).toBe(500);
  await expect(follow).toBeVisible();

  // Tapped, it goes to the line, and then there is nothing to offer.
  await follow.tap();
  await expect(follow).toHaveCount(0);
  const c = (await canvas.boundingBox())!;
  const line = (await page.getByTestId("collage-playhead").boundingBox())!;
  expect(line.y).toBeGreaterThanOrEqual(c.y - 1);
  expect(line.y).toBeLessThanOrEqual(c.y + c.height + 1);

  const text = (await page.getByTestId("collage").innerText()).toLowerCase();
  expect(text).not.toMatch(/\d+:\d\d/);
  expect(text).not.toMatch(/\b\d+(\.\d+)?\s?(s|sec|seconds?|ms|db|bpm|%)\b/);

  await page.getByTestId("collage-play").tap();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "idle");
  await expect(page.getByTestId("collage-follow")).toHaveCount(0);
});

test("an edit mid-play says on the phone that the change has gone quiet", async ({ page, request }) => {
  const { hash } = await firstSound(request);
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", hash, 0, 0, 0.5, 0.02), regionRow("r2", hash, 1, 0, 0.3, 0.02)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  await page.getByTestId("collage-play").tap();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing", { timeout: 20_000 });

  await takeUp(page, "r1");
  const end = handle(page, "r1", "end");
  await end.scrollIntoViewIfNeeded();
  await thumbDrag(page, end, -40);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  // The block that stopped is under the thumb that stopped it, so the bar is
  // the only place this can be said.
  const hint = page.getByTestId("collage-hint");
  await expect(hint).toContainText("gone quiet");
  const bb = (await hint.boundingBox())!;
  expect(bb.y + bb.height).toBeLessThanOrEqual(page.viewportSize()!.height + 1);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  await page.screenshot({ path: "screenshots/collage-phone-quiet.png" });
  await page.getByTestId("collage-play").tap();
  await expect(page.getByTestId("collage-hint")).toHaveCount(0);
});

/* Balance -------------------------------------------------------------------- */

/** The travel across, mirroring `GAIN_SPAN_PX` in `lib/collage.ts`. */
const GAIN_SPAN_PX = 96;

/** Everything the file holds for the collage, levels included. */
async function storedRegions(request: APIRequestContext) {
  const detail = (await (await request.get(`/api/projects/${PROJECT}`)).json()) as {
    document: {
      collage?: {
        regions?: Array<{ id: string; start_s: number; end_s: number; at_s: number; rate: number; gain: number; track: number }>;
      } | null;
    };
  };
  return detail.document.collage?.regions ?? [];
}

/** A thumb on a target, moved `dx` across in steps, then lifted. */
async function thumbAcross(page: Page, target: Locator, dx: number, lift = true): Promise<{ x: number; y: number }> {
  const box = (await target.boundingBox())!;
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await touch(target, "pointerdown", x, y);
  const steps = 6;
  for (let i = 1; i <= steps; i += 1) {
    await touch(target, "pointermove", x + (dx * i) / steps, y);
    await page.waitForTimeout(16);
  }
  if (lift) await touch(target, "pointerup", x + dx, y);
  return { x: x + dx, y };
}

test("balance with one thumb: a thumb-sized button, no handles while it is on, and a drag across the block sets its level", async ({
  page,
  request,
}) => {
  const { hash } = await firstSound(request);
  // Four seconds at full speed: forty pixels tall, so the grab reaches out to
  // a thumb either side of it and is where the drag across begins.
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", hash, 0, 10, 4)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  const viewport = page.viewportSize()!;
  const button = page.getByTestId("collage-balance");

  // The button is a thumb, and the whole bar is still on the screen with five
  // targets in its second row.
  const bb = (await button.boundingBox())!;
  expect(bb.height).toBeGreaterThanOrEqual(44);
  expect(bb.width).toBeGreaterThanOrEqual(44);
  expect(bb.x + bb.width).toBeLessThanOrEqual(viewport.width + 1);
  expect(bb.y + bb.height).toBeLessThanOrEqual(viewport.height + 1);
  await expect(button).toBeDisabled();

  // Take the region up, then the button. No handle is needed and none is left.
  await takeUp(page, "r1");
  await expect(button).toBeEnabled();
  await button.tap();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "balance");
  await expect(page.getByTestId("handle")).toHaveCount(0);
  await expect(page.getByTestId("collage-mode")).toContainText("balance is on");
  const modeBox = (await page.getByTestId("collage-mode").boundingBox())!;
  expect(modeBox.height).toBeGreaterThanOrEqual(44);
  expect(modeBox.y + modeBox.height).toBeLessThanOrEqual(viewport.height + 1);

  // A thumb on the grab is weighing, not scrolling, in either direction.
  const grab = region(page, "r1").getByTestId("region-grab");
  expect(await grab.evaluate((node) => getComputedStyle(node).touchAction)).toBe("none");
  const grabBox = (await grab.boundingBox())!;
  expect(grabBox.height).toBeGreaterThanOrEqual(44);
  expect(grabBox.width).toBeGreaterThanOrEqual(44);
  await page.screenshot({ path: "screenshots/collage-phone-balance-on.png" });

  let writes = 0;
  page.on("request", (r) => {
    if (r.method() === "PUT" && r.url().includes("/collage")) writes += 1;
  });

  // Half the travel to the right is the whole of the top half of the range,
  // and a little past it, so the drag also meets the wall. The block gets
  // heavier as the thumb goes, and nothing is written until the lift.
  const before = (await region(page, "r1").boundingBox())!;
  const fillBefore = await region(page, "r1").evaluate((node) => getComputedStyle(node).backgroundColor);
  const held = await thumbAcross(page, grab, GAIN_SPAN_PX / 2 + 12, false);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-balancing", "true");
  await expect(region(page, "r1")).toHaveAttribute("data-gain", "2");
  await expect(page.getByTestId("collage-mode")).toContainText("as loud as it goes");
  expect(writes).toBe(0);
  const fillDuring = await region(page, "r1").evaluate((node) => getComputedStyle(node).backgroundColor);
  expect(fillDuring, "the block did not take on the weight").not.toBe(fillBefore);
  await page.screenshot({ path: "screenshots/collage-phone-balancing.png" });
  await touch(grab, "pointerup", held.x, held.y);

  await expect(page.getByTestId("collage")).toHaveAttribute("data-balancing", "false");
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(writes).toBe(1);

  // The level is in the file, and nothing about time moved with it: the same
  // moment, the same cut, the same track, the same box on the screen.
  const stored = await storedRegions(request);
  expect(stored[0].gain).toBe(2);
  expect(stored[0]).toMatchObject({ at_s: 10, start_s: 0, end_s: 4, rate: 1, track: 0 });
  const after = (await region(page, "r1").boundingBox())!;
  expect(after.y).toBeCloseTo(before.y, 0);
  expect(after.x).toBeCloseTo(before.x, 0);
  expect(after.height).toBeCloseTo(before.height, 0);

  // Balance stays on for the next one: levels are set against each other.
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "balance");

  // Back down, further than the range is wide: silence, and no further.
  await thumbAcross(page, grab, -300);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(writes).toBe(2);
  expect((await storedRegions(request))[0].gain).toBe(0);
  await expect(page.getByTestId("collage-mode")).toContainText("balance is on");
  await page.screenshot({ path: "screenshots/collage-phone-balanced-quiet.png" });

  // Five targets in the bar's second row now that undo is there, and they all
  // sit on one line inside the phone, each still a thumb.
  const row = await page.evaluate(() => {
    const names = ["collage-play", "collage-snip", "collage-stretch", "collage-balance", "collage-undo"];
    return names.map((name) => {
      const node = document.querySelector(`[data-testid="${name}"]`);
      const box = node?.getBoundingClientRect();
      return box ? { name, x: box.x, y: box.y, w: box.width, h: box.height, bottom: box.bottom } : null;
    });
  });
  expect(row.every((b) => b !== null)).toBe(true);
  for (const button of row) {
    expect(button!.h, `${button!.name} is not a thumb tall`).toBeGreaterThanOrEqual(44);
    expect(button!.w, `${button!.name} is not a thumb wide`).toBeGreaterThanOrEqual(44);
    expect(button!.x + button!.w, `${button!.name} runs off the side`).toBeLessThanOrEqual(viewport.width + 1);
    expect(button!.bottom, `${button!.name} is under the bottom of the phone`).toBeLessThanOrEqual(
      viewport.height + 1,
    );
    expect(button!.y, `${button!.name} wrapped onto a line of its own`).toBeCloseTo(row[0]!.y, 0);
  }

  // No figure anywhere: not on the screen, not on a label, not on a title.
  const text = (await page.getByTestId("collage").innerText()).toLowerCase();
  expect(text).not.toMatch(/\b\d+(\.\d+)?\s?(s|ms|db|%)\b/);
  expect(text).not.toMatch(/\d+:\d\d/);
  const spoken = await page.getByTestId("collage").evaluate((node) =>
    Array.from(node.querySelectorAll("[aria-label], [title]"))
      .map((el) => `${el.getAttribute("aria-label") ?? ""} ${el.getAttribute("title") ?? ""}`)
      .join("\n")
      .toLowerCase(),
  );
  expect(spoken).not.toMatch(/\b\d+(\.\d+)?\s?(s|sec|seconds?|ms|db|%)\b/);

  // The button puts trim back, handles and all.
  await button.tap();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  await expect(page.getByTestId("handle")).toHaveCount(2);
});

test("a thumb that wanders along the block while it drags across changes the level and never the moment", async ({
  page,
  request,
}) => {
  const { hash } = await firstSound(request);
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", hash, 0, 10, 4), regionRow("r2", hash, 1, 10, 4)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  await takeUp(page, "r1");
  await page.getByTestId("collage-balance").tap();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "balance");

  // A real thumb does not travel in a straight line. This one goes a quarter
  // of the way across and sixty pixels down the block at the same time —
  // enough, in trim mode, to trim six seconds off a cut.
  const grab = region(page, "r1").getByTestId("region-grab");
  const box = (await grab.boundingBox())!;
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await touch(grab, "pointerdown", x, y);
  for (let i = 1; i <= 6; i += 1) {
    await touch(grab, "pointermove", x + (GAIN_SPAN_PX / 4) * (i / 6), y + 10 * i);
    await page.waitForTimeout(16);
  }
  await touch(grab, "pointerup", x + GAIN_SPAN_PX / 4, y + 60);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");

  const stored = await storedRegions(request);
  const first = stored.find((r) => r.id === "r1")!;
  expect(first.gain).toBeCloseTo(1.5, 6);
  // Nothing about where or how long it is has moved a hair.
  expect(first).toMatchObject({ at_s: 10, start_s: 0, end_s: 4, rate: 1, track: 0 });
  // And its neighbour on the next track is exactly as it was.
  expect(stored.find((r) => r.id === "r2")).toMatchObject({ at_s: 10, start_s: 0, end_s: 4, gain: 1, track: 1 });

  // Taking the other region up keeps balance on, aimed at it.
  await takeUp(page, "r2");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "balance");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "r2");
  await thumbAcross(page, region(page, "r2").getByTestId("region-grab"), -GAIN_SPAN_PX / 4);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  const both = await storedRegions(request);
  expect(both.find((r) => r.id === "r2")!.gain).toBeCloseTo(0.5, 6);
  expect(both.find((r) => r.id === "r1")!.gain).toBeCloseTo(1.5, 6);
});

test("turning the phone mid-balance lets go without writing anything", async ({ page, request }) => {
  const { hash } = await firstSound(request);
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", hash, 0, 10, 4)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  await takeUp(page, "r1");
  await page.getByTestId("collage-balance").tap();

  let writes = 0;
  page.on("request", (r) => {
    if (r.method() === "PUT" && r.url().includes("/collage")) writes += 1;
  });
  const grab = region(page, "r1").getByTestId("region-grab");
  await thumbAcross(page, grab, GAIN_SPAN_PX / 2, false);
  await expect(region(page, "r1")).toHaveAttribute("data-gain", "2");

  await page.setViewportSize({ width: 852, height: 393 });
  await expect(page.getByTestId("collage")).toHaveAttribute("data-balancing", "false");
  // The level goes back to what the file holds, and nothing was written.
  await expect(region(page, "r1")).toHaveAttribute("data-gain", "1");
  await page.waitForTimeout(300);
  expect(writes).toBe(0);
  expect((await storedRegions(request))[0].gain).toBe(1);
});

test("a second thumb on the block mid-balance stops nothing and starts nothing: the sound being judged keeps sounding", async ({
  page,
  request,
}) => {
  const { hash } = await firstSound(request);
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", hash, 0, 10, 4)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  await takeUp(page, "r1");
  await page.getByTestId("collage-balance").tap();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "balance");
  // Taking the region up played it, which is what a balance is judged
  // against: the level moves under the ear rather than on the next tap.
  await expect(region(page, "r1")).toHaveAttribute("data-playing", "true");

  const grab = region(page, "r1").getByTestId("region-grab");
  const box = (await grab.boundingBox())!;
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await touch(grab, "pointerdown", x, y);
  for (let i = 1; i <= 4; i += 1) {
    await touch(grab, "pointermove", x + 6 * i, y);
    await page.waitForTimeout(16);
  }
  await expect(region(page, "r1")).toHaveAttribute("data-gain", "1.5");

  // A phone held in one hand and balanced with the other finds a second
  // thumb on the block sooner or later. A tap on a block plays it, so this
  // is the touch that would stop the sound the ear is judging against.
  await touch(grab, "pointerdown", x - 20, y + 4, 9);
  await touch(grab, "pointerup", x - 20, y + 4, 9);
  await page.waitForTimeout(200);
  await expect(region(page, "r1")).toHaveAttribute("data-playing", "true");
  await expect(region(page, "r1")).toHaveAttribute("data-gain", "1.5");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-balancing", "true");

  // And the first thumb still owns the gesture: it finishes and it writes.
  await touch(grab, "pointermove", x + 24, y);
  await touch(grab, "pointerup", x + 24, y);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect((await storedRegions(request)).find((r) => r.id === "r1")!.gain).toBeCloseTo(1.5, 6);
});

test("a thumb that lands where a track-0 block meets the edge of the glass runs out of room, and the next drag carries on", async ({
  page,
  request,
}) => {
  const { hash } = await firstSound(request);
  // Three tracks, as the real project has: four columns of a hundred and
  // twenty-eight are wider than a phone, so the canvas scrolls and track zero
  // really does begin at the edge of the glass.
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: {
      regions: [regionRow("r1", hash, 0, 10, 4), regionRow("r2", hash, 1, 10, 4), regionRow("r3", hash, 2, 10, 4)],
    },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  await takeUp(page, "r1");
  await page.getByTestId("collage-balance").tap();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "balance");

  // A thumb that lands on the first pixels of that block has less glass to
  // its left than the range needs, and a real thumb cannot leave the screen.
  // This is the worst landing there is: the block's own left edge.
  const grab = region(page, "r1").getByTestId("region-grab");
  const box = (await grab.boundingBox())!;
  const room = box.x;
  expect(room, "a track-0 block now has a whole range of glass to its left").toBeLessThan(GAIN_SPAN_PX / 2);
  const y = box.y + box.height / 2;
  await touch(grab, "pointerdown", room, y);
  for (let i = 1; i <= 4; i += 1) {
    await touch(grab, "pointermove", Math.max(0, room - (room * i) / 4), y);
    await page.waitForTimeout(16);
  }
  await touch(grab, "pointerup", 0, y);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  // The glass ran out before the range did: the level came down by the
  // travel the screen allowed and stopped there, short of silence.
  const once = (await storedRegions(request)).find((r) => r.id === "r1")!.gain;
  expect(once, "one drag from the worst landing reached silence after all").toBeGreaterThan(0);
  expect(once).toBeCloseTo(1 - (2 * room) / GAIN_SPAN_PX, 2);
  // And the bar does not claim a wall, because there was none: the glass ran
  // out, not the range.
  await expect(page.getByTestId("collage-mode")).toHaveAttribute("data-bound", "");

  // The second drag carries on from where the first stopped, which is what
  // makes the whole range reachable from anywhere on the block.
  for (let round = 0; round < 3; round += 1) {
    const again = region(page, "r1").getByTestId("region-grab");
    const at = (await again.boundingBox())!;
    const from = at.x + at.width - 4;
    await touch(again, "pointerdown", from, y);
    for (let i = 1; i <= 6; i += 1) {
      await touch(again, "pointermove", Math.max(0, from - (from * i) / 6), y);
      await page.waitForTimeout(16);
    }
    await touch(again, "pointerup", 0, y);
    await page.waitForTimeout(150);
  }
  await expect(region(page, "r1")).toHaveAttribute("data-gain", "0");
  expect((await storedRegions(request)).find((r) => r.id === "r1")!.gain).toBe(0);
});

/**
 * The mean lightness of a block as the screen really draws it, waveform and
 * all, on a scale of nought to 255.
 *
 * `blockLuma` in the desktop spec reads the fill's declared colour. This reads
 * the pixels, because the fill is not the only ink in the box: the waveform is
 * drawn over it and does not follow the level, so what the eye actually gets
 * is the two together.
 */
async function blockInk(page: Page, regionId: string): Promise<number> {
  const shot = await region(page, regionId).screenshot();
  return page.evaluate(async (b64) => {
    const img = new Image();
    img.src = `data:image/png;base64,${b64}`;
    await img.decode();
    const canvas = document.createElement("canvas");
    canvas.width = img.width;
    canvas.height = img.height;
    const ctx = canvas.getContext("2d")!;
    ctx.drawImage(img, 0, 0);
    const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    let sum = 0;
    for (let i = 0; i < data.length; i += 4) {
      sum += 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2];
    }
    return (sum * 4) / data.length;
  }, shot.toString("base64"));
}

test("weight is read off the block as it is really drawn, not off the fill alone: silence, unity and the loudest are three different amounts of ink", async ({
  page,
  request,
}) => {
  const { hash } = await firstSound(request);
  // The same sound at three levels, side by side, each long enough that the
  // waveform inside it is most of what the eye gets.
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: {
      regions: [
        { ...regionRow("r1", hash, 0, 2, 6), gain: 0 },
        { ...regionRow("r2", hash, 1, 2, 6), gain: 1 },
        { ...regionRow("r3", hash, 2, 2, 6), gain: 2 },
      ],
    },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  await expect(page.getByTestId("region")).toHaveCount(3);

  const quiet = await blockInk(page, "r1");
  const unity = await blockInk(page, "r2");
  const loud = await blockInk(page, "r3");
  expect(quiet, "a silent block is not darker than an untouched one, as it is drawn").toBeLessThan(unity);
  expect(unity, "the loudest block is not lighter than an untouched one, as it is drawn").toBeLessThan(loud);
  // Each level is a plainly different amount of ink on the glass, not a
  // difference that only a colour picker can find. A twelfth of the span is
  // about the smallest step a phone held at arm's length will show.
  expect(unity - quiet).toBeGreaterThan((loud - quiet) / 12);
  expect(loud - unity).toBeGreaterThan((loud - quiet) / 12);

  // The canvas behind them, for scale: whatever the level, a block is a block
  // and can still be found and taken up.
  const ground = await page.evaluate(() => {
    const canvas = document.querySelector('[data-testid="collage-canvas"]') ?? document.body;
    const parts = getComputedStyle(canvas as HTMLElement).backgroundColor.match(/[\d.]+/g)!.map(Number);
    return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2];
  });
  expect(quiet, "a silent block disappeared into the canvas").toBeGreaterThan(ground);
});

test("switching mode under a balancing thumb writes nothing and leaves the level where the file has it", async ({
  page,
  request,
}) => {
  const { hash } = await firstSound(request);
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", hash, 0, 10, 4)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  await takeUp(page, "r1");
  await page.getByTestId("collage-balance").tap();

  let writes = 0;
  page.on("request", (r) => {
    if (r.method() === "PUT" && r.url().includes("/collage")) writes += 1;
  });
  const grab = region(page, "r1").getByTestId("region-grab");
  await thumbAcross(page, grab, GAIN_SPAN_PX / 2, false);
  await expect(region(page, "r1")).toHaveAttribute("data-gain", "2");

  // A second thumb on the snip button while the first is still on the block.
  // The thumb that started the drag is not the one that pressed the button,
  // so the drag is let go of rather than applied.
  await page.getByTestId("collage-snip").tap();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "snip");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-balancing", "false");
  await expect(region(page, "r1")).toHaveAttribute("data-gain", "1");
  await page.waitForTimeout(300);
  expect(writes).toBe(0);
  expect((await storedRegions(request)).find((r) => r.id === "r1")!.gain).toBe(1);
});

test("every target in the bar is on the screen once balance is in it, undo included", async ({
  page,
  request,
}) => {
  const { hash } = await firstSound(request);
  const put = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [regionRow("r1", hash, 0, 10, 4)] },
  });
  expect(put.ok()).toBe(true);
  await page.goto("/collage");
  await takeUp(page, "r1");
  await page.getByTestId("collage-balance").tap();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "balance");

  // Undo only exists once there is something to take back, so make one
  // balance first. That is also when the row goes from four targets to five.
  await thumbAcross(page, region(page, "r1").getByTestId("region-grab"), GAIN_SPAN_PX / 4);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  await expect(page.getByTestId("collage-undo")).toHaveAttribute("data-depth", "1");

  // Balance is the fifth target in a row that held four. Undo is the last of
  // them and the one that matters most: it is the way back from a held
  // whole-region snip, and a thumb cannot reach what is under the fold.
  const viewport = page.viewportSize()!;
  for (const name of ["collage-play", "collage-snip", "collage-stretch", "collage-balance", "collage-undo"]) {
    const box = (await page.getByTestId(name).boundingBox())!;
    expect(box, `${name} is not on the screen at all`).toBeTruthy();
    expect(box.height, `${name} is not a thumb tall`).toBeGreaterThanOrEqual(44);
    expect(box.width, `${name} is not a thumb wide`).toBeGreaterThanOrEqual(44);
    expect(box.y + box.height, `${name} runs off the bottom of the phone`).toBeLessThanOrEqual(viewport.height + 1);
    expect(box.x + box.width, `${name} runs off the side of the phone`).toBeLessThanOrEqual(viewport.width + 1);
    expect(box.x, `${name} starts off the side of the phone`).toBeGreaterThanOrEqual(-1);
  }

  // And the same with the bar at its tallest: a wall message is two lines.
  const grab = region(page, "r1").getByTestId("region-grab");
  await thumbAcross(page, grab, -400, false);
  await expect(page.getByTestId("collage-mode")).toHaveAttribute("data-bound", "quiet");
  const undo = (await page.getByTestId("collage-undo").boundingBox())!;
  expect(undo.y + undo.height, "undo went under the fold once the bar said a wall").toBeLessThanOrEqual(
    viewport.height + 1,
  );
  const held = (await grab.boundingBox())!;
  await touch(grab, "pointerup", held.x, held.y + held.height / 2);
});
