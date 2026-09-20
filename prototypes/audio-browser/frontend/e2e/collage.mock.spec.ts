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
  await expect(button).toBeDisabled();
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
  await expect(button).toBeDisabled();

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
