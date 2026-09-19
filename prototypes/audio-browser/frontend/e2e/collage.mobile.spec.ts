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

/** One touch pointer event at a point, dispatched on the handle. */
async function touch(target: Locator, type: string, clientX: number, clientY: number): Promise<void> {
  await target.dispatchEvent(type, {
    pointerType: "touch",
    pointerId: 7,
    isPrimary: true,
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
