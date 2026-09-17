/**
 * Skipping silence on the phone.
 *
 * The phone is the primary target: most of this listening happens on an iPhone
 * over Tailscale. This project runs WebKit at 393 by 852 with touch, so it is
 * the only place that can show whether a third control fits in the player bar,
 * whether a thumb can hit it, and whether a scrub by touch is honoured.
 */

import { expect, test, type ConsoleMessage, type Page } from "@playwright/test";

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

/** The dev server's hot-reload socket, which says nothing about the page. */
const IGNORED = [/webpack-hmr/, /Failed to load resource/i];

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

async function findRow(
  page: Page,
  filter: string,
  want: (row: Row, intervals: Interval[]) => boolean,
): Promise<{ row: Row; index: number; intervals: Interval[] }> {
  const body = await api(page, `/api/files?${filter}&limit=20`);
  const items = body.items as Row[];
  for (let i = 0; i < items.length; i += 1) {
    const silence = await api(page, `/api/files/${items[i].hash}/silence`);
    const intervals = silence.intervals as Interval[];
    if (want(items[i], intervals)) return { row: items[i], index: i, intervals };
  }
  throw new Error(`no fixture row under ${filter} matched`);
}

function audioState(page: Page) {
  return page.getByTestId("audio").evaluate((node) => {
    const el = node as HTMLAudioElement;
    return { time: el.currentTime, paused: el.paused, duration: el.duration };
  });
}

const LEADING = "ext=.wav&min_dur=40&sort=name";
const hasLead = (_r: Row, gaps: Interval[]) =>
  gaps.length > 0 && gaps[0].start_s === 0 && gaps[0].end_s >= 6;

test("the skip toggle is a thumb-sized target and the bar still fits", async ({ page }) => {
  const errors = watchConsole(page);
  const { index } = await findRow(page, LEADING, hasLead);

  await page.goto(`/?${LEADING}`);
  await waitForRows(page);
  await page.locator(`[data-index="${index}"]`).tap();

  const bar = page.getByTestId("player-bar");
  await expect(bar).toBeVisible();

  const toggle = page.getByTestId("skip-toggle");
  const box = await toggle.boundingBox();
  expect(box, "the skip toggle has no box").not.toBeNull();
  expect(box!.width, "too small for a thumb").toBeGreaterThanOrEqual(32);
  expect(box!.height, "too small for a thumb").toBeGreaterThanOrEqual(32);

  // The bar holds three controls now. It must still sit inside the viewport,
  // not under the iOS toolbar.
  const viewport = page.viewportSize();
  const barBox = await bar.boundingBox();
  expect(barBox!.y + barBox!.height).toBeLessThanOrEqual(viewport!.height + 1);

  // And the name it belongs to is still readable beside it.
  const name = await bar.locator(".who").boundingBox();
  expect(name!.width).toBeGreaterThan(150);

  await page.waitForTimeout(400);
  expect(errors, "the phone logged console errors").toEqual([]);
});

test("the leading silence is gone by the time a thumb lets go", async ({ page }) => {
  const { row, index, intervals } = await findRow(page, LEADING, hasLead);
  const lead = intervals[0].end_s;

  await page.goto(`/?${LEADING}`);
  await waitForRows(page);
  await page.locator(`[data-index="${index}"]`).tap();
  await expect(page.getByTestId("player-bar")).toHaveAttribute("data-hash", row.hash);

  await expect
    .poll(async () => (await audioState(page)).time, {
      message: "the phone sat through the leading silence",
      timeout: 6_000,
    })
    .toBeGreaterThanOrEqual(lead - 0.1);
});

test("tapping the toggle does not also judge the sound", async ({ page }) => {
  // The toggle sits beside the star and the discard button, which are the two
  // most-used controls in the interface. A thumb that hits the wrong one of
  // three would be discarding sounds by accident.
  const { index } = await findRow(page, LEADING, hasLead);
  await page.goto(`/?${LEADING}`);
  await waitForRows(page);
  await page.locator(`[data-index="${index}"]`).tap();

  const favorite = page.getByTestId("player-favorite");
  const before = await favorite.innerText();

  await page.getByTestId("skip-toggle").tap();
  await expect(page.getByTestId("skip-toggle")).toHaveAttribute("aria-pressed", "false");
  await expect(favorite).toHaveText(before);
  await expect(page.getByTestId("undo-bar")).toHaveCount(0);
});

test("a scrub by touch into silence is honoured", async ({ page }) => {
  const filter = "ext=.wav&min_dur=60&sort=name";
  const { row, index, intervals } = await findRow(page, filter, (_r, gaps) =>
    gaps.some((g, i) => i > 0 && g.end_s - g.start_s >= 8),
  );
  const gap = intervals.find((g, i) => i > 0 && g.end_s - g.start_s >= 8)!;

  await page.goto(`/?${filter}`);
  await waitForRows(page);
  await page.locator(`[data-index="${index}"]`).tap();
  await expect(page.getByTestId("player-bar")).toHaveAttribute("data-hash", row.hash);

  // The detail view's waveform is the one with room to aim at. Reaching it
  // through the player bar's link keeps the sound playing.
  await page.getByTestId("player-bar").locator("a").first().tap();
  await expect(page.getByTestId("detail")).toBeVisible();
  await expect.poll(async () => (await audioState(page)).duration).toBeGreaterThan(0);

  const waveform = page.getByTestId("detail").getByTestId("waveform");
  const box = await waveform.boundingBox();
  const x = ((gap.start_s + 2) / row.duration_s) * box!.width;
  await waveform.tap({ position: { x, y: box!.height / 2 } });

  await expect.poll(async () => (await audioState(page)).time, { timeout: 5_000 }).toBeGreaterThanOrEqual(
    gap.start_s,
  );

  // Two seconds on, the playhead is still in the stretch that was asked for.
  await page.waitForTimeout(2_000);
  const after = await audioState(page);
  expect(after.time, "the skipper fought a deliberate scrub").toBeLessThan(gap.end_s);
  expect(after.time).toBeGreaterThan(gap.start_s);
});
