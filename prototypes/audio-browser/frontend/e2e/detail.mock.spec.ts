/**
 * The detail view: one sound, its waveform, and one classifier's spans.
 *
 * There is no list of paths here any more. A path is a name for a hash, and
 * content addressing made that list correct rather than interesting; what the
 * page is about is the sound.
 */

import { expect, test } from "@playwright/test";

import { api, paintedPixels } from "./helpers";

test("the detail page paints its waveform from the peaks endpoint", async ({ page }) => {
  const body = await api(page, "/api/files?limit=1&min_dur=2");
  const hash = (body.items as Array<{ hash: string }>)[0].hash;

  // Nothing decodes audio in the browser. If the canvas has ink, it came from
  // the peaks route.
  let peaksRequested = false;
  page.on("request", (req) => {
    if (req.url().includes(`/api/files/${hash}/peaks`)) peaksRequested = true;
  });

  await page.goto(`/sounds/${hash}`);
  const waveform = page.getByTestId("detail").getByTestId("waveform");
  await expect.poll(async () => Number(await waveform.getAttribute("data-buckets"))).toBe(1000);
  await expect.poll(async () => paintedPixels(waveform)).toBeGreaterThan(1000);
  expect(peaksRequested).toBe(true);
});

test("it asks one classifier for spans and tints only those", async ({ page }) => {
  // The bakeoff found YAMNet and an unrelated model agree 82.9% of the time
  // while CLAP agrees with neither. Three tints over one second is a picture of
  // that disagreement and says nothing, so one method is asked for by name.
  const asked: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.endsWith("/spans")) asked.push(url.search);
  });

  const body = await api(page, "/api/files?limit=40&min_dur=4&sort=name");
  const rows = body.items as Array<{ hash: string }>;
  // Half the fixture carries spans, so find one that does.
  let withSpans: string | null = null;
  for (const row of rows) {
    const spans = await api(page, `/api/files/${row.hash}/spans?method=yamnet`);
    if ((spans.spans as unknown[]).length > 0) {
      withSpans = row.hash;
      break;
    }
  }
  expect(withSpans, "no fixture sound in the first 40 carries spans").toBeTruthy();

  const before = asked.length;
  await page.goto(`/sounds/${withSpans}`);
  await expect(page.getByTestId("detail")).toBeVisible();
  await expect(page.getByTestId("span-method")).toHaveAttribute("data-method", "yamnet");

  expect(asked.length).toBeGreaterThan(before);
  for (const search of asked.slice(before)) expect(search).toBe("?method=yamnet");
});

test("the paths panel is gone, and so is the star", async ({ page }) => {
  const body = await api(page, "/api/files?limit=1&sort=name");
  const hash = (body.items as Array<{ hash: string }>)[0].hash;
  await page.goto(`/sounds/${hash}`);
  await expect(page.getByTestId("detail")).toBeVisible();

  await expect(page.getByTestId("alias-list")).toHaveCount(0);
  await expect(page.getByTestId("alias")).toHaveCount(0);
  await expect(page.getByTestId("detail-favorite")).toHaveCount(0);
  // Nothing on the page names a place on disk.
  expect(await page.getByTestId("detail").textContent()).not.toContain("/Users/");
});

test("discarding from the detail page writes through and can be undone", async ({ page }) => {
  const body = await api(page, "/api/files?limit=1&sort=name");
  const hash = (body.items as Array<{ hash: string }>)[0].hash;
  await page.goto(`/sounds/${hash}`);

  const button = page.getByTestId("detail-discard");
  await expect(button).toHaveAttribute("aria-pressed", "false");
  await button.click();
  await expect(button).toHaveAttribute("aria-pressed", "true");
  expect((await api(page, `/api/files/${hash}`)).deleted).toBe(true);

  await button.click();
  await expect(button).toHaveAttribute("aria-pressed", "false");
  await expect.poll(async () => (await api(page, `/api/files/${hash}`)).deleted).toBe(false);
});
