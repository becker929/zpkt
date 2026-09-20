/**
 * The collage view against the real stack, reading only.
 *
 * The project in `collage` here is one of the user's real projects (HW011 on
 * the day this was written). Opening it, listing its sounds, hearing one, and
 * fetching a slice are all reads and are checked here against real material:
 * fifteen sources, one of them nearly fifteen minutes long, with filenames
 * that carry dates and clock times of their own.
 *
 * Nothing here stamps, saves, or undoes. Every request the page makes that is
 * not a read is refused before it leaves the browser and fails the test, and
 * `live-guard` fingerprints the projects directory around the whole live run.
 * Every write is exercised against the mock server in `collage.mock.spec.ts`
 * and `collage.mobile.spec.ts`.
 */

import { expect, test, type Page } from "@playwright/test";

/** Refuse and record any request that is not a read. */
function readOnly(page: Page): string[] {
  const writes: string[] = [];
  void page.route("**/api/**", async (route) => {
    const method = route.request().method();
    if (method === "GET" || method === "HEAD" || method === "OPTIONS") return route.continue();
    writes.push(`${method} ${new URL(route.request().url()).pathname}`);
    return route.abort();
  });
  return writes;
}

test("opens the real project in collage, and the picker holds its frozen set", async ({ page }) => {
  const index = await page.request.get("/api/projects");
  test.skip(!index.ok(), "projects are not being served");
  const items = ((await index.json()) as { items: Array<{ id: string; column: string; abandoned: unknown }> }).items;
  const inCollage = items.filter((p) => p.column === "collage" && p.abandoned === null);
  test.skip(inCollage.length === 0, "nothing is in collage");

  const writes = readOnly(page);
  await page.goto("/collage");
  await expect(page.getByTestId("collage")).toBeVisible();
  const id = await page.getByTestId("collage").getAttribute("data-project-id");
  expect(inCollage.map((p) => p.id)).toContain(id);

  const detail = (await (await page.request.get(`/api/projects/${id}`)).json()) as {
    items: Array<{ hash: string; duration_s: number | null; filename: string }>;
    document: { collage?: { regions: unknown[] } | null };
  };
  // What is drawn is what the file holds, no more.
  await expect(page.getByTestId("region")).toHaveCount(detail.document.collage?.regions.length ?? 0);

  await page.getByTestId("collage-choose").click();
  await expect(page.getByTestId("collage-picker")).toBeVisible();
  await expect(page.getByTestId("picker-row")).toHaveCount(detail.items.length);
  for (const row of detail.items) {
    await expect(page.locator(`[data-testid="picker-row"][data-hash="${row.hash}"]`)).toHaveCount(1);
  }

  // Hear the longest one: streamed by hash, not decoded.
  const longest = detail.items.reduce((m, r) => ((r.duration_s ?? 0) > (m.duration_s ?? 0) ? r : m));
  await page.locator(`[data-testid="picker-row"][data-hash="${longest.hash}"]`).click();
  const audio = page.getByTestId("audio");
  await expect.poll(async () => audio.evaluate((node) => (node as HTMLAudioElement).src)).toContain(longest.hash);
  await expect(page.getByTestId("picker-preview")).toBeVisible();

  // Choosing it is still only a choice. Nothing is written until a stamp.
  await page.getByTestId("picker-use").click();
  await expect(page.getByTestId("collage-picker")).toHaveCount(0);
  await expect(page.getByTestId("collage-choose")).toHaveAttribute("data-hash", longest.hash);
  expect(writes).toEqual([]);
});

test("a bounded slice of a real source answers 48 kHz stereo WAV", async ({ page }) => {
  const index = await page.request.get("/api/projects");
  test.skip(!index.ok(), "projects are not being served");
  const items = ((await index.json()) as { items: Array<{ id: string; column: string; abandoned: unknown }> }).items;
  const project = items.find((p) => p.column === "collage" && p.abandoned === null);
  test.skip(!project, "nothing is in collage");
  const detail = (await (await page.request.get(`/api/projects/${project!.id}`)).json()) as {
    items: Array<{ hash: string; duration_s: number | null }>;
  };
  const sound = detail.items.find((r) => (r.duration_s ?? 0) >= 2);
  test.skip(!sound, "no sound two seconds long to cut from");

  const slice = await page.request.get(`/api/files/${sound!.hash}/slice?start=0.5&end=1.5`);
  expect(slice.status()).toBe(200);
  expect(slice.headers()["content-type"]).toContain("audio/wav");
  const bytes = Buffer.from(await slice.body());
  expect(bytes.subarray(0, 4).toString()).toBe("RIFF");
  expect(bytes.readUInt16LE(22)).toBe(2);
  expect(bytes.readUInt32LE(24)).toBe(48000);
  expect(bytes.length).toBe(44 + 48000 * 4);
});

test("no seconds, no grid, no decibels on the real material", async ({ page }) => {
  const index = await page.request.get("/api/projects");
  test.skip(!index.ok(), "projects are not being served");
  const items = ((await index.json()) as { items: Array<{ column: string; abandoned: unknown }> }).items;
  test.skip(!items.some((p) => p.column === "collage" && p.abandoned === null), "nothing is in collage");

  readOnly(page);
  await page.goto("/collage");
  await expect(page.getByTestId("collage")).toBeVisible();

  // The mode buttons are drawn against the real material and refuse until
  // there is something for them to act on. Nothing here takes a region up:
  // that is a read, but the level or the cut it would then set would not be.
  await expect(page.getByTestId("collage-balance")).toBeDisabled();
  await expect(page.getByTestId("collage-stretch")).toBeDisabled();

  await page.getByTestId("collage-choose").click();
  await expect(page.getByTestId("collage-picker")).toBeVisible();

  // The view's own text, and the text it hangs on titles and labels. Real
  // filenames carry clock times (`…T16:22:55Z.m4a`), and a filename is the
  // sound's name, not a reading of it; a time the interface printed would
  // stand on its own, with a space or the start of a line before it.
  const text = await page.getByTestId("collage").innerText();
  const attrs = await page.getByTestId("collage").evaluate((node) =>
    Array.from(node.querySelectorAll("[title],[aria-label]"))
      .map((n) => `${n.getAttribute("title") ?? ""} ${n.getAttribute("aria-label") ?? ""}`)
      .join("\n"),
  );
  const all = `${text}\n${attrs}`;
  expect(all).not.toMatch(/(?:^|\s)\d{1,2}:\d\d(?::\d\d)?(?:\s|$)/m);
  expect(all).not.toMatch(/(?:^|\s)\d+(?:[.,]\d+)?\s?(?:s|sec|secs|ms|min|mins|h)(?:\s|$)/im);
  expect(all).not.toMatch(/\bdB\b/i);
  // Nothing drawn on the blank but regions.
  expect(await page.getByTestId("collage-space").locator(":scope > :not([data-testid='region'])").count()).toBe(0);

  // The header above the view has dropped its hours of sound. The real
  // collection's total would otherwise sit over a screen that never says a
  // number of seconds.
  const stats = page.getByTestId("topbar-stats");
  await expect(stats).toHaveAttribute("data-hours", "hidden");
  await expect(stats).not.toHaveText("…");
  expect(await stats.innerText()).not.toMatch(/\d(?:[.,]\d+)?\s?h\b/);
});
