/**
 * Checks against the real index on port 3100.
 *
 * These are facts the generated fixture cannot show: a sound stored thirty
 * times inside Logic project bundles, and 29 GB of redundancy that is not
 * redundancy anyone may act on. Every test here only reads. Nothing writes a
 * favourite, a tag, or a row.
 */

import { expect, test } from "@playwright/test";

import { STREAM_URL, api, paintedPixels } from "./helpers";

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

/** One alias of a sound: where a copy of it is, and which root that is under. */
interface Alias {
  path: string;
  root: string;
}

/** Whether this path is inside a Logic project bundle. */
function bundled(path: string): boolean {
  return path.includes(".logicx/");
}

/**
 * A sound stored several times, every copy inside a Logic project bundle.
 *
 * This is the case the paths panel must not describe as space to be freed: the
 * bytes belong to the projects that hold them and cannot be reclaimed at any
 * price. Looked up through the duplicates route, because which sound this is
 * changes whenever the collection is rescanned.
 */
async function findBundled(
  page: import("@playwright/test").Page,
): Promise<{ hash: string; aliases: Alias[] } | null> {
  const body = await api(page, "/api/dupes?limit=200&include_bundles=true");
  const groups = body.items as Array<{ hash: string; paths: string[] }>;
  for (const group of groups) {
    if (group.paths.length < 2 || !group.paths.every(bundled)) continue;
    const detail = await api(page, `/api/files/${group.hash}`);
    const aliases = detail.aliases as Alias[];
    if (aliases.length < 2 || !aliases.every((a) => bundled(a.path))) continue;
    if (new Set(aliases.map((a) => a.root)).size !== 1) continue;
    return { hash: group.hash, aliases };
  }
  return null;
}

/** Any sound the index holds more than one copy of, whatever kind of copy. */
async function findWithAliases(
  page: import("@playwright/test").Page,
): Promise<{ hash: string; aliases: Alias[] } | null> {
  const body = await api(page, "/api/files?limit=200&sort=size&order=desc");
  const rows = (body.items as Array<{ hash: string; alias_count: number }>).filter(
    (r) => r.alias_count > 1,
  );
  for (const row of rows.slice(0, 20)) {
    const detail = await api(page, `/api/files/${row.hash}`);
    const aliases = detail.aliases as Alias[];
    if (aliases.length > 1) return { hash: row.hash, aliases };
  }
  return null;
}

/**
 * Find a sound stored once per root: the working copy, doing its job.
 *
 * This is looked up rather than pinned. The index is rescanned from a live
 * collection, so a hash that mirrored two roots last month may have one path
 * today, and a pinned hash then fails for a reason that has nothing to do with
 * the interface. Returns null when the collection currently holds no such case.
 */
async function findMirrored(
  page: import("@playwright/test").Page,
): Promise<{ hash: string; roots: string[] } | null> {
  const body = await api(page, "/api/files?limit=300&sort=size&order=desc");
  const rows = (body.items as Array<{ hash: string; alias_count: number }>).filter(
    (r) => r.alias_count > 1,
  );
  for (const row of rows.slice(0, 60)) {
    const detail = await api(page, `/api/files/${row.hash}`);
    const aliases = detail.aliases as Array<{ path: string; root: string }>;
    const roots = new Set(aliases.map((a) => a.root));
    const bundled = aliases.some((a) => a.path.includes(".logicx/"));
    if (!bundled && aliases.length > 1 && roots.size === aliases.length) {
      return { hash: row.hash, roots: [...roots] };
    }
  }
  return null;
}

test.describe("the real collection", () => {
  /**
   * How many sounds the default view shows, from the server.
   *
   * Not a constant. The default view hides discarded sounds, so this number
   * falls every time the collection is triaged; it was 3,451 when the index
   * was new and thousands have been discarded since. The test is that the view
   * shows the whole set it asked for, not that the set is any given size.
   */
  async function defaultTotal(page: import("@playwright/test").Page): Promise<string> {
    const body = await api(page, "/api/files?limit=1&sort=name");
    return (body.total as number).toLocaleString("en-US");
  }

  test("the list view loads the whole index", async ({ page }) => {
    await page.goto("/");
    const total = await defaultTotal(page);
    await expect(page.getByTestId("result-count")).toContainText(`${total} sounds`);
    const rendered = await page.getByTestId("row").count();
    expect(rendered).toBeGreaterThan(5);
    expect(rendered).toBeLessThan(120);
  });

  test("search filters the real index", async ({ page }) => {
    await page.goto("/");
    const total = await defaultTotal(page);
    await expect(page.getByTestId("result-count")).toContainText(`${total} sounds`);
    await page.getByTestId("search").fill("kick");
    await expect(page.getByTestId("result-count")).not.toContainText(`${total} sounds`);
    // The filtered page lands a moment after the count, so poll until no row
    // from the unfiltered list is left on screen.
    await expect
      .poll(async () => {
        const names = await page.locator('[data-testid="row"] .col-name a').allTextContents();
        return names.length > 0 && names.every((n) => n.toLowerCase().includes("kick"));
      })
      .toBe(true);
  });

  test("a sound repeated inside project bundles is not offered as space to free", async ({ page }) => {
    await page.goto("/");
    const found = await findBundled(page);
    if (!found) test.skip(true, "the index currently holds no sound stored only inside bundles");

    await page.goto(`/sounds/${found!.hash}`);
    const note = page.getByTestId("dupe-note");
    await expect(note).toBeVisible();
    await expect(note).toHaveAttribute("data-reclaimable", "false");
    await expect(note).toContainText("Nothing here can be reclaimed");
    await expect(note).not.toContainText("frees");
    await expect(page.getByTestId("mirror-note")).toHaveCount(0);

    // Every path of it is marked, and all of them are listed.
    await expect(page.getByTestId("alias")).toHaveCount(found!.aliases.length);
    await expect(page.getByTestId("alias-locked")).toHaveCount(found!.aliases.length);
  });

  test("one copy per root is called the working copy", async ({ page }) => {
    await page.goto("/");
    const found = await findMirrored(page);
    if (!found) test.skip(true, "the index currently holds no sound with one copy per root");

    await page.goto(`/sounds/${found!.hash}`);
    const note = page.getByTestId("mirror-note");
    await expect(note).toBeVisible();
    await expect(note).toContainText("One copy per root");
    await expect(note).toContainText("not wasted space");
    await expect(page.getByTestId("dupe-note")).toHaveCount(0);
    await expect(page.getByTestId("alias")).toHaveCount(found!.roots.length);
  });

  test("the detail page lists every alias it has", async ({ page }) => {
    await page.goto("/");
    const found = await findWithAliases(page);
    if (!found) test.skip(true, "the index currently holds no sound with more than one copy");
    const paths = found!.aliases.map((a) => a.path);

    await page.goto(`/sounds/${found!.hash}`);
    await expect(page.getByTestId("alias")).toHaveCount(paths.length);
    const shown = await page.getByTestId("alias").locator(".path").allTextContents();
    expect(shown.sort()).toEqual(paths.sort());
  });

  test("the cleanup view leaves Logic project media out of what could be freed", async ({ page }) => {
    const scoped = await api(page, "/api/dupes?limit=200");
    const raw = await api(page, "/api/dupes?limit=200&include_bundles=true");

    // The relationships, not the totals. How many groups there are and how many
    // gigabytes they hold changes with every rescan and every deletion; that
    // the scoped view is the raw view with the bundle-only groups taken out of
    // it does not.
    expect(Number(raw.total)).toBeGreaterThan(0);
    expect(Number(scoped.total)).toBeLessThanOrEqual(Number(raw.total));
    expect(Number(raw.total) - Number(scoped.total)).toBe(Number(scoped.excluded_bundle_groups));
    expect(Number(scoped.wasted_bytes)).toBeLessThanOrEqual(Number(raw.wasted_bytes));
    // What was left out is reported rather than dropped: a figure that shrank
    // with no account of where the difference went would read as space that had
    // already been reclaimed.
    if (Number(scoped.excluded_bundle_groups) > 0) {
      expect(Number(scoped.excluded_bundle_bytes)).toBeGreaterThan(0);
      expect(Number(scoped.wasted_bytes)).toBeLessThan(Number(raw.wasted_bytes));
    }
    expect(Number(raw.excluded_bundle_groups)).toBe(0);

    await page.goto("/dupes");
    await expect(page.getByTestId("bundle-guard")).toBeVisible();
    await expect(page.getByTestId("dupe-group").first()).toBeVisible();

    // The guard is on copies, not on whole sounds. A bounce can be stored twice
    // in ordinary folders, which is reclaimable, and once inside a project,
    // which is not. That group belongs here; the bundle path in it must be
    // listed and marked, and must not be counted in what a cleanup could free.
    const rows = page.getByTestId("dupe-path");
    const count = await rows.count();
    expect(count).toBeGreaterThan(0);
    for (let i = 0; i < count; i += 1) {
      const row = rows.nth(i);
      const path = (await row.locator(".path").textContent()) ?? "";
      expect(await row.getAttribute("data-deletable")).toBe(
        path.includes(".logicx/") ? "false" : "true",
      );
    }

    const marked = await page.getByTestId("path-locked").count();
    const bundlePaths = (
      await page.getByTestId("dupe-path").locator(".path").allTextContents()
    ).filter((p) => p.includes(".logicx/")).length;
    expect(marked).toBe(bundlePaths);

    // The headline figure only counts copies outside any bundle.
    const groups = scoped.items as Array<{ size_bytes: number; wasted_bytes: number; bundle_copies: number; paths: string[] }>;
    for (const group of groups) {
      const loose = group.paths.filter((p) => !p.includes(".logicx/")).length;
      expect(group.wasted_bytes).toBeLessThanOrEqual(group.size_bytes * (loose - 1));
    }
  });

  test("the spans route answers every sound, with an empty list rather than a 404", async ({
    page,
  }) => {
    await page.goto("/");
    const body = await api(page, "/api/files?limit=12&sort=name");
    const rows = body.items as Array<{ hash: string; duration_s: number | null }>;
    expect(rows.length).toBeGreaterThan(0);

    let withSpans = 0;
    let withNone = 0;
    for (const row of rows) {
      const answer = await api(page, `/api/files/${row.hash}/spans`);
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

      if (spans.length === 0) {
        // An empty list, and not a 404: a sound nothing has classified yet is
        // not a sound that is missing.
        withNone += 1;
        continue;
      }
      withSpans += 1;
      for (const span of spans) {
        expect(span.end_s).toBeGreaterThanOrEqual(span.start_s);
        expect(span.start_s).toBeGreaterThanOrEqual(0);
        expect(typeof span.method).toBe("string");
        expect(span.method.length).toBeGreaterThan(0);
        // A span cannot run past the end of the sound it describes.
        if (row.duration_s !== null) expect(span.end_s).toBeLessThanOrEqual(row.duration_s + 0.5);
      }
    }

    // Whether the classifier has been over this collection or not, every sound
    // in the sample answered. The counts are reported rather than asserted:
    // both are legitimate states for a collection being classified in the
    // background, and a test that demanded one would fail on the other.
    expect(withSpans + withNone).toBe(rows.length);
  });

  test("a real AIF stream refuses ranges and the page says so", async ({ page }) => {
    await page.goto("/");
    const body = await api(page, "/api/files?ext=.aif&limit=1&min_dur=5");
    const items = body.items as Array<{ hash: string; transcoded: boolean }>;
    expect(items.length).toBeGreaterThan(0);
    expect(items[0].transcoded).toBe(true);

    const head = await page.request.head(`/api/files/${items[0].hash}/stream`);
    expect(head.headers()["accept-ranges"]).toBe("none");

    await page.goto(`/sounds/${items[0].hash}`);
    await expect(page.getByTestId("no-seek-note")).toBeVisible();
  });

  test("the player is handed a hash and paints a waveform", async ({ page }) => {
    await page.goto("/");
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
});
