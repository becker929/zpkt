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
async function writesDuring(page: Page, run: () => Promise<void>): Promise<number> {
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
