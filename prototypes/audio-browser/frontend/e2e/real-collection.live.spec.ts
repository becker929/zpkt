/**
 * Checks against the real index on port 3100.
 *
 * These are facts the generated fixture cannot show: a spans table filled in by
 * a classifier running in the background, an AIF stream that really is
 * transcoded, and a queue built from a collection that is being triaged every
 * day. Every test here only reads. Nothing writes a decision or a row.
 */

import { expect, test } from "@playwright/test";

import { STREAM_URL, api, paintedPixels, waitForHydration, waitForRows } from "./helpers";

/**
 * Nothing here is a pinned hash or a pinned count.
 *
 * The index is rescanned from a live collection and is triaged every day:
 * sounds are discarded, files move, and a classifier fills in spans that were
 * not there last week. A test that froze a hash or a total would fail for a
 * reason that has nothing to do with the interface, and a suite that fails for
 * reasons nobody caused teaches people to ignore it. Every test below looks up
 * the case it needs, says so when the collection currently holds no such case,
 * and checks the relationships between the numbers rather than the numbers.
 */

/** A search wide enough to hit most of the collection. */
const WIDE = "/search?q=a";

test.describe("the real collection", () => {
  test("search filters the real index", async ({ page }) => {
    await page.goto(WIDE);
    await waitForRows(page);
    const wide = await page.getByTestId("result-count").textContent();

    await waitForHydration(page);
    await page.getByTestId("search").fill("kick");
    await expect(page.getByTestId("search")).toHaveValue("kick");
    await expect(page.getByTestId("result-count")).not.toHaveText(wide ?? "");
    // The filtered page lands a moment after the count, so poll until no row
    // from the previous query is left on screen.
    await expect
      .poll(async () => {
        const names = await page.locator('[data-testid="row"] .col-name a').allTextContents();
        return names.length > 0 && names.every((n) => n.toLowerCase().includes("kick"));
      })
      .toBe(true);
  });

  test("an empty query lists nothing at all", async ({ page }) => {
    // The rule the whole interface turns on: no surface shows the undecided
    // collection, so a search box cannot be one by default.
    await page.goto("/search");
    await expect(page.getByTestId("search-idle")).toBeVisible();
    await expect(page.getByTestId("row")).toHaveCount(0);
  });

  test("no surface names a place on disk", async ({ page }) => {
    await page.goto(WIDE);
    await waitForRows(page);
    const row = page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first();
    const hash = await row.getAttribute("data-hash");

    await page.goto(`/sounds/${hash}`);
    await expect(page.getByTestId("detail")).toBeVisible();
    const text = (await page.getByTestId("detail").textContent()) ?? "";
    expect(text).not.toContain("/Users/");
    expect(text).not.toContain("daw-library");
    await expect(page.getByTestId("alias")).toHaveCount(0);
  });

  test("the spans route answers every sound, with an empty list rather than a 404", async ({
    page,
  }) => {
    const body = await api(page, "/api/files?limit=12&sort=name");
    const rows = body.items as Array<{ hash: string; duration_s: number | null }>;
    expect(rows.length).toBeGreaterThan(0);

    let answered = 0;
    for (const row of rows) {
      const answer = await api(page, `/api/files/${row.hash}/spans?method=yamnet`);
      expect(answer.hash, "the route answered about a different sound").toBe(row.hash);
      // The client reads either `spans` or `items`, so the test does too: it is
      // checking that every sound gets a list, not which key it arrives under.
      const spans = (answer.spans ?? answer.items ?? []) as Array<{
        start_s: number;
        end_s: number;
        label: string;
        method: string;
      }>;
      expect(Array.isArray(spans), `no list of spans for ${row.hash}`).toBe(true);
      answered += 1;

      for (const span of spans) {
        expect(span.end_s).toBeGreaterThanOrEqual(span.start_s);
        expect(span.start_s).toBeGreaterThanOrEqual(0);
        // Asked for one method, so one method is what comes back. Tinting the
        // three over each other is what this replaced.
        expect(span.method).toBe("yamnet");
        // A span cannot run past the end of the sound it describes.
        if (row.duration_s !== null) expect(span.end_s).toBeLessThanOrEqual(row.duration_s + 0.5);
      }
    }

    // Whether the classifier has been over this collection or not, every sound
    // in the sample answered. An empty list is not a missing sound.
    expect(answered).toBe(rows.length);
  });

  test("a real AIF stream refuses ranges and the page says so", async ({ page }) => {
    const body = await api(page, "/api/files?ext=.aif&limit=1&min_dur=5");
    const items = body.items as Array<{ hash: string; transcoded: boolean }>;
    test.skip(items.length === 0, "the index currently holds no AIF over five seconds");
    expect(items[0].transcoded).toBe(true);

    const head = await page.request.head(`/api/files/${items[0].hash}/stream`);
    expect(head.headers()["accept-ranges"]).toBe("none");

    await page.goto(`/sounds/${items[0].hash}`);
    await expect(page.getByTestId("no-seek-note")).toBeVisible();
  });

  test("the player is handed a hash and paints a waveform", async ({ page }) => {
    await page.goto(WIDE);
    await waitForRows(page);
    await page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first().click();
    await expect(page.getByTestId("player-bar")).toBeVisible();

    const src = await page.getByTestId("audio").evaluate((node) => (node as HTMLAudioElement).src);
    expect(new URL(src).pathname).toMatch(STREAM_URL);
    expect(src).not.toContain("daw-library");

    const waveform = page.getByTestId("player-bar").getByTestId("waveform");
    await expect.poll(async () => Number(await waveform.getAttribute("data-buckets")), {
      timeout: 40_000,
    }).toBeGreaterThan(0);
    await expect.poll(async () => paintedPixels(waveform)).toBeGreaterThan(200);
  });

  test("the swipe view paints a real sound from the real collection", async ({ page }) => {
    await page.goto("/");
    // Three answers are possible and they arrive after a request. Wait for one
    // of them, or a skip here would only be saying the page had not loaded.
    await expect(
      page
        .getByTestId("swipe-card")
        .or(page.getByTestId("swipe-done"))
        .or(page.getByTestId("swipe-absent")),
    ).toBeVisible();
    test.skip(await page.getByTestId("swipe-absent").isVisible(), "the queue cannot be read here");
    test.skip(await page.getByTestId("swipe-done").isVisible(), "nothing is undecided");

    const src = await page.getByTestId("audio").evaluate((node) => (node as HTMLAudioElement).src);
    expect(new URL(src).pathname).toMatch(STREAM_URL);
    expect(src).not.toContain("daw-library");

    const waveform = page.getByTestId("swipe-card").getByTestId("waveform");
    await expect.poll(async () => Number(await waveform.getAttribute("data-buckets")), {
      timeout: 40_000,
    }).toBeGreaterThan(0);
    await expect.poll(async () => paintedPixels(waveform)).toBeGreaterThan(200);
  });
});
