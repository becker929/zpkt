/**
 * How many requests the swipe view spends on one sound.
 *
 * `GET /api/swipe` hands over the sound, its silent gaps, its spans and the
 * project on the bench in one answer. The view is swiped from a phone over a
 * tailnet, where every extra round trip is felt, so it must not ask again for
 * anything that answer already carried.
 *
 * Counted here rather than reasoned about: the three routes are named, the
 * page is driven through two sounds, and the total is divided by the two.
 */

import { expect, test, type Page } from "@playwright/test";

/** The routes that carry one sound's data. Peaks and the stream are audio. */
const PER_SOUND = /^\/api\/swipe$|\/silence$|\/spans$/;

interface Counter {
  paths: string[];
  stop(): void;
}

function count(page: Page): Counter {
  const paths: string[] = [];
  const listener = (request: { url(): string; method(): string }) => {
    if (request.method() !== "GET") return;
    const { pathname } = new URL(request.url());
    if (PER_SOUND.test(pathname)) paths.push(pathname);
  };
  page.on("request", listener);
  return { paths, stop: () => page.off("request", listener) };
}

test("one sound costs one request", async ({ page }) => {
  const counter = count(page);

  await page.goto("/");
  await expect(page.getByTestId("swipe-card")).toBeVisible();
  const first = await page.getByTestId("swipe").getAttribute("data-hash");
  expect(first).toBeTruthy();

  // The waveform is the last thing on the card to arrive, so a painted one is
  // proof that everything this sound needed has been asked for.
  const waveform = page.getByTestId("swipe-card").getByTestId("waveform");
  await expect.poll(async () => Number(await waveform.getAttribute("data-buckets"))).toBeGreaterThan(0);

  // The second sound, reached the only way there is: by answering the first.
  await page.getByTestId("swipe-discard").click();
  await expect.poll(async () => page.getByTestId("swipe").getAttribute("data-hash")).not.toBe(first);
  await expect.poll(async () => Number(await waveform.getAttribute("data-buckets"))).toBeGreaterThan(0);

  counter.stop();

  const swipes = counter.paths.filter((p) => p === "/api/swipe");
  const silence = counter.paths.filter((p) => p.endsWith("/silence"));
  const spans = counter.paths.filter((p) => p.endsWith("/spans"));

  // eslint-disable-next-line no-console
  console.log(
    `two sounds cost ${counter.paths.length} requests: ` +
      `${swipes.length} swipe, ${silence.length} silence, ${spans.length} spans`,
  );

  // One answer per sound, and nothing asked for twice. `/api/swipe` may be
  // re-read once more after the answer lands, so the bound is on the two
  // routes that must not be called at all.
  expect(silence, `the swipe view re-fetched silence: ${silence.join(", ")}`).toHaveLength(0);
  expect(spans, `the swipe view re-fetched spans: ${spans.join(", ")}`).toHaveLength(0);
  expect(swipes.length).toBeGreaterThan(0);

  // Two sounds were shown, and everything they needed came from the two queue
  // answers. Before this, the same two sounds cost six requests.
  expect(counter.paths.length / 2, "a sound cost more than one request").toBeLessThanOrEqual(1);

  // Put the discarded sound back: the mock server keeps its state in memory.
  await page.getByTestId("swipe-undo").click();
  await expect(page.getByTestId("swipe-last")).toHaveCount(0);
});

test.afterEach(async ({ page }) => {
  const response = await page.request.get("/api/files?deleted=true&limit=1000");
  const body = (await response.json()) as { items: Array<{ hash: string }> };
  const hashes = body.items.map((f) => f.hash);
  if (hashes.length > 0) {
    await page.request.post("/api/bulk", { data: { hashes, action: "restore" } });
  }
});
