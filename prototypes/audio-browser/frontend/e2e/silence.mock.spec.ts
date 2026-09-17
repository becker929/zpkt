/**
 * Skipping silence.
 *
 * A quarter of the collection is dead air: 11.5 hours of 45.8. The player has
 * to jump over it, and every length the interface prints has to stop counting
 * it. The test that matters most is the last kind in this file: an explicit
 * scrub into a silent stretch must be left alone. A skipper that fights a
 * deliberate seek is worse than no skipper.
 *
 * These run against mock mode, whose fixture carries the same shape of
 * measurement as the real tables: every gap down to 0.4 seconds, filtered to
 * the 2 second floor when it is read.
 */

import { expect, test, type Page } from "@playwright/test";

import { api, waitForRows } from "./helpers";

interface Interval {
  start_s: number;
  end_s: number;
}

interface Row {
  hash: string;
  filename: string;
  duration_s: number;
  sounding_s: number | null;
}

const FLOOR = 2.0;

async function silenceOf(page: Page, hash: string, minGap?: number) {
  const suffix = minGap === undefined ? "" : `?min_gap=${minGap}`;
  const body = await api(page, `/api/files/${hash}/silence${suffix}`);
  return {
    intervals: body.intervals as Interval[],
    sounding_s: body.sounding_s as number,
    duration_s: body.duration_s as number,
    silent_s: body.silent_s as number,
  };
}

/**
 * The first row of a filtered view that satisfies `want`, with its index.
 *
 * The index matters: the test clicks that row in the list, which is what gives
 * the player a queue. Only the first couple of dozen rows are in the DOM, so
 * the scan is capped at what is reachable without scrolling.
 */
async function findRow(
  page: Page,
  filter: string,
  want: (row: Row, intervals: Interval[]) => boolean,
): Promise<{ row: Row; index: number; intervals: Interval[] }> {
  const body = await api(page, `/api/files?${filter}&limit=24`);
  const items = body.items as Row[];
  for (let i = 0; i < items.length; i += 1) {
    const { intervals } = await silenceOf(page, items[i].hash);
    if (want(items[i], intervals)) return { row: items[i], index: i, intervals };
  }
  throw new Error(`no fixture row under ${filter} matched`);
}

/** The audio element's own account of itself. */
function audioState(page: Page) {
  return page.getByTestId("audio").evaluate((node) => {
    const el = node as HTMLAudioElement;
    return { src: el.src, time: el.currentTime, paused: el.paused, duration: el.duration };
  });
}

/** Click the waveform at a time, using its measured width. */
async function scrubTo(page: Page, waveform: ReturnType<Page["getByTestId"]>, t: number, durationS: number) {
  const box = await waveform.boundingBox();
  expect(box, "the waveform has no box to click").not.toBeNull();
  const x = Math.min(Math.max((t / durationS) * box!.width, 1), box!.width - 1);
  await waveform.click({ position: { x, y: box!.height / 2 } });
}

/* The measurement itself ---------------------------------------------------- */

test("the route filters to the floor and the two numbers agree", async ({ page }) => {
  const { row } = await findRow(page, "ext=.wav&min_dur=40&sort=name", (_r, gaps) => gaps.length > 0);

  const atFloor = await silenceOf(page, row.hash, FLOOR);
  const everything = await silenceOf(page, row.hash, 0.4);

  // Nothing under the floor survives, and lowering the floor never loses a gap.
  for (const gap of atFloor.intervals) expect(gap.end_s - gap.start_s).toBeGreaterThanOrEqual(FLOOR);
  expect(everything.intervals.length).toBeGreaterThanOrEqual(atFloor.intervals.length);
  expect(everything.sounding_s).toBeLessThanOrEqual(atFloor.sounding_s + 0.001);

  // Sounding duration is wall duration minus exactly what is returned.
  const silent = atFloor.intervals.reduce((sum, g) => sum + (g.end_s - g.start_s), 0);
  expect(atFloor.sounding_s).toBeCloseTo(atFloor.duration_s - silent, 2);
});

test("a row carries its sounding length", async ({ page }) => {
  const { row } = await findRow(page, "ext=.wav&min_dur=40&sort=name", (r, gaps) => gaps.length > 0);
  const measured = await silenceOf(page, row.hash, FLOOR);
  expect(row.sounding_s).toBeCloseTo(measured.sounding_s, 2);
  expect(row.sounding_s!).toBeLessThan(row.duration_s);
});

/* What the interface prints ------------------------------------------------- */

test("the length in a row is the sounding length, and says when it is shorter", async ({ page }) => {
  const filter = "q=a&ext=.wav&min_dur=40&sort=name";
  const { row, index } = await findRow(
    page,
    filter,
    (r, gaps) => gaps.length > 0 && r.duration_s - (r.sounding_s ?? r.duration_s) > 5,
  );

  await page.goto(`/search?${filter.replace("sort=name", "sort=name&order=asc")}`);
  await waitForRows(page);

  const length = page.locator(`[data-index="${index}"] [data-testid="length"]`);
  await expect(length).toHaveAttribute("data-sounding", "true");
  await expect(length).toHaveAttribute("data-differs", "true");

  // The number shown is the sounding one, not the wall one.
  const minutes = (s: number) => `${Math.floor(Math.round(s) / 60)}:`;
  await expect(length).toContainText(minutes(row.sounding_s!));
  await expect(length).toHaveAttribute("title", /of sound in /);
});

test("the detail view shows sounding, wall, and how much silence", async ({ page }) => {
  const { row } = await findRow(page, "ext=.wav&min_dur=40&sort=name", (r, gaps) => gaps.length > 1);
  await page.goto(`/sounds/${row.hash}`);

  await expect(page.getByTestId("detail")).toBeVisible();
  await expect(page.getByTestId("detail-sounding")).toHaveAttribute("data-differs", "true");
  await expect(page.getByTestId("detail-silence")).not.toContainText("not measured");
  await expect(page.getByTestId("detail-silence")).not.toContainText("none");

  // Wall duration stays on the page beside it. The difference is the point.
  const sounding = await page.getByTestId("detail-sounding").innerText();
  const wall = await page.getByTestId("detail-wall").innerText();
  expect(sounding).not.toBe(wall);
});

test("the header counts sounding hours, not wall hours", async ({ page }) => {
  await page.goto("/");
  const stats = await api(page, "/api/stats");
  expect(stats.total_sounding_s as number).toBeLessThan(stats.total_duration_s as number);

  const bar = page.getByTestId("topbar-stats");
  await expect(bar).toHaveAttribute("data-hours", "sounding");
  await expect(bar).toContainText("sounding");
  const hours = `${((stats.total_sounding_s as number) / 3600).toFixed(1)} h`;
  await expect(bar).toContainText(hours);
});

test("the waveform tints the silent stretches", async ({ page }) => {
  const { row, intervals } = await findRow(page, "ext=.wav&min_dur=40&sort=name", (_r, gaps) => gaps.length > 1);
  await page.goto(`/sounds/${row.hash}`);

  const waveform = page.getByTestId("detail").getByTestId("waveform");
  await expect(waveform).toHaveAttribute("data-silent-regions", String(intervals.length));
});

/* The player ---------------------------------------------------------------- */

test("leading silence is gone before it is heard", async ({ page }) => {
  const filter = "q=a&ext=.wav&min_dur=40&sort=name";
  const { row, index, intervals } = await findRow(
    page,
    filter,
    (_r, gaps) => gaps.length > 0 && gaps[0].start_s === 0 && gaps[0].end_s >= 6,
  );
  const lead = intervals[0].end_s;

  await page.goto(`/search?${filter}`);
  await waitForRows(page);
  await page.locator(`[data-index="${index}"]`).click();
  await expect(page.getByTestId("player-bar")).toHaveAttribute("data-hash", row.hash);

  // The gap is at least six seconds, so reaching its end this soon can only
  // have happened by jumping.
  await expect
    .poll(async () => (await audioState(page)).time, {
      message: "the player sat through the leading silence",
      timeout: 5_000,
    })
    .toBeGreaterThanOrEqual(lead - 0.1);

  await expect(page.getByTestId("player-readout")).toContainText("skipping");
});

test("a deliberate scrub into silence is left alone", async ({ page }) => {
  // The one that decides whether this feature is usable. Someone who scrubs
  // into a quiet passage means it, and being dragged out of it a quarter of a
  // second later is how an auto-skipper becomes infuriating.
  const filter = "ext=.wav&min_dur=60&sort=name";
  const { row, intervals } = await findRow(page, filter, (_r, gaps) =>
    gaps.some((g, i) => i > 0 && g.end_s - g.start_s >= 8),
  );
  const gap = intervals.find((g, i) => i > 0 && g.end_s - g.start_s >= 8)!;

  await page.goto(`/sounds/${row.hash}`);
  await page.getByTestId("detail-play").click();
  await expect(page.getByTestId("player-bar")).toHaveAttribute("data-hash", row.hash);
  await expect.poll(async () => (await audioState(page)).duration).toBeGreaterThan(0);

  const waveform = page.getByTestId("detail").getByTestId("waveform");
  const target = gap.start_s + 2;
  await scrubTo(page, waveform, target, row.duration_s);

  // It lands where it was told to.
  await expect
    .poll(async () => (await audioState(page)).time, { timeout: 5_000 })
    .toBeGreaterThanOrEqual(gap.start_s);

  // And it stays there: two seconds later the playhead has crept forward
  // inside the gap rather than being thrown to its end.
  await page.waitForTimeout(2_000);
  const after = await audioState(page);
  expect(after.time, "the skipper threw the playhead out of a gap the user chose").toBeLessThan(gap.end_s);
  expect(after.time).toBeGreaterThan(gap.start_s);
});

test("a scrub made before the measurement lands is still honoured", async ({ page }) => {
  // The detail view loads a sound and positions it a moment later, which can
  // be before the silence route has answered. The aim has to survive that, or
  // clicking a tinted region on a cold page would be undone the instant the
  // measurement arrived.
  const filter = "ext=.wav&min_dur=60&sort=name";
  const { row, intervals } = await findRow(page, filter, (_r, gaps) =>
    gaps.some((g, i) => i > 0 && g.end_s - g.start_s >= 8),
  );
  const gap = intervals.find((g, i) => i > 0 && g.end_s - g.start_s >= 8)!;

  await page.goto(`/sounds/${row.hash}`);
  await expect(page.getByTestId("detail")).toBeVisible();

  // Hold the measurement back so the seek certainly goes first.
  await page.route("**/silence*", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 900));
    await route.continue();
  });

  // No play first: the click both loads the sound and positions it.
  const waveform = page.getByTestId("detail").getByTestId("waveform");
  await scrubTo(page, waveform, gap.start_s + 2, row.duration_s);

  await expect
    .poll(async () => (await audioState(page)).time, { timeout: 8_000 })
    .toBeGreaterThanOrEqual(gap.start_s);

  await page.waitForTimeout(2_000);
  const after = await audioState(page);
  expect(after.time, "a late measurement undid the user's scrub").toBeLessThan(gap.end_s);
});

test("leaving the excused gap puts the skipper back to work", async ({ page }) => {
  // An excusal covers the one stretch that was scrubbed into, not the rest of
  // the sound. Once playback is past it, the next gap is skipped as usual.
  // The second gap has to arrive soon after the first, or this test spends
  // half a minute listening to the sounding part in between.
  const filter = "ext=.wav&min_dur=60&sort=name";
  const { row, intervals } = await findRow(
    page,
    filter,
    (_r, gaps) =>
      gaps.length >= 2 &&
      gaps[0].start_s === 0 &&
      gaps[0].end_s >= 4 &&
      gaps[1].start_s - gaps[0].end_s <= 9,
  );
  const lead = intervals[0];
  const next = intervals[1];

  await page.goto(`/sounds/${row.hash}`);
  await page.getByTestId("detail-play").click();
  await expect.poll(async () => (await audioState(page)).duration).toBeGreaterThan(0);

  const waveform = page.getByTestId("detail").getByTestId("waveform");
  // Into the leading gap on purpose, near its end so playback leaves it soon.
  await scrubTo(page, waveform, lead.end_s - 1.2, row.duration_s);
  await expect.poll(async () => (await audioState(page)).time, { timeout: 5_000 }).toBeLessThan(lead.end_s);

  // Playback runs on into the sounding part, and the following gap is skipped.
  await expect
    .poll(async () => (await audioState(page)).time, {
      message: "the second gap was not skipped after the first was excused",
      timeout: 30_000,
    })
    .toBeGreaterThanOrEqual(next.end_s - 0.1);
});

test("trailing silence ends the track instead of playing out", async ({ page }) => {
  const filter = "q=a&ext=.wav&min_dur=40&max_dur=300&sort=name";
  const { row, index, intervals } = await findRow(page, filter, (r, gaps) => {
    const last = gaps[gaps.length - 1];
    return Boolean(last) && last.end_s >= r.duration_s - 0.4 && last.end_s - last.start_s >= 5;
  });
  const tail = intervals[intervals.length - 1];

  // From a view with rows, so the player has a queue to advance into.
  await page.goto(`/search?${filter}`);
  await waitForRows(page);
  await page.locator(`[data-index="${index}"]`).click();
  await expect(page.getByTestId("player-bar")).toHaveAttribute("data-hash", row.hash);

  // Scrub to just before the tail, on the detail view's wide waveform where a
  // pixel is a tenth of a second. Follow the player bar's own link rather than
  // loading the URL: a fresh page load would throw away the queue and the
  // sound playing in it.
  await page.getByTestId("player-bar").locator("a").first().click();
  await expect(page.getByTestId("detail")).toBeVisible();
  await expect.poll(async () => (await audioState(page)).duration).toBeGreaterThan(0);
  const waveform = page.getByTestId("detail").getByTestId("waveform");
  await scrubTo(page, waveform, tail.start_s - 1, row.duration_s);

  // Playback walks into the tail and the queue moves on, rather than counting
  // out however many seconds of nothing are left.
  await expect(page.getByTestId("player-bar"), "the queue did not advance out of the tail").not.toHaveAttribute(
    "data-hash",
    row.hash,
    { timeout: 15_000 },
  );
});

/* The toggle ---------------------------------------------------------------- */

test("the toggle turns it off, and the choice survives a reload", async ({ page }) => {
  const filter = "q=a&ext=.wav&min_dur=40&sort=name";
  const { row, index, intervals } = await findRow(
    page,
    filter,
    (_r, gaps) => gaps.length > 0 && gaps[0].start_s === 0 && gaps[0].end_s >= 8,
  );
  const lead = intervals[0].end_s;

  await page.goto(`/search?${filter}`);
  await waitForRows(page);
  await page.locator(`[data-index="${index}"]`).click();

  const toggle = page.getByTestId("skip-toggle");
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "false");

  // Reload, and the player still has the answer it was given.
  await page.reload();
  await waitForRows(page);
  await page.locator(`[data-index="${index}"]`).click();
  await expect(page.getByTestId("player-bar")).toHaveAttribute("data-hash", row.hash);
  await expect(page.getByTestId("skip-toggle")).toHaveAttribute("aria-pressed", "false");

  // With it off, the leading silence is played rather than jumped.
  await page.waitForTimeout(2_500);
  const state = await audioState(page);
  expect(state.time, "the skipper ran with the toggle off").toBeLessThan(lead - 1);
  await expect(page.getByTestId("player-readout")).toContainText("silent");
  await expect(page.getByTestId("player-readout")).not.toContainText("skipping");

  // Put it back, and the gap goes at once.
  await page.getByTestId("skip-toggle").click();
  await expect
    .poll(async () => (await audioState(page)).time, { timeout: 5_000 })
    .toBeGreaterThanOrEqual(lead - 0.1);
});

/* Streams that cannot be skipped -------------------------------------------- */

test("an AIF says silence cannot be skipped in it", async ({ page }) => {
  const { row } = await findRow(page, "ext=.aif&min_dur=40&sort=name", (_r, gaps) => gaps.length > 0);
  await page.goto(`/sounds/${row.hash}`);

  // Said where the unseekable notice already is, rather than nowhere.
  const note = page.getByTestId("no-seek-note");
  await expect(note).toBeVisible();
  await expect(note).toContainText("converted from AIF");
  await expect(note).toContainText("silence cannot be skipped");

  // And no toggle pretending it would work here.
  await expect(page.getByTestId("detail-skip-toggle")).toHaveCount(0);

  await page.getByTestId("detail-play").click();
  await expect(page.getByTestId("skip-toggle")).toHaveAttribute("data-blocked", "true");
  await expect(page.getByTestId("player-readout")).toContainText("unskippable");

  // The playhead is left where it is: there is nowhere to seek to.
  await page.waitForTimeout(1_500);
  const state = await audioState(page);
  expect(state.time).toBeLessThan(3);
});
