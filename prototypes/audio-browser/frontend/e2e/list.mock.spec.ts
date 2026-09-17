/**
 * The list view: rendering, virtualisation, search, favourites, and the shape
 * of the URL the audio element is given.
 */

import { expect, test } from "@playwright/test";

import { STREAM_URL, api, paintedPixels, renderedRowCount, waitForRows } from "./helpers";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await waitForRows(page);
});

test("the list loads the whole collection", async ({ page }) => {
  const body = await api(page, "/api/files?limit=1");
  expect(body.total).toBe(3451);
  await expect(page.getByTestId("row").first()).toBeVisible();
});

test("only the visible window exists in the DOM", async ({ page }) => {
  // 3,451 rows rendered outright stalls the tab. The scroller is sized for the
  // whole set; the DOM holds the window plus a small overscan.
  const rendered = await renderedRowCount(page);
  expect(rendered).toBeGreaterThan(5);
  expect(rendered).toBeLessThan(120);
});

test("scrolling swaps the rows rather than adding to them", async ({ page }) => {
  const firstIndex = async () =>
    Number(await page.getByTestId("row").first().getAttribute("data-index"));

  expect(await firstIndex()).toBe(0);
  await page.getByTestId("scroller").evaluate((node) => {
    node.scrollTop = 20000;
  });
  await expect.poll(firstIndex).toBeGreaterThan(400);

  // Still a window, not a grown list.
  expect(await renderedRowCount(page)).toBeLessThan(120);

  // And the rows that arrive are real, not placeholders.
  await expect
    .poll(async () => page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').count())
    .toBeGreaterThan(0);
});

test("search narrows the list", async ({ page }) => {
  await expect(page.getByTestId("result-count")).toHaveText("3,451 sounds");

  await page.getByTestId("search").fill("kick");
  await expect(page.getByTestId("result-count")).not.toHaveText("3,451 sounds");
  await expect(page.getByTestId("result-count")).toContainText("sounds");

  // Every rendered row matches the term. The filtered page arrives a moment
  // after the count, so poll until no stale row is left.
  await expect
    .poll(async () => {
      const names = await page.locator('[data-testid="row"] .col-name a').allTextContents();
      return names.length > 0 && names.every((n) => n.toLowerCase().includes("kick"));
    })
    .toBe(true);
});

test("clearing the search restores the list", async ({ page }) => {
  const box = page.getByTestId("search");
  await box.fill("kick");
  // The count settles after the debounce, so wait on it rather than on the
  // rows: the old page is still on screen for a moment.
  await expect(page.getByTestId("result-count")).not.toHaveText("3,451 sounds");
  await expect
    .poll(async () => page.locator('[data-testid="row"] .col-name a').first().textContent())
    .toContain("kick");

  await box.fill("");
  await expect(page.getByTestId("result-count")).toHaveText("3,451 sounds");
  await expect
    .poll(async () => page.locator('[data-testid="row"] .col-name a').first().textContent())
    .not.toContain("kick");
});

test("a search that matches nothing says so", async ({ page }) => {
  await page.getByTestId("search").fill("zzzz-no-such-sound");
  await expect(page.getByText("nothing matches this filter.")).toBeVisible();
});

test("a favourite survives a reload", async ({ page }) => {
  // Favourites attach to the hash, so the state must come back from the server
  // rather than from component memory.
  const row = page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first();
  const hash = await row.getAttribute("data-hash");
  const toggle = row.getByTestId("favorite-toggle");
  const before = await toggle.getAttribute("aria-pressed");

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", before === "true" ? "false" : "true");

  await page.reload();
  await waitForRows(page);
  const after = page.locator(`[data-testid="row"][data-hash="${hash}"] [data-testid="favorite-toggle"]`);
  await expect(after).toHaveAttribute("aria-pressed", before === "true" ? "false" : "true");

  // Put it back, so the next test starts from the same collection.
  await after.click();
  await expect(after).toHaveAttribute("aria-pressed", before ?? "false");
});

test("a favourite set on one hash is visible through the filter", async ({ page }) => {
  const row = page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first();
  const hash = await row.getAttribute("data-hash");
  const toggle = row.getByTestId("favorite-toggle");
  const wasFavorite = (await toggle.getAttribute("aria-pressed")) === "true";
  if (wasFavorite) test.skip(true, "the first row is already a favourite");

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");

  const favorites = await api(page, "/api/files?favorite=true&limit=1000");
  const hashes = (favorites.items as Array<{ hash: string }>).map((f) => f.hash);
  expect(hashes).toContain(hash);

  await page.locator(`[data-testid="row"][data-hash="${hash}"] [data-testid="favorite-toggle"]`).click();
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
});

test("the audio element is handed a hash, never a path", async ({ page }) => {
  // This is the whole defence against path traversal, so it is checked in the
  // browser and not only in the server tests.
  await page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first().click();
  await expect(page.getByTestId("player-bar")).toBeVisible();

  const src = await page.getByTestId("audio").evaluate((node) => (node as HTMLAudioElement).src);
  expect(new URL(src).pathname).toMatch(STREAM_URL);
  expect(src).not.toContain("daw-library");
  expect(src).not.toContain("..");
});

test("the player bar paints a waveform for the clicked row", async ({ page }) => {
  await page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first().click();
  const waveform = page.getByTestId("player-bar").getByTestId("waveform");
  await expect(waveform).toBeVisible();
  await expect.poll(async () => Number(await waveform.getAttribute("data-buckets"))).toBeGreaterThan(0);
  await expect.poll(async () => paintedPixels(waveform)).toBeGreaterThan(500);
});

test("clicking a row's name opens its detail page", async ({ page }) => {
  const row = page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first();
  const hash = await row.getAttribute("data-hash");
  await row.locator(".col-name a").click();
  await expect(page.getByTestId("detail")).toHaveAttribute("data-hash", hash ?? "");
});
