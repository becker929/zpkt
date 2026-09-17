/**
 * Streams the server transcodes cannot be seeked.
 *
 * AIF goes through ffmpeg on the way out. The response has no length until
 * ffmpeg finishes, so it carries `Accept-Ranges: none` and the browser has
 * nowhere to jump to. About 1,180 paths in the collection are AIF. The
 * interface must say so; a click that silently does nothing is the bug.
 */

import { expect, test } from "@playwright/test";

import { api } from "./helpers";

async function firstOfExt(page: import("@playwright/test").Page, ext: string): Promise<string> {
  const body = await api(page, `/api/files?ext=${encodeURIComponent(ext)}&limit=1&min_dur=5`);
  const items = body.items as Array<{ hash: string }>;
  expect(items.length, `no ${ext} in the fixture`).toBeGreaterThan(0);
  return items[0].hash;
}

test("the stream itself refuses ranges", async ({ page }) => {
  await page.goto("/");
  const hash = await firstOfExt(page, ".aif");
  const response = await page.request.get(`/api/files/${hash}/stream`);
  expect(response.headers()["accept-ranges"]).toBe("none");
});

test("the detail view says an AIF cannot be seeked", async ({ page }) => {
  await page.goto("/");
  const hash = await firstOfExt(page, ".aif");
  await page.goto(`/sounds/${hash}`);

  await expect(page.getByTestId("no-seek-note")).toBeVisible();
  await expect(page.getByTestId("no-seek-note")).toContainText("converted from AIF");
  await expect(page.getByTestId("detail").getByTestId("waveform")).toHaveAttribute(
    "data-seekable",
    "false",
  );
});

test("a WAV says nothing, because it seeks", async ({ page }) => {
  await page.goto("/");
  const hash = await firstOfExt(page, ".wav");
  await page.goto(`/sounds/${hash}`);

  await expect(page.getByTestId("detail")).toBeVisible();
  await expect(page.getByTestId("no-seek-note")).toHaveCount(0);
  await expect(page.getByTestId("detail").getByTestId("waveform")).toHaveAttribute(
    "data-seekable",
    "true",
  );
});

test("clicking the waveform of an AIF explains the refusal", async ({ page }) => {
  await page.goto("/");
  const hash = await firstOfExt(page, ".aif");
  await page.goto(`/sounds/${hash}`);

  await page.getByTestId("detail-play").click();
  await expect(page.getByTestId("player-bar")).toBeVisible();

  const waveform = page.getByTestId("detail").getByTestId("waveform");
  await expect.poll(async () => Number(await waveform.getAttribute("data-buckets"))).toBeGreaterThan(0);
  await waveform.click({ position: { x: 300, y: 40 } });

  await expect(page.getByTestId("player-notice")).toBeVisible();
  await expect(page.getByTestId("player-notice")).toContainText("no positions to seek to");
});

test("the player bar flags the loaded sound as unseekable", async ({ page }) => {
  await page.goto("/");
  const hash = await firstOfExt(page, ".aif");
  await page.goto(`/sounds/${hash}`);
  await page.getByTestId("detail-play").click();

  await expect(page.getByTestId("player-bar")).toContainText("no seeking");
  await expect(page.getByTestId("player-bar").getByTestId("waveform")).toHaveAttribute(
    "data-seekable",
    "false",
  );
});
