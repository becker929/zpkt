/**
 * The phone.
 *
 * This project runs under an iPhone device descriptor, which means WebKit at
 * 393 by 852 with touch and a device pixel ratio of 3, not a narrow desktop
 * window. Three things are checked here that a desktop run cannot show: that
 * nothing mismatches during hydration, that a filename is readable in a column
 * half a phone wide, and that the player bar stays on screen and keeps playing
 * across a navigation.
 */

import { expect, test, type ConsoleMessage, type Page } from "@playwright/test";

import { waitForRows } from "./helpers";

/**
 * Console errors that are not the application's.
 *
 * The development server's hot-reload socket does not complete its handshake
 * under WebKit. That is the dev server talking to itself and says nothing about
 * the page.
 */
const IGNORED = [/webpack-hmr/, /Failed to load resource/i];

/** Collect page errors so a test can assert the console stayed clean. */
function watchConsole(page: Page): string[] {
  const seen: string[] = [];
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (IGNORED.some((pattern) => pattern.test(text))) return;
    seen.push(text.split("\n")[0]);
  });
  page.on("pageerror", (err) => seen.push(`pageerror: ${err.message}`));
  return seen;
}

const VIEWS = ["/", "/decided", "/search", "/board"];

test("every view hydrates without a mismatch", async ({ context }) => {
  // React reports a hydration mismatch as a console error whose first line
  // starts "A tree hydrated" or "Hydration failed". Either one fails this test,
  // along with any other error the page logs.
  //
  // Each view gets its own page. Leaving a view mid-flight cancels its requests
  // and the browser logs that, which has nothing to do with hydration.
  for (const view of VIEWS) {
    const page = await context.newPage();
    const errors = watchConsole(page);
    await page.goto(view);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);
    expect(errors, `${view} logged console errors`).toEqual([]);
    await page.close();
  }
});

test("the detail view hydrates without a mismatch", async ({ page }) => {
  // Read the hash through the request context rather than by visiting the list
  // first: leaving the list mid-fetch cancels its requests, and WebKit reports
  // a cancelled fetch as a page error that has nothing to do with hydration.
  const response = await page.request.get("/api/files?limit=1&sort=name");
  const hash = ((await response.json()) as { items: Array<{ hash: string }> }).items[0].hash;

  const errors = watchConsole(page);
  await page.goto(`/sounds/${hash}`);
  await expect(page.getByTestId("detail")).toBeVisible();
  await page.waitForTimeout(500);
  expect(errors).toEqual([]);
});

test("the filter bar is one line until it is asked for more", async ({ page }) => {
  await page.goto("/search?q=kick");
  await waitForRows(page);

  // Four stacked rows of filters used to take a quarter of the screen. The
  // resting state is the search box, the count, and a disclosure.
  const controls = page.getByTestId("controls");
  const box = await controls.boundingBox();
  expect(box, "the filter bar has no box").not.toBeNull();
  expect(box!.height).toBeLessThan(70);

  await expect(page.getByTestId("ext")).toBeHidden();
  await page.getByTestId("filters-toggle").click();
  await expect(page.getByTestId("ext")).toBeVisible();
  await expect(page.getByTestId("sort")).toBeVisible();

  // And the toggle counts what is set, so a filter cannot hide behind the fold
  // unannounced.
  await page.getByTestId("ext").selectOption(".wav");
  await expect(page.getByTestId("filters-toggle")).toContainText("(1)");
  await page.getByTestId("ext").selectOption("");
  await expect(page.getByTestId("filters-toggle")).not.toContainText("(1)");
});

test("the name column takes most of the screen and shows more than a digit", async ({ page }) => {
  await page.goto(LONG_NAMES_FIRST);
  await waitForRows(page);

  const row = page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first();
  const rowBox = await row.boundingBox();
  const nameBox = await row.locator(".col-name").boundingBox();
  expect(rowBox).not.toBeNull();
  expect(nameBox).not.toBeNull();

  // The columns that were dropped — the index, the path count, the size and
  // the star — gave their room to the name.
  const share = nameBox!.width / rowBox!.width;
  expect(share).toBeGreaterThan(0.5);
  expect(nameBox!.width).toBeGreaterThan(140);

  // Every row is still one line: a record of decisions must stay scannable.
  expect(rowBox!.height).toBeLessThan(60);
});

/**
 * A view whose first rows are session-style names.
 *
 * Sorted Z–A the fixture opens on `wet-cardboard_2024-…_mono-check_…wav`, which
 * is the shape of name this column exists for. Sorted A–Z it opens on
 * `808 sub 00.wav`, which fits and therefore proves nothing.
 */
const LONG_NAMES_FIRST = "/search?q=-&sort=name&order=desc";

test("only the sound being listened to scrolls its name", async ({ page }) => {
  await page.goto(LONG_NAMES_FIRST);
  await waitForRows(page);

  const marquees = page.locator('[data-testid="row"] [data-testid="marquee"]');
  await expect.poll(async () => marquees.count()).toBeGreaterThan(5);

  // Nothing moves until a row is chosen.
  await expect(page.locator('[data-testid="row"] [data-testid="marquee"][data-running="true"]')).toHaveCount(0);

  // At least one name in the fixture is too long for half a phone, or this
  // test proves nothing.
  await expect
    .poll(async () => page.locator('[data-testid="row"] [data-testid="marquee"][data-overflow="true"]').count())
    .toBeGreaterThan(0);

  const overflowing = page
    .locator('[data-testid="row"]:has([data-testid="marquee"][data-overflow="true"])')
    .first();
  await overflowing.click();
  await expect(page.getByTestId("player-bar")).toBeVisible();

  // Exactly the playing row scrolls, not all thirty.
  await expect
    .poll(async () => page.locator('[data-testid="row"] [data-testid="marquee"][data-running="true"]').count())
    .toBe(1);
});

test("a name that fits never scrolls", async ({ page }) => {
  // Searched for a short noun, the fixture opens on `808 sub 00.wav`, which
  // fits on a phone with room to spare. Nothing about it should move, even once
  // it is the sound being played.
  await page.goto("/search?q=808&sort=name&order=asc");
  await waitForRows(page);

  const fitting = page.locator('[data-testid="row"] [data-testid="marquee"][data-overflow="false"]');
  await expect.poll(async () => fitting.count()).toBeGreaterThan(0);

  const row = page.locator('[data-testid="row"]:has([data-testid="marquee"][data-overflow="false"])').first();
  await row.click();
  await expect(page.getByTestId("player-bar")).toBeVisible();
  await page.waitForTimeout(300);
  await expect(page.locator('[data-testid="row"] [data-testid="marquee"][data-running="true"]')).toHaveCount(0);
});

test("reduced motion stops the scroll", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(LONG_NAMES_FIRST);
  await waitForRows(page);
  await page
    .locator('[data-testid="row"]:has([data-testid="marquee"][data-overflow="true"])')
    .first()
    .click();
  await expect(page.getByTestId("player-bar")).toBeVisible();
  await page.waitForTimeout(500);
  await expect(page.locator('[data-testid="marquee"][data-running="true"]')).toHaveCount(0);
});

test("the player bar is on screen on every view and keeps playing across them", async ({ page }) => {
  await page.goto("/search?q=kick");
  await waitForRows(page);
  await page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first().click();

  const bar = page.getByTestId("player-bar");
  await expect(bar).toBeVisible();
  const hash = await bar.getAttribute("data-hash");

  const audio = page.getByTestId("audio");
  const state = () =>
    audio.evaluate((node) => {
      const el = node as HTMLAudioElement;
      return { src: el.src, time: el.currentTime, paused: el.paused };
    });

  // Play far enough in that a restart would be unmistakable.
  await expect.poll(async () => (await state()).time).toBeGreaterThan(0.5);
  const before = await state();
  expect(before.paused).toBe(false);

  const viewport = page.viewportSize();
  expect(viewport).not.toBeNull();

  // Not the swipe view: it has no player bar, because the bottom of the screen
  // there belongs to its two answers.
  for (const label of ["decided", "board", "search"]) {
    await page.getByRole("link", { name: label, exact: true }).click();
    await expect(page.getByTestId("player-bar")).toBeVisible();
    await expect(page.getByTestId("player-bar")).toHaveAttribute("data-hash", hash ?? "");

    // Visible means inside the viewport, not merely in the document. `100vh`
    // put this bar underneath the iOS toolbar, which is how it went missing.
    const box = await page.getByTestId("player-bar").boundingBox();
    expect(box, `no player bar box on ${label}`).not.toBeNull();
    expect(box!.y + box!.height, `the player bar hangs below the viewport on ${label}`).toBeLessThanOrEqual(
      viewport!.height + 1,
    );

    // The name, the transport and the waveform all survive the move.
    await expect(page.getByTestId("player-bar").getByTestId("marquee")).toBeVisible();
    await expect(page.getByTestId("player-bar").getByTestId("waveform")).toBeVisible();
    await expect(page.getByTestId("play-pause")).toBeVisible();

    const now = await state();
    expect(now.src, `the stream reloaded on ${label}`).toBe(before.src);
    expect(now.paused, `playback stopped on ${label}`).toBe(false);
    // A tolerance, not a gap: WebKit reports `currentTime` at two different
    // precisions on two reads of the same instant, so an exact comparison
    // fails on a playhead that never moved backwards.
    expect(now.time, `playback restarted on ${label}`).toBeGreaterThanOrEqual(before.time - 0.05);
  }
});

test("the player bar survives opening a sound's detail page", async ({ page }) => {
  await page.goto("/search?q=kick");
  await waitForRows(page);
  await page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first().click();
  await expect(page.getByTestId("player-bar")).toBeVisible();

  const audio = page.getByTestId("audio");
  const timeOf = () => audio.evaluate((node) => (node as HTMLAudioElement).currentTime);
  await expect.poll(timeOf).toBeGreaterThan(0.5);
  const before = await timeOf();

  await page.getByTestId("player-bar").locator("a").first().click();
  await expect(page.getByTestId("detail")).toBeVisible();
  await expect(page.getByTestId("player-bar")).toBeVisible();
  expect(await timeOf()).toBeGreaterThanOrEqual(before - 0.05);
});

test("a transcoded stream still refuses to seek on a phone", async ({ page }) => {
  const response = await page.request.get("/api/files?ext=.aif&limit=1&min_dur=5");
  const hash = ((await response.json()) as { items: Array<{ hash: string }> }).items[0].hash;

  await page.goto(`/sounds/${hash}`);
  await expect(page.getByTestId("no-seek-note")).toBeVisible();
  await page.getByTestId("detail-play").click();
  await expect(page.getByTestId("player-bar")).toContainText("no seeking");
  await expect(page.getByTestId("player-bar").getByTestId("waveform")).toHaveAttribute(
    "data-seekable",
    "false",
  );
});

test("tapping a row's discard button does not also load the row", async ({ page }) => {
  // The button is 34 pixels wide inside a 46 pixel row. A thumb that hits it
  // must not also start playback.
  await page.goto("/search?q=kick");
  await waitForRows(page);
  const row = page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first();
  const hash = await row.getAttribute("data-hash");

  await row.getByTestId("discard-row").tap();
  await expect(page.getByTestId("player-bar")).toHaveCount(0);
  await expect(row.getByTestId("restore-row")).toBeVisible();

  // Put the fixture back the way it was found.
  await row.getByTestId("restore-row").tap();
  await expect(page.locator(`[data-testid="row"][data-hash="${hash}"] [data-testid="discard-row"]`)).toBeVisible();
});

test("the swipe view has no player bar and its answers own the bottom", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("swipe-card")).toBeVisible();
  await expect(page.getByTestId("player-bar")).toHaveCount(0);
  await expect(page.getByTestId("player-idle")).toHaveCount(0);
  await expect(page.getByTestId("swipe-discard")).toBeVisible();
  await expect(page.getByTestId("swipe-take")).toBeVisible();
});
