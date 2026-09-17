/**
 * The search view: matches only, and the shape of the URL the audio element is
 * given.
 *
 * An empty query shows an empty view. That is the rule the whole interface
 * turns on: no surface lists the undecided collection, so a search box that
 * answered "nothing typed" with 3,451 rows would put the catalogue straight
 * back.
 */

import { expect, test } from "@playwright/test";

import { STREAM_URL, paintedPixels, renderedRowCount, waitForHydration, waitForRows } from "./helpers";

test("an empty query is an empty view", async ({ page }) => {
  await page.goto("/search");
  await expect(page.getByTestId("search-idle")).toBeVisible();
  await expect(page.getByTestId("row")).toHaveCount(0);
  await expect(page.getByTestId("scroller")).toHaveCount(0);
});

test("typing a name lists the matches and nothing else", async ({ page }) => {
  await page.goto("/search");
  await waitForHydration(page);
  await page.getByTestId("search").fill("kick");
  await expect(page.getByTestId("search")).toHaveValue("kick");
  await waitForRows(page);

  await expect(page.getByTestId("result-count")).toContainText("sounds");
  await expect(page.getByTestId("result-count")).not.toHaveText("3,451 sounds");

  // Every rendered row matches the term. The filtered page arrives a moment
  // after the count, so poll until no stale row is left.
  await expect
    .poll(async () => {
      const names = await page.locator('[data-testid="row"] .col-name a').allTextContents();
      return names.length > 0 && names.every((n) => n.toLowerCase().includes("kick"));
    })
    .toBe(true);
});

test("clearing the query empties the view rather than opening the collection", async ({ page }) => {
  await page.goto("/search?q=kick");
  await waitForRows(page);
  await page.getByTestId("search").fill("");
  await expect(page.getByTestId("search")).toHaveValue("");
  await expect(page.getByTestId("search-idle")).toBeVisible();
  await expect(page.getByTestId("row")).toHaveCount(0);
});

test("a search that matches nothing says so", async ({ page }) => {
  await page.goto("/search?q=zzzz-no-such-sound");
  await expect(page.getByTestId("list-empty")).toContainText("zzzz-no-such-sound");
  await expect(page.getByTestId("row")).toHaveCount(0);
});

test("only the visible window of a large match exists in the DOM", async ({ page }) => {
  // A common term still matches hundreds of rows. Rendering them outright
  // stalls the tab; the scroller is sized for the set and the DOM holds the
  // window plus a small overscan.
  await page.goto("/search?q=a");
  await waitForRows(page);
  const rendered = await renderedRowCount(page);
  expect(rendered).toBeGreaterThan(5);
  expect(rendered).toBeLessThan(120);

  const firstIndex = async () => Number(await page.getByTestId("row").first().getAttribute("data-index"));
  expect(await firstIndex()).toBe(0);
  await page.getByTestId("scroller").evaluate((node) => {
    node.scrollTop = 6000;
  });
  await expect.poll(firstIndex).toBeGreaterThan(50);
  expect(await renderedRowCount(page)).toBeLessThan(120);
});

test("a search reaches a sound that was discarded", async ({ page }) => {
  // Hiding a discarded sound from a search for its own name would make the
  // discard pile unreachable by name, which is the one thing a search is for.
  const response = await page.request.get("/api/files?q=kick&limit=1&sort=name");
  const hash = ((await response.json()) as { items: Array<{ hash: string; filename: string }> }).items[0];
  await page.request.put(`/api/files/${hash.hash}/deleted`);

  try {
    await page.goto(`/search?q=${encodeURIComponent(hash.filename)}`);
    await waitForRows(page);
    await expect(page.locator(`[data-testid="row"][data-hash="${hash.hash}"]`)).toBeVisible();
  } finally {
    await page.request.delete(`/api/files/${hash.hash}/deleted`);
  }
});

test("the audio element is handed a hash, never a path", async ({ page }) => {
  await page.goto("/search?q=kick");
  await waitForRows(page);
  await page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first().click();
  await expect(page.getByTestId("player-bar")).toBeVisible();

  const src = await page.getByTestId("audio").evaluate((node) => (node as HTMLAudioElement).src);
  expect(new URL(src).pathname).toMatch(STREAM_URL);
  expect(src).not.toContain("daw-library");
  expect(src).not.toContain("..");
});

test("the player bar paints a waveform for the clicked row", async ({ page }) => {
  await page.goto("/search?q=kick");
  await waitForRows(page);
  await page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first().click();
  const waveform = page.getByTestId("player-bar").getByTestId("waveform");
  await expect(waveform).toBeVisible();
  await expect.poll(async () => Number(await waveform.getAttribute("data-buckets"))).toBeGreaterThan(0);
  await expect.poll(async () => paintedPixels(waveform)).toBeGreaterThan(500);
});

test("clicking a row's name opens its detail page", async ({ page }) => {
  await page.goto("/search?q=kick");
  await waitForRows(page);
  const row = page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first();
  const hash = await row.getAttribute("data-hash");
  await row.locator(".col-name a").click();
  await expect(page.getByTestId("detail")).toHaveAttribute("data-hash", hash ?? "");
});
