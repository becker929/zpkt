/**
 * The detail view: waveform, alias list, and what the paths panel concludes
 * about a sound stored more than once.
 *
 * The verdict is the part worth locking down. Three different facts share the
 * same panel, and getting them confused is how a user ends up deleting a safety
 * copy or a Logic project's own media.
 */

import { expect, test } from "@playwright/test";

import { api, paintedPixels } from "./helpers";

interface Alias {
  path: string;
  root: string;
}

/**
 * Find a fixture sound whose paths match a shape the panel has to handle.
 *
 * The list response carries the path count, so only candidates with the right
 * count need a detail fetch. The search is bounded so a fixture change shows up
 * as a clear failure rather than a slow one.
 */
async function findFile(
  page: import("@playwright/test").Page,
  wanted: "mirror" | "bundle" | "single",
): Promise<{ hash: string; aliases: Alias[] }> {
  const body = await api(page, "/api/files?limit=400&sort=name");
  const rows = (body.items as Array<{ hash: string; alias_count: number }>).filter((r) =>
    wanted === "single" ? r.alias_count === 1 : r.alias_count > 1,
  );

  for (const row of rows.slice(0, 40)) {
    if (wanted === "single") return { hash: row.hash, aliases: [] };
    const detail = await api(page, `/api/files/${row.hash}`);
    const aliases = detail.aliases as Alias[];
    const roots = new Set(aliases.map((a) => a.root));
    const bundles = aliases.filter((a) => a.path.includes(".logicx/")).length;
    if (wanted === "bundle" && bundles > 1) return { hash: row.hash, aliases };
    if (wanted === "mirror" && bundles === 0 && aliases.length > 1 && roots.size === aliases.length) {
      return { hash: row.hash, aliases };
    }
  }
  throw new Error(`no fixture sound within the first 40 candidates is a ${wanted} case`);
}

test("the detail page lists every alias of the hash", async ({ page }) => {
  const body = await api(page, "/api/files?limit=200&sort=name");
  const rows = body.items as Array<{ hash: string; alias_count: number }>;
  const target = rows.find((r) => r.alias_count >= 3) ?? rows[0];

  await page.goto(`/sounds/${target.hash}`);
  await expect(page.getByTestId("detail")).toBeVisible();

  // The alias panel is the point of the page: a sound with five paths shows
  // all five, not a count.
  await expect(page.getByTestId("alias")).toHaveCount(target.alias_count);
  const shown = await page.getByTestId("alias").locator(".path").allTextContents();
  const detail = await api(page, `/api/files/${target.hash}`);
  expect(shown.sort()).toEqual((detail.aliases as Alias[]).map((a) => a.path).sort());
});

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

test("one copy per root is called a working copy, not waste", async ({ page }) => {
  const { hash } = await findFile(page, "mirror");
  await page.goto(`/sounds/${hash}`);
  await expect(page.getByTestId("mirror-note")).toBeVisible();
  await expect(page.getByTestId("mirror-note")).toContainText("not wasted space");
  await expect(page.getByTestId("dupe-note")).toHaveCount(0);
});

test("copies inside a project bundle are never called reclaimable", async ({ page }) => {
  const { hash } = await findFile(page, "bundle");
  await page.goto(`/sounds/${hash}`);

  const note = page.getByTestId("dupe-note");
  await expect(note).toBeVisible();
  await expect(note).toHaveAttribute("data-reclaimable", "false");
  await expect(note).toContainText("Nothing here can be reclaimed");
  // No figure that reads as space to be freed.
  await expect(note).not.toContainText("frees");
  // And each such path is marked where it is listed.
  await expect(page.getByTestId("alias-locked").first()).toBeVisible();
});

test("a sound with one path gets no note at all", async ({ page }) => {
  const { hash } = await findFile(page, "single");
  await page.goto(`/sounds/${hash}`);
  await expect(page.getByTestId("alias")).toHaveCount(1);
  await expect(page.getByTestId("dupe-note")).toHaveCount(0);
  await expect(page.getByTestId("mirror-note")).toHaveCount(0);
});

test("the detail page favourite toggle writes through to the server", async ({ page }) => {
  const body = await api(page, "/api/files?limit=1&sort=name");
  const hash = (body.items as Array<{ hash: string }>)[0].hash;
  await page.goto(`/sounds/${hash}`);

  const toggle = page.getByTestId("detail-favorite");
  const before = (await toggle.getAttribute("aria-pressed")) === "true";
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", String(!before));

  await page.reload();
  await expect(page.getByTestId("detail-favorite")).toHaveAttribute("aria-pressed", String(!before));

  // Leave the fixture as it was found.
  await page.getByTestId("detail-favorite").click();
  await expect(page.getByTestId("detail-favorite")).toHaveAttribute("aria-pressed", String(before));
});
