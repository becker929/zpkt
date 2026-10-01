/**
 * Silence against the real index.
 *
 * The frontend was written before `GET /api/files/{hash}/silence` existed, so
 * the first thing these check is that a server without it degrades honestly:
 * lengths fall back to wall duration, no row prints 0:00 for a sound that is
 * minutes long, and sorting by sounding length does not put an error on the
 * screen. Every one of them stays true once the route ships, so none of this
 * has to be deleted then.
 *
 * Read only. No test here writes to the index.
 */

import { expect, test, type Page } from "@playwright/test";

import { waitForRows } from "./helpers";

interface Row {
  hash: string;
  filename: string;
  duration_s: number | null;
  sounding_s?: number | null;
}

/** Whether the server serves the silence route at all. */
async function silenceServed(page: Page): Promise<boolean> {
  const first = await page.request.get("/api/files?limit=1&sort=name");
  const hash = ((await first.json()) as { items: Row[] }).items[0].hash;
  const response = await page.request.get(`/api/files/${hash}/silence`);
  return response.status() !== 404;
}

/**
 * A search wide enough to hit most of the collection.
 *
 * Nothing lists the undecided collection, so these tests reach their rows
 * through the search view. A single letter is the widest net a search offers,
 * and it is still a search: an empty query shows nothing.
 */
const WIDE = "/search?q=a";

test("no length in a row reads as zero for a sound that has one", async ({ page }) => {
  // The failure this guards against is a missing `sounding_s` coerced to 0,
  // which would print "0:00" against a five minute stem.
  await page.goto(`${WIDE}&sort=duration&order=desc`);
  await waitForRows(page);

  const lengths = page.locator('[data-testid="row"] [data-testid="length"]');
  await expect.poll(async () => lengths.count()).toBeGreaterThan(3);

  const texts = await lengths.allInnerTexts();
  for (const text of texts) {
    expect(text.trim(), "a length rendered as zero").not.toBe("0:00");
    expect(text.trim()).not.toBe("");
  }
});

test("an unmeasured row says so rather than guessing", async ({ page }) => {
  await page.goto(`${WIDE}&sort=name`);
  await waitForRows(page);

  const first = page.locator('[data-testid="row"] [data-testid="length"]').first();
  const measured = await first.getAttribute("data-sounding");
  expect(["true", "unknown"]).toContain(measured);

  // Whichever it is, the title says which number is on screen.
  const title = await first.getAttribute("title");
  expect(title).toBeTruthy();
  if (measured === "unknown") expect(title).toContain("not been measured");
  else expect(title).toContain("of sound");
});

test("sorting by sounding length keeps the list working", async ({ page }) => {
  // The server may not know this sort yet. The list falls back to wall
  // duration rather than showing the user a 422.
  await page.goto(`${WIDE}&sort=sounding&order=asc`);
  await waitForRows(page);
  await expect(page.locator(".error")).toHaveCount(0);
  await expect(page.getByTestId("result-count")).not.toContainText("loading");
});

test("the header's hours are whichever the server can report", async ({ page }) => {
  await page.goto("/");
  const bar = page.getByTestId("topbar-stats");
  await expect(bar).toContainText("sounds");

  const response = await page.request.get("/api/stats");
  const stats = (await response.json()) as Record<string, number | null>;
  const sounding = stats.total_sounding_s ?? stats.sounding_duration_s ?? null;

  if (sounding === null || sounding === undefined) {
    await expect(bar).toHaveAttribute("data-hours", "wall");
    await expect(bar).not.toContainText("sounding");
  } else {
    await expect(bar).toHaveAttribute("data-hours", "sounding");
    await expect(bar).toContainText(`${(sounding / 3600).toFixed(1)} h`);
  }
});

test("the detail view is honest about what has been measured", async ({ page }) => {
  const response = await page.request.get("/api/files?limit=1&sort=duration&order=desc");
  const row = ((await response.json()) as { items: Row[] }).items[0];
  await page.goto(`/sounds/${row.hash}`);
  await expect(page.getByTestId("detail")).toBeVisible();

  const served = await silenceServed(page);
  const silence = page.getByTestId("detail-silence");
  if (!served) {
    await expect(silence).toContainText("not measured");
    await expect(page.getByTestId("detail-sounding")).toHaveText("—");
  } else {
    await expect(silence).not.toContainText("not measured");
  }

  // Wall duration is on the page either way.
  await expect(page.getByTestId("detail-wall")).not.toHaveText("—");
});

test("a sound still plays when nothing about its silence is known", async ({ page }) => {
  await page.goto(`${WIDE}&sort=name`);
  await waitForRows(page);
  await page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first().click();
  await expect(page.getByTestId("player-bar")).toBeVisible();

  const time = () =>
    page.getByTestId("audio").evaluate((node) => (node as HTMLAudioElement).currentTime);
  await expect.poll(time, { timeout: 20_000 }).toBeGreaterThan(0.4);
});
