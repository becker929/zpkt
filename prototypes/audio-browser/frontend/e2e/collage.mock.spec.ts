/**
 * The collage view: choose a sound, stamp it, hear it, trim it.
 *
 * Against mock mode, where the project in `collage` is `conveyor belt` with two
 * frozen sounds, both about a second long. Every test writes an empty
 * arrangement back before and after itself: the mock server keeps its projects
 * in memory and is reused between runs, so a region left behind would be drawn
 * by the next run's first test.
 *
 * The sounds are short, so the trim tests write regions straight in with a
 * slow `rate`: a second of source at a twentieth speed is twenty seconds on the
 * canvas, which is enough to drag across. The model allows it, and the view
 * has to draw and trim a slowed region correctly anyway.
 *
 * Nothing here touches the real projects directory.
 */

import { expect, test, type APIRequestContext, type Locator, type Page } from "@playwright/test";

import { STREAM_URL, api } from "./helpers";

/** The fixture project in `collage`. */
const PROJECT = "2026-09-12-conveyor-belt";

/** The geometry the view draws with. Mirrors `lib/collage.ts`. */
const PX_PER_S = 10;
const TRACK_W = 128;
const TOP_PAD = 56;
const HANDLE_H = 44;
const MIN_REGION_S = 0.25;

interface RegionRow {
  id: string;
  hash: string;
  track: number;
  start_s: number;
  end_s: number;
  at_s: number;
  rate: number;
  gain: number;
  fade_in_s: number;
  fade_out_s: number;
}

async function resetCollage(request: APIRequestContext): Promise<void> {
  const response = await request.put(`/api/projects/${PROJECT}/collage`, { data: { regions: [] } });
  expect(response.ok(), `resetting the collage answered ${response.status()}`).toBe(true);
}

async function writeRegions(request: APIRequestContext, regions: RegionRow[]): Promise<void> {
  const response = await request.put(`/api/projects/${PROJECT}/collage`, { data: { regions } });
  expect(response.ok(), `writing regions answered ${response.status()}`).toBe(true);
}

async function regionsOnServer(page: Page): Promise<RegionRow[]> {
  const detail = await api(page, `/api/projects/${PROJECT}`);
  const document = detail.document as { collage?: { regions?: RegionRow[] } | null };
  return document.collage?.regions ?? [];
}

/** The project's sounds, with their lengths, read through the API. */
async function sounds(page: Page): Promise<Array<{ hash: string; duration_s: number; filename: string }>> {
  const detail = await api(page, `/api/projects/${PROJECT}`);
  return (detail.items as Array<{ hash: string; duration_s: number; filename: string }>).map((row) => ({
    hash: row.hash,
    duration_s: row.duration_s,
    filename: row.filename,
  }));
}

/** A region row, exactly as the file holds it. */
function regionRow(id: string, hash: string, track: number, atS: number, startS: number, endS: number, rate = 1): RegionRow {
  return { id, hash, track, start_s: startS, end_s: endS, at_s: atS, rate, gain: 1, fade_in_s: 0, fade_out_s: 0 };
}

/** Open the picker, hear the `index`th sound, and choose it. */
async function choose(page: Page, index: number): Promise<string> {
  await page.getByTestId("collage-choose").click();
  await expect(page.getByTestId("collage-picker")).toBeVisible();
  const row = page.getByTestId("picker-row").nth(index);
  const hash = (await row.getAttribute("data-hash")) ?? "";
  await row.click();
  await page.getByTestId("picker-use").click();
  await expect(page.getByTestId("collage-picker")).toHaveCount(0);
  await expect(page.getByTestId("collage-choose")).toHaveAttribute("data-hash", hash);
  return hash;
}

/**
 * Click the canvas at a point inside the blank, in canvas coordinates.
 *
 * The canvas scrolls, and a point below the fold would be under the stamp
 * bar. Scroll it into the middle of the canvas first, the way a thumb would.
 */
async function stampAt(page: Page, x: number, y: number): Promise<void> {
  await page.getByTestId("collage-canvas").evaluate((node, target) => {
    node.scrollTop = Math.max(0, target - 200);
  }, y);
  const space = page.getByTestId("collage-space");
  await space.click({ position: { x, y } });
}

async function regionBox(page: Page, nth: number) {
  const region = page.getByTestId("region").nth(nth);
  const space = await page.getByTestId("collage-space").boundingBox();
  const box = await region.boundingBox();
  expect(space).not.toBeNull();
  expect(box).not.toBeNull();
  return { top: box!.y - space!.y, left: box!.x - space!.x, width: box!.width, height: box!.height };
}

function handle(page: Page, regionId: string, end: "start" | "end") {
  return page.locator(`[data-testid="handle"][data-region-id="${regionId}"][data-end="${end}"]`);
}

/** How many pixels a region's own canvas painted. `paintedPixels` expects a wrapper. */
async function paintedOn(canvas: Locator): Promise<number> {
  return canvas.evaluate((node) => {
    const c = node as HTMLCanvasElement;
    const ctx = c.getContext("2d");
    if (!ctx || c.width === 0 || c.height === 0) return 0;
    const { data } = ctx.getImageData(0, 0, c.width, c.height);
    let painted = 0;
    for (let i = 3; i < data.length; i += 4) if (data[i] !== 0) painted += 1;
    return painted;
  });
}

function region(page: Page, regionId: string) {
  return page.locator(`[data-testid="region"][data-region-id="${regionId}"]`);
}

/**
 * Take a region up, if it is not up already, by clicking its box. Only the
 * region taken up has handles. The click plays the region too; that is what
 * a tap on a region does, and a drag on a handle stops it.
 */
async function takeUp(page: Page, regionId: string) {
  const target = region(page, regionId);
  if ((await target.getAttribute("data-selected")) === "true") return;
  const box = (await target.boundingBox())!;
  await target.click({ position: { x: 10, y: Math.min(box.height / 2, 30) } });
  await expect(target).toHaveAttribute("data-selected", "true");
}

/** Select a handle by clicking it, and wait until the view says it is selected. */
async function select(page: Page, regionId: string, end: "start" | "end") {
  await takeUp(page, regionId);
  const h = handle(page, regionId, end);
  await h.scrollIntoViewIfNeeded();
  await h.click();
  await expect(h).toHaveAttribute("data-selected", "true");
  return h;
}

/** Drag a selected handle by `dy` pixels with the mouse, in steps, and let go. */
async function drag(page: Page, regionId: string, end: "start" | "end", dy: number): Promise<void> {
  const h = await select(page, regionId, end);
  const box = (await h.boundingBox())!;
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, y + dy, { steps: 8 });
  await page.mouse.up();
}

/** How many times the arrangement was written while `run` ran. */
async function writesDuring(page: Page, run: () => Promise<unknown>): Promise<number> {
  let writes = 0;
  const listener = (request: { method(): string; url(): string }) => {
    if (request.method() === "PUT" && request.url().includes("/collage")) writes += 1;
  };
  page.on("request", listener);
  await run();
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  page.off("request", listener);
  return writes;
}

test.beforeEach(async ({ request }) => {
  await resetCollage(request);
});

test.afterEach(async ({ request }) => {
  await resetCollage(request);
});

test("opens the project in collage with a genuinely empty canvas", async ({ page }) => {
  await page.goto("/collage");
  await expect(page.getByTestId("collage")).toBeVisible();
  await expect(page.getByTestId("collage-project")).toHaveText("conveyor belt");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-regions", "0");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-tracks", "0");
  await expect(page.getByTestId("region")).toHaveCount(0);

  // Nothing drawn: no lanes, no ticks, no ruler. The blank has no children.
  expect(await page.getByTestId("collage-space").locator("*").count()).toBe(0);

  // No player bar. The bottom of the screen belongs to the stamp bar.
  await expect(page.getByTestId("player-bar")).toHaveCount(0);
  await expect(page.getByTestId("player-idle")).toHaveCount(0);
  await expect(page.getByTestId("collage-choose")).toBeVisible();
});

test("no seconds, no grid, no decibels appear anywhere in the view, nor hours in the header", async ({ page }) => {
  await page.goto("/collage");
  await choose(page, 0);
  await stampAt(page, 40, 200);
  await expect(page.getByTestId("region")).toHaveCount(1);
  await page.getByTestId("collage-choose").click();
  await expect(page.getByTestId("collage-picker")).toBeVisible();

  const text = (await page.getByTestId("collage").innerText()).toLowerCase();
  // m:ss, a bare count of seconds, and a decibel figure.
  expect(text).not.toMatch(/\d+:\d\d/);
  expect(text).not.toMatch(/\b\d+(\.\d+)?\s?s\b/);
  expect(text).not.toMatch(/\bdb\b/);

  // The header above the view keeps its count of sounds and its bytes, and
  // drops its hours: hours are seconds by another name.
  const stats = page.getByTestId("topbar-stats");
  await expect(stats).toHaveAttribute("data-hours", "hidden");
  await expect(stats).not.toHaveText("…");
  expect(await stats.innerText()).not.toMatch(/\d(\.\d+)?\s?h\b/);
  expect(await stats.innerText()).toMatch(/sounds/);

  // And gets them back on any other view.
  await page.goto("/board");
  await expect(page.getByTestId("topbar-stats")).not.toHaveAttribute("data-hours", "hidden");
  await expect(page.getByTestId("topbar-stats")).toContainText("h");
});

test("a sound can be heard before it is chosen, and the preview stops when it is", async ({ page }) => {
  await page.goto("/collage");
  await page.getByTestId("collage-choose").click();
  await expect(page.getByTestId("collage-picker")).toBeVisible();
  await expect(page.getByTestId("picker-row")).toHaveCount(2);

  // Nothing is chosen by opening the picker. Choosing takes a sound and a press.
  await expect(page.getByTestId("picker-use")).toBeDisabled();

  const row = page.getByTestId("picker-row").first();
  const hash = await row.getAttribute("data-hash");
  await row.click();

  // Heard through the shared player, streamed by hash. Nothing is decoded.
  const audio = page.getByTestId("audio");
  await expect.poll(async () => audio.evaluate((node) => (node as HTMLAudioElement).src)).toMatch(STREAM_URL);
  expect(await audio.evaluate((node) => (node as HTMLAudioElement).src)).toContain(hash);
  await expect(page.getByTestId("picker-preview")).toBeVisible();
  await expect(page.getByTestId("picker-preview").getByTestId("waveform")).toBeVisible();

  await page.getByTestId("picker-use").click();
  await expect(page.getByTestId("collage-picker")).toHaveCount(0);
  await expect(page.getByTestId("collage-choose")).toHaveAttribute("data-hash", hash ?? "");
  await expect.poll(async () => audio.evaluate((node) => (node as HTMLAudioElement).paused)).toBe(true);
});

test("tapping the canvas before choosing stamps nothing and opens the picker", async ({ page }) => {
  await page.goto("/collage");
  await stampAt(page, 60, 200);
  await expect(page.getByTestId("region")).toHaveCount(0);
  await expect(page.getByTestId("collage-hint")).toBeVisible();
  await expect(page.getByTestId("collage-picker")).toBeVisible();
  expect(await regionsOnServer(page)).toEqual([]);
});

test("stamping makes the first track and starts time at the top; beside it makes a track", async ({ page }) => {
  await page.goto("/collage");
  const set = await sounds(page);
  const hash = await choose(page, 0);
  const duration = set.find((s) => s.hash === hash)!.duration_s;

  // The first stamp, wherever the thumb was, starts time at zero.
  await stampAt(page, 40, 320);
  await expect(page.getByTestId("region")).toHaveCount(1);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-tracks", "1");
  const first = await regionBox(page, 0);
  expect(first.top).toBeCloseTo(TOP_PAD, 0);
  expect(first.left).toBeCloseTo(0, 0);
  expect(first.width).toBeCloseTo(TRACK_W, 0);
  // Height is duration, exactly. Nothing pads a short sound up to a thumb.
  expect(first.height).toBeCloseTo(duration * PX_PER_S, 0);
  await expect(page.getByTestId("region").first()).toHaveAttribute("data-track", "0");

  // The second stamp lands where it was tapped.
  const y2 = Math.round(first.top + first.height + 100);
  await stampAt(page, 40, y2);
  await expect(page.getByTestId("region")).toHaveCount(2);
  const second = await regionBox(page, 1);
  expect(second.top).toBeCloseTo(y2, 0);
  await expect(page.getByTestId("region").nth(1)).toHaveAttribute("data-track", "0");

  // Beside the first track is a new track.
  await stampAt(page, TRACK_W + 40, 320);
  await expect(page.getByTestId("region")).toHaveCount(3);
  await expect(page.getByTestId("region").nth(2)).toHaveAttribute("data-track", "1");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-tracks", "2");
  const third = await regionBox(page, 2);
  expect(third.left).toBeCloseTo(TRACK_W, 0);

  // Saved whole, every field present at its untouched value.
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  const stored = await regionsOnServer(page);
  expect(stored).toHaveLength(3);
  expect(stored[0]).toMatchObject({
    id: "r1",
    hash,
    track: 0,
    start_s: 0,
    at_s: 0,
    rate: 1,
    gain: 1,
    fade_in_s: 0,
    fade_out_s: 0,
  });
  expect(stored[0].end_s).toBeCloseTo(duration, 2);
  expect(stored[2].track).toBe(1);
  expect(stored.map((r) => r.id)).toEqual(["r1", "r2", "r3"]);

  // Reload draws what was saved, in the same places.
  await page.reload();
  await expect(page.getByTestId("region")).toHaveCount(3);
  const again = await regionBox(page, 1);
  expect(again.top).toBeCloseTo(second.top, 0);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-tracks", "2");
});

test("a stamp that would overlap a region slides down to sit after it", async ({ page }) => {
  await page.goto("/collage");
  const set = await sounds(page);
  const hash = await choose(page, 0);
  const d = set.find((s) => s.hash === hash)!.duration_s;

  // A at the top. B thirty seconds after A ends. Then C aimed just above B,
  // with too little room before B for a sound d long: it lands right after
  // B's sound, whatever d is.
  await stampAt(page, 40, 200);
  const bAt = d + 30;
  await stampAt(page, 40, Math.round(TOP_PAD + bAt * PX_PER_S));
  await expect(page.getByTestId("region")).toHaveCount(2);
  // Aimed at the flank of the track, beside B's top handle, so the tap is a
  // stamp and not a selection.
  const cAim = bAt - d / 2;
  await stampAt(page, 12, Math.round(TOP_PAD + cAim * PX_PER_S));
  await expect(page.getByTestId("region")).toHaveCount(3);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");

  const stored = await regionsOnServer(page);
  expect(stored[2].at_s).toBeCloseTo(bAt + d, 1);
  const c = await regionBox(page, 2);
  expect(c.top).toBeCloseTo(TOP_PAD + (bAt + d) * PX_PER_S, 0);
});

test("tapping a region plays it from a bounded slice, and does not stamp", async ({ page }) => {
  await page.goto("/collage");
  const set = await sounds(page);
  const hash = await choose(page, 0);
  const duration = set.find((s) => s.hash === hash)!.duration_s;
  await stampAt(page, 40, 200);
  await expect(page.getByTestId("region")).toHaveCount(1);

  const region = page.getByTestId("region").first();
  const slice = page.waitForRequest((request) => request.url().includes(`/api/files/${hash}/slice?`));
  await region.click();
  const request = await slice;
  const url = new URL(request.url());
  expect(Number(url.searchParams.get("start"))).toBe(0);
  // The first piece is at most fifteen seconds, never the whole source.
  expect(Number(url.searchParams.get("end"))).toBeLessThanOrEqual(Math.min(duration, 15) + 0.001);
  expect(url.pathname).not.toContain("stream");

  await expect(region).toHaveAttribute("data-playing", "true");
  await expect(page.getByTestId("region")).toHaveCount(1);
  await expect(page.getByTestId("collage-play-error")).toHaveCount(0);

  // A second tap stops it.
  await region.click();
  await expect(region).toHaveAttribute("data-playing", "false");
  await expect(page.getByTestId("region")).toHaveCount(1);
});

test("undo is a stack: each stamp is a step, the button says how many, and the last undo empties it", async ({ page }) => {
  await page.goto("/collage");
  await choose(page, 0);
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);
  await stampAt(page, 40, 200);
  // Well after the first region, inside the blank the view leaves below it.
  const blank = await page.getByTestId("collage-space").boundingBox();
  await stampAt(page, 40, Math.round(blank!.height - 60));
  await expect(page.getByTestId("region")).toHaveCount(2);
  await expect(page.getByTestId("collage-undo")).toBeVisible();
  await expect(page.getByTestId("collage-undo")).toHaveAttribute("data-depth", "2");
  await expect(page.getByTestId("collage-undo")).toContainText("2 steps");

  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("region")).toHaveCount(1);
  await expect(page.getByTestId("collage-undo")).toHaveAttribute("data-depth", "1");
  await expect(page.getByTestId("collage-undo")).toContainText("1 step");
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(await regionsOnServer(page)).toHaveLength(1);

  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("region")).toHaveCount(0);
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(await regionsOnServer(page)).toHaveLength(0);
});

/* Trim ----------------------------------------------------------------------- */

test("a region shows the sound inside it: peaks, silence and spans, drawn down the box", async ({ page, request }) => {
  const set = await sounds(page);
  const sound = set[0];
  // Slowed twenty times, so a second of source is a hand's height on screen.
  await writeRegions(request, [regionRow("r1", sound.hash, 0, 0, 0, sound.duration_s, 0.05)]);
  await page.goto("/collage");
  const region = page.getByTestId("region").first();
  await expect(region).toBeVisible();

  const wave = region.getByTestId("region-wave");
  await expect.poll(async () => Number(await wave.getAttribute("data-buckets"))).toBe(1000);
  await expect.poll(async () => paintedOn(wave)).toBeGreaterThan(200);

  // Taller than wide: the sound runs down the region.
  const box = (await wave.boundingBox())!;
  expect(box.height).toBeGreaterThan(box.width);
  const regionBoxNow = (await region.boundingBox())!;
  expect(box.height).toBeCloseTo(regionBoxNow.height, 0);

  // The silence it tints is the same measurement every other view draws.
  const silence = await api(page, `/api/files/${sound.hash}/silence?min_gap=2`);
  const intervals = silence.intervals as unknown[];
  await expect(wave).toHaveAttribute("data-silent-regions", String(intervals.length));
});

test("the region taken up has a handle at each end, outside its box and a thumb tall; no other region has any", async ({
  page,
}) => {
  await page.goto("/collage");
  const set = await sounds(page);
  const hash = await choose(page, 0);
  const d = set.find((s) => s.hash === hash)!.duration_s;
  await stampAt(page, 40, 200);
  await stampAt(page, TRACK_W + 40, 200);
  await expect(page.getByTestId("region")).toHaveCount(2);
  // Nothing is taken up: no handles anywhere. Each region has a grab.
  await expect(page.getByTestId("handle")).toHaveCount(0);
  await expect(page.getByTestId("region-grab")).toHaveCount(2);
  await takeUp(page, "r1");
  await expect(page.getByTestId("handle")).toHaveCount(2);
  await expect(handle(page, "r2", "start")).toHaveCount(0);

  const box = (await page.getByTestId("region").first().boundingBox())!;
  const start = (await handle(page, "r1", "start").boundingBox())!;
  const end = (await handle(page, "r1", "end").boundingBox())!;
  // A second of sound is ten pixels of box. The handles are the reach.
  expect(box.height).toBeCloseTo(d * PX_PER_S, 0);
  expect(start.height).toBeGreaterThanOrEqual(HANDLE_H);
  expect(end.height).toBeGreaterThanOrEqual(HANDLE_H);
  expect(start.width).toBeGreaterThanOrEqual(44);
  // Against the box's edge, give or take its one-pixel border.
  expect(Math.abs(start.y + start.height - box.y)).toBeLessThanOrEqual(2);
  expect(Math.abs(end.y - (box.y + box.height))).toBeLessThanOrEqual(2);

  // Handles carry no numbers either, and neither does anything a screen
  // reader or a hover would say.
  const text = (await page.getByTestId("collage").innerText()).toLowerCase();
  expect(text).not.toMatch(/\b\d+(\.\d+)?\s?s\b/);
  const spoken = await page.getByTestId("collage").evaluate((node) =>
    Array.from(node.querySelectorAll("[aria-label], [title]"))
      .map((el) => `${el.getAttribute("aria-label") ?? ""} ${el.getAttribute("title") ?? ""}`)
      .join("\n")
      .toLowerCase(),
  );
  expect(spoken).not.toMatch(/\d+:\d\d/);
  expect(spoken).not.toMatch(/\b\d+(\.\d+)?\s?(s|sec|seconds?|ms|db)\b/);
});

test("a tap takes a region up; a tap on a handle selects it, one at a time; a tap on the blank puts it down and stamps", async ({
  page,
}) => {
  await page.goto("/collage");
  await choose(page, 0);
  await stampAt(page, 40, 200);
  await expect(page.getByTestId("region")).toHaveCount(1);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "");

  // Up, with no handle selected yet.
  await takeUp(page, "r1");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "r1");
  await expect(page.getByTestId("region").first()).toHaveAttribute("data-playing", "true");

  await select(page, "r1", "start");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "r1:start");
  await expect(page.getByTestId("region").first()).toHaveAttribute("data-selected", "true");

  // The other end takes the selection over. Never two.
  await select(page, "r1", "end");
  await expect(handle(page, "r1", "start")).toHaveAttribute("data-selected", "false");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "r1:end");

  // Taking up and selecting are not writing.
  await expect(page.getByTestId("collage-undo")).toHaveAttribute("data-depth", "1");

  // A tap on the blank, with a sound chosen, puts the region down and
  // stamps. One tap, not two: a tap that only let go would be a dead tap
  // after every listen.
  await stampAt(page, 40, 500);
  await expect(page.getByTestId("region")).toHaveCount(2);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "");
  await expect(page.getByTestId("handle")).toHaveCount(0);

  // Escape puts it down too.
  await select(page, "r2", "start");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "");
  await expect(page.getByTestId("region")).toHaveCount(2);
});

test("letting go of the start handle keeps the handle under the thumb: the canvas moves, not the handle", async ({
  page,
  request,
}) => {
  // Trimming the start keeps the region where it sounds, so the new start is
  // drawn at the top of the box, which is not where the thumb is. If nothing
  // moved, the handle would jump back up by the whole drag and the thumb
  // would be left over the middle of the region. The canvas scrolls by the
  // same distance instead.
  const set = await sounds(page);
  const sound = set[0];
  const rate = 0.05;
  await writeRegions(request, [regionRow("r1", sound.hash, 0, 30, 0, sound.duration_s, rate)]);
  await page.goto("/collage");
  const canvas = page.getByTestId("collage-canvas");
  await canvas.evaluate((node) => {
    node.scrollTop = 200;
  });
  const h = await select(page, "r1", "start");
  const hb = (await h.boundingBox())!;
  const x = hb.x + hb.width / 2;
  const y = hb.y + hb.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, y + 100, { steps: 6 });
  const held = (await h.boundingBox())!;
  expect(held.y + held.height / 2).toBeCloseTo(y + 100, 0);
  await page.mouse.up();
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  const [stored] = await regionsOnServer(page);
  expect(stored.start_s).toBeCloseTo(0.5, 2);
  expect(stored.at_s).toBe(30);
  // Where the thumb lifted is where the handle still is.
  const after = (await h.boundingBox())!;
  expect(after.y + after.height / 2).toBeCloseTo(y + 100, 0);
  expect(await canvas.evaluate((node) => node.scrollTop)).toBeCloseTo(100, 0);
});

test("undo, three times over trim, stamp, trim: each step takes back exactly the last change", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  const sound = set[0];
  const rate = 0.05;
  await writeRegions(request, [regionRow("r1", sound.hash, 0, 0, 0, sound.duration_s, rate)]);
  await page.goto("/collage");
  await choose(page, 0);

  await drag(page, "r1", "end", -60);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  await stampAt(page, TRACK_W + 40, 200);
  await expect(page.getByTestId("region")).toHaveCount(2);
  await drag(page, "r1", "end", -40);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  await expect(page.getByTestId("collage-undo")).toHaveAttribute("data-depth", "3");
  let stored = await regionsOnServer(page);
  expect(stored[0].end_s).toBeCloseTo(sound.duration_s - 0.5, 2);
  expect(stored).toHaveLength(2);

  // Back one: the second trim. The handle stays selected.
  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("collage-undo")).toHaveAttribute("data-depth", "2");
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  stored = await regionsOnServer(page);
  expect(stored[0].end_s).toBeCloseTo(sound.duration_s - 0.3, 2);
  expect(stored).toHaveLength(2);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "r1:end");

  // Back two: the stamp.
  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("collage-undo")).toHaveAttribute("data-depth", "1");
  await expect(page.getByTestId("region")).toHaveCount(1);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  stored = await regionsOnServer(page);
  expect(stored[0].end_s).toBeCloseTo(sound.duration_s - 0.3, 2);

  // Back three: the first trim. Nothing left to take back.
  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  stored = await regionsOnServer(page);
  expect(stored[0].end_s).toBeCloseTo(sound.duration_s, 3);
  expect(stored).toHaveLength(1);
});

test("dragging the end handle trims the end; the region keeps its place; one write per drag", async ({ page, request }) => {
  const set = await sounds(page);
  const sound = set[0];
  const rate = 0.05;
  await writeRegions(request, [regionRow("r1", sound.hash, 0, 3, 0, sound.duration_s, rate)]);
  await page.goto("/collage");
  await expect(page.getByTestId("region")).toHaveCount(1);
  const before = await regionBox(page, 0);
  expect(before.top).toBeCloseTo(TOP_PAD + 3 * PX_PER_S, 0);
  expect(before.height).toBeCloseTo((sound.duration_s / rate) * PX_PER_S, 0);

  // A hundred pixels up is ten canvas seconds, which is half a second of
  // source at this rate.
  const writes = await writesDuring(page, () => drag(page, "r1", "end", -100));
  expect(writes).toBe(1);

  const [stored] = await regionsOnServer(page);
  expect(stored.end_s).toBeCloseTo(sound.duration_s - 0.5, 2);
  expect(stored.start_s).toBe(0);
  expect(stored.at_s).toBe(3);
  expect(stored.rate).toBe(rate);

  const after = await regionBox(page, 0);
  expect(after.top).toBeCloseTo(before.top, 0);
  expect(after.height).toBeCloseTo(before.height - 100, 0);
  // The handle is still selected, and the box is the new truth.
  await expect(handle(page, "r1", "end")).toHaveAttribute("data-selected", "true");
  await expect(page.getByTestId("collage-undo")).toHaveAttribute("data-depth", "1");
});

test("dragging the start handle trims the start of the cut; where the region sounds does not move", async ({ page, request }) => {
  const set = await sounds(page);
  const sound = set[0];
  const rate = 0.05;
  await writeRegions(request, [regionRow("r1", sound.hash, 0, 3, 0, sound.duration_s, rate)]);
  await page.goto("/collage");
  const before = await regionBox(page, 0);

  // While the thumb is down, the part being cut is shown, and nothing is
  // written yet.
  const h = await select(page, "r1", "start");
  const hb = (await h.boundingBox())!;
  const x = hb.x + hb.width / 2;
  const y = hb.y + hb.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, y + 100, { steps: 6 });
  await expect(page.getByTestId("collage")).toHaveAttribute("data-dragging", "true");
  const cut = (await page.getByTestId("region-cut").boundingBox())!;
  expect(cut.height).toBeCloseTo(100, 0);
  const handleNow = (await h.boundingBox())!;
  expect(handleNow.y).toBeCloseTo(hb.y + 100, 0);
  const boxDuring = await regionBox(page, 0);
  expect(boxDuring.height).toBeCloseTo(before.height, 0);
  await page.mouse.up();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-dragging", "false");
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");

  const [stored] = await regionsOnServer(page);
  expect(stored.start_s).toBeCloseTo(0.5, 2);
  expect(stored.end_s).toBeCloseTo(sound.duration_s, 3);
  expect(stored.at_s).toBe(3);

  // Same top, shorter: the cut begins later in the source and sounds at the
  // same moment.
  const after = await regionBox(page, 0);
  expect(after.top).toBeCloseTo(before.top, 0);
  expect(after.height).toBeCloseTo(before.height - 100, 0);
});

test("a trim stops at the source's ends, at the other handle, and at a quarter of a second", async ({ page, request }) => {
  const set = await sounds(page);
  const sound = set[0];
  const rate = 0.05;
  await writeRegions(request, [regionRow("r1", sound.hash, 0, 0, 0.2, 0.9, rate)]);
  await page.goto("/collage");

  // Past the source's end: the end handle stops where the sound does, and
  // the box grows to exactly the sound.
  await drag(page, "r1", "end", 2000);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  let [stored] = await regionsOnServer(page);
  expect(stored.end_s).toBeCloseTo(sound.duration_s, 3);
  expect(stored.start_s).toBeCloseTo(0.2, 3);

  // Before the source's start: the start handle stops at zero.
  await drag(page, "r1", "start", -2000);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  [stored] = await regionsOnServer(page);
  expect(stored.start_s).toBe(0);

  // Across the other end: the end handle stops a quarter of a second after
  // the start, never on it, never past it. The region can not be trimmed to
  // nothing.
  await drag(page, "r1", "end", -3000);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  [stored] = await regionsOnServer(page);
  expect(stored.end_s).toBeCloseTo(MIN_REGION_S, 3);
  expect(stored.end_s - stored.start_s).toBeCloseTo(MIN_REGION_S, 3);
  const box = await regionBox(page, 0);
  expect(box.height).toBeCloseTo((MIN_REGION_S / rate) * PX_PER_S, 0);

  // And the start handle, dragged down past the end, stops the same distance
  // short of it.
  await drag(page, "r1", "end", 400);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  await drag(page, "r1", "start", 3000);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  [stored] = await regionsOnServer(page);
  expect(stored.end_s - stored.start_s).toBeCloseTo(MIN_REGION_S, 3);
  expect(stored.end_s).toBeGreaterThan(MIN_REGION_S + 0.5);
});

test("a region cannot be trimmed into the region below it on the same track", async ({ page, request }) => {
  const set = await sounds(page);
  const sound = set[0];
  const rate = 0.05;
  // A holds a second of source, twenty canvas seconds. B begins twenty-two
  // canvas seconds in. A may grow by two canvas seconds and no more.
  await writeRegions(request, [
    regionRow("r1", sound.hash, 0, 0, 0, 1.0, rate),
    regionRow("r2", sound.hash, 0, 22, 0, 0.5, rate),
  ]);
  await page.goto("/collage");
  await expect(page.getByTestId("region")).toHaveCount(2);

  await drag(page, "r1", "end", 100);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  const stored = await regionsOnServer(page);
  // Two canvas seconds at a twentieth is a tenth of a second of source.
  expect(stored[0].end_s).toBeCloseTo(1.1, 3);
  expect(stored[1]).toMatchObject({ at_s: 22, start_s: 0, end_s: 0.5 });

  const a = (await page.getByTestId("region").nth(0).boundingBox())!;
  const b = (await page.getByTestId("region").nth(1).boundingBox())!;
  expect(a.y + a.height).toBeLessThanOrEqual(b.y + 0.5);
});

test("a region written longer than its source is pulled back to the source by any trim", async ({ page, request }) => {
  const set = await sounds(page);
  const sound = set[0];
  // A cut that claims three hundred seconds of a one-second sound.
  await writeRegions(request, [regionRow("r1", sound.hash, 0, 0, 0, 300)]);
  await page.goto("/collage");
  const before = await regionBox(page, 0);
  expect(before.height).toBeCloseTo(300 * PX_PER_S, 0);

  await drag(page, "r1", "end", -10);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  const [stored] = await regionsOnServer(page);
  expect(stored.end_s).toBeCloseTo(sound.duration_s, 3);
  const after = await regionBox(page, 0);
  expect(after.height).toBeCloseTo(sound.duration_s * PX_PER_S, 0);
});

test("undo takes back a trim, and a trim stops the region it is trimming", async ({ page, request }) => {
  const set = await sounds(page);
  const sound = set[0];
  const rate = 0.05;
  await writeRegions(request, [regionRow("r1", sound.hash, 0, 0, 0, sound.duration_s, rate)]);
  await page.goto("/collage");
  const region = page.getByTestId("region").first();

  // Playing, then trimmed: the slice being played is the cut being changed,
  // so it stops.
  await region.click({ position: { x: 10, y: 60 } });
  await expect(region).toHaveAttribute("data-playing", "true");
  await drag(page, "r1", "end", -60);
  await expect(region).toHaveAttribute("data-playing", "false");
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  let [stored] = await regionsOnServer(page);
  expect(stored.end_s).toBeCloseTo(sound.duration_s - 0.3, 2);

  await expect(page.getByTestId("collage-undo")).toHaveAttribute("data-depth", "1");
  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  [stored] = await regionsOnServer(page);
  expect(stored.end_s).toBeCloseTo(sound.duration_s, 3);
  // The handle is still selected, so the trim can be tried again from it.
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "r1:end");
});

test("a selected handle moves by keyboard: a tenth of a second, a whole one with shift", async ({ page, request }) => {
  const set = await sounds(page);
  const sound = set[0];
  await writeRegions(request, [regionRow("r1", sound.hash, 0, 0, 0, sound.duration_s, 0.05)]);
  await page.goto("/collage");
  const h = await select(page, "r1", "end");
  await h.focus();
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  let [stored] = await regionsOnServer(page);
  // A tenth of a canvas second at a twentieth is five thousandths of source.
  expect(stored.end_s).toBeCloseTo(sound.duration_s - 0.005, 3);
  await page.keyboard.press("Shift+ArrowUp");
  await expect(page.getByTestId("collage-undo")).toHaveAttribute("data-depth", "2");
  [stored] = await regionsOnServer(page);
  expect(stored.end_s).toBeCloseTo(sound.duration_s - 0.055, 3);
});

test("the write refuses a region from outside the frozen set, and a cut that ends before it begins", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  const good: RegionRow = {
    id: "r1",
    hash: set[0].hash,
    track: 0,
    start_s: 0,
    end_s: 1,
    at_s: 0,
    rate: 1,
    gain: 1,
    fade_in_s: 0,
    fade_out_s: 0,
  };

  const foreign = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [{ ...good, hash: "f".repeat(64) }] },
  });
  expect(foreign.status()).toBe(422);
  expect(String(((await foreign.json()) as { detail: string }).detail)).toContain("frozen set");

  const backwards = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [{ ...good, start_s: 2, end_s: 1 }] },
  });
  expect(backwards.status()).toBe(422);

  const extra = await request.put(`/api/projects/${PROJECT}/collage`, {
    data: { regions: [{ ...good, note: "" }] },
  });
  expect(extra.status()).toBe(422);

  // A project still in `stored` has nothing to arrange yet.
  const stored = await request.put("/api/projects/2026-09-16-rust-and-rebar/collage", {
    data: { regions: [] },
  });
  expect(stored.status()).toBe(409);

  // And the good one goes in.
  const ok = await request.put(`/api/projects/${PROJECT}/collage`, { data: { regions: [good] } });
  expect(ok.status()).toBe(200);
  expect(await regionsOnServer(page)).toHaveLength(1);
});

test("the slice route is bounded and answers 48 kHz stereo WAV", async ({ page, request }) => {
  const set = await sounds(page);
  const hash = set[0].hash;

  const ok = await request.get(`/api/files/${hash}/slice?start=0&end=1`);
  expect(ok.status()).toBe(200);
  expect(ok.headers()["content-type"]).toContain("audio/wav");
  const bytes = Buffer.from(await ok.body());
  expect(bytes.subarray(0, 4).toString()).toBe("RIFF");
  expect(bytes.readUInt16LE(22)).toBe(2);
  expect(bytes.readUInt32LE(24)).toBe(48000);
  // One second: 48,000 frames of two 16-bit samples, plus the header.
  expect(bytes.length).toBe(44 + 48000 * 4);

  // Bounded: a whole long source is refused, however long the region. The
  // project's own sounds may be short, so the case uses a long one from the
  // collection.
  const long = await api(page, "/api/files?min_dur=120&limit=1");
  const longHash = (long.items as Array<{ hash: string }>)[0].hash;
  const tooLong = await request.get(`/api/files/${longHash}/slice?start=0&end=100`);
  expect(tooLong.status()).toBe(413);

  const backwards = await request.get(`/api/files/${hash}/slice?start=2&end=1`);
  expect(backwards.status()).toBe(422);
});

/* Snip ----------------------------------------------------------------------- */

/**
 * The snip tests write cuts three seconds long at a tenth speed: thirty
 * canvas seconds, three hundred pixels, and one pixel is a hundredth of a
 * second of source. The cut may run past the end of the fixture's one-second
 * sound; a snip never consults the source's length, and only the tests that
 * play a region keep the cut inside the sound.
 */

/** Turn snip on from the bar, and wait for the view to say so. */
async function enterSnip(page: Page): Promise<void> {
  await page.getByTestId("collage-snip").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "snip");
}

/**
 * Drag down a region's grab with the mouse, from `fromY` to `toY` pixels
 * below the top of its box, and let go unless told not to. Snip mode must
 * already be on.
 */
async function snipDrag(page: Page, regionId: string, fromY: number, toY: number, lift = true) {
  const target = region(page, regionId);
  const box = (await target.boundingBox())!;
  const x = box.x + TRACK_W / 2;
  await page.mouse.move(x, box.y + fromY);
  await page.mouse.down();
  await page.mouse.move(x, box.y + toY, { steps: 8 });
  if (lift) await page.mouse.up();
  return { x, box };
}

test("with nothing stamped there is nothing to snip, and the button says so by refusing", async ({ page }) => {
  await page.goto("/collage");
  await expect(page.getByTestId("collage-snip")).toBeDisabled();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
});

test("snip is a mode entered by a button: while it is on there are no handles and the bar says so; the button again puts trim back", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 3, 0.1)]);
  await page.goto("/collage");
  const snipButton = page.getByTestId("collage-snip");
  await expect(snipButton).toBeEnabled();
  await expect(snipButton).toHaveAttribute("aria-pressed", "false");

  // Trim is the default: the region taken up has its handles.
  await takeUp(page, "r1");
  await expect(page.getByTestId("handle")).toHaveCount(2);

  // Snip on: the handles go, the choose button gives way to a plain
  // statement of which mode is on, and the region stays taken up.
  await enterSnip(page);
  await expect(snipButton).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("handle")).toHaveCount(0);
  await expect(page.getByTestId("collage-choose")).toHaveCount(0);
  await expect(page.getByTestId("collage-mode")).toContainText("snip is on");
  await expect(region(page, "r1")).toHaveAttribute("data-selected", "true");

  // Still no seconds, no grid, no decibels, in the bar or in what it says
  // on hover.
  const text = (await page.getByTestId("collage").innerText()).toLowerCase();
  expect(text).not.toMatch(/\d+:\d\d/);
  expect(text).not.toMatch(/\b\d+(\.\d+)?\s?s\b/);
  expect(text).not.toMatch(/\bdb\b/);
  const spoken = await page.getByTestId("collage").evaluate((node) =>
    Array.from(node.querySelectorAll("[aria-label], [title]"))
      .map((el) => `${el.getAttribute("aria-label") ?? ""} ${el.getAttribute("title") ?? ""}`)
      .join("\n")
      .toLowerCase(),
  );
  expect(spoken).not.toMatch(/\b\d+(\.\d+)?\s?(s|sec|seconds?|ms|db)\b/);

  // A tap on the blank in snip mode stamps nothing and opens nothing: it
  // only lets go.
  await stampAt(page, 40, 500);
  await expect(page.getByTestId("region")).toHaveCount(1);
  await expect(page.getByTestId("collage-picker")).toHaveCount(0);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "snip");

  // The button again: trim is back, and so are the handles once the region
  // is taken up again.
  await snipButton.click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  await expect(page.getByTestId("collage-choose")).toBeVisible();
  await takeUp(page, "r1");
  await expect(page.getByTestId("handle")).toHaveCount(2);

  // The statement in the bar is the other way out.
  await enterSnip(page);
  await page.getByTestId("collage-mode").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");

  // Nothing in any of that was a change.
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);
});

test("a snip through the middle leaves two regions that keep their place in time; the first is taken up and both trim at the seam", async ({
  page,
  request,
}) => {
  // The whole of the sound, so the halves can be trimmed afterwards without
  // the trim's own rule, that a cut ends where the sound does, getting in
  // the way. At a twentieth speed a pixel is five thousandths of a second.
  const set = await sounds(page);
  const { hash, duration_s: d } = set[0];
  const rate = 0.05;
  const px = (s: number) => Math.round((s / rate) * PX_PER_S);
  await writeRegions(request, [regionRow("r1", hash, 0, 3, 0, d, rate)]);
  await page.goto("/collage");
  const before = await regionBox(page, 0);
  expect(before.height).toBeCloseTo(px(d), 0);
  await enterSnip(page);

  // The span: from two fifths of the way down to three fifths, in whole
  // pixels, which is what a thumb can say.
  const fromPx = px(0.4 * d);
  const toPx = px(0.6 * d);
  const fromS = (fromPx / PX_PER_S) * rate;
  const toS = (toPx / PX_PER_S) * rate;

  // While the thumb is down, the span being cut out is striped, and
  // nothing is written.
  const writes = await writesDuring(page, async () => {
    await snipDrag(page, "r1", fromPx, toPx, false);
    await expect(page.getByTestId("collage")).toHaveAttribute("data-snipping", "true");
    const bandBox = (await page.getByTestId("region-snip").boundingBox())!;
    expect(bandBox.height).toBeCloseTo(toPx - fromPx, 0);
    // Inside the box's one-pixel border.
    const spaceY = (await page.getByTestId("collage-space").boundingBox())!.y;
    expect(Math.abs(bandBox.y - (spaceY + before.top + fromPx))).toBeLessThanOrEqual(2);
    await expect(page.getByTestId("region-snip")).toHaveAttribute("data-whole", "false");
    await expect(page.getByTestId("region")).toHaveCount(1);
    await page.mouse.up();
  });
  expect(writes).toBe(1);

  // Two regions. Both keep the source, the track, the rate and the rest.
  // The first keeps its id and its place; the second's material sounds
  // exactly when it did before: a real gap, not a splice.
  await expect(page.getByTestId("region")).toHaveCount(2);
  const stored = await regionsOnServer(page);
  expect(stored).toHaveLength(2);
  expect(stored[0]).toMatchObject({ id: "r1", hash, track: 0, at_s: 3, start_s: 0, rate, gain: 1, fade_in_s: 0, fade_out_s: 0 });
  expect(stored[0].end_s).toBeCloseTo(fromS, 3);
  expect(stored[1]).toMatchObject({ id: "r2", hash, track: 0, rate, gain: 1, fade_in_s: 0, fade_out_s: 0 });
  expect(stored[1].start_s).toBeCloseTo(toS, 3);
  expect(stored[1].end_s).toBeCloseTo(d, 3);
  // The second half's material was sounding `toS` of source after the
  // region began, which at this rate is `toPx / 10` canvas seconds later.
  const secondAt = 3 + toS / rate;
  expect(stored[1].at_s).toBeCloseTo(secondAt, 3);

  // Drawn where they sound: the first where it was, the second where its
  // material was, the striped span now blank between them.
  const a = await regionBox(page, 0);
  const b = await regionBox(page, 1);
  expect(a.top).toBeCloseTo(before.top, 0);
  expect(Math.abs(a.height - fromPx)).toBeLessThanOrEqual(1);
  expect(Math.abs(b.top - (before.top + toPx))).toBeLessThanOrEqual(1);
  expect(Math.abs(b.height - (px(d) - toPx))).toBeLessThanOrEqual(1);

  // A finished snip is the end of snip mode. The first half is taken up,
  // so its handles are live at once.
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "r1");
  await expect(handle(page, "r1", "end")).toHaveCount(1);
  await expect(handle(page, "r2", "start")).toHaveCount(0);

  // The seam: the two grabs never overlap.
  const ga = (await region(page, "r1").getByTestId("region-grab").boundingBox())!;
  const gb = (await region(page, "r2").getByTestId("region-grab").boundingBox())!;
  expect(ga.y + ga.height).toBeLessThanOrEqual(gb.y + 0.5);

  // Trim the first half's inner edge down by ten pixels, a twentieth of a
  // second: it grows into the gap.
  await drag(page, "r1", "end", 10);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  let now = await regionsOnServer(page);
  expect(now[0].end_s).toBeCloseTo(fromS + 0.05, 3);
  expect(now[0].at_s).toBe(3);
  // And all the way: it stops where the second half begins to sound.
  await drag(page, "r1", "end", 400);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  now = await regionsOnServer(page);
  expect(now[0].end_s).toBeCloseTo(toS, 3);

  // Then the second half's inner edge, straight after: taken up by a tap,
  // its start handle drags. It keeps its place, as a trim does.
  await drag(page, "r2", "start", 10);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  now = await regionsOnServer(page);
  expect(now[1].start_s).toBeCloseTo(toS + 0.05, 3);
  expect(now[1].at_s).toBeCloseTo(secondAt, 3);
  await expect(page.getByTestId("collage-undo")).toHaveAttribute("data-depth", "4");
});

test("a snip that would leave a half shorter than a quarter second runs on to that edge; the material that is left stays where it sounded", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 3, 0, 3, 0.1)]);
  await page.goto("/collage");
  const before = await regionBox(page, 0);
  await enterSnip(page);

  // Near the end: the last tenth of a second would be left over, so the
  // removal runs on to the end. One region, its end trimmed. The band said
  // so before the lift: it reached the bottom of the box.
  await snipDrag(page, "r1", 270, 290, false);
  let bandBox = (await page.getByTestId("region-snip").boundingBox())!;
  expect(bandBox.height).toBeCloseTo(30, 0);
  await expect(page.getByTestId("region-snip")).toHaveAttribute("data-whole", "false");
  await page.mouse.up();
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  await expect(page.getByTestId("region")).toHaveCount(1);
  let [stored] = await regionsOnServer(page);
  expect(stored.id).toBe("r1");
  expect(stored.end_s).toBeCloseTo(2.7, 2);
  expect(stored.start_s).toBe(0);
  expect(stored.at_s).toBe(3);
  let box = await regionBox(page, 0);
  expect(box.top).toBeCloseTo(before.top, 0);
  expect(box.height).toBeCloseTo(270, 0);

  // Near the start: the first tenth would be left over, so the removal
  // runs back to the start. One region, and unlike a trim of the start its
  // material stays where it sounded: the box's top moves down by exactly
  // the span, which is what the stripes said would go.
  await enterSnip(page);
  await snipDrag(page, "r1", 10, 40, false);
  bandBox = (await page.getByTestId("region-snip").boundingBox())!;
  expect(bandBox.height).toBeCloseTo(40, 0);
  await page.mouse.up();
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  await expect(page.getByTestId("region")).toHaveCount(1);
  [stored] = await regionsOnServer(page);
  expect(stored.id).toBe("r1");
  expect(stored.start_s).toBeCloseTo(0.4, 2);
  expect(stored.end_s).toBeCloseTo(2.7, 2);
  expect(stored.at_s).toBeCloseTo(7, 2);
  box = await regionBox(page, 0);
  expect(box.top).toBeCloseTo(before.top + 40, 0);
  expect(box.height).toBeCloseTo(230, 0);

  // Two undos: the one original region, untouched.
  await page.getByTestId("collage-undo").click();
  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  [stored] = await regionsOnServer(page);
  expect(stored).toMatchObject({ id: "r1", start_s: 0, end_s: 3, at_s: 3 });
});

test("a snip across the whole region removes it, the stripes having said so; one undo brings it back", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  const hash = set[0].hash;
  // A long cut, and beside it a cut of one and a fifth seconds at full
  // speed: twelve pixels, in which any thumb's travel leaves less than a
  // quarter of a second on either side.
  await writeRegions(request, [regionRow("r1", hash, 0, 0, 0, 3, 0.1), regionRow("r2", hash, 1, 0, 0, 1.2)]);
  await page.goto("/collage");
  await expect(page.getByTestId("region")).toHaveCount(2);

  // Top to bottom, within a thumb of each edge: nothing would be left, and
  // the band covers the whole box and says so. A lift does not take it yet:
  // the thumb has to hold still on it first, and the bar says so.
  await enterSnip(page);
  await snipDrag(page, "r1", 2, 298, false);
  const bandBox = (await page.getByTestId("region-snip").boundingBox())!;
  const box = (await region(page, "r1").boundingBox())!;
  expect(Math.abs(bandBox.y - box.y)).toBeLessThanOrEqual(2);
  expect(bandBox.height).toBeCloseTo(box.height, 0);
  await expect(page.getByTestId("region-snip")).toHaveAttribute("data-whole", "true");
  await expect(page.getByTestId("collage-mode")).toHaveAttribute("data-band", "whole");
  await expect(page.getByTestId("region-snip")).toHaveAttribute("data-armed", "true");
  await expect(page.getByTestId("collage-mode")).toHaveAttribute("data-band", "armed");
  await expect(page.getByTestId("collage-mode")).toContainText("let go to take the whole region out");
  const writes = await writesDuring(page, () => page.mouse.up());
  expect(writes).toBe(1);
  await expect(page.getByTestId("region")).toHaveCount(1);
  await expect(region(page, "r1")).toHaveCount(0);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  let stored = await regionsOnServer(page);
  expect(stored.map((r) => r.id)).toEqual(["r2"]);

  // The short one: eight pixels of travel out of twelve leaves two on each
  // side, under the minimum both, so the whole of it goes, once held.
  await enterSnip(page);
  await snipDrag(page, "r2", 2, 10, false);
  await expect(page.getByTestId("region-snip")).toHaveAttribute("data-whole", "true");
  await expect(page.getByTestId("region-snip")).toHaveAttribute("data-armed", "true");
  await page.mouse.up();
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  await expect(page.getByTestId("region")).toHaveCount(0);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-tracks", "0");
  // With nothing left to snip, snip is off and the bar offers a sound again.
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  await expect(page.getByTestId("collage-choose")).toBeVisible();

  // One undo each. The originals come back whole.
  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("region")).toHaveCount(1);
  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("region")).toHaveCount(2);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  stored = await regionsOnServer(page);
  expect(stored[0]).toMatchObject({ id: "r1", start_s: 0, end_s: 3, at_s: 0 });
  expect(stored[1]).toMatchObject({ id: "r2", start_s: 0, end_s: 1.2, at_s: 0, track: 1 });
});

test("a whole-region snip is a hold: lifted at once it takes nothing and snip stays on; moved, the hold starts again; held still, a lift takes it", async ({
  page,
  request,
}) => {
  // The only delete on the surface. On the short cuts snipping makes, a
  // thumb's drag across the grab takes the whole region more often than
  // not, and the band saying so is under the thumb. So the band alone must
  // not remove anything: the thumb has to stop on it and stay.
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 3, 0.1), regionRow("r2", set[0].hash, 1, 0, 0, 3, 0.1)]);
  await page.goto("/collage");
  await enterSnip(page);
  let writes = 0;
  page.on("request", (r) => {
    if (r.method() === "PUT" && r.url().includes("/collage")) writes += 1;
  });

  // Swept through and lifted: the band was whole for a moment, nothing
  // goes, snip is still on, and the view says what a whole snip takes.
  await snipDrag(page, "r1", 2, 298, false);
  await expect(page.getByTestId("region-snip")).toHaveAttribute("data-whole", "true");
  await expect(page.getByTestId("region-snip")).toHaveAttribute("data-armed", "false");
  await expect(page.getByTestId("collage-mode")).toContainText("hold still to take the whole region out");
  await page.mouse.up();
  await page.waitForTimeout(300);
  expect(writes).toBe(0);
  await expect(page.getByTestId("region")).toHaveCount(2);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "snip");
  await expect(page.getByTestId("collage-hint")).toContainText("hold still");
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);

  // Held, but the thumb moves a tap's worth before the hold is up: the
  // hold starts again from there, and a lift straight after takes nothing.
  const { x } = await snipDrag(page, "r1", 2, 298, false);
  const box = (await region(page, "r1").boundingBox())!;
  await page.waitForTimeout(400);
  await expect(page.getByTestId("region-snip")).toHaveAttribute("data-armed", "false");
  await page.mouse.move(x, box.y + 320, { steps: 2 });
  await page.waitForTimeout(400);
  await expect(page.getByTestId("region-snip")).toHaveAttribute("data-whole", "true");
  await expect(page.getByTestId("region-snip")).toHaveAttribute("data-armed", "false");
  await page.mouse.up();
  await page.waitForTimeout(300);
  expect(writes).toBe(0);
  await expect(page.getByTestId("region")).toHaveCount(2);

  // Still for the whole hold: the band arms, the bar says a lift takes it,
  // and the lift does. One write, the hint gone, trim back, undo standing.
  await snipDrag(page, "r1", 2, 298, false);
  await expect(page.getByTestId("region-snip")).toHaveAttribute("data-armed", "true");
  await expect(page.getByTestId("collage-mode")).toHaveAttribute("data-band", "armed");
  await page.mouse.up();
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(writes).toBe(1);
  await expect(page.getByTestId("region")).toHaveCount(1);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  await expect(page.getByTestId("collage-hint")).toHaveCount(0);
  await expect(page.getByTestId("collage-undo")).toHaveAttribute("data-depth", "1");

  // A band that is whole and then is not, disarms at once: dragged back
  // inside the region after the hold, the lift is an ordinary snip.
  await enterSnip(page);
  await snipDrag(page, "r2", 2, 298, false);
  await expect(page.getByTestId("region-snip")).toHaveAttribute("data-armed", "true");
  const b2 = (await region(page, "r2").boundingBox())!;
  await page.mouse.move(b2.x + TRACK_W / 2, b2.y + 150, { steps: 4 });
  await expect(page.getByTestId("region-snip")).toHaveAttribute("data-whole", "false");
  await expect(page.getByTestId("region-snip")).toHaveAttribute("data-armed", "false");
  await page.mouse.up();
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  await expect(page.getByTestId("region")).toHaveCount(1);
  const [stored] = await regionsOnServer(page);
  expect(stored.id).toBe("r2");
  expect(stored.start_s).toBeCloseTo(1.5, 2);
});

test("a drag that cuts nothing leaves snip on; undoing away the last region turns it off", async ({ page, request }) => {
  // A one-second cut: ten pixels, with a grab reaching a thumb's worth
  // above and below it.
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 1)]);
  await page.goto("/collage");
  await enterSnip(page);
  let writes = 0;
  page.on("request", (r) => {
    if (r.method() === "PUT" && r.url().includes("/collage")) writes += 1;
  });
  // Down from the grab's reach below the box, away from it: the span is
  // empty, nothing is striped, nothing is written, and snip is still on,
  // because no snip was made.
  await snipDrag(page, "r1", 14, 60);
  await page.waitForTimeout(300);
  expect(writes).toBe(0);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "snip");
  await expect(page.getByTestId("region-snip")).toHaveCount(0);
  await expect(page.getByTestId("collage-hint")).toHaveCount(0);

  // Stamp one beside it, undo it away while snip is on: with a region
  // still there, snip stays on.
  await page.getByTestId("collage-mode").click();
  await choose(page, 0);
  let landed = 0;
  page.on("response", (r) => {
    if (r.request().method() === "PUT" && r.url().includes("/collage")) landed += 1;
  });
  await stampAt(page, TRACK_W + 40, 500);
  await expect(page.getByTestId("region")).toHaveCount(2);
  await enterSnip(page);
  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("region")).toHaveCount(1);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "snip");

  // From nothing: stamp one, turn snip on, undo it away. With nothing to
  // snip, snip is off, the button refuses, and the way to a sound is back
  // in the bar rather than a mode label about regions that are not there.
  // The stamp's write and the undo's are queued one after the other, and
  // the bar says saved after the first; both have to land before anything
  // is written over them.
  await expect.poll(() => landed).toBe(2);
  await writeRegions(request, []);
  await page.reload();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-regions", "0");
  await choose(page, 0);
  await stampAt(page, 40, 100);
  await expect(page.getByTestId("region")).toHaveCount(1);
  await enterSnip(page);
  await expect(page.getByTestId("collage-choose")).toHaveCount(0);
  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("region")).toHaveCount(0);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  await expect(page.getByTestId("collage-snip")).toBeDisabled();
  await expect(page.getByTestId("collage-choose")).toBeVisible();
});

test("trim and snip disagree at the start: a trim keeps the region's place, a snip keeps the material's moment", async ({
  page,
  request,
}) => {
  // Two identical regions on two tracks. The same forty pixels of source
  // are taken off the start of each: one by dragging the start handle, one
  // by snipping from the top. Both end up holding the same cut. They differ
  // in when it sounds: the trimmed one still starts where the region did,
  // so the material heard at its top has changed; the snipped one starts
  // forty pixels later, so the material still sounds when it did, and the
  // box's top has moved down to it. This is a record of the difference, not
  // a ruling on it.
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 5, 0, 3, 0.1), regionRow("r2", set[0].hash, 1, 5, 0, 3, 0.1)]);
  await page.goto("/collage");
  const a0 = await regionBox(page, 0);
  const b0 = await regionBox(page, 1);
  expect(a0.top).toBeCloseTo(b0.top, 0);

  await drag(page, "r1", "start", 40);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  await enterSnip(page);
  await snipDrag(page, "r2", 2, 40);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  await expect(page.getByTestId("collage-undo")).toHaveAttribute("data-depth", "2");

  const [trimmed, snipped] = await regionsOnServer(page);
  expect(trimmed.start_s).toBeCloseTo(0.4, 2);
  expect(snipped.start_s).toBeCloseTo(0.4, 2);
  expect(trimmed.end_s).toBe(3);
  expect(snipped.end_s).toBe(3);
  expect(trimmed.at_s).toBe(5);
  expect(snipped.at_s).toBeCloseTo(9, 2);
  const a1 = await regionBox(page, 0);
  const b1 = await regionBox(page, 1);
  expect(a1.top).toBeCloseTo(a0.top, 0);
  expect(b1.top).toBeCloseTo(b0.top + 40, 0);
  expect(a1.height).toBeCloseTo(b1.height, 0);
});

test("in snip mode a tap plays and cuts nothing; a thumb that barely travels is a tap; the source is never touched", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  const sound = set[0];
  await writeRegions(request, [regionRow("r1", sound.hash, 0, 0, 0, sound.duration_s, 0.1)]);
  await page.goto("/collage");
  await enterSnip(page);
  const target = region(page, "r1");
  const box = (await target.boundingBox())!;
  const x = box.x + TRACK_W / 2;

  let writes = 0;
  page.on("request", (r) => {
    if (r.method() === "PUT" && r.url().includes("/collage")) writes += 1;
  });
  // A tap.
  await page.mouse.move(x, box.y + 30);
  await page.mouse.down();
  await page.mouse.up();
  await expect(target).toHaveAttribute("data-playing", "true");
  await expect(target).toHaveAttribute("data-selected", "true");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "snip");
  // A single pixel.
  await page.mouse.move(x, box.y + 30);
  await page.mouse.down();
  await page.mouse.move(x, box.y + 31);
  await page.mouse.up();
  await expect(target).toHaveAttribute("data-playing", "false");
  // Seven pixels: still a tap.
  await page.mouse.move(x, box.y + 30);
  await page.mouse.down();
  await page.mouse.move(x, box.y + 37, { steps: 3 });
  await page.mouse.up();
  await expect(target).toHaveAttribute("data-playing", "true");
  await page.waitForTimeout(200);
  expect(writes).toBe(0);
  await expect(page.getByTestId("region")).toHaveCount(1);
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "snip");

  // Now a real snip of the region that is playing: it stops, because the
  // slice being played is the cut being changed. The source is a file the
  // interface can only read; a snip is one PUT of the arrangement.
  const seen: string[] = [];
  page.on("request", (r) => {
    if (r.method() !== "GET" && r.method() !== "HEAD") seen.push(`${r.method()} ${new URL(r.url()).pathname}`);
  });
  await snipDrag(page, "r1", 30, 60);
  await expect(target).toHaveAttribute("data-playing", "false");
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(writes).toBe(1);
  expect(seen).toEqual([`PUT /api/projects/${PROJECT}/collage`]);
  await expect(page.getByTestId("region")).toHaveCount(2);
});

test("the second half can be snipped again at once, and every half is told apart by where it is and what it holds", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 3, 0.1)]);
  await page.goto("/collage");
  await enterSnip(page);
  await snipDrag(page, "r1", 100, 150);
  await expect(page.getByTestId("region")).toHaveCount(2);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");

  // Straight into the second half. Fifty to eighty pixels into r2's box is
  // two seconds to two point three of source.
  await enterSnip(page);
  await snipDrag(page, "r2", 50, 80);
  await expect(page.getByTestId("region")).toHaveCount(3);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  const stored = await regionsOnServer(page);
  expect(stored.map((r) => r.id)).toEqual(["r1", "r2", "r3"]);
  expect(stored[0]).toMatchObject({ start_s: 0, at_s: 0 });
  expect(stored[0].end_s).toBeCloseTo(1.0, 2);
  expect(stored[1].start_s).toBeCloseTo(1.5, 2);
  expect(stored[1].end_s).toBeCloseTo(2.0, 2);
  expect(stored[1].at_s).toBeCloseTo(15, 2);
  expect(stored[2].start_s).toBeCloseTo(2.3, 2);
  expect(stored[2].end_s).toBeCloseTo(3, 3);
  expect(stored[2].at_s).toBeCloseTo(23, 2);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "r2");
  await expect(page.getByTestId("collage-undo")).toHaveAttribute("data-depth", "2");

  // Three boxes, in order down the track, none overlapping, and each one
  // draws its own stretch of the sound.
  const boxes = [await regionBox(page, 0), await regionBox(page, 1), await regionBox(page, 2)];
  expect(boxes[0].top + boxes[0].height).toBeLessThanOrEqual(boxes[1].top + 0.5);
  expect(boxes[1].top + boxes[1].height).toBeLessThanOrEqual(boxes[2].top + 0.5);
  expect(boxes.map((b) => Math.round(b.height))).toEqual([100, 50, 70]);
  await expect(page.getByTestId("region-wave")).toHaveCount(3);

  // Undo, twice: the one original.
  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("region")).toHaveCount(2);
  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("region")).toHaveCount(1);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  const [one] = await regionsOnServer(page);
  expect(one).toMatchObject({ id: "r1", start_s: 0, end_s: 3, at_s: 0 });
});

test("a snip that runs off the region, or onto the next one, snips only the region it started on", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  const hash = set[0].hash;
  // r1 is three hundred pixels; r2 starts fifty pixels below its end.
  await writeRegions(request, [regionRow("r1", hash, 0, 0, 0, 3, 0.1), regionRow("r2", hash, 0, 35, 0, 1, 0.1)]);
  await page.goto("/collage");
  await enterSnip(page);

  // Down from inside r1, past its end, and onto r2's box: r1 loses its
  // last second, r2 is untouched.
  await snipDrag(page, "r1", 200, 380);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  let stored = await regionsOnServer(page);
  expect(stored).toHaveLength(2);
  expect(stored[0].end_s).toBeCloseTo(2.0, 2);
  expect(stored[1]).toMatchObject({ id: "r2", at_s: 35, start_s: 0, end_s: 1 });

  // Up from inside r1 and off its top, into the blank above time: r1 loses
  // its first second, and what is left stays where it sounded.
  await enterSnip(page);
  await snipDrag(page, "r1", 100, -40);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  stored = await regionsOnServer(page);
  expect(stored).toHaveLength(2);
  expect(stored[0].start_s).toBeCloseTo(1.0, 2);
  expect(stored[0].end_s).toBeCloseTo(2.0, 2);
  expect(stored[0].at_s).toBeCloseTo(10, 2);
  expect(stored[1].at_s).toBe(35);
});

test("Escape mid-snip lets go without writing, and the thumb lifting afterwards writes nothing either", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 3, 0.1)]);
  await page.goto("/collage");
  await enterSnip(page);
  let writes = 0;
  page.on("request", (r) => {
    if (r.method() === "PUT" && r.url().includes("/collage")) writes += 1;
  });
  await snipDrag(page, "r1", 100, 150, false);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-snipping", "true");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-snipping", "false");
  await expect(page.getByTestId("region-snip")).toHaveCount(0);
  await page.mouse.up();
  await page.waitForTimeout(300);
  expect(writes).toBe(0);
  await expect(page.getByTestId("region")).toHaveCount(1);
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);
  const [stored] = await regionsOnServer(page);
  expect(stored).toMatchObject({ start_s: 0, end_s: 3 });
});

/* Stretch -------------------------------------------------------------------- */

/**
 * The stretch tests write cuts four seconds long at full speed: forty pixels,
 * one pixel a tenth of a collage second. The cut may run past the end of the
 * fixture's one-second sound; a stretch never consults the source's length,
 * and only the tests that play a region keep the cut inside the sound.
 */

/** A rate written as a figure: "0.5x", "2 ×", "x4". */
const RATE_FIGURE = /(\d+(\.\d+)?\s?(x(?![a-z])|×))|((^|[^a-z])x\s?\d)|(×\s?\d)/;

/** Nothing on screen, spoken or hovered, may say a rate, a time or a level. */
async function noFigures(page: Page): Promise<void> {
  const text = (await page.getByTestId("collage").innerText()).toLowerCase();
  expect(text).not.toMatch(/\d+:\d\d/);
  expect(text).not.toMatch(/\b\d+(\.\d+)?\s?(s|sec|seconds?|ms|db|bpm|%)\b/);
  expect(text).not.toMatch(RATE_FIGURE);
  const spoken = await page.getByTestId("collage").evaluate((node) =>
    Array.from(node.querySelectorAll("[aria-label], [title]"))
      .map((el) => `${el.getAttribute("aria-label") ?? ""} ${el.getAttribute("title") ?? ""}`)
      .join("\n")
      .toLowerCase(),
  );
  expect(spoken).not.toMatch(/\d+:\d\d/);
  expect(spoken).not.toMatch(/\b\d+(\.\d+)?\s?(s|sec|seconds?|ms|db|bpm|%)\b/);
  expect(spoken).not.toMatch(RATE_FIGURE);
}

/** Select a handle, then turn stretch on from the bar if it is not on already, and wait for the view to say so. */
async function enterStretch(page: Page, regionId: string, end: "start" | "end") {
  const h = await select(page, regionId, end);
  if ((await page.getByTestId("collage").getAttribute("data-mode")) !== "stretch") {
    await page.getByTestId("collage-stretch").click();
  }
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "stretch");
  await expect(h).toHaveAttribute("data-kind", "stretch");
  return h;
}

/** Enter stretch on a handle and drag it by `dy` pixels with the mouse, letting go unless told not to. */
async function stretchDrag(page: Page, regionId: string, end: "start" | "end", dy: number, lift = true) {
  const h = await enterStretch(page, regionId, end);
  const box = (await h.boundingBox())!;
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, y + dy, { steps: 8 });
  if (lift) await page.mouse.up();
  return { x, y };
}

/** How many times the arrangement was written while `run` ran, for a run that may write nothing. */
async function countWrites(page: Page, run: () => Promise<void>): Promise<number> {
  let writes = 0;
  const listener = (request: { method(): string; url(): string }) => {
    if (request.method() === "PUT" && request.url().includes("/collage")) writes += 1;
  };
  page.on("request", listener);
  await run();
  await page.waitForTimeout(300);
  page.off("request", listener);
  return writes;
}

test("stretch is a mode entered by a button with a handle already selected: one handle shows, the bar says so, and every way out returns to trim", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 4)]);
  await page.goto("/collage");
  const button = page.getByTestId("collage-stretch");

  // Nothing selected: refused. A region taken up with no handle chosen:
  // still refused. Stretch is a drag on a handle, and needs one.
  await expect(button).toHaveCount(0);
  await takeUp(page, "r1");
  await expect(button).toBeDisabled();
  await select(page, "r1", "end");
  await expect(button).toBeEnabled();
  await expect(button).toHaveAttribute("aria-pressed", "false");

  // On: the selected handle stays, the other goes, snip is off, and the
  // choose button gives way to a plain statement of the mode.
  await button.click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "stretch");
  await expect(button).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("collage-snip")).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByTestId("handle")).toHaveCount(1);
  await expect(handle(page, "r1", "end")).toHaveAttribute("data-selected", "true");
  await expect(handle(page, "r1", "end")).toHaveAttribute("data-kind", "stretch");
  await expect(handle(page, "r1", "start")).toHaveCount(0);
  await expect(page.getByTestId("collage-choose")).toHaveCount(0);
  await expect(page.getByTestId("collage-mode")).toContainText("stretch is on");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "r1:end");
  await noFigures(page);

  // The button again: trim is back, both handles, the handle still selected.
  await button.click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  await expect(page.getByTestId("handle")).toHaveCount(2);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "r1:end");
  await expect(handle(page, "r1", "end")).toHaveAttribute("data-kind", "trim");

  // The statement in the bar is the other way out.
  await button.click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "stretch");
  await page.getByTestId("collage-mode").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");

  // Escape lets go of the handle, and with it of stretch.
  await button.click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "stretch");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "");
  await expect(button).toHaveCount(0);

  // A tap on the blank lets go too, and stamps nothing, even with a sound
  // chosen: the bar said stretch was on, not that a tap would stamp.
  await choose(page, 0);
  await enterStretch(page, "r1", "start");
  await stampAt(page, 40, 500);
  await expect(page.getByTestId("region")).toHaveCount(1);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "");

  // Taking another region up is letting go of this handle.
  await stampAt(page, TRACK_W + 40, 200);
  await expect(page.getByTestId("region")).toHaveCount(2);
  await enterStretch(page, "r1", "end");
  await takeUp(page, "r2");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "r2");
  await expect(button).toBeDisabled();

  // Snip pressed while stretch is on: snip is on and stretch is not. Never two.
  await enterStretch(page, "r1", "end");
  await enterSnip(page);
  await expect(button).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByTestId("handle")).toHaveCount(0);

  // The one change in all of that was the stamp.
  await expect(page.getByTestId("collage-undo")).toHaveAttribute("data-depth", "1");
});

test("dragging the end handle in stretch mode moves the rate and nothing else: the box grows from the bottom, one write, undo restores the rate", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 3, 0, 4)]);
  await page.goto("/collage");
  const before = await regionBox(page, 0);
  expect(before.height).toBeCloseTo(40, 0);

  const writes = await writesDuring(page, async () => {
    const { y } = await stretchDrag(page, "r1", "end", 40, false);
    await expect(page.getByTestId("collage")).toHaveAttribute("data-dragging", "true");
    // The part being taken in is outlined below the box, the handle is with
    // the thumb, and the box keeps its length until the lift.
    const more = (await page.getByTestId("region-more").boundingBox())!;
    expect(more.height).toBeCloseTo(40, 0);
    const hb = (await handle(page, "r1", "end").boundingBox())!;
    expect(hb.y + hb.height / 2).toBeCloseTo(y + 40, 0);
    expect((await regionBox(page, 0)).height).toBeCloseTo(40, 0);
    await expect(page.getByTestId("collage-mode")).toContainText("let go to keep it");
    await noFigures(page);
    await page.mouse.up();
  });
  expect(writes).toBe(1);

  // Twice as long is half the speed. The cut and the place are untouched.
  const [stored] = await regionsOnServer(page);
  expect(stored.rate).toBeCloseTo(0.5, 6);
  expect(stored).toMatchObject({ start_s: 0, end_s: 4, at_s: 3, gain: 1 });
  const after = await regionBox(page, 0);
  expect(after.top).toBeCloseTo(before.top, 0);
  expect(after.height).toBeCloseTo(80, 0);
  // The sound inside stretched with the box.
  const wave = region(page, "r1").getByTestId("region-wave");
  expect((await wave.boundingBox())!.height).toBeCloseTo(80, 0);

  // A finished stretch is the end of stretch mode. The handle stays
  // selected, so the button is ready for another.
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "r1:end");
  await expect(page.getByTestId("handle")).toHaveCount(2);
  await expect(page.getByTestId("collage-stretch")).toBeEnabled();
  await expect(page.getByTestId("collage-stretch")).toHaveAttribute("aria-pressed", "false");

  // Undo: the rate, and only the rate, comes back.
  await expect(page.getByTestId("collage-undo")).toHaveAttribute("data-depth", "1");
  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  const [undone] = await regionsOnServer(page);
  expect(undone).toMatchObject({ rate: 1, start_s: 0, end_s: 4, at_s: 3 });
  expect((await regionBox(page, 0)).height).toBeCloseTo(40, 0);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "r1:end");
});

test("dragging the start handle in stretch mode keeps the bottom anchored: the region begins earlier or later, and its cut does not move", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 10, 0, 4)]);
  await page.goto("/collage");
  const before = await regionBox(page, 0);
  expect(before.top).toBeCloseTo(TOP_PAD + 100, 0);
  const bottom = before.top + before.height;

  // Up forty: twice as long, half the speed, and it begins forty pixels
  // earlier so that it still ends where it did. In trim mode the same drag
  // would have moved the cut and held the top.
  let writes = await writesDuring(page, () => stretchDrag(page, "r1", "start", -40));
  expect(writes).toBe(1);
  let [stored] = await regionsOnServer(page);
  expect(stored.rate).toBeCloseTo(0.5, 6);
  expect(stored.at_s).toBeCloseTo(6, 3);
  expect(stored).toMatchObject({ start_s: 0, end_s: 4 });
  let box = await regionBox(page, 0);
  expect(box.top).toBeCloseTo(before.top - 40, 0);
  expect(box.top + box.height).toBeCloseTo(bottom, 0);

  // Down sixty: shorter than it began, twice the speed, beginning later.
  // The part being cut away is striped at the top while the thumb is down.
  writes = await writesDuring(page, async () => {
    await stretchDrag(page, "r1", "start", 60, false);
    const cut = (await page.getByTestId("region-cut").boundingBox())!;
    expect(cut.height).toBeCloseTo(60, 0);
    // Inside the box's one-pixel border.
    expect(Math.abs(cut.y - (await region(page, "r1").boundingBox())!.y)).toBeLessThanOrEqual(2);
    await page.mouse.up();
  });
  expect(writes).toBe(1);
  [stored] = await regionsOnServer(page);
  expect(stored.rate).toBeCloseTo(2, 6);
  expect(stored.at_s).toBeCloseTo(12, 3);
  expect(stored).toMatchObject({ start_s: 0, end_s: 4 });
  box = await regionBox(page, 0);
  expect(box.height).toBeCloseTo(20, 0);
  expect(box.top + box.height).toBeCloseTo(bottom, 0);

  // Two undos: where it was, at the speed it was.
  await page.getByTestId("collage-undo").click();
  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  [stored] = await regionsOnServer(page);
  expect(stored).toMatchObject({ rate: 1, at_s: 10, start_s: 0, end_s: 4 });
});

test("a stretch stops at a quarter speed and at four times; past them the handle stays on the wall and the bar says so, without a number", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 4)]);
  await page.goto("/collage");

  // How far the handle has travelled from where it was resting. The claim
  // being tested is that it stops at the wall, which is a distance moved,
  // not a place. Measuring the place instead would drag in the box's own
  // one-pixel border, which has nothing to do with the bound. The thumb
  // going past the edge of the canvas scrolls it, so the screen is not the
  // place to measure either; the box is the reference and it does not move
  // during a drag, because the drag only draws a preview.
  const handleAgainstBox = async () => {
    const hb = (await handle(page, "r1", "end").boundingBox())!;
    const rb = (await region(page, "r1").boundingBox())!;
    return hb.y + hb.height / 2 - (rb.y + rb.height);
  };
  const handleMovedBy = async (from: number) => (await handleAgainstBox()) - from;

  // The handle only exists once stretch mode is on, so rest is measured
  // after entering it. Entering writes nothing, so it can sit outside the
  // write count; `stretchDrag` enters again and finds it already on.
  await enterStretch(page, "r1", "end");
  let rest = await handleAgainstBox();

  // Two thousand pixels down asks for two hundred seconds of a four-second
  // cut. It gets sixteen: four times as long, and the handle stops there.
  let writes = await writesDuring(page, async () => {
    await stretchDrag(page, "r1", "end", 2000, false);
    await expect(page.getByTestId("collage-mode")).toHaveAttribute("data-bound", "slow");
    await expect(page.getByTestId("collage-mode")).toContainText("as slow as it goes");
    expect(await handleMovedBy(rest)).toBeCloseTo(120, 0);
    expect((await page.getByTestId("region-more").boundingBox())!.height).toBeCloseTo(120, 0);
    await noFigures(page);
    await page.mouse.up();
  });
  expect(writes).toBe(1);
  let [stored] = await regionsOnServer(page);
  expect(stored.rate).toBeCloseTo(0.25, 6);
  expect((await regionBox(page, 0)).height).toBeCloseTo(160, 0);

  // And two thousand up asks for less than nothing. It gets a second: four
  // times the speed, ten pixels, and the handle stops there.
  await enterStretch(page, "r1", "end");
  rest = await handleAgainstBox();
  writes = await writesDuring(page, async () => {
    await stretchDrag(page, "r1", "end", -2000, false);
    await expect(page.getByTestId("collage-mode")).toHaveAttribute("data-bound", "fast");
    await expect(page.getByTestId("collage-mode")).toContainText("as fast as it goes");
    expect(await handleMovedBy(rest)).toBeCloseTo(-150, 0);
    await noFigures(page);
    await page.mouse.up();
  });
  expect(writes).toBe(1);
  [stored] = await regionsOnServer(page);
  expect(stored.rate).toBeCloseTo(4, 6);
  expect(stored).toMatchObject({ start_s: 0, end_s: 4, at_s: 0 });
  expect((await regionBox(page, 0)).height).toBeCloseTo(10, 0);

  // A region written slower than the bound, as the trim tests write them,
  // may be brought back towards the bound and never taken further out.
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 1, 0.05)]);
  await page.reload();
  expect((await regionBox(page, 0)).height).toBeCloseTo(200, 0);
  writes = await countWrites(page, async () => {
    await stretchDrag(page, "r1", "end", 100, false);
    await expect(page.getByTestId("collage-mode")).toHaveAttribute("data-bound", "slow");
    await page.mouse.up();
  });
  expect(writes).toBe(0);
  [stored] = await regionsOnServer(page);
  expect(stored.rate).toBe(0.05);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "stretch");
  writes = await writesDuring(page, () => stretchDrag(page, "r1", "end", -100));
  expect(writes).toBe(1);
  [stored] = await regionsOnServer(page);
  expect(stored.rate).toBeCloseTo(0.1, 6);
  expect((await regionBox(page, 0)).height).toBeCloseTo(100, 0);
});

test("a stretch cannot run into the region below on its track, nor the start into the one above or past the first moment", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  const hash = set[0].hash;
  await writeRegions(request, [
    regionRow("r1", hash, 0, 0, 0, 4),
    regionRow("r2", hash, 0, 10, 0, 3),
    regionRow("r3", hash, 1, 2, 0, 4),
  ]);
  await page.goto("/collage");
  await expect(page.getByTestId("region")).toHaveCount(3);

  // The end of the first stops where the second begins.
  let writes = await writesDuring(page, async () => {
    await stretchDrag(page, "r1", "end", 500, false);
    await expect(page.getByTestId("collage-mode")).toHaveAttribute("data-bound", "room");
    await expect(page.getByTestId("collage-mode")).toContainText("no more room on the track");
    await noFigures(page);
    await page.mouse.up();
  });
  expect(writes).toBe(1);
  let stored = await regionsOnServer(page);
  expect(stored[0].rate).toBeCloseTo(0.4, 6);
  expect(stored[0].at_s).toBe(0);
  expect(stored[1]).toMatchObject({ id: "r2", at_s: 10, start_s: 0, end_s: 3, rate: 1 });
  let a = (await region(page, "r1").boundingBox())!;
  let b = (await region(page, "r2").boundingBox())!;
  expect(a.y + a.height).toBeLessThanOrEqual(b.y + 0.5);
  expect(a.y + a.height).toBeCloseTo(b.y, 0);

  // Put it back, and the start of the second stops where the first ends.
  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  writes = await writesDuring(page, async () => {
    await stretchDrag(page, "r2", "start", -500, false);
    await expect(page.getByTestId("collage-mode")).toHaveAttribute("data-bound", "room");
    await page.mouse.up();
  });
  expect(writes).toBe(1);
  stored = await regionsOnServer(page);
  expect(stored[1].rate).toBeCloseTo(1 / 3, 6);
  expect(stored[1].at_s).toBeCloseTo(4, 3);
  expect(stored[1]).toMatchObject({ start_s: 0, end_s: 3 });
  expect(stored[0]).toMatchObject({ id: "r1", rate: 1, at_s: 0 });
  a = (await region(page, "r1").boundingBox())!;
  b = (await region(page, "r2").boundingBox())!;
  expect(a.y + a.height).toBeLessThanOrEqual(b.y + 0.5);
  expect(b.y + b.height).toBeCloseTo(TOP_PAD + 130 + (await page.getByTestId("collage-space").boundingBox())!.y, 0);

  // A region alone on its track: the start stops at the first moment.
  writes = await writesDuring(page, () => stretchDrag(page, "r3", "start", -500));
  expect(writes).toBe(1);
  stored = await regionsOnServer(page);
  expect(stored[2].at_s).toBe(0);
  expect(stored[2].rate).toBeCloseTo(4 / 6, 6);
  const c = await regionBox(page, 2);
  expect(c.top).toBeCloseTo(TOP_PAD, 0);
  expect(c.height).toBeCloseTo(60, 0);
});

test("stretch, then trim the same handle: the cut moves at the new rate, the box and the sound inside it agree, and the slice is cut at one speed", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  const { hash, duration_s: d } = set[0];
  await writeRegions(request, [regionRow("r1", hash, 0, 0, 0, d)]);
  await page.goto("/collage");

  // Twenty pixels longer: two collage seconds on top of the sound's own.
  let writes = await writesDuring(page, () => stretchDrag(page, "r1", "end", 20));
  expect(writes).toBe(1);
  const rate = d / (d + 2);
  let [stored] = await regionsOnServer(page);
  expect(stored.rate).toBeCloseTo(rate, 5);
  expect(stored.end_s).toBeCloseTo(d, 3);

  // Stretch has ended, so the same handle now trims. Ten pixels up is one
  // collage second, which at this rate is `rate` seconds of source.
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  writes = await writesDuring(page, () => drag(page, "r1", "end", -10));
  expect(writes).toBe(1);
  [stored] = await regionsOnServer(page);
  expect(stored.rate).toBeCloseTo(rate, 5);
  expect(stored.end_s).toBeCloseTo(d - rate, 2);
  expect(stored.start_s).toBe(0);

  // The box is the cut over the rate, and the sound is drawn over exactly
  // that height.
  const box = await regionBox(page, 0);
  expect(box.height).toBeCloseTo(((d - rate) / rate) * PX_PER_S, 0);
  const wave = region(page, "r1").getByTestId("region-wave");
  expect((await wave.boundingBox())!.height).toBeCloseTo(box.height, 0);

  // What plays is that cut, sliced at one speed. The rate is applied in the
  // browser; the route never hears of it.
  const slice = page.waitForRequest((r) => r.url().includes(`/api/files/${hash}/slice?`));
  await region(page, "r1").click({ position: { x: 10, y: 5 } });
  const url = new URL((await slice).url());
  expect(Number(url.searchParams.get("start"))).toBe(0);
  expect(Number(url.searchParams.get("end"))).toBeCloseTo(d - rate, 2);
  expect(url.searchParams.has("rate")).toBe(false);
  await expect(region(page, "r1")).toHaveAttribute("data-playing", "true");
});

test("stretch, snip, then stretch a half: both halves keep the rate, the second keeps its moment, and each half stretches on its own", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 4)]);
  await page.goto("/collage");
  await stretchDrag(page, "r1", "end", 40);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect((await regionBox(page, 0)).height).toBeCloseTo(80, 0);

  // Twenty to forty pixels down a half-speed region is one to two seconds
  // of source. Both halves are half speed; the second sounds where its
  // material did, four collage seconds in.
  await enterSnip(page);
  await snipDrag(page, "r1", 20, 40);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  await expect(page.getByTestId("region")).toHaveCount(2);
  let stored = await regionsOnServer(page);
  expect(stored[0]).toMatchObject({ id: "r1", at_s: 0, start_s: 0 });
  expect(stored[0].end_s).toBeCloseTo(1, 2);
  expect(stored[0].rate).toBeCloseTo(0.5, 6);
  expect(stored[1].id).toBe("r2");
  expect(stored[1].start_s).toBeCloseTo(2, 2);
  expect(stored[1].end_s).toBe(4);
  expect(stored[1].at_s).toBeCloseTo(4, 2);
  expect(stored[1].rate).toBeCloseTo(0.5, 6);
  expect(Math.round((await regionBox(page, 0)).height)).toBe(20);
  expect(Math.round((await regionBox(page, 1)).height)).toBe(40);

  // The second half, twice as long again: a quarter speed, same moment.
  const writes = await writesDuring(page, () => stretchDrag(page, "r2", "end", 40));
  expect(writes).toBe(1);
  stored = await regionsOnServer(page);
  expect(stored[1].rate).toBeCloseTo(0.25, 6);
  expect(stored[1].at_s).toBeCloseTo(4, 2);
  expect(stored[0].rate).toBeCloseTo(0.5, 6);
  expect(Math.round((await regionBox(page, 1)).height)).toBe(80);

  // The first half, as long as it can be: it stops at the second, which is
  // also where a quarter speed would stop it.
  await writesDuring(page, () => stretchDrag(page, "r1", "end", 100));
  stored = await regionsOnServer(page);
  expect(stored[0].rate).toBeCloseTo(0.25, 6);
  const a = (await region(page, "r1").boundingBox())!;
  const b = (await region(page, "r2").boundingBox())!;
  expect(a.y + a.height).toBeLessThanOrEqual(b.y + 0.5);
  expect(a.y + a.height).toBeCloseTo(b.y, 0);
});

test("a stretched region plays for its stretched length from a slice cut at one speed; stretching a playing region stops it", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  const { hash, duration_s: d } = set[0];
  // The whole sound at a quarter speed: four times as long to play.
  await writeRegions(request, [regionRow("r1", hash, 0, 0, 0, d, 0.25)]);
  await page.goto("/collage");
  const target = region(page, "r1");
  expect((await target.boundingBox())!.height).toBeCloseTo(d * 4 * PX_PER_S, 0);

  const slice = page.waitForRequest((r) => r.url().includes(`/api/files/${hash}/slice?`));
  const started = Date.now();
  await target.click({ position: { x: 10, y: 10 } });
  const url = new URL((await slice).url());
  expect(Number(url.searchParams.get("start"))).toBe(0);
  expect(Number(url.searchParams.get("end"))).toBeCloseTo(d, 3);
  expect(url.searchParams.has("rate")).toBe(false);
  await expect(target).toHaveAttribute("data-playing", "true");

  // Still going well after the sound's own length has passed: at one speed
  // it would have ended by now.
  await page.waitForTimeout(Math.round((d + 0.6) * 1000));
  await expect(target).toHaveAttribute("data-playing", "true");
  // And over by the time four times the length has, and not much later.
  await expect(target).toHaveAttribute("data-playing", "false", { timeout: Math.round(d * 4 * 1000) + 3000 });
  const took = (Date.now() - started) / 1000;
  expect(took).toBeGreaterThan(d * 3);
  expect(took).toBeLessThan(d * 4 + 3);

  // Playing again, then stretched: the slice being played is the rate
  // being changed, so it stops, and the next tap plays the new rate.
  await target.click({ position: { x: 10, y: 10 } });
  await expect(target).toHaveAttribute("data-playing", "true");
  await stretchDrag(page, "r1", "end", -20);
  await expect(target).toHaveAttribute("data-playing", "false");
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  const [stored] = await regionsOnServer(page);
  expect(stored.rate).toBeCloseTo(d / (d * 4 - 2), 5);
  const again = page.waitForRequest((r) => r.url().includes(`/api/files/${hash}/slice?`));
  await target.click({ position: { x: 10, y: 5 } });
  const url2 = new URL((await again).url());
  expect(Number(url2.searchParams.get("end"))).toBeCloseTo(d, 3);
  await expect(target).toHaveAttribute("data-playing", "true");
});

test("switching modes mid-stretch lets go without writing; a selected stretch handle nudges the length by keyboard", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 4)]);
  await page.goto("/collage");

  // Mid-drag, the other finger presses snip: the drag is let go, and the
  // thumb lifting afterwards writes nothing. A mouse has no other finger,
  // so the press is the button's own click event.
  let writes = await countWrites(page, async () => {
    await stretchDrag(page, "r1", "end", 30, false);
    await expect(page.getByTestId("collage")).toHaveAttribute("data-dragging", "true");
    await page.getByTestId("collage-snip").dispatchEvent("click");
    await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "snip");
    await expect(page.getByTestId("collage")).toHaveAttribute("data-dragging", "false");
    await expect(page.getByTestId("region-more")).toHaveCount(0);
    await page.mouse.up();
  });
  expect(writes).toBe(0);
  let [stored] = await regionsOnServer(page);
  expect(stored.rate).toBe(1);
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);
  await page.getByTestId("collage-snip").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");

  // Escape mid-drag: the same, and the handle is let go of.
  writes = await countWrites(page, async () => {
    await stretchDrag(page, "r1", "end", 30, false);
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("collage")).toHaveAttribute("data-dragging", "false");
    await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
    await page.mouse.up();
  });
  expect(writes).toBe(0);

  // By keyboard: a tenth of a collage second longer, then a whole one.
  const h = await enterStretch(page, "r1", "end");
  await h.focus();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  [stored] = await regionsOnServer(page);
  expect(stored.rate).toBeCloseTo(4 / 4.1, 5);
  await page.keyboard.press("Shift+ArrowDown");
  await expect(page.getByTestId("collage-undo")).toHaveAttribute("data-depth", "2");
  [stored] = await regionsOnServer(page);
  expect(stored.rate).toBeCloseTo(4 / 5.1, 5);
  expect(stored).toMatchObject({ start_s: 0, end_s: 4, at_s: 0 });
  expect((await regionBox(page, 0)).height).toBeCloseTo(51, 0);
});

/* Stretch, adversarial ------------------------------------------------------- */

test("a stretch that has met no wall says so, and says it whatever the length of the cut", async ({
  page,
  request,
}) => {
  const set = await sounds(page);

  // A rate is rounded before it is stored, so the length that comes back out
  // of a stored rate is not exactly the length the thumb asked for. Read as a
  // shortfall in length, that rounding cannot be told apart from a wall, and
  // the difference grows with the cut. A wall is a fact about the rate, so
  // these drags land nowhere near one and the bar must stay quiet.
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 4)]);
  await page.goto("/collage");
  await enterStretch(page, "r1", "end");
  const h = handle(page, "r1", "end");
  const first = (await h.boundingBox())!;
  const x = first.x + first.width / 2;
  const y = first.y + first.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  for (const dy of [17, 23, 33, 41, 57, 63, -11, -19]) {
    await page.mouse.move(x, y + dy);
    await expect(page.getByTestId("collage-mode"), `four-second cut dragged ${dy}`).toHaveAttribute(
      "data-bound",
      "",
    );
    await expect(page.getByTestId("collage-mode")).toContainText("let go to keep it");
  }
  await page.mouse.up();
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");

  // Fifteen minutes of source, which is what the first real project holds.
  // Alone on its track, at full speed, every one of these drags is inside
  // both bounds by a wide margin.
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 900)]);
  await page.reload();
  await enterStretch(page, "r1", "end");
  // Put the handle in the middle of the canvas, so the thumb is nowhere near
  // the edge that scrolls and every drag below is exactly the distance given.
  await page.getByTestId("collage-canvas").evaluate((node) => {
    node.scrollTop = node.scrollHeight - node.clientHeight - 400;
  });
  await page.waitForTimeout(100);
  const second = (await h.boundingBox())!;
  const x2 = second.x + second.width / 2;
  const y2 = second.y + second.height / 2;
  await page.mouse.move(x2, y2);
  await page.mouse.down();
  for (const dy of [-40, -20, -7, 7, 20, 40, 61]) {
    await page.mouse.move(x2, y2 + dy);
    await expect(page.getByTestId("collage-mode"), `fifteen-minute cut dragged ${dy}`).toHaveAttribute(
      "data-bound",
      "",
    );
    await expect(page.getByTestId("collage-mode")).toContainText("let go to keep it");
  }
  await page.mouse.up();
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
});

test("the start handle stopped by the first moment says that, not that the track is crowded", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  // Alone on its track with two seconds above it. Slowing it from the start
  // runs out of time before it runs out of rate, and there is no neighbour.
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 2, 0, 4)]);
  await page.goto("/collage");
  await stretchDrag(page, "r1", "start", -500, false);
  await expect(page.getByTestId("collage-mode")).toHaveAttribute("data-bound", "top");
  await expect(page.getByTestId("collage-mode")).toContainText("this is the first moment");
  await noFigures(page);
  await page.mouse.up();
  const [stored] = await regionsOnServer(page);
  expect(stored.at_s).toBe(0);
  expect(stored.rate).toBeCloseTo(4 / 6, 6);
});

test("a stretched region is scheduled in pieces that join without a seam, each played at its rate", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  const hash = set[0].hash;

  // The fixture's sounds are a second long, so a cut that spans more than
  // one piece has to be served here. The shape is the route's: a 48 kHz
  // stereo WAV of exactly the stretch asked for, at one speed.
  await page.route(/\/api\/files\/.*\/slice\?/, async (route) => {
    const url = new URL(route.request().url());
    const from = Number(url.searchParams.get("start"));
    const to = Number(url.searchParams.get("end"));
    const sampleRate = 48000;
    const frames = Math.round((to - from) * sampleRate);
    const body = Buffer.alloc(44 + frames * 4);
    body.write("RIFF", 0);
    body.writeUInt32LE(36 + frames * 4, 4);
    body.write("WAVE", 8);
    body.write("fmt ", 12);
    body.writeUInt32LE(16, 16);
    body.writeUInt16LE(1, 20);
    body.writeUInt16LE(2, 22);
    body.writeUInt32LE(sampleRate, 24);
    body.writeUInt32LE(sampleRate * 4, 28);
    body.writeUInt16LE(4, 32);
    body.writeUInt16LE(16, 34);
    body.write("data", 36);
    body.writeUInt32LE(frames * 4, 40);
    for (let i = 0; i < frames; i += 1) {
      const value = Math.round(Math.sin(2 * Math.PI * 220 * (from + i / sampleRate)) * 12000);
      body.writeInt16LE(value, 44 + i * 4);
      body.writeInt16LE(value, 44 + i * 4 + 2);
    }
    await route.fulfill({ status: 200, headers: { "content-type": "audio/wav" }, body });
  });

  // Every piece scheduled, with the moment it was told to start, its own
  // length and the speed it was given.
  await page.addInitScript(() => {
    const store: Array<{ when: number; duration: number; rate: number }> = [];
    (window as unknown as { __pieces: typeof store }).__pieces = store;
    const proto = AudioBufferSourceNode.prototype;
    const original = proto.start;
    proto.start = function (this: AudioBufferSourceNode, when?: number, ...rest: number[]) {
      store.push({ when: when ?? 0, duration: this.buffer?.duration ?? 0, rate: this.playbackRate.value });
      return (original as (when?: number, ...rest: number[]) => void).call(this, when, ...rest);
    };
  });

  const pieces = async () =>
    page.evaluate(() => (window as unknown as { __pieces: Array<{ when: number; duration: number; rate: number }> }).__pieces);

  // Forty seconds of source is three pieces. A quarter speed makes each one
  // last four times as long to play, and the next must begin exactly then.
  for (const rate of [0.25, 4]) {
    await writeRegions(request, [regionRow("r1", hash, 0, 0, 0, 40, rate)]);
    await page.goto("/collage");
    await region(page, "r1").click({ position: { x: 10, y: 5 } });
    await expect(region(page, "r1")).toHaveAttribute("data-playing", "true");
    await expect.poll(async () => (await pieces()).length, { timeout: 20_000 }).toBeGreaterThanOrEqual(3);
    const scheduled = await pieces();
    for (const piece of scheduled) expect(piece.rate, `every piece plays at ${rate}`).toBe(rate);
    for (let i = 1; i < scheduled.length; i += 1) {
      const gap = scheduled[i].when - (scheduled[i - 1].when + scheduled[i - 1].duration / rate);
      // A hundredth of a millisecond: a sample at 48 kHz is two hundredths.
      expect(Math.abs(gap), `piece ${i} at ${rate} joins the one before it`).toBeLessThan(1e-5);
    }
    // Leaving the view is what stops it: the next pass navigates again.
  }
  await page.goto("/board");
});

/* Playing the piece ---------------------------------------------------------- */

/**
 * What Web Audio was actually told to do.
 *
 * The view's own state says a piece is playing; that is the view agreeing
 * with itself. These tests listen one level down, at the calls the browser
 * received: every buffer source started, the moment it was given, its speed,
 * the gain it went through, the context it belongs to, and whether that gain
 * reached that context's destination. A mix is a sum at one destination, so
 * that is what is checked, rather than the view's word for it.
 *
 * Stops are recorded with the clock, so "everything at once" can be measured
 * instead of asserted, and each one carries its buffer's length, which is how
 * a stopped source is traced back to the region that owns it.
 */
interface Scheduled {
  when: number;
  duration: number;
  rate: number;
  gain: number;
  ctx: number;
  /**
   * Every node between this source and the end of the graph, in order.
   *
   * The mix no longer ends at the destination directly: it goes through a
   * trim and a shaper that hold the sum inside the rails. So "the voice
   * reaches the one destination" is read off the whole chain rather than off
   * one hop, and a test can also say what the chain is made of.
   */
  path: string[];
  toDestination: boolean;
  /**
   * The context's clock at the moment the browser was told to start this
   * piece. A `when` earlier than this is a moment that has already gone, and
   * Web Audio answers it by sounding the piece at once — on top of whatever
   * is still sounding from the piece before it.
   */
  now: number;
}

interface Heard {
  pieces: Scheduled[];
  stops: Array<{ at: number; duration: number }>;
  closes: number;
  /**
   * Every level the browser was told to ramp a gain to.
   *
   * A balance made while something sounds does not reschedule anything: it
   * moves a gain that is already in the mix. So "the level was heard" is read
   * off the ramps the gain was given, which is a thing the browser was told,
   * not a thing the view says about itself.
   */
  ramps: number[];
}

/**
 * The mix bus as the browser was told to build it.
 *
 * The table a `WaveShaperNode` was given, the trim in front of it, and
 * whether it was asked to oversample. Read separately from `heard` because
 * the table is sixteen thousand numbers and nothing else needs it.
 */
interface Bus {
  points: number[] | null;
  trim: number | null;
  oversample: string | null;
  /** How many shapers were built. Fifteen voices share one bus, or they do not. */
  built: number;
}

async function listen(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const heard: Heard = { pieces: [], stops: [], closes: 0, ramps: [] };
    (window as unknown as { __heard: Heard }).__heard = heard;
    const bus: Bus = { points: null, trim: null, oversample: null, built: 0 };
    (window as unknown as { __bus: Bus }).__bus = bus;
    let contexts = 0;
    const idOf = (ctx: BaseAudioContext): number => {
      const tagged = ctx as BaseAudioContext & { __id?: number };
      if (tagged.__id === undefined) tagged.__id = (contexts += 1);
      // Kept so a test can read the same clock the voices were scheduled
      // against, and put the playhead against it rather than against itself.
      (window as unknown as { __ctx: BaseAudioContext }).__ctx = ctx;
      return tagged.__id;
    };
    type Tracked = { __dest?: unknown };
    const remember = (proto: { connect: unknown }) => {
      const original = proto.connect as (this: unknown, dest: unknown, ...rest: unknown[]) => unknown;
      (proto as { connect: unknown }).connect = function (this: Tracked, dest: unknown, ...rest: unknown[]) {
        this.__dest = dest;
        // The one gain that feeds a shaper is the bus's trim, and its value
        // is what the table's range has to be read against.
        if (dest instanceof WaveShaperNode && this instanceof GainNode) bus.trim = this.gain.value;
        return original.call(this, dest, ...rest);
      };
    };
    remember(AudioBufferSourceNode.prototype as unknown as { connect: unknown });
    remember(GainNode.prototype as unknown as { connect: unknown });
    remember(WaveShaperNode.prototype as unknown as { connect: unknown });

    // The table itself, and whether the shaper was asked to oversample. Both
    // are taken as they are set, so a test reads what the browser got.
    const own = (name: "curve" | "oversample") => {
      const descriptor = Object.getOwnPropertyDescriptor(WaveShaperNode.prototype, name);
      if (!descriptor?.set) return;
      const set = descriptor.set;
      Object.defineProperty(WaveShaperNode.prototype, name, {
        ...descriptor,
        set(this: WaveShaperNode, value: unknown) {
          if (name === "curve") {
            bus.points = value ? Array.from(value as Float32Array) : null;
            bus.built += 1;
          } else {
            bus.oversample = String(value);
          }
          set.call(this, value);
        },
      });
    };
    own("curve");
    own("oversample");

    /** Every node from `node` onwards, in order, ending at the destination. */
    const pathOf = (node: unknown): string[] => {
      const names: string[] = [];
      let at = node as (AudioNode & Tracked) | undefined;
      for (let hop = 0; hop < 8 && at; hop += 1) {
        at = (at as Tracked).__dest as (AudioNode & Tracked) | undefined;
        if (!at) break;
        names.push(at === at.context?.destination ? "destination" : at.constructor.name);
        if (at === at.context?.destination) break;
      }
      return names;
    };

    const proto = AudioBufferSourceNode.prototype;
    const start = proto.start;
    proto.start = function (this: AudioBufferSourceNode & Tracked, when?: number, ...rest: number[]) {
      const through = this.__dest;
      const isGain = through instanceof GainNode;
      const path = pathOf(this);
      heard.pieces.push({
        when: when ?? 0,
        duration: this.buffer?.duration ?? 0,
        rate: this.playbackRate.value,
        gain: isGain ? through.gain.value : -1,
        ctx: idOf(this.context),
        path,
        toDestination: path[path.length - 1] === "destination",
        now: this.context.currentTime,
      });
      return (start as (when?: number, ...rest: number[]) => void).call(this, when, ...rest);
    };
    const stop = proto.stop;
    proto.stop = function (this: AudioBufferSourceNode, ...args: number[]) {
      heard.stops.push({ at: performance.now(), duration: this.buffer?.duration ?? 0 });
      return (stop as (...args: number[]) => void).apply(this, args);
    };
    const close = AudioContext.prototype.close;
    AudioContext.prototype.close = function (this: AudioContext) {
      heard.closes += 1;
      return close.call(this);
    };
    const ramp = AudioParam.prototype.linearRampToValueAtTime;
    AudioParam.prototype.linearRampToValueAtTime = function (this: AudioParam, value: number, when: number) {
      heard.ramps.push(value);
      return ramp.call(this, value, when);
    };
  });
}

async function heard(page: Page): Promise<Heard> {
  return page.evaluate(() => (window as unknown as { __heard: Heard }).__heard);
}

/** The mix bus as it was built. Sixteen thousand numbers; asked for by name. */
async function bus(page: Page): Promise<Bus> {
  return page.evaluate(() => (window as unknown as { __bus: Bus }).__bus);
}

/** When a scheduled piece stops sounding, on the context's own clock. */
function endsAt(piece: Scheduled): number {
  return piece.when + piece.duration / piece.rate;
}

/**
 * When a scheduled piece really sounds, and until when.
 *
 * Web Audio does not wait for a moment that has gone: a source told to start
 * in the past starts at once. So what a listener hears is the later of the
 * moment asked for and the clock as it was when the browser was told.
 */
function sounding(piece: Scheduled): { from: number; to: number } {
  const from = Math.max(piece.when, piece.now);
  return { from, to: from + piece.duration / piece.rate };
}

/**
 * Serve the slice route from here, so a cut can be longer than the second the
 * fixture's sounds hold.
 *
 * The shape is the real route's: a 48 kHz stereo WAV of exactly the span
 * asked for, at one speed. `held` says how many milliseconds a piece
 * beginning at a given moment is kept waiting, which is how a network that
 * stalls part-way through a region is reproduced.
 */
async function serveSlices(page: Page, held: (fromS: number) => number = () => 0): Promise<void> {
  await page.route(/\/api\/files\/.*\/slice\?/, async (route) => {
    const url = new URL(route.request().url());
    const from = Number(url.searchParams.get("start"));
    const to = Number(url.searchParams.get("end"));
    const wait = held(from);
    if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
    const sampleRate = 48000;
    const frames = Math.round((to - from) * sampleRate);
    const body = Buffer.alloc(44 + frames * 4);
    body.write("RIFF", 0);
    body.writeUInt32LE(36 + frames * 4, 4);
    body.write("WAVE", 8);
    body.write("fmt ", 12);
    body.writeUInt32LE(16, 16);
    body.writeUInt16LE(1, 20);
    body.writeUInt16LE(2, 22);
    body.writeUInt32LE(sampleRate, 24);
    body.writeUInt32LE(sampleRate * 4, 28);
    body.writeUInt16LE(4, 32);
    body.writeUInt16LE(16, 34);
    body.write("data", 36);
    body.writeUInt32LE(frames * 4, 40);
    await route.fulfill({ status: 200, headers: { "content-type": "audio/wav" }, body });
  });
}

/** The scheduled piece whose buffer is `lengthS` of source, to a hundredth. */
function cut(pieces: Scheduled[], lengthS: number): Scheduled {
  const found = pieces.find((p) => Math.abs(p.duration - lengthS) < 0.005);
  expect(found, `no piece was scheduled from a ${Math.round(lengthS * 1000)}-millisecond cut`).toBeTruthy();
  return found!;
}

test("with nothing stamped the transport refuses, and there is no playhead", async ({ page }) => {
  await page.goto("/collage");
  await expect(page.getByTestId("collage-play")).toBeDisabled();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "idle");
  await expect(page.getByTestId("collage-playhead")).toHaveCount(0);
  // The canvas is still genuinely empty: the playhead is not a lane waiting
  // to be filled, it is a thing that exists only while something sounds.
  expect(await page.getByTestId("collage-space").locator("*").count()).toBe(0);
  await noFigures(page);
});

test("play sounds every region at its own moment and its own rate, summed through one destination", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  const hash = set[0].hash;
  // Three cuts of three different lengths, so every scheduled piece can be
  // traced back to the region that asked for it. On three tracks, slowed so
  // they are seconds long on the canvas, and overlapping: the second begins
  // while the first and third are still sounding.
  await writeRegions(request, [
    regionRow("r1", hash, 0, 0, 0, 0.3, 0.05),
    regionRow("r2", hash, 1, 2, 0, 0.5, 0.05),
    regionRow("r3", hash, 2, 0, 0.2, 0.9, 0.1),
  ]);
  await listen(page);
  await page.goto("/collage");
  await expect(page.getByTestId("region")).toHaveCount(3);
  await expect(page.getByTestId("collage-play")).toBeEnabled();

  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  await expect(page.getByTestId("collage-play-error")).toHaveCount(0);

  const { pieces } = await heard(page);
  expect(pieces).toHaveLength(3);
  // One context, one destination, and every voice a plain unity gain into it.
  expect(new Set(pieces.map((p) => p.ctx)).size).toBe(1);
  for (const p of pieces) {
    expect(p.toDestination, "a voice that did not reach the destination").toBe(true);
    expect(p.gain).toBe(1);
  }

  const a = cut(pieces, 0.3);
  const b = cut(pieces, 0.5);
  const c = cut(pieces, 0.7);
  expect(a.rate).toBeCloseTo(0.05, 6);
  expect(b.rate).toBeCloseTo(0.05, 6);
  expect(c.rate).toBeCloseTo(0.1, 6);

  // The moments are `at_s` on one clock: the second begins two seconds after
  // the other two, which begin together.
  expect(b.when - a.when).toBeCloseTo(2, 2);
  expect(c.when - a.when).toBeCloseTo(0, 2);

  // And they really overlap. When the second begins, the other two are still
  // sounding, so what leaves the destination at that moment is three voices
  // added together and not one played after another.
  expect(endsAt(a)).toBeGreaterThan(b.when + 1);
  expect(endsAt(c)).toBeGreaterThan(b.when + 1);
  await noFigures(page);

  // Stop: everything goes at once, inside a frame of everything else.
  const before = (await heard(page)).stops.length;
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "idle");
  await expect(page.getByTestId("collage-playhead")).toHaveCount(0);
  const taken = (await heard(page)).stops.slice(before);
  expect(taken.length).toBeGreaterThanOrEqual(3);
  const spread = Math.max(...taken.map((s) => s.at)) - Math.min(...taken.map((s) => s.at));
  expect(spread, "the voices were not silenced together").toBeLessThan(50);
});

test("the playhead is a line following the piece's time, and it crawls across a slowed region", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  // Eight tenths of a second of source at a twentieth speed: sixteen seconds
  // on the canvas, a hundred and sixty pixels tall.
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 0.8, 0.05)]);
  await page.goto("/collage");
  const box = await regionBox(page, 0);
  expect(box.height).toBeCloseTo(160, 0);

  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  const line = page.getByTestId("collage-playhead");
  await expect(line).toBeVisible();

  // A line: thin, across every track, and carrying no text at all.
  const lb = (await line.boundingBox())!;
  expect(lb.height).toBeLessThanOrEqual(4);
  expect(lb.width).toBeGreaterThanOrEqual(TRACK_W);
  expect(await line.innerText()).toBe("");

  const spaceY = (await page.getByTestId("collage-space").boundingBox())!.y;
  const at = async () => (await line.boundingBox())!.y - spaceY;
  const first = await at();
  await page.waitForTimeout(2000);
  const second = await at();

  // Ten pixels a second: the piece's own time, the same scale every region is
  // drawn at, so the line and the boxes always agree.
  expect(second - first).toBeGreaterThan(14);
  expect(second - first).toBeLessThan(26);
  // Two seconds in, eight tenths of a second of material is long gone at one
  // speed. Slowed, the line is barely into the box.
  expect(second).toBeLessThan(TOP_PAD + box.height / 2);
  expect(second).toBeGreaterThan(TOP_PAD);
  await noFigures(page);

  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage-playhead")).toHaveCount(0);
});

test("the piece stops itself at the end, the line goes with it, and playing again starts at the top", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  // Half a second of source at half speed: one second of piece.
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 0.5, 0.5)]);
  await listen(page);
  await page.goto("/collage");

  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  // It ends on its own, without a second tap.
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "idle", { timeout: 15_000 });
  await expect(page.getByTestId("collage-playhead")).toHaveCount(0);
  await expect(page.getByTestId("collage-play-error")).toHaveCount(0);
  expect((await heard(page)).pieces).toHaveLength(1);

  // Again, from the top: a longer arrangement this time, so where the line
  // starts can be seen rather than inferred.
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 0.5, 0.05)]);
  await page.reload();
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  const spaceY = (await page.getByTestId("collage-space").boundingBox())!.y;
  const line = (await page.getByTestId("collage-playhead").boundingBox())!;
  expect(line.y - spaceY).toBeGreaterThanOrEqual(TOP_PAD - 2);
  expect(line.y - spaceY).toBeLessThan(TOP_PAD + 30);
  await page.getByTestId("collage-play").click();
});

test("both ends of the stretch range play together, heavily overlapped, in one mix", async ({ page, request }) => {
  const set = await sounds(page);
  const hash = set[0].hash;
  // Four regions, four tracks, all beginning at the first moment: two at the
  // slowest a stretch goes and two at the fastest. Different cuts, so each is
  // told apart by its buffer.
  await writeRegions(request, [
    regionRow("r1", hash, 0, 0, 0, 0.3, 0.25),
    regionRow("r2", hash, 1, 0, 0, 0.4, 0.25),
    regionRow("r3", hash, 2, 0, 0, 0.5, 4),
    regionRow("r4", hash, 3, 0, 0, 0.6, 4),
  ]);
  await listen(page);
  await page.goto("/collage");
  await expect(page.getByTestId("region")).toHaveCount(4);
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");

  const { pieces } = await heard(page);
  expect(pieces).toHaveLength(4);
  expect(new Set(pieces.map((p) => p.ctx)).size).toBe(1);
  expect(cut(pieces, 0.3).rate).toBe(0.25);
  expect(cut(pieces, 0.4).rate).toBe(0.25);
  expect(cut(pieces, 0.5).rate).toBe(4);
  expect(cut(pieces, 0.6).rate).toBe(4);
  // All four begin at the same moment, and all four are sounding then.
  const first = Math.min(...pieces.map((p) => p.when));
  for (const p of pieces) {
    expect(p.when - first).toBeCloseTo(0, 3);
    expect(p.toDestination).toBe(true);
    expect(endsAt(p)).toBeGreaterThan(p.when);
  }
  await page.getByTestId("collage-play").click();
});

test("a region whose slice the server refuses drops out; the rest of the piece plays; all refused, nothing starts", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  const [one, two] = set;
  await writeRegions(request, [
    regionRow("r1", one.hash, 0, 0, 0, 0.4, 0.05),
    regionRow("r2", two.hash, 1, 0, 0, 0.6, 0.05),
  ]);
  await listen(page);
  await page.route(new RegExp(`/api/files/${one.hash}/slice\\?`), (route) =>
    route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "no such sound" }) }),
  );
  await page.goto("/collage");
  await page.getByTestId("collage-play").click();

  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  await expect(page.getByTestId("collage-play-error")).toContainText("dropped out of the mix");
  const { pieces } = await heard(page);
  expect(pieces).toHaveLength(1);
  expect(pieces[0].duration).toBeCloseTo(0.6, 2);
  await noFigures(page);
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "idle");

  // Every region refused: nothing is scheduled, nothing sounds, and the view
  // says so rather than showing a line moving over silence.
  await page.route(new RegExp(`/api/files/${two.hash}/slice\\?`), (route) =>
    route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "no such sound" }) }),
  );
  const before = (await heard(page)).pieces.length;
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage-play-error")).toContainText("could not play the collage");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "idle");
  await expect(page.getByTestId("collage-playhead")).toHaveCount(0);
  expect((await heard(page)).pieces.length).toBe(before);
});

test("editing a region while the piece plays silences that region and leaves the rest sounding", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  const hash = set[0].hash;
  // Two long regions on two tracks, told apart by the length of their cuts.
  await writeRegions(request, [
    regionRow("r1", hash, 0, 0, 0, 0.35, 0.02),
    regionRow("r2", hash, 1, 0, 0, 0.6, 0.02),
  ]);
  await listen(page);
  await page.goto("/collage");
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  expect((await heard(page)).pieces).toHaveLength(2);
  const before = (await heard(page)).stops.length;

  // A tap on a region while the piece plays takes it up and does not play it
  // on its own. That is what keeps trim, snip and stretch reachable mid-play.
  await takeUp(page, "r1");
  await expect(region(page, "r1")).toHaveAttribute("data-playing", "false");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");

  await drag(page, "r1", "end", -40);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");

  // The region that was cut went quiet. The other is still sounding, and the
  // piece is still playing.
  const taken = (await heard(page)).stops.slice(before);
  expect(taken.map((s) => Math.round(s.duration * 100))).toEqual([35]);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  await expect(page.getByTestId("collage-playhead")).toBeVisible();
  const [stored] = await regionsOnServer(page);
  // Forty pixels up is four canvas seconds, which at this rate is eight
  // hundredths of a second of source.
  expect(stored.end_s).toBeCloseTo(0.27, 2);

  // Undo is an edit too, and takes the same rule: the region it puts back is
  // not rescheduled into a piece already sounding.
  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  expect((await heard(page)).pieces).toHaveLength(2);
  await page.getByTestId("collage-play").click();
});

test("leaving the view stops the piece and lets the context go", async ({ page, request }) => {
  const set = await sounds(page);
  const hash = set[0].hash;
  await writeRegions(request, [
    regionRow("r1", hash, 0, 0, 0, 0.3, 0.02),
    regionRow("r2", hash, 1, 0, 0, 0.6, 0.02),
  ]);
  await listen(page);
  await page.goto("/collage");
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  expect((await heard(page)).pieces).toHaveLength(2);
  const before = await heard(page);

  // A link, not a reload: the document survives, so a piece left running
  // would carry on sounding over another view.
  await page.getByRole("link", { name: "board", exact: true }).click();
  await expect(page.getByTestId("collage")).toHaveCount(0);
  const after = await heard(page);
  expect(after.stops.length - before.stops.length).toBeGreaterThanOrEqual(2);
  expect(after.closes).toBeGreaterThan(before.closes);
});

test("snip and stretch are still reachable while the piece plays", async ({ page, request }) => {
  const set = await sounds(page);
  const hash = set[0].hash;
  await writeRegions(request, [
    regionRow("r1", hash, 0, 0, 0, 0.6, 0.02),
    regionRow("r2", hash, 1, 0, 0, 0.3, 0.02),
  ]);
  await page.goto("/collage");
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");

  // Playing is not a mode. Snip goes on and off underneath it. The span is
  // taken out of the middle, leaving a quarter of a second of source on each
  // side, which at this rate is a hundred and twenty-five pixels.
  await enterSnip(page);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  await snipDrag(page, "r1", 130, 170);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  await expect(page.getByTestId("region")).toHaveCount(3);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");

  // And stretch, which needs a handle, which needs a region taken up. Up the
  // way, so the region plays faster: written slower than the bound, it may
  // come back towards it and never go further out.
  await stretchDrag(page, "r2", "end", -60);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  const stored = await regionsOnServer(page);
  expect(stored.find((r) => r.id === "r2")!.rate).toBeGreaterThan(0.02);
  await noFigures(page);
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "idle");
});

test("one thing sounds at a time: play stops a region, and opening the picker stops the piece", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  const hash = set[0].hash;
  await writeRegions(request, [
    regionRow("r1", hash, 0, 0, 0, 0.6, 0.02),
    regionRow("r2", hash, 1, 0, 0, 0.3, 0.02),
  ]);
  await listen(page);
  await page.goto("/collage");

  // A region playing on its own, then the whole piece: the region stops.
  await region(page, "r1").click({ position: { x: 10, y: 10 } });
  await expect(region(page, "r1")).toHaveAttribute("data-playing", "true");
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  await expect(region(page, "r1")).toHaveAttribute("data-playing", "false");

  // The picker is a sheet over the whole screen and its rows play. The piece
  // steps aside rather than sounding under it.
  await page.getByTestId("collage-choose").click();
  await expect(page.getByTestId("collage-picker")).toBeVisible();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "idle");
  await expect(page.getByTestId("collage-playhead")).toHaveCount(0);
  await page.getByTestId("picker-close").click();
});

test("a region that goes quiet under an edit says so, and stops saying it on the next play", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  const hash = set[0].hash;
  await writeRegions(request, [
    regionRow("r1", hash, 0, 0, 0, 0.35, 0.02),
    regionRow("r2", hash, 1, 0, 0, 0.6, 0.02),
  ]);
  await page.goto("/collage");
  // Edited with nothing playing, nothing has gone quiet and nothing is said.
  await drag(page, "r1", "end", -20);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  await expect(page.getByTestId("collage-hint")).toHaveCount(0);

  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  await drag(page, "r1", "end", -20);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  // A block that went quiet looks exactly like a block that ended, and on a
  // phone it is under the thumb that stopped it. The bar says which it was.
  await expect(page.getByTestId("collage-hint")).toContainText("gone quiet");
  await expect(page.getByTestId("collage-hint")).toContainText("next time you play");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  await noFigures(page);

  // It is about this pass, so it goes when the pass does.
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "idle");
  await expect(page.getByTestId("collage-hint")).toHaveCount(0);
});

test("snipping a sounding region takes both halves out of the pass, and says so", async ({ page, request }) => {
  const set = await sounds(page);
  const hash = set[0].hash;
  await writeRegions(request, [
    regionRow("r1", hash, 0, 0, 0, 0.6, 0.02),
    regionRow("r2", hash, 1, 0, 0, 0.35, 0.02),
  ]);
  await listen(page);
  await page.goto("/collage");
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  expect((await heard(page)).pieces).toHaveLength(2);
  const before = (await heard(page)).stops.length;

  await enterSnip(page);
  await snipDrag(page, "r1", 130, 170);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  await expect(page.getByTestId("region")).toHaveCount(3);

  // The region that was cut in two stops, and neither half is put back into
  // the pass: what sounds from here is only what was not touched.
  const taken = (await heard(page)).stops.slice(before);
  expect(taken.map((s) => Math.round(s.duration * 100))).toEqual([60]);
  expect((await heard(page)).pieces, "a half was scheduled into a pass already running").toHaveLength(2);
  await expect(page.getByTestId("collage-hint")).toContainText("gone quiet");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  await page.getByTestId("collage-play").click();
});

test("a sound stamped while the piece plays is not folded into the pass it was stamped in", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 0.6, 0.02)]);
  await listen(page);
  await page.goto("/collage");
  await choose(page, 1);
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  expect((await heard(page)).pieces).toHaveLength(1);

  // Stamped on a second track while the line is running. The piece is
  // scheduled once, at the tap, so this block is drawn and the line crosses
  // it in silence. It is heard on the next play.
  await stampAt(page, TRACK_W + 40, 200);
  await expect(page.getByTestId("region")).toHaveCount(2);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  expect((await heard(page)).pieces).toHaveLength(1);

  await page.getByTestId("collage-play").click();
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  expect((await heard(page)).pieces).toHaveLength(3);
  await page.getByTestId("collage-play").click();
});

test("an edit made while the first pieces load stays out of the pass it was made in", async ({ page, request }) => {
  const set = await sounds(page);
  const hash = set[0].hash;
  await writeRegions(request, [
    regionRow("r1", hash, 0, 0, 0, 0.35, 0.02),
    regionRow("r2", hash, 1, 0, 0, 0.6, 0.02),
  ]);
  await listen(page);
  // The gap the transport calls `loading…`. The tap has already decided what
  // this pass holds, so an edit made in that gap is an edit mid-play and
  // takes the same rule: the region that changed does not sound this time.
  // Without that, a region cut in the gap sounds with the material the cut
  // removed, and nothing stops it.
  await serveSlices(page, () => 6000);
  await page.goto("/collage");
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "loading");

  await drag(page, "r1", "end", -40);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing", { timeout: 30_000 });

  const { pieces } = await heard(page);
  expect(
    pieces.map((p) => Math.round(p.duration * 100)).sort((a, b) => a - b),
    "the region cut while the piece loaded was sounded anyway",
  ).toEqual([60]);
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "idle");
});

test("stopping before the first sound leaves nothing scheduled, and the next play is clean", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  const hash = set[0].hash;
  await writeRegions(request, [
    regionRow("r1", hash, 0, 0, 0, 0.35, 0.02),
    regionRow("r2", hash, 1, 0, 0, 0.6, 0.02),
  ]);
  await listen(page);
  await serveSlices(page, () => 3000);
  await page.goto("/collage");

  const play = page.getByTestId("collage-play");
  await play.click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "loading");
  await expect(play).toContainText("stop");
  // A second tap gives up on the pieces still coming. Nothing may sound once
  // they land: the piece was stopped before it ever began.
  await play.click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "idle");
  await page.waitForTimeout(5000);
  expect((await heard(page)).pieces, "a piece sounded after the transport was stopped").toHaveLength(0);
  await expect(page.getByTestId("collage-playhead")).toHaveCount(0);

  // And the pass after it is whole: both regions, once each.
  await play.click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing", { timeout: 30_000 });
  const { pieces } = await heard(page);
  expect(pieces.map((p) => Math.round(p.duration * 100)).sort((a, b) => a - b)).toEqual([35, 60]);
  await play.click();
});

test("a piece that arrives late never sounds on top of the piece before it", async ({ page, request }) => {
  test.setTimeout(150_000);
  const set = await sounds(page);
  // Two and a half minutes of source at four times speed: ten pieces, each
  // lasting under four seconds, so the region is fetched as it plays rather
  // than up front. One piece in the middle is held back longer than the lead
  // the player keeps, which is what a phone on a bad connection does.
  await serveSlices(page, (from) => (from === 45 ? 14_000 : 0));
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 150, 4)]);
  await listen(page);
  await page.goto("/collage");

  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing", { timeout: 30_000 });
  await expect
    .poll(async () => (await heard(page)).pieces.length, { timeout: 90_000 })
    .toBeGreaterThanOrEqual(6);

  const { pieces } = await heard(page);
  for (const p of pieces) {
    expect(
      p.when,
      "a piece was told to start at a moment that had already gone, so it sounded at once",
    ).toBeGreaterThan(p.now - 0.05);
  }
  // And therefore nothing doubles: the region is one sound, not two copies of
  // itself a few seconds apart.
  const heardAt = pieces.map(sounding).sort((a, b) => a.from - b.from);
  for (let i = 1; i < heardAt.length; i += 1) {
    expect(heardAt[i].from, `piece ${i} began while piece ${i - 1} was still sounding`).toBeGreaterThan(
      heardAt[i - 1].to - 0.05,
    );
  }
  // A region that fell behind says so. A silent gap with nothing on screen is
  // indistinguishable from a region that simply ended.
  await expect(page.getByTestId("collage-play-error")).toContainText("fell behind");
  await noFigures(page);
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "idle");
});

test("when several regions drop out the view says how many, not “one”", async ({ page, request }) => {
  const set = await sounds(page);
  const [one, two] = set;
  await writeRegions(request, [
    regionRow("r1", one.hash, 0, 0, 0, 0.4, 0.05),
    regionRow("r2", one.hash, 1, 0, 0, 0.5, 0.05),
    regionRow("r3", two.hash, 2, 0, 0, 0.6, 0.05),
  ]);
  await listen(page);
  await page.route(new RegExp(`/api/files/${one.hash}/slice\\?`), (route) =>
    route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "no such sound" }) }),
  );
  await page.goto("/collage");
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  await expect(page.getByTestId("collage-play-error")).toContainText("2 regions dropped out of the mix");
  await noFigures(page);
  await page.getByTestId("collage-play").click();
});

test("a later voice lands where the line says it will, not where the line says it is", async ({ page, request }) => {
  test.setTimeout(90_000);
  const set = await sounds(page);
  const hash = set[0].hash;
  // Two voices a minute apart: the first at the top, the second six hundred
  // pixels down. A minute is not thirty-six, but the check is linear — an
  // offset or a wrong scale shows at ten seconds as surely as at ten minutes,
  // and one pixel is a tenth of a second.
  await writeRegions(request, [
    regionRow("r1", hash, 0, 0, 0, 0.3, 0.005),
    regionRow("r2", hash, 1, 60, 0, 0.5, 0.005),
  ]);
  await listen(page);
  await page.goto("/collage");
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");

  const { pieces } = await heard(page);
  const later = cut(pieces, 0.5);
  // Let the line run, then read where it is and what the clock says in one
  // go, off the same context the voices were handed to.
  await page.waitForTimeout(8000);
  const seen = await page.evaluate(() => {
    const space = document.querySelector('[data-testid="collage-space"]')!.getBoundingClientRect();
    const line = document.querySelector('[data-testid="collage-playhead"]')!.getBoundingClientRect();
    return { y: line.y - space.y, clock: (window as unknown as { __ctx: AudioContext }).__ctx.currentTime };
  });
  expect(seen.y, "the line did not move").toBeGreaterThan(TOP_PAD + 60);

  // Where the line says the second region begins, said in the clock's own
  // terms: the pixels still to travel, at ten a second, from the clock now.
  const lineSays = seen.clock + (TOP_PAD + 60 * PX_PER_S - seen.y) / PX_PER_S;
  // A tenth of a second is one pixel, and a frame of the line's own lag.
  expect(Math.abs(lineSays - later.when), "the line and the voice disagree about when it sounds").toBeLessThan(0.2);
  await page.getByTestId("collage-play").click();
});

test("the line can be got back to once it has gone off the screen", async ({ page, request }) => {
  test.setTimeout(120_000);
  const set = await sounds(page);
  // A piece far taller than the screen: a second of source at a hundredth
  // speed is a hundred seconds, a thousand pixels. A short window, so the
  // line leaves the bottom of it in a reasonable time.
  await page.setViewportSize({ width: 1000, height: 420 });
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 1, 0.01)]);
  await page.goto("/collage");
  await expect(page.getByTestId("collage-follow")).toHaveCount(0);

  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing", { timeout: 30_000 });
  // The line is at the top and in view, so nothing offers to find it.
  await expect(page.getByTestId("collage-follow")).toHaveCount(0);

  // Scrolled past, the line is above the window. The offer appears; it never
  // moves the canvas by itself, so it cannot fight a thumb.
  const canvas = page.getByTestId("collage-canvas");
  await canvas.evaluate((node) => {
    node.scrollTop = 700;
  });
  const follow = page.getByTestId("collage-follow");
  await expect(follow).toBeVisible();
  await expect(follow).toContainText("the playhead is above");
  const bb = (await follow.boundingBox())!;
  expect(bb.height, "a target under a thumb").toBeGreaterThanOrEqual(44);

  await follow.click();
  await expect(follow).toHaveCount(0);
  const inView = async () => {
    const c = (await canvas.boundingBox())!;
    const line = await page.getByTestId("collage-playhead").boundingBox();
    return line !== null && line.y >= c.y - 1 && line.y <= c.y + c.height + 1;
  };
  expect(await inView(), "the line was not brought back into the window").toBe(true);

  // And the other way: left alone, the line runs off the bottom and the same
  // offer brings it back.
  await canvas.evaluate((node) => {
    node.scrollTop = 0;
  });
  await expect(follow).toContainText("the playhead is below", { timeout: 90_000 });
  await follow.click();
  await expect(follow).toHaveCount(0);
  expect(await inView()).toBe(true);
  await noFigures(page);

  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "idle");
  await expect(page.getByTestId("collage-follow")).toHaveCount(0);
});

/* Balance -------------------------------------------------------------------- */

/**
 * The sixth gesture: how loud a region is.
 *
 * A mode, entered by a button with a region taken up, in which a drag
 * *across* the block moves its level. Along the block is time and stays free;
 * across it is the only thing balance can reach, and `at_s` is not in the
 * gesture's hands at all. The block's fill takes on the weight, so loudness
 * is something the eye reads off the canvas rather than a figure anywhere.
 *
 * And the bus under all of it, which saturates: fifteen voices at unity go
 * past full scale the moment they overlap, and past full scale a device cuts
 * the tops off. The tests on the curve read the table the browser was really
 * given and do the arithmetic on it, because "gentle" and "transparent" are
 * claims about a function and are checked as such.
 */

/** The bounds and the travel, mirroring `lib/collage.ts`. */
const GAIN_MAX = 2;
const GAIN_SPAN_PX = 96;

/** The canvas's own background, for compositing a region's fill against it. */
const CANVAS_BG = { r: 0x0e, g: 0x10, b: 0x13 };

/** Take a region up and turn balance on, if it is not on already. */
async function enterBalance(page: Page, regionId: string) {
  await takeUp(page, regionId);
  if ((await page.getByTestId("collage").getAttribute("data-mode")) !== "balance") {
    await page.getByTestId("collage-balance").click();
  }
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "balance");
  return region(page, regionId);
}

/** Drag sideways across a region's grab by `dx` pixels, letting go unless told not to. */
async function balanceDrag(page: Page, regionId: string, dx: number, lift = true) {
  await enterBalance(page, regionId);
  const grab = region(page, regionId).getByTestId("region-grab");
  await grab.scrollIntoViewIfNeeded();
  const box = (await grab.boundingBox())!;
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + dx, y, { steps: 8 });
  if (lift) await page.mouse.up();
  return { x, y };
}

/** What the file holds for one region. */
async function rowOnServer(page: Page, id: string): Promise<RegionRow> {
  const found = (await regionsOnServer(page)).find((r) => r.id === id);
  expect(found, `no region ${id} on the server`).toBeTruthy();
  return found!;
}

/**
 * How light a region's block is, on a screen with no colour in it.
 *
 * The fill is translucent, so what an eye sees is the fill over the canvas.
 * This composites the two and returns the luminance of the result, which is
 * exactly the quantity a greyscale screen keeps and a hue does not.
 */
async function blockLuma(page: Page, regionId: string): Promise<number> {
  const colour = await region(page, regionId).evaluate((node) => getComputedStyle(node).backgroundColor);
  const parts = colour.match(/[\d.]+/g);
  expect(parts, `could not read the fill: ${colour}`).toBeTruthy();
  const [r, g, b] = parts!.slice(0, 3).map(Number);
  const a = parts!.length > 3 ? Number(parts![3]) : 1;
  const over = (top: number, under: number) => top * a + under * (1 - a);
  const lin = (v: number) => {
    const s = v / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return (
    0.2126 * lin(over(r, CANVAS_BG.r)) +
    0.7152 * lin(over(g, CANVAS_BG.g)) +
    0.0722 * lin(over(b, CANVAS_BG.b))
  );
}

test("balance is a mode entered by a button with a region taken up: the bar says so, the handles go, and every way out returns to trim", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 4)]);
  await page.goto("/collage");
  const button = page.getByTestId("collage-balance");

  // Nothing taken up: refused. Balance is a gesture on a whole region and
  // needs one in hand, exactly as stretch needs a handle.
  await expect(button).toHaveCount(0);
  await takeUp(page, "r1");
  await expect(button).toBeEnabled();
  await expect(button).toHaveAttribute("aria-pressed", "false");

  // On: no handles at all, snip and stretch off, and the choose button gives
  // way to a plain statement of the mode.
  await button.click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "balance");
  await expect(button).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("collage-snip")).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByTestId("collage-stretch")).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByTestId("handle")).toHaveCount(0);
  await expect(page.getByTestId("collage-choose")).toHaveCount(0);
  await expect(page.getByTestId("collage-mode")).toContainText("balance is on");
  await noFigures(page);

  // The button again: trim is back, and so are both handles.
  await button.click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  await expect(page.getByTestId("handle")).toHaveCount(2);

  // The statement in the bar is the other way out.
  await button.click();
  await page.getByTestId("collage-mode").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");

  // Escape puts the region down, and with it balance.
  await button.click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "balance");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "");
  await expect(button).toHaveCount(0);

  // A tap on the blank puts it down too, and stamps nothing even with a sound
  // chosen: the bar said balance was on, not that a tap would stamp.
  await choose(page, 0);
  await enterBalance(page, "r1");
  await stampAt(page, 40, 500);
  await expect(page.getByTestId("region")).toHaveCount(1);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");

  // Snip pressed while balance is on: snip is on and balance is not. Never two.
  await enterBalance(page, "r1");
  await enterSnip(page);
  await expect(button).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "snip");
  await page.getByTestId("collage-snip").click();

  // Taking a *different* region up keeps balance on, aimed at that region.
  // Levels are set against each other, so a button tap between two voices
  // would sit in the middle of one job. Stretch ends instead; that is the
  // difference between a gesture on a handle and a gesture on a block.
  await stampAt(page, TRACK_W + 40, 200);
  await expect(page.getByTestId("region")).toHaveCount(2);
  await enterBalance(page, "r1");
  await takeUp(page, "r2");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "balance");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "r2");

  // The one change in all of that was the stamp.
  await expect(page.getByTestId("collage-undo")).toHaveAttribute("data-depth", "1");
});

test("dragging across a region moves its level and nothing else: one write, one undo step, and it survives a reload", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 3, 0, 4)]);
  await page.goto("/collage");
  const before = await regionBox(page, 0);

  const writes = await writesDuring(page, async () => {
    // A quarter of the travel across is a quarter of the range: half a unit.
    await balanceDrag(page, "r1", GAIN_SPAN_PX / 4, false);
    await expect(page.getByTestId("collage")).toHaveAttribute("data-balancing", "true");
    await expect(region(page, "r1")).toHaveAttribute("data-gain", "1.5");
    await expect(page.getByTestId("collage-mode")).toContainText("let go to keep it");
    // The block has not moved in time, nor across tracks, nor changed length.
    const during = await regionBox(page, 0);
    expect(during).toEqual(before);
    await page.mouse.up();
  });
  expect(writes, "a balance is one write, on the lift").toBe(1);

  const kept = await rowOnServer(page, "r1");
  expect(kept.gain).toBeCloseTo(1.5, 6);
  // Everything else is exactly what it was. A sideways drag is not allowed to
  // touch time, and `at_s` is the field that would show it if it did.
  expect({ ...kept, gain: 1 }).toEqual(regionRow("r1", set[0].hash, 0, 3, 0, 4));
  expect(await regionBox(page, 0)).toEqual(before);
  await noFigures(page);

  // One undo step, and it takes the level back.
  await expect(page.getByTestId("collage-undo")).toHaveAttribute("data-depth", "1");
  await page.getByTestId("collage-undo").click();
  await expect(region(page, "r1")).toHaveAttribute("data-gain", "1");
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect((await rowOnServer(page, "r1")).gain).toBe(1);

  // Again, and through a reload: the level is in the file, not in the view.
  await balanceDrag(page, "r1", GAIN_SPAN_PX / 4);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  await page.reload();
  await expect(region(page, "r1")).toHaveAttribute("data-gain", "1.5");
});

test("a balance stops at silence and at the loudest, and the bar says which wall without a number", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 4)]);
  await page.goto("/collage");

  // All the way down, and a long way past. The block stops at silence.
  await balanceDrag(page, "r1", -400, false);
  await expect(region(page, "r1")).toHaveAttribute("data-gain", "0");
  await expect(page.getByTestId("collage-mode")).toContainText("as quiet as it goes");
  await expect(page.getByTestId("collage-mode")).toHaveAttribute("data-bound", "quiet");
  await noFigures(page);
  await page.mouse.up();
  expect((await rowOnServer(page, "r1")).gain).toBe(0);

  // And all the way up from there, twice as far as the range is wide.
  await balanceDrag(page, "r1", GAIN_SPAN_PX * 2, false);
  await expect(region(page, "r1")).toHaveAttribute("data-gain", String(GAIN_MAX));
  await expect(page.getByTestId("collage-mode")).toContainText("as loud as it goes");
  await expect(page.getByTestId("collage-mode")).toHaveAttribute("data-bound", "loud");
  await noFigures(page);
  await page.mouse.up();
  expect((await rowOnServer(page, "r1")).gain).toBe(GAIN_MAX);

  // A drag that gets what it asks for says nothing about a wall.
  await balanceDrag(page, "r1", -GAIN_SPAN_PX / 2, false);
  await expect(page.getByTestId("collage-mode")).toHaveAttribute("data-bound", "");
  await expect(region(page, "r1")).toHaveAttribute("data-gain", "1");
  await page.mouse.up();
});

test("the block's weight follows its level and survives greyscale; what is taken up or sounding says so elsewhere", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  const hash = set[0].hash;
  await writeRegions(request, [
    { ...regionRow("r1", hash, 0, 0, 0, 4), gain: 0 },
    { ...regionRow("r2", hash, 1, 0, 0, 4), gain: 1 },
    { ...regionRow("r3", hash, 2, 0, 0, 4), gain: GAIN_MAX },
  ]);
  await page.goto("/collage");
  await expect(page.getByTestId("region")).toHaveCount(3);

  // The same sound, the same hue, three levels. Weight is what tells them
  // apart, and weight is lightness, which is what a screen with no colour in
  // it keeps.
  const quiet = await blockLuma(page, "r1");
  const middle = await blockLuma(page, "r2");
  const loud = await blockLuma(page, "r3");
  expect(quiet, "a silent block is not lighter than an untouched one").toBeLessThan(middle);
  expect(middle, "the loudest block is not lighter than an untouched one").toBeLessThan(loud);
  // And by enough to see: each step is more than a tenth of the whole span.
  expect(middle - quiet).toBeGreaterThan((loud - quiet) / 10);
  expect(loud - middle).toBeGreaterThan((loud - quiet) / 10);

  // The untouched level draws exactly as every block drew before balance
  // existed: half the weight, which is the fill the view has always used.
  const unity = await region(page, "r2").evaluate((node) => {
    const hue = getComputedStyle(node).getPropertyValue("--hue").trim();
    const probe = document.createElement("div");
    probe.style.backgroundColor = `hsl(${hue} 45% 30% / 0.55)`;
    document.body.appendChild(probe);
    const want = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return { got: getComputedStyle(node).backgroundColor, want };
  });
  expect(unity.got, "the untouched level no longer draws as it always did").toBe(unity.want);

  // Taken up and sounding are said outside the box. Weight is the fill, so
  // neither of them can be mistaken for a level, and a level cannot hide one.
  const before = await region(page, "r2").evaluate((node) => {
    const style = getComputedStyle(node);
    return { fill: style.backgroundColor, ring: style.boxShadow, edge: style.borderTopColor };
  });
  await takeUp(page, "r2");
  const after = await region(page, "r2").evaluate((node) => {
    const style = getComputedStyle(node);
    return { fill: style.backgroundColor, ring: style.boxShadow, edge: style.borderTopColor };
  });
  expect(after.fill, "taking a region up changed its weight").toBe(before.fill);
  expect(after.ring).not.toBe(before.ring);
  expect(after.edge).not.toBe(before.edge);
});

test("a stretched region keeps its rate through a balance, and a balanced region keeps its level through a stretch", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 5, 0, 4, 0.5)]);
  await page.goto("/collage");

  // Balance first. The rate, the cut and the moment all come through it.
  await balanceDrag(page, "r1", GAIN_SPAN_PX / 2);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  const balanced = await rowOnServer(page, "r1");
  expect(balanced.gain).toBeCloseTo(2, 6);
  expect(balanced.rate).toBe(0.5);
  expect(balanced.at_s).toBe(5);
  expect(balanced.start_s).toBe(0);
  expect(balanced.end_s).toBe(4);

  // Then stretch the same region. The level comes through that.
  await page.getByTestId("collage-mode").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  await stretchDrag(page, "r1", "end", -20);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  const stretched = await rowOnServer(page, "r1");
  expect(stretched.rate, "the stretch did nothing").not.toBe(0.5);
  expect(stretched.gain).toBeCloseTo(2, 6);
  expect(stretched.at_s).toBe(5);
});

test("the mix bus saturates: the curve is the signal below its knee, never leaves the rails, and has no corner", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 0.5, 0.05)]);
  await listen(page);
  await serveSlices(page);
  await page.goto("/collage");
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");

  // Every voice reaches the one destination, and it reaches it through the
  // shaper. There is exactly one of those: the sum is shaped once.
  const { pieces } = await heard(page);
  expect(pieces.length).toBeGreaterThan(0);
  for (const p of pieces) {
    expect(p.toDestination).toBe(true);
    expect(p.path).toEqual(["GainNode", "GainNode", "WaveShaperNode", "destination"]);
  }

  const { points, trim, oversample, built } = await bus(page);
  expect(built, "more than one shaper was built").toBe(1);
  expect(points).toBeTruthy();
  expect(trim, "the trim in front of the table is not a power of two").toBe(0.125);
  // Oversampling would run even an untouched signal through a filter pair,
  // and "the signal below the knee is the signal" would become "almost".
  expect(oversample).toBe("none");

  const table = points!;
  const last = table.length - 1;
  const headroom = 1 / trim!;
  // The node's own arithmetic: scale in, look up, interpolate. This is what
  // the browser does to a sample, done here so the claims are about the graph
  // and not about a function in a file.
  const through = (x: number): number => {
    const v = (last / 2) * (x / headroom + 1);
    if (v <= 0) return table[0];
    if (v >= last) return table[last];
    const k = Math.floor(v);
    const f = v - k;
    return (1 - f) * table[k] + f * table[k + 1];
  };

  // 1. Below the knee it does nothing at all. A single region at gain 1 whose
  //    peaks stay under this is passed through as itself.
  let knee = 0;
  for (let i = 0; i <= 4000; i += 1) {
    const x = i / 4000;
    if (Math.abs(through(x) - x) > 1e-6) break;
    knee = x;
  }
  expect(knee, "the curve bends before the level a real recording sits at").toBeGreaterThanOrEqual(0.79);
  let strayed = 0;
  let strayedAt = 0;
  for (let i = -4000; i <= 4000; i += 1) {
    const x = (i / 4000) * knee;
    const off = Math.abs(through(x) - x);
    if (off > strayed) {
      strayed = off;
      strayedAt = x;
    }
  }
  expect(strayed, `the curve moved ${strayedAt}, which is below its knee`).toBeLessThan(1e-6);

  // 2. It never leaves the rails, so the device never has to cut anything off.
  let peak = 0;
  for (let i = 0; i <= 20000; i += 1) {
    const x = -40 + (80 * i) / 20000;
    peak = Math.max(peak, Math.abs(through(x)));
  }
  expect(peak, "the bus put a sample past full scale").toBeLessThanOrEqual(1 + 1e-6);

  // 3. It is odd, and it only ever goes up: no fold, no direct current.
  let previous = -Infinity;
  let backwards: number | null = null;
  let lopsided = 0;
  for (let i = 0; i <= 20000; i += 1) {
    const x = -10 + (20 * i) / 20000;
    const y = through(x);
    if (y < previous - 1e-6 && backwards === null) backwards = x;
    lopsided = Math.max(lopsided, Math.abs(y + through(-x)));
    previous = y;
  }
  expect(backwards, `the curve turned back at ${backwards}`).toBeNull();
  expect(lopsided, "the curve is not odd").toBeLessThan(1e-5);

  // 4. And it has no corner. The two pieces meet with the same slope, which is
  //    the whole difference between drive and tearing: a hard clip's corner is
  //    what makes its harmonics fall away as slowly as they do.
  const step = 0.002;
  const slopeBelow = (through(knee) - through(knee - step)) / step;
  const slopeAbove = (through(knee + step) - through(knee)) / step;
  expect(slopeBelow).toBeCloseTo(1, 2);
  expect(slopeAbove).toBeCloseTo(1, 1);

  // 5. What it costs a sound that really does reach full scale: a fraction of
  //    a decibel on its loudest sample, and nothing anywhere else.
  expect(through(1)).toBeGreaterThan(0.95);
  expect(through(1)).toBeLessThan(1);
  // And where the drive lives: a sum of two is already all but at the rail,
  // which is what "push more in and it gets harder" means.
  expect(through(2)).toBeGreaterThan(0.99);

  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "idle");

  // A region heard on its own goes through a bus too. A single region taken
  // all the way up is past full scale by itself, and a preview that tore
  // where the piece did not would be the wrong thing to balance by.
  //
  // The tap that takes a region up also starts it playing, at the level it
  // had then, so the drag is heard on that voice as a ramp — which is the
  // whole point of balancing one region against nothing but itself.
  const ramped = (await heard(page)).ramps.length;
  await balanceDrag(page, "r1", GAIN_SPAN_PX);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(
    (await heard(page)).ramps.slice(ramped).some((to) => Math.abs(to - GAIN_MAX) < 1e-6),
    "the region being previewed was not taken up to the level the thumb left it at",
  ).toBe(true);

  // And the next preview starts there rather than ramping to it.
  await page.getByTestId("collage-mode").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  if ((await region(page, "r1").getAttribute("data-playing")) === "true") {
    await region(page, "r1").click({ position: { x: 10, y: 5 } });
    await expect(region(page, "r1")).toHaveAttribute("data-playing", "false");
  }
  const alone = (await heard(page)).pieces.length;
  await region(page, "r1").click({ position: { x: 10, y: 5 } });
  await expect.poll(async () => (await heard(page)).pieces.length).toBeGreaterThan(alone);
  const preview = (await heard(page)).pieces.slice(alone);
  for (const p of preview) {
    expect(p.gain, "the preview did not carry the region's level").toBe(GAIN_MAX);
    expect(p.path).toEqual(["GainNode", "GainNode", "WaveShaperNode", "destination"]);
  }
});

/**
 * Every sample worth asking the browser about below the knee.
 *
 * The table's own points, where the answer is a lookup and no interpolation;
 * the middle of every cell, where the interpolation is worked hardest; a dense
 * sweep that lands wherever it lands; and the handful of exact values the
 * arithmetic turns on — the knee itself, the last table point under it, and the
 * cell those two share, which is the only cell below the knee that is not a
 * straight line.
 */
function belowTheKnee(): number[] {
  const xs: number[] = [0, 0.8, -0.8, 0.5, -0.5, 1e-4, -1e-4, 1e-7, -1e-7];
  // Every table point below the knee, and the middle of every cell. The table
  // steps by 1/1024 of an input, because its range is ±8 over 2^14 cells.
  for (let k = -819; k <= 819; k += 1) {
    xs.push(k / 1024, k / 1024 + 1 / 2048);
  }
  // The cell the knee falls inside: 819/1024 is the last point that is still
  // the identity, and 820/1024 is already bent.
  for (let i = 0; i <= 64; i += 1) xs.push(819 / 1024 + (i / 64) * (0.8 - 819 / 1024));
  // A sweep with no respect for the table's grid.
  for (let i = 0; i <= 40000; i += 1) xs.push((i / 20000 - 1) * 0.8);
  // And arbitrary levels, so nothing here is a grid in disguise.
  let seed = 12345;
  for (let i = 0; i < 4000; i += 1) {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    xs.push((seed / 2147483648) * 1.6 - 0.8);
  }
  return xs.filter((x) => Math.abs(x) <= 0.8);
}

/**
 * Push samples through a graph the browser really builds and renders.
 *
 * Returns what came out of the bus and what came out of the same source with
 * nothing between it and the destination, so the difference is the bus's and
 * only the bus's. The voice's own gain is in the chain at unity, because the
 * claim is about a region at unity and that node is part of its path.
 */
async function throughTheBus(
  page: Page,
  table: number[],
  trim: number,
  oversample: string,
  xs: number[],
): Promise<{ input: number[]; plain: number[]; shaped: number[] }> {
  return page.evaluate(
    async ({ table, trim, oversample, xs }) => {
      const rate = 48000;
      // A whole number of render quanta, so nothing is decided by the tail.
      const n = Math.ceil(xs.length / 128) * 128;
      const samples = new Float32Array(n);
      samples.set(Float32Array.from(xs));
      const render = async (shaped: boolean): Promise<number[]> => {
        const ctx = new OfflineAudioContext(1, n, rate);
        const buffer = ctx.createBuffer(1, n, rate);
        buffer.copyToChannel(samples, 0);
        const source = ctx.createBufferSource();
        source.buffer = buffer;
        let out: AudioNode = source;
        if (shaped) {
          const voice = ctx.createGain();
          voice.gain.value = 1;
          const cut = ctx.createGain();
          cut.gain.value = trim;
          const shaper = ctx.createWaveShaper();
          shaper.curve = Float32Array.from(table);
          shaper.oversample = oversample as OverSampleType;
          source.connect(voice);
          voice.connect(cut);
          cut.connect(shaper);
          out = shaper;
        }
        out.connect(ctx.destination);
        source.start(0);
        const rendered = await ctx.startRendering();
        return Array.from(rendered.getChannelData(0).subarray(0, xs.length));
      };
      // The samples as the buffer really holds them: a level named in this
      // test is a double, and what a browser plays is always a float.
      const input = Array.from(samples.subarray(0, xs.length));
      return { input, plain: await render(false), shaped: await render(true) };
    },
    { table, trim, oversample, xs },
  );
}

/**
 * How far a sample may move below the knee, and why it moves at all.
 *
 * The curve is the identity there and the table's points are exact, so the
 * arithmetic on paper gives the sample back untouched. The browser's does not
 * quite: a `WaveShaperNode` finds its place in the table by working out
 * `(x + 1)` in **single** precision, and adding one to a small number in single
 * precision throws away everything below one part in 2^24 of that one. The
 * trim in front of the table is 1/8, so in the signal's own terms every sample
 * lands on a grid whose step is `8 · 2^-23` above nothing and `8 · 2^-24`
 * below it — the two sides of one, where a float's step changes — and no
 * sample moves by more than half the wider of those, which is this number.
 *
 * Chromium and WebKit both do it, and the Web Audio specification does not say
 * they may not: it writes the lookup down as arithmetic and names no precision.
 * So this is a property of every table-based bus in a browser, not of this one,
 * and it cannot be tuned away — a smaller table range would make the grid
 * finer and the clamp past the range harder, and no range makes it vanish,
 * because a float's precision is relative and the table's range is absolute.
 *
 * What it means in the ear: a distortion floor about 126 dB below full scale,
 * flat, whatever the signal is doing. Two bits coarser than a 24-bit
 * destination and thirty decibels under the noise floor of any real field
 * recording. Inaudible — but not nothing, which is what "bit-exact" would
 * mean, and the difference matters because it is the kind of claim that gets
 * repeated.
 */
const BUS_BOUND = 8 * 2 ** -24;

test("below the knee the bus is transparent to one part in two million of full scale, and no further", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 0.5, 0.05)]);
  await listen(page);
  await serveSlices(page);
  await page.goto("/collage");
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  const { points, trim, oversample } = await bus(page);
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "idle");
  expect(points).toBeTruthy();
  expect(trim).toBe(0.125);
  expect(oversample).toBe("none");

  // The table the view really handed the node, the trim really in front of it,
  // and a graph the browser really renders. Nothing here models the node,
  // which is the whole point: the arithmetic inside it is not the arithmetic
  // this file would do, and that is exactly what the old claim missed.
  const xs = belowTheKnee();
  const { input, plain, shaped } = await throughTheBus(page, points!, trim!, oversample!, xs);

  // The source on its own is the signal, so anything the comparison finds
  // belongs to the bus rather than to the way the samples got in.
  let sourceMoved = 0;
  for (let i = 0; i < input.length; i += 1) sourceMoved = Math.max(sourceMoved, Math.abs(plain[i] - input[i]));
  expect(sourceMoved, "the source did not deliver the samples it was given").toBe(0);

  let worst = 0;
  let worstAt = 0;
  for (let i = 0; i < input.length; i += 1) {
    const off = Math.abs(shaped[i] - plain[i]);
    if (off > worst) {
      worst = off;
      worstAt = input[i];
    }
  }
  expect(
    worst,
    `a sample moved by ${worst} at ${worstAt}, which is further than the node's own rounding can account for`,
  ).toBeLessThanOrEqual(BUS_BOUND);

  // It is a grid, not a drift: whatever the level, a sample lands on the
  // nearest point of the same grid and never on the far side of nothing. A
  // sample quieter than half a step does land on nothing — the grid is
  // absolute, so it has a bottom — and that bottom is 132 dB down.
  let flipped: number | null = null;
  for (let i = 0; i < input.length; i += 1) {
    if (shaped[i] * input[i] < 0) flipped = input[i];
  }
  expect(flipped, `the bus flipped the sign of ${flipped}`).toBeNull();

  // Digital silence stays digital silence. A region taken all the way down
  // must leave nothing behind on the bus at all.
  const quiet = shaped[input.indexOf(0)];
  expect(Object.is(quiet, 0) || Object.is(quiet, -0), "the bus put something under silence").toBe(true);

  // And where the bus really is exact: every point the table names. Those are
  // this file's own arithmetic — powers of two all the way down — and they do
  // come back untouched, which is what makes the rest of it a browser's
  // rounding rather than a mistake in the curve.
  const grid = Array.from({ length: 1639 }, (_, i) => (i - 819) / 1024);
  const onGrid = await throughTheBus(page, points!, trim!, oversample!, grid);
  let moved = 0;
  let movedAt = 0;
  for (let i = 0; i < grid.length; i += 1) {
    if (Object.is(onGrid.shaped[i], onGrid.plain[i])) continue;
    moved += 1;
    movedAt = grid[i];
  }
  expect(moved, `${moved} of the table's own points came back changed, the last at ${movedAt}`).toBe(0);
});

test("oversampling would end the identity, which is why the bus does not ask for it", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 0.5, 0.05)]);
  await listen(page);
  await serveSlices(page);
  await page.goto("/collage");
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  const { points, trim } = await bus(page);
  await page.getByTestId("collage-play").click();

  // The same table, the same trim, the same samples: the only change is the
  // filter pair oversampling puts around the lookup. If this passed unchanged
  // too, `oversample: "none"` would be a preference rather than a reason.
  const xs = belowTheKnee();
  const { plain, shaped } = await throughTheBus(page, points!, trim!, "2x", xs);
  let differing = 0;
  for (let i = 0; i < plain.length; i += 1) if (!Object.is(shaped[i], plain[i])) differing += 1;
  expect(differing, "oversampling left a quiet signal alone, so the reason given for not using it is not the reason").toBeGreaterThan(0);
});

test("the knee has no corner in the table itself: the step never jumps where the two pieces meet", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 0.5, 0.05)]);
  await listen(page);
  await serveSlices(page);
  await page.goto("/collage");
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  const { points } = await bus(page);
  await page.getByTestId("collage-play").click();
  const table = points!;

  // The node draws straight lines between the points, so the slope of the
  // curve it really makes is the difference between neighbours. A corner is a
  // jump in that difference from one cell to the next. Over the whole table
  // the largest jump must be a rounding error, not a step: a hard clip at the
  // same place would jump by a whole cell's worth in one go.
  const steps: number[] = [];
  for (let i = 0; i < table.length - 1; i += 1) steps.push(table[i + 1] - table[i]);
  const cell = 1 / 1024;
  let jump = 0;
  let jumpAt = 0;
  for (let i = 0; i < steps.length - 1; i += 1) {
    const change = Math.abs(steps[i + 1] - steps[i]);
    if (change > jump) {
      jump = change;
      jumpAt = (i + 1) / 1024 - 8;
    }
  }
  expect(jump / cell, `the slope jumped by ${jump / cell} of a cell at ${jumpAt}`).toBeLessThan(0.01);

  // And the slope really is one on the way in to the knee and one on the way
  // out of it, read off the table rather than off a model of it.
  const at = (x: number) => table[Math.round((x + 8) * 1024)];
  const below = (at(0.8) - at(0.8 - cell)) / cell;
  const above = (at(0.8 + cell) - at(0.8)) / cell;
  expect(below).toBeCloseTo(1, 6);
  expect(above).toBeCloseTo(1, 3);
});

test("fifteen voices at the loudest balance allows, all on top of each other, reach the destination hard and not torn", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 0.5, 0.05)]);
  await listen(page);
  await serveSlices(page);
  await page.goto("/collage");
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  const { points, trim } = await bus(page);
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "idle");

  // The worst mix this view can be made to produce: every region cut from the
  // same source, stamped at the same moment, every one of them taken all the
  // way up. Fifteen voices at two, perfectly correlated, is a sum of thirty.
  const result = await page.evaluate(
    async ({ table, trim }) => {
      const rate = 48000;
      const n = 4096;
      const tone = new Float32Array(n);
      // Full scale, and a shape with both a smooth part and a hard edge, so
      // the bus is asked about a peak and about a jump.
      for (let i = 0; i < n; i += 1) {
        tone[i] = i < n / 2 ? Math.sin((2 * Math.PI * 220 * i) / rate) : i % 2 ? 1 : -1;
      }
      const build = async (shaped: boolean, voices: number, level: number): Promise<Float32Array> => {
        const ctx = new OfflineAudioContext(1, n, rate);
        const buffer = ctx.createBuffer(1, n, rate);
        buffer.copyToChannel(tone, 0);
        let out: AudioNode;
        if (shaped) {
          const cut = ctx.createGain();
          cut.gain.value = trim;
          const shaper = ctx.createWaveShaper();
          shaper.curve = Float32Array.from(table);
          shaper.oversample = "none";
          cut.connect(shaper);
          shaper.connect(ctx.destination);
          out = cut;
        } else {
          out = ctx.destination;
        }
        for (let voice = 0; voice < voices; voice += 1) {
          const source = ctx.createBufferSource();
          source.buffer = buffer;
          const gain = ctx.createGain();
          gain.gain.value = level;
          source.connect(gain);
          gain.connect(out);
          source.start(0);
        }
        return (await ctx.startRendering()).getChannelData(0);
      };
      // The longest stretch a signal holds one value near its own top. A
      // sine has one there already, at its turning point, so what matters is
      // how much longer the bus makes it.
      const flatnessOf = (wave: Float32Array): number => {
        let top = 0;
        for (let i = 0; i < n; i += 1) top = Math.max(top, Math.abs(wave[i]));
        let longest = 0;
        let run = 0;
        for (let i = 1; i < n; i += 1) {
          if (wave[i] === wave[i - 1] && Math.abs(wave[i]) > 0.9 * top) {
            run += 1;
            longest = Math.max(longest, run);
          } else {
            run = 0;
          }
        }
        return longest;
      };
      const measure = (plain: Float32Array, shaped: Float32Array) => {
        let plainPeak = 0;
        let peak = 0;
        let overOne = 0;
        let sharpened = 0;
        const flat = flatnessOf(shaped);
        const wasFlat = flatnessOf(plain);
        for (let i = 0; i < n; i += 1) {
          plainPeak = Math.max(plainPeak, Math.abs(plain[i]));
          peak = Math.max(peak, Math.abs(shaped[i]));
          if (Math.abs(shaped[i]) > 1) overOne += 1;
          // The bus never makes an edge that was not already in the sum. The
          // curve's steepest slope is one, so no step out may be bigger than
          // the step in — tearing is a jump the bus *added*, and there is none.
          if (i > 0) {
            const stepIn = Math.abs(plain[i] - plain[i - 1]);
            const stepOut = Math.abs(shaped[i] - shaped[i - 1]);
            if (stepOut > stepIn + 1e-6) sharpened += 1;
          }
        }
        return { plainPeak, peak, overOne, flat, wasFlat, sharpened };
      };

      const twoPlain = await build(false, 2, 1);
      const two = measure(twoPlain, await build(true, 2, 1));
      const hardPlain = await build(false, 15, 2);
      const hard = measure(hardPlain, await build(true, 15, 2));

      // Where the curve stops telling one level from another: the first input
      // above the knee whose neighbours in the table come back as the same
      // float. Past it the bus is a ceiling rather than a drive, and how far
      // past the knee that is is the whole of what "gentle" means here.
      let ceiling = Infinity;
      for (let j = 8192; j < table.length - 1; j += 1) {
        if (table[j + 1] === table[j]) {
          ceiling = j / 1024 - 8;
          break;
        }
      }
      return { two, hard, ceiling };
    },
    { table: points!, trim: trim! },
  );

  // Two regions at unity, on top of each other: a sum of two, which is the
  // everyday overlap this view makes and the case the bus exists for. Past
  // full scale, and it comes back inside without flattening a single sample.
  expect(result.two.plainPeak).toBeGreaterThan(1.9);
  expect(result.two.overOne, "an ordinary overlap left the rails").toBe(0);
  // At the very top of that sum the curve's slope is about one in forty
  // thousand, so the two samples either side of the peak come back as one
  // float. That is a tie at a turning point, not a plateau, and it is the
  // only one: everything else in the wave still moves.
  expect(
    result.two.flat,
    `an ordinary overlap came out with a plateau ${result.two.flat} samples long, against ${result.two.wasFlat} going in`,
  ).toBeLessThanOrEqual(1);
  expect(result.two.sharpened, "the bus made an edge sharper than the one it was given").toBe(0);

  // And this is why: the curve runs out of room fast. Above this input two
  // neighbouring points of the table are the same float, so the bus cannot
  // tell those levels apart at all. It is a knee at 0.8 and a ceiling not far
  // above — a limiter more than a drive — which is worth knowing when the
  // range a thumb can ask for goes to two.
  expect(result.ceiling, "the curve is a ceiling well below the loudest a region may be").toBeLessThan(2);
  expect(result.ceiling, "the curve stopped moving before the knee did").toBeGreaterThan(0.8);

  // And the worst mix the gesture allows: every region cut from one source,
  // stamped at one moment, every one of them taken all the way up. Thirty
  // times over the rail, which a device would cut off square.
  expect(result.hard.plainPeak, "the worst mix is no longer past full scale, so this proves nothing").toBeGreaterThan(20);
  expect(result.hard.overOne, `${result.hard.overOne} samples left the rails`).toBe(0);
  expect(result.hard.peak).toBeLessThanOrEqual(1);
  expect(result.hard.sharpened, "the bus made an edge sharper than the one it was given").toBe(0);
  // It does sit at the rail there, and for a long time: thirty into a curve
  // that is within a millionth of one by eight is a square wave, and that is
  // what "push more in and it gets harder" means at the end of the range.
  // Nothing on the surface says so — there is no meter, by design — so the
  // only way to know is that it sounds like that.
  expect(
    result.hard.flat,
    "the worst mix the gesture allows no longer sits at the rail",
  ).toBeGreaterThan(result.hard.wasFlat);
});

test("a level another tool wrote past the ceiling may come down and not go further up", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  // The model allows any level at or above nothing, and nothing in this view
  // writes one above two. A later stage might, and a gesture must not undo
  // that decision the moment a thumb lands on the block.
  await writeRegions(request, [{ ...regionRow("r1", set[0].hash, 0, 0, 0, 4), gain: 5 }]);
  await page.goto("/collage");
  await expect(region(page, "r1")).toHaveAttribute("data-gain", "5");

  // Up: it stays where it was, and the bar says it is as loud as it goes.
  await balanceDrag(page, "r1", GAIN_SPAN_PX, false);
  await expect(region(page, "r1")).toHaveAttribute("data-gain", "5");
  await expect(page.getByTestId("collage-mode")).toHaveAttribute("data-bound", "loud");
  await page.mouse.up();
  expect((await rowOnServer(page, "r1")).gain).toBe(5);

  // Down: it moves, and the range is the one the drag's travel says.
  await balanceDrag(page, "r1", -GAIN_SPAN_PX / 2);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect((await rowOnServer(page, "r1")).gain).toBe(4);
  // And the block is drawn at the top of the weight it can show, not past it.
  await expect(region(page, "r1")).toHaveAttribute("data-gain", "4");
});

test("balancing a region while the piece plays moves its level under the ear instead of silencing it", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  const hash = set[0].hash;
  await writeRegions(request, [
    regionRow("r1", hash, 0, 0, 0, 0.6, 0.05),
    regionRow("r2", hash, 1, 0, 0, 0.8, 0.05),
  ]);
  await listen(page);
  await serveSlices(page);
  await page.goto("/collage");
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  const scheduled = (await heard(page)).pieces.length;
  const stopped = (await heard(page)).stops.length;

  // Balance one of them while both sound. Nothing is rescheduled and nothing
  // is stopped: the gain that voice already runs through is ramped.
  await balanceDrag(page, "r1", -GAIN_SPAN_PX / 4);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  const after = await heard(page);
  expect(after.pieces.length, "a balance rescheduled the piece").toBe(scheduled);
  expect(after.stops.length, "a balance stopped a voice").toBe(stopped);
  expect(after.ramps.some((to) => Math.abs(to - 0.5) < 1e-6), "no gain was ramped to the new level").toBe(true);
  // And nothing says the region went quiet, because it did not.
  await expect(page.getByTestId("collage-hint")).toHaveCount(0);

  // A change to the *material* still takes its region out of the pass. The
  // two rules sit side by side, and this is the line between them.
  await page.getByTestId("collage-mode").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  await drag(page, "r2", "end", -20);
  await expect(page.getByTestId("collage-hint")).toContainText("gone quiet");
  expect((await heard(page)).stops.length).toBeGreaterThan(stopped);

  await page.getByTestId("collage-play").click();
});

test("undoing a balance while the piece plays takes the level back under the ear, and undoing a cut still goes quiet", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  const hash = set[0].hash;
  await writeRegions(request, [
    regionRow("r1", hash, 0, 0, 0, 0.6, 0.05),
    regionRow("r2", hash, 1, 0, 0, 0.8, 0.05),
  ]);
  await listen(page);
  await serveSlices(page);
  await page.goto("/collage");

  // Balance one region, then play, then undo the balance under the ear. Undo
  // is a change like any other, so it must follow the same line: a level goes
  // back by ramping, and the piece carries on.
  await balanceDrag(page, "r1", -GAIN_SPAN_PX / 4);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  const scheduled = (await heard(page)).pieces.length;
  const stopped = (await heard(page)).stops.length;

  await page.getByTestId("collage-undo").click();
  await expect(region(page, "r1")).toHaveAttribute("data-gain", "1");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  const back = await heard(page);
  expect(back.pieces.length, "an undone balance rescheduled the piece").toBe(scheduled);
  expect(back.stops.length, "an undone balance stopped a voice").toBe(stopped);
  expect(back.ramps.some((to) => Math.abs(to - 1) < 1e-6), "the level was not taken back under the ear").toBe(true);
  await expect(page.getByTestId("collage-hint")).toHaveCount(0);

  // And an undo that puts material back is still a change to the material:
  // that region leaves the pass and the bar says so, exactly as the edit did.
  await page.getByTestId("collage-mode").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  await drag(page, "r2", "end", -20);
  await expect(page.getByTestId("collage-hint")).toContainText("gone quiet");
  const cut = (await heard(page)).stops.length;
  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("collage-hint")).toContainText("gone quiet");
  expect((await heard(page)).stops.length).toBeGreaterThanOrEqual(cut);
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "idle");
});

test("fifteen voices at the loudest balance allows still sum through one shaper into one destination", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  const hash = set[0].hash;
  // Fifteen regions, every one of them at the top of the range, all sounding
  // over each other from the first moment. This is the case the bus exists
  // for: summed plainly it is thirty times full scale.
  const many = Array.from({ length: 15 }, (_, i) => ({
    ...regionRow(`r${i + 1}`, hash, i, 0, 0, 0.6, 0.05),
    gain: GAIN_MAX,
  }));
  await writeRegions(request, many);
  await listen(page);
  await serveSlices(page);
  await page.goto("/collage");
  await expect(page.getByTestId("region")).toHaveCount(15);

  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  await expect(page.getByTestId("collage-play-error")).toHaveCount(0);

  const { pieces } = await heard(page);
  expect(pieces).toHaveLength(15);
  expect(new Set(pieces.map((p) => p.ctx)).size).toBe(1);
  for (const p of pieces) {
    expect(p.gain).toBe(GAIN_MAX);
    expect(p.toDestination).toBe(true);
    expect(p.path).toEqual(["GainNode", "GainNode", "WaveShaperNode", "destination"]);
  }
  // And they really overlap: all fifteen sounding at once is the sum the bus
  // has to hold.
  const spans = pieces.map(sounding);
  const at = Math.max(...spans.map((s) => s.from)) + 0.01;
  expect(spans.filter((s) => s.from <= at && s.to > at)).toHaveLength(15);
  expect((await bus(page)).built, "one shaper for fifteen voices").toBe(1);

  await page.getByTestId("collage-play").click();
});

test("a level is reached by the keyboard as well, and the block's weight follows", async ({ page, request }) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 4)]);
  await page.goto("/collage");
  await enterBalance(page, "r1");

  await region(page, "r1").focus();
  await page.keyboard.press("ArrowRight");
  await expect(region(page, "r1")).toHaveAttribute("data-gain", "1.1");
  await page.keyboard.press("Shift+ArrowLeft");
  await expect(region(page, "r1")).toHaveAttribute("data-gain", "0.7");
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect((await rowOnServer(page, "r1")).gain).toBeCloseTo(0.7, 6);
  await noFigures(page);

  // Two steps, two undo steps.
  await expect(page.getByTestId("collage-undo")).toHaveAttribute("data-depth", "2");
});

/* Move, copy, and removing a track ------------------------------------------ */

/**
 * Carry a region by its body: take it up, then a pointer down on its grab,
 * moved `dx` across and `dy` down, and lifted unless told not to.
 *
 * The grab is the body's hit area, and the body carries the region only once
 * that region is in hand — every other body is canvas, and canvas scrolls.
 * There is still no mode: what makes this a move rather than the tap that
 * plays the region is that the pointer travels.
 */
async function carry(page: Page, regionId: string, dx: number, dy: number, lift = true) {
  await takeUp(page, regionId);
  const grab = region(page, regionId).getByTestId("region-grab");
  await grab.scrollIntoViewIfNeeded();
  const box = (await grab.boundingBox())!;
  const x = box.x + box.width / 2;
  const y = box.y + Math.min(box.height / 2, 24);
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + dx, y + dy, { steps: 8 });
  if (lift) await page.mouse.up();
  return { x: x + dx, y: y + dy };
}

/** Press the track button, keep it pressed for `ms`, and let go. */
async function holdTrack(page: Page, ms: number) {
  const box = (await page.getByTestId("collage-track").boundingBox())!;
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.waitForTimeout(ms);
  await page.mouse.up();
}

/** The stored region with this id. */
function stored(rows: RegionRow[], id: string): RegionRow {
  const found = rows.find((r) => r.id === id);
  expect(found, `no region ${id} in the file`).toBeTruthy();
  return found!;
}

test("dragging a region's body moves it down its track: one write, one undo step, and the material is untouched", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  // A second of source at a twentieth speed: twenty canvas seconds, two
  // hundred pixels, which is a body to take hold of.
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 5, 0.1, 0.9, 0.05)]);
  await page.goto("/collage");
  await expect(page.getByTestId("region")).toHaveCount(1);

  // Taken up, which is to say sounding on its own. Moving it changes nothing
  // about the material, so the slice being heard is still the right one and
  // it plays on under the thumb.
  await takeUp(page, "r1");
  await expect(region(page, "r1")).toHaveAttribute("data-playing", "true");

  const writes = await writesDuring(page, async () => {
    await carry(page, "r1", 0, 100);
  });
  expect(writes).toBe(1);
  await expect(region(page, "r1")).toHaveAttribute("data-playing", "true");

  const after = stored(await regionsOnServer(page), "r1");
  // A hundred pixels down is ten collage seconds.
  expect(after.at_s).toBeCloseTo(15, 3);
  expect(after.track).toBe(0);
  // Nothing about the material moved: not the cut, not the rate, not the level.
  expect(after.start_s).toBeCloseTo(0.1, 6);
  expect(after.end_s).toBeCloseTo(0.9, 6);
  expect(after.rate).toBeCloseTo(0.05, 6);
  expect(after.gain).toBeCloseTo(1, 6);
  await noFigures(page);

  // One change, one step back.
  await expect(page.getByTestId("collage-undo")).toHaveAttribute("data-depth", "1");
  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(stored(await regionsOnServer(page), "r1").at_s).toBeCloseTo(5, 3);
});

test("a body dragged across changes track, and past the last track makes one more and never two", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [
    regionRow("r1", set[0].hash, 0, 0, 0, 1, 0.05),
    regionRow("r2", set[0].hash, 0, 30, 0, 1, 0.05),
  ]);
  await page.goto("/collage");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-tracks", "1");

  // A whole column across, and a new track comes into being beside the last
  // one, exactly as a stamp beside it would.
  await carry(page, "r1", TRACK_W, 0);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(stored(await regionsOnServer(page), "r1").track).toBe(1);
  expect(stored(await regionsOnServer(page), "r1").at_s).toBeCloseTo(0, 3);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-tracks", "2");

  // Another column across, and there is nowhere further to go: one new track
  // per gesture, never two, so a thumb carried off the edge cannot open a
  // run of empty columns.
  await carry(page, "r1", TRACK_W, 0);
  await page.waitForTimeout(200);
  expect(stored(await regionsOnServer(page), "r1").track).toBe(1);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-tracks", "2");
});

test("a move onto a neighbour settles after it, and a move above the first moment stops there; the bar says which, without a number", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  // Two twenty-second boxes on one track: the first at the top, the second
  // from thirty to fifty.
  await writeRegions(request, [
    regionRow("r1", set[0].hash, 0, 0, 0, 1, 0.05),
    regionRow("r2", set[0].hash, 0, 30, 0, 1, 0.05),
  ]);
  await page.goto("/collage");

  // Carried down onto its neighbour: it comes to rest after it, which is the
  // slide a stamp has always made, and the bar says so while the thumb holds.
  await carry(page, "r1", 0, 350, false);
  await expect(page.getByTestId("collage-mode")).toHaveAttribute("data-bound", "settled");
  await expect(page.getByTestId("collage-mode")).toContainText("there is something there");
  await noFigures(page);
  await page.mouse.up();
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(stored(await regionsOnServer(page), "r1").at_s).toBeCloseTo(50, 3);
  expect(stored(await regionsOnServer(page), "r2").at_s).toBeCloseTo(30, 3);

  // And carried back up past the first moment: it stops at the top.
  await carry(page, "r1", 0, -900, false);
  await expect(page.getByTestId("collage-mode")).toContainText("first moment");
  await page.mouse.up();
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(stored(await regionsOnServer(page), "r1").at_s).toBeCloseTo(0, 3);
});

test("a drag that is really a tap plays the region and moves nothing, in hand or not", async ({ page, request }) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 5, 0, 1, 0.05)]);
  await page.goto("/collage");

  let writes = 0;
  page.on("request", (r) => {
    if (r.method() === "PUT" && r.url().includes("/collage")) writes += 1;
  });

  // A thumb on a region not yet in hand. Four pixels is inside a tap's slop,
  // and the body of a region not in hand is canvas anyway: it plays, takes
  // itself up, and nothing about the arrangement is written.
  const grab = region(page, "r1").getByTestId("region-grab");
  await grab.scrollIntoViewIfNeeded();
  const first = (await grab.boundingBox())!;
  await page.mouse.move(first.x + first.width / 2, first.y + 24);
  await page.mouse.down();
  await page.mouse.move(first.x + first.width / 2 + 2, first.y + 28, { steps: 4 });
  await page.mouse.up();
  await expect(region(page, "r1")).toHaveAttribute("data-playing", "true");
  await expect(region(page, "r1")).toHaveAttribute("data-selected", "true");
  await page.waitForTimeout(300);
  expect(writes).toBe(0);
  expect(stored(await regionsOnServer(page), "r1").at_s).toBeCloseTo(5, 3);
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);

  // And the same thumb on the same region now that it is in hand, where the
  // body does carry it. Inside the slop it still does not: nothing moves and
  // nothing is written.
  const held = (await grab.boundingBox())!;
  await page.mouse.move(held.x + held.width / 2, held.y + 24);
  await page.mouse.down();
  await page.mouse.move(held.x + held.width / 2 + 2, held.y + 28, { steps: 4 });
  await expect(page.getByTestId("collage")).toHaveAttribute("data-moving", "");
  await page.mouse.up();
  await page.waitForTimeout(300);
  expect(writes).toBe(0);
  expect(stored(await regionsOnServer(page), "r1").at_s).toBeCloseTo(5, 3);
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);
});

test("a move that empties a track leaves the column blank and moves nothing else", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [
    regionRow("r1", set[0].hash, 0, 0, 0, 1, 0.05),
    regionRow("r2", set[0].hash, 1, 0, 0, 1, 0.05),
    regionRow("r3", set[0].hash, 2, 0, 0, 1, 0.05),
  ]);
  await page.goto("/collage");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-tracks", "3");

  // The middle one is carried onto the first track, where it settles after
  // what is already there.
  await carry(page, "r2", -TRACK_W, 0);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  const rows = await regionsOnServer(page);
  expect(stored(rows, "r2").track).toBe(0);
  expect(stored(rows, "r2").at_s).toBeCloseTo(20, 3);
  // The track it left is blank and stays where it was. Nothing is drawn per
  // track, so an emptied one is canvas and not an empty lane, and the region
  // beyond it is not dragged sideways by a gesture that was not about it.
  expect(rows.filter((r) => r.track === 1)).toHaveLength(0);
  expect(stored(rows, "r3").track).toBe(2);
  expect(stored(rows, "r3").at_s).toBeCloseTo(0, 3);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-tracks", "3");
});

test("switching mode under a moving thumb writes nothing, and Escape puts the region back", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 5, 0, 1, 0.05)]);
  await page.goto("/collage");

  let writes = 0;
  page.on("request", (r) => {
    if (r.method() === "PUT" && r.url().includes("/collage")) writes += 1;
  });
  await carry(page, "r1", 0, 120, false);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-moving", "r1");
  // A mouse has no second finger, so the press on the other button is the
  // button's own click event: the drag's pointer is still captured.
  await page.getByTestId("collage-snip").dispatchEvent("click");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-moving", "");
  await page.mouse.up();
  await page.waitForTimeout(250);
  expect(writes).toBe(0);
  expect(stored(await regionsOnServer(page), "r1").at_s).toBeCloseTo(5, 3);

  await page.getByTestId("collage-snip").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");
  await carry(page, "r1", 0, 120, false);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-moving", "r1");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-moving", "");
  await page.mouse.up();
  await page.waitForTimeout(250);
  expect(writes).toBe(0);
  expect(stored(await regionsOnServer(page), "r1").at_s).toBeCloseTo(5, 3);
});

test("copy is a stamp: the copy keeps the cut, the rate, the level and the fades, and gets an id of its own", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [
    { ...regionRow("r1", set[0].hash, 0, 0, 0.2, 0.8, 0.05), gain: 0.4, fade_in_s: 0.01, fade_out_s: 0.02 },
  ]);
  await page.goto("/collage");

  // With nothing taken up there is nothing to copy, and the button says so
  // by refusing.
  await expect(page.getByTestId("collage-copy")).toHaveCount(0);
  await takeUp(page, "r1");
  await expect(page.getByTestId("collage-copy")).toBeEnabled();

  await page.getByTestId("collage-copy").click();
  // A paste is armed, and the bar says so where the chosen sound is named.
  await expect(page.getByTestId("collage-paste")).toBeVisible();
  await expect(page.getByTestId("collage-choose")).toHaveCount(0);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-clipboard", "r1");
  await noFigures(page);
  // Nothing has been written by copying: what changed is what the next tap does.
  expect(await regionsOnServer(page)).toHaveLength(1);

  const writes = await writesDuring(page, async () => {
    await stampAt(page, 40, TOP_PAD + 400);
  });
  expect(writes).toBe(1);
  const rows = await regionsOnServer(page);
  expect(rows).toHaveLength(2);
  const copy = stored(rows, "r2");
  const original = stored(rows, "r1");
  expect(copy.hash).toBe(original.hash);
  expect(copy.start_s).toBeCloseTo(original.start_s, 6);
  expect(copy.end_s).toBeCloseTo(original.end_s, 6);
  expect(copy.rate).toBeCloseTo(original.rate, 6);
  expect(copy.gain).toBeCloseTo(original.gain, 6);
  expect(copy.fade_in_s).toBeCloseTo(0.01, 6);
  expect(copy.fade_out_s).toBeCloseTo(0.02, 6);
  expect(copy.at_s).toBeCloseTo(40, 1);
  expect(copy.id).not.toBe(original.id);
  // The original did not move.
  expect(original.at_s).toBeCloseTo(0, 3);

  // One tap is what a copy is for: the clipboard is empty again and the bar
  // is back to offering a sound.
  await expect(page.getByTestId("collage-paste")).toHaveCount(0);
  await expect(page.getByTestId("collage-choose")).toBeVisible();

  // And one undo takes the copy back.
  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(await regionsOnServer(page)).toHaveLength(1);
});

test("an armed paste can be cancelled, and a copy pasted onto an occupied spot settles after it", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  // Two twenty-second boxes on one track, with ten seconds of room between.
  await writeRegions(request, [
    regionRow("r1", set[0].hash, 0, 0, 0, 1, 0.05),
    regionRow("r2", set[0].hash, 0, 30, 0, 1, 0.05),
  ]);
  await page.goto("/collage");
  await takeUp(page, "r1");
  await page.getByTestId("collage-copy").click();
  await expect(page.getByTestId("collage-paste")).toBeVisible();

  // Cancelled: the bar goes back to offering a sound, and the blank is blank
  // again. The first tap on it puts the region down; the second, with nothing
  // chosen and nothing copied, offers the picker rather than a region.
  await page.getByTestId("collage-paste").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-clipboard", "");
  await expect(page.getByTestId("collage-choose")).toBeVisible();
  await stampAt(page, 40, TOP_PAD + 600);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-selected", "");
  await stampAt(page, 40, TOP_PAD + 600);
  await expect(page.getByTestId("collage-picker")).toBeVisible();
  await page.getByTestId("picker-close").click();
  expect(await regionsOnServer(page)).toHaveLength(2);

  // Armed again, and put down in the gap between the two, where it is too
  // long to fit: it slides past the one below it, the way a stamp does.
  await takeUp(page, "r1");
  await page.getByTestId("collage-copy").click();
  await stampAt(page, 40, TOP_PAD + 250);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  const rows = await regionsOnServer(page);
  expect(rows).toHaveLength(3);
  const copy = stored(rows, "r3");
  expect(copy.track).toBe(0);
  expect(copy.at_s).toBeCloseTo(50, 3);
});

test("a copy outlives the region it came from: the track goes, and the copy still lands", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [
    regionRow("r1", set[0].hash, 0, 0, 0.3, 0.7, 0.05),
    regionRow("r2", set[0].hash, 1, 0, 0, 1, 0.05),
  ]);
  await page.goto("/collage");
  await takeUp(page, "r1");
  await page.getByTestId("collage-copy").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-clipboard", "r1");

  // The region the copy was taken from goes with its track. The clipboard is
  // a snapshot, not a pointer at a region, so it is still a copy of what was
  // taken and the paste still lands.
  await holdTrack(page, 800);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  let rows = await regionsOnServer(page);
  expect(rows).toHaveLength(1);
  expect(stored(rows, "r2").track).toBe(0);

  await expect(page.getByTestId("collage-paste")).toBeVisible();
  await stampAt(page, TRACK_W + 40, TOP_PAD + 300);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  rows = await regionsOnServer(page);
  expect(rows).toHaveLength(2);
  const copy = rows.find((r) => r.id !== "r2")!;
  expect(copy.start_s).toBeCloseTo(0.3, 6);
  expect(copy.end_s).toBeCloseTo(0.7, 6);
  expect(copy.track).toBe(1);
});

test("removing a track is a hold: let go early and nothing goes; held, the track and everything on it goes and the tracks beyond it close up", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [
    regionRow("r1", set[0].hash, 0, 0, 0, 1, 0.05),
    regionRow("r2", set[0].hash, 1, 0, 0, 1, 0.05),
    regionRow("r3", set[0].hash, 1, 30, 0, 1, 0.05),
    regionRow("r4", set[0].hash, 2, 0, 0, 1, 0.05),
  ]);
  await page.goto("/collage");
  await expect(page.getByTestId("collage-track")).toHaveCount(0);
  await takeUp(page, "r2");
  await expect(page.getByTestId("collage-track")).toBeEnabled();

  // Let go before the wait is over and nothing goes. The bar says what would
  // have, because the amber that said it is gone with the press.
  await holdTrack(page, 120);
  await expect(page.getByTestId("collage-hint")).toContainText("press its button and hold it");
  await page.waitForTimeout(250);
  expect(await regionsOnServer(page)).toHaveLength(4);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-doomed", "");

  // Pressed and kept pressed: the column and both regions on it are drawn in
  // amber, and the statement says what letting go will do.
  const button = (await page.getByTestId("collage-track").boundingBox())!;
  await page.mouse.move(button.x + button.width / 2, button.y + button.height / 2);
  await page.mouse.down();
  await expect(page.getByTestId("collage-doomed")).toHaveAttribute("data-track", "1");
  await expect(page.getByTestId("region-doomed")).toHaveCount(2);
  await expect(page.getByTestId("collage-mode")).toContainText("keep holding");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-doomed", "armed", { timeout: 4000 });
  await expect(page.getByTestId("collage-mode")).toContainText("let go to remove this track");
  await noFigures(page);
  await page.mouse.up();

  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  const rows = await regionsOnServer(page);
  expect(rows.map((r) => r.id).sort()).toEqual(["r1", "r4"]);
  // The track beyond the one removed closed up, and nothing else about it
  // changed: a track is a lane on the screen, not a bus.
  expect(stored(rows, "r4").track).toBe(1);
  expect(stored(rows, "r4").at_s).toBeCloseTo(0, 3);
  expect(stored(rows, "r1").track).toBe(0);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-tracks", "2");
  await expect(page.getByTestId("collage-doomed")).toHaveCount(0);

  // One undo brings the track and both its regions back where they were.
  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  const back = await regionsOnServer(page);
  expect(back.map((r) => r.id).sort()).toEqual(["r1", "r2", "r3", "r4"]);
  expect(stored(back, "r2").track).toBe(1);
  expect(stored(back, "r3").at_s).toBeCloseTo(30, 3);
  expect(stored(back, "r4").track).toBe(2);
});

test("removing the only track leaves the canvas as empty as it began", async ({ page, request }) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 1, 0.05)]);
  await page.goto("/collage");
  await takeUp(page, "r1");
  await holdTrack(page, 800);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");

  expect(await regionsOnServer(page)).toHaveLength(0);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-regions", "0");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-tracks", "0");
  expect(await page.getByTestId("collage-space").locator("*").count()).toBe(0);
  // Every gesture that needs something to act on refuses again.
  await expect(page.getByTestId("collage-play")).toBeDisabled();
  await expect(page.getByTestId("collage-snip")).toBeDisabled();
  await expect(page.getByTestId("collage-copy")).toHaveCount(0);
  await expect(page.getByTestId("collage-track")).toHaveCount(0);

  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(await regionsOnServer(page)).toHaveLength(1);
});

test("a move in time takes a region out of the pass being heard; a move across tracks does not, and nor does removing a track take the rest of the mix", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  const hash = set[0].hash;
  // Three regions told apart by the length of their cuts, on three tracks.
  // The third sounds after the second is over, so carrying it onto the
  // second's track lands it in free room and its moment does not move.
  await writeRegions(request, [
    regionRow("r1", hash, 0, 0, 0, 0.35, 0.02),
    regionRow("r2", hash, 1, 0, 0, 0.6, 0.02),
    regionRow("r3", hash, 2, 32, 0, 0.8, 0.02),
  ]);
  await listen(page);
  await page.goto("/collage");
  await page.getByTestId("collage-play").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  expect((await heard(page)).pieces).toHaveLength(3);

  // Across a track and nothing else: a track is a lane on the screen and the
  // mix is a plain sum, so nothing about the sound changed and it plays on.
  let before = (await heard(page)).stops.length;
  await carry(page, "r3", -TRACK_W, 0);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(stored(await regionsOnServer(page), "r3").track).toBe(1);
  expect(stored(await regionsOnServer(page), "r3").at_s).toBeCloseTo(32, 3);
  expect((await heard(page)).stops.slice(before)).toHaveLength(0);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");

  // A track removed mid-play takes every region on it out of the mix — both
  // of them — and leaves the rest of it sounding.
  before = (await heard(page)).stops.length;
  await takeUp(page, "r2");
  await holdTrack(page, 800);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(
    (await heard(page)).stops
      .slice(before)
      .map((s) => Math.round(s.duration * 100))
      .sort((a, b) => a - b),
  ).toEqual([60, 80]);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  await expect(page.getByTestId("collage-playhead")).toBeVisible();
  // And it says so in the words a removal earns: what went is not coming
  // back on the next play, so the bar does not promise it will.
  await expect(page.getByTestId("collage-hint")).toContainText("the rest of the piece plays on");
  await expect(page.getByTestId("collage-hint")).not.toContainText("next time you play");

  // Along the track: when it sounds has moved, and the pass being heard was
  // scheduled at the tap, so that one region goes quiet and says so.
  before = (await heard(page)).stops.length;
  await carry(page, "r1", 0, 200);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect((await heard(page)).stops.slice(before).map((s) => Math.round(s.duration * 100))).toEqual([35]);
  await expect(page.getByTestId("collage-hint")).toContainText("gone quiet");
  await expect(page.getByTestId("collage")).toHaveAttribute("data-piece", "playing");
  await page.getByTestId("collage-play").click();
});

test("the header keeps no triage bar over the collage", async ({ page }) => {
  await page.goto("/decided");
  // The counter is on every other view: a filled bar and a percentage.
  await expect(page.getByTestId("triage-counter")).toBeVisible();

  await page.goto("/collage");
  await expect(page.getByTestId("collage")).toBeVisible();
  // Not here. A filled horizontal bar a thumb above a canvas that has sworn
  // off meters reads as one, and the percentage beside it is a figure about
  // a job this view is not doing.
  await expect(page.getByTestId("triage-counter")).toHaveCount(0);
  const header = await page.locator("header.topbar").innerText();
  expect(header).not.toMatch(/\d+\s?%/);
});

test("the clipboard holds what was copied, not what the canvas holds now: copy, undo, paste", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 0, 0, 1, 0.05)]);
  await page.goto("/collage");

  // Bring the region down, which is one change and one undo step.
  await enterBalance(page, "r1");
  await region(page, "r1").press("ArrowLeft");
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(stored(await regionsOnServer(page), "r1").gain).toBeCloseTo(0.9, 3);
  await page.getByTestId("collage-balance").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-mode", "trim");

  // Copy it at that level, then take the level back. The region on the canvas
  // is at the level it began at; the copy is a snapshot and is not.
  await page.getByTestId("collage-copy").click();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-clipboard", "r1");
  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(stored(await regionsOnServer(page), "r1").gain).toBeCloseTo(1, 3);
  // Undo did not disarm the paste: the copy is still waiting for a tap.
  await expect(page.getByTestId("collage-paste")).toBeVisible();

  await stampAt(page, 40, TOP_PAD + 500);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  const rows = await regionsOnServer(page);
  expect(rows).toHaveLength(2);
  const made = rows.find((r) => r.id !== "r1")!;
  expect(made.gain, "the copy came back at the level the region was taken back to").toBeCloseTo(0.9, 3);
  expect(stored(rows, "r1").gain).toBeCloseTo(1, 3);
});

test("a move that goes out and comes back writes nothing, and a region cannot settle after itself", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [regionRow("r1", set[0].hash, 0, 5, 0, 1, 0.05)]);
  await page.goto("/collage");
  await takeUp(page, "r1");

  let writes = 0;
  page.on("request", (r) => {
    if (r.method() === "PUT" && r.url().includes("/collage")) writes += 1;
  });

  // Carried down and back to where it started, clear of the edge where the
  // canvas would scroll itself under the thumb. Nothing about the arrangement
  // changed, so nothing is written and nothing is on the stack.
  const grab = region(page, "r1").getByTestId("region-grab");
  const box = (await grab.boundingBox())!;
  const canvas = (await page.getByTestId("collage-canvas").boundingBox())!;
  const x = box.x + box.width / 2;
  const y = box.y + 24;
  const down = Math.min(200, canvas.y + canvas.height - 64 - y);
  expect(down, "the canvas is too short for this to measure anything").toBeGreaterThan(80);
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, y + down, { steps: 8 });
  await expect(page.getByTestId("collage")).toHaveAttribute("data-moving", "r1");
  expect(await page.getByTestId("collage-canvas").evaluate((node) => node.scrollTop)).toBe(0);
  await page.mouse.move(x, y, { steps: 8 });
  // Back where it began, and not pushed past itself: a region is never a
  // neighbour of its own, so there is nothing on the track to settle after.
  await expect(page.getByTestId("collage-mode")).toContainText("let go to put it here");
  await page.mouse.up();
  await page.waitForTimeout(300);
  expect(writes).toBe(0);
  expect(stored(await regionsOnServer(page), "r1").at_s).toBeCloseTo(5, 3);
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);
});

test("an emptied column in the middle stays, and the track button cannot close it", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [
    regionRow("r1", set[0].hash, 0, 0, 0, 1, 0.05),
    regionRow("r2", set[0].hash, 1, 0, 0, 1, 0.05),
    regionRow("r3", set[0].hash, 2, 0, 0, 1, 0.05),
  ]);
  await page.goto("/collage");

  // The middle track is emptied by carrying its region onto the first.
  await carry(page, "r2", -TRACK_W, 0);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(stored(await regionsOnServer(page), "r2").track).toBe(0);
  expect(stored(await regionsOnServer(page), "r3").track).toBe(2);

  // The column it left is blank canvas and stays in the count, because a
  // track is a lane and the lane beyond it has not moved. There is nothing
  // on the empty column to take up, so the track button can only ever be
  // aimed at a column that has something on it: the gap is closed by
  // carrying what is beyond it across, one region at a time, and not by the
  // gesture whose name says it removes a track.
  await expect(page.getByTestId("collage")).toHaveAttribute("data-tracks", "3");
  await expect(page.getByTestId("collage-count")).toContainText("3 tracks");
  await takeUp(page, "r3");
  await holdTrack(page, 800);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  // Holding it with the region beyond the gap in hand takes that region, not
  // the gap: the empty column is still there and the piece is one region
  // shorter.
  const rows = await regionsOnServer(page);
  expect(rows.map((r) => r.id).sort()).toEqual(["r1", "r2"]);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-tracks", "1");
  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect((await regionsOnServer(page)).map((r) => r.id).sort()).toEqual(["r1", "r2", "r3"]);
});

test("nothing anywhere on the page reads as a time, a level, a rate or a percentage, in any state the bar can be in", async ({
  page,
  request,
}) => {
  const set = await sounds(page);
  await writeRegions(request, [
    regionRow("r1", set[0].hash, 0, 0, 0, 1, 0.05),
    regionRow("r2", set[0].hash, 1, 30, 0, 1, 0.05),
  ]);
  await page.goto("/collage");
  await expect(page.getByTestId("region")).toHaveCount(2);

  /**
   * Everything on the page a person can read: the text of it, and every
   * `aria-label` and `title` on it, header and navigation included.
   *
   * The whole document and not only the view, because the figures this
   * surface has sworn off have arrived from outside it before — the triage
   * bar's percentage sat in the header over a canvas with no meters on it.
   */
  const nothingReadsAsAFigure = async (where: string) => {
    const readable = await page.evaluate(() => {
      const spoken = Array.from(document.querySelectorAll("[aria-label], [title]"))
        .map((el) => `${el.getAttribute("aria-label") ?? ""} ${el.getAttribute("title") ?? ""}`)
        .join("\n");
      return `${document.body.innerText}\n${spoken}`.toLowerCase();
    });
    // m:ss; a count of seconds, milliseconds, decibels, beats or per cent;
    // a playback rate. Bytes are not on this list: a file's size is a fact
    // about the disk and not a figure about the sound.
    expect(readable, `${where}: a clock`).not.toMatch(/\d+:\d\d/);
    expect(readable, `${where}: a figure`).not.toMatch(
      /\b\d+(\.\d+)?\s?(s|sec|secs|second|seconds|ms|db|bpm|%|hz|khz)\b/,
    );
    expect(readable, `${where}: a rate`).not.toMatch(/\b\d+(\.\d+)?\s?(x|×)\b/);
    expect(readable, `${where}: hours`).not.toMatch(/\b\d+(\.\d+)?\s?h\b/);
  };

  await nothingReadsAsAFigure("nothing in hand");
  await takeUp(page, "r1");
  await expect(page.getByTestId("collage-in-hand")).toHaveCount(1);
  await nothingReadsAsAFigure("a region in hand");

  await page.getByTestId("collage-copy").click();
  await expect(page.getByTestId("collage-paste")).toBeVisible();
  await nothingReadsAsAFigure("a copy armed");
  await page.getByTestId("collage-paste").click();

  await takeUp(page, "r1");
  await carry(page, "r1", 0, 120, false);
  await expect(page.getByTestId("collage")).toHaveAttribute("data-moving", "r1");
  await nothingReadsAsAFigure("a region under a thumb");
  await page.keyboard.press("Escape");
  await page.mouse.up();

  await takeUp(page, "r1");
  const button = (await page.getByTestId("collage-track").boundingBox())!;
  await page.mouse.move(button.x + button.width / 2, button.y + button.height / 2);
  await page.mouse.down();
  await expect(page.getByTestId("collage")).toHaveAttribute("data-doomed", "armed", { timeout: 4000 });
  await nothingReadsAsAFigure("a track held towards removal");
  await page.keyboard.press("Escape");
  await page.mouse.up();
});
