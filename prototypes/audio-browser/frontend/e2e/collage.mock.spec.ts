/**
 * The collage view: choose a sound, stamp it, hear it.
 *
 * Against mock mode, where the project in `collage` is `conveyor belt` with two
 * frozen sounds. Every test writes an empty arrangement back before and after
 * itself: the mock server keeps its projects in memory and is reused between
 * runs, so a region left behind would be drawn by the next run's first test.
 *
 * Nothing here touches the real projects directory.
 */

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { STREAM_URL, api } from "./helpers";

/** The fixture project in `collage`. */
const PROJECT = "2026-09-12-conveyor-belt";

/** The geometry the view draws with. Mirrors `lib/collage.ts`. */
const PX_PER_S = 10;
const TRACK_W = 128;
const TOP_PAD = 12;
const MIN_REGION_H = 44;

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

function heightFor(durationS: number): number {
  return Math.max(durationS * PX_PER_S, MIN_REGION_H);
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

test("no seconds, no grid, no decibels appear anywhere in the view", async ({ page }) => {
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
  // Height is duration.
  expect(first.height).toBeCloseTo(heightFor(duration), 0);
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

  // A at the top. B thirty seconds after A ends. Then C aimed between them
  // with too little room: it lands after B, whatever d is. "After" is after
  // B's box, not B's sound: a cut shorter than a thumb is drawn a thumb tall,
  // and C sits below the box so the two can both be tapped.
  const footprint = Math.max(d, MIN_REGION_H / PX_PER_S);
  await stampAt(page, 40, 200);
  const bAt = d + 30;
  await stampAt(page, 40, Math.round(TOP_PAD + bAt * PX_PER_S));
  await expect(page.getByTestId("region")).toHaveCount(2);
  const cAim = Math.max(footprint + 0.5, bAt - footprint / 2);
  await stampAt(page, 40, Math.round(TOP_PAD + cAim * PX_PER_S));
  await expect(page.getByTestId("region")).toHaveCount(3);

  const stored = await regionsOnServer(page);
  expect(stored[2].at_s).toBeCloseTo(bAt + footprint, 1);
  const c = await regionBox(page, 2);
  expect(c.top).toBeCloseTo(TOP_PAD + (bAt + footprint) * PX_PER_S, 0);
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

test("undo takes back the last stamp, on screen and on disk", async ({ page }) => {
  await page.goto("/collage");
  await choose(page, 0);
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);
  await stampAt(page, 40, 200);
  // Well after the first region, inside the blank the view leaves below it.
  const blank = await page.getByTestId("collage-space").boundingBox();
  await stampAt(page, 40, Math.round(blank!.height - 60));
  await expect(page.getByTestId("region")).toHaveCount(2);
  await expect(page.getByTestId("collage-undo")).toBeVisible();

  await page.getByTestId("collage-undo").click();
  await expect(page.getByTestId("region")).toHaveCount(1);
  await expect(page.getByTestId("collage-undo")).toHaveCount(0);
  await expect(page.getByTestId("collage-save")).toHaveAttribute("data-state", "saved");
  expect(await regionsOnServer(page)).toHaveLength(1);
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
