/**
 * What one real sound costs on the real stack.
 *
 * The mock counts the same thing, but the number that matters is this one: the
 * swipe view is used from a phone over a tailnet against the server on 8090,
 * and every round trip there is felt.
 *
 * Read only. It loads the view and counts; it answers nothing, so the real
 * index is untouched.
 */

import { expect, test } from "@playwright/test";

/** The routes that carry one sound's data. Peaks and the stream are audio. */
const PER_SOUND = /^\/api\/swipe$|\/silence$|\/spans$/;

test("a real sound arrives in one request", async ({ page }) => {
  const paths: string[] = [];
  page.on("request", (request) => {
    if (request.method() !== "GET") return;
    const { pathname } = new URL(request.url());
    if (PER_SOUND.test(pathname)) paths.push(pathname);
  });

  await page.goto("/");

  // Every sound in the collection may have been answered, which is the end of
  // the pass and not a failure. There is nothing to count in that case.
  const done = await page.getByTestId("swipe-done").count();
  test.skip(done > 0, "nothing is undecided, so there is no sound to count");

  await expect(page.getByTestId("swipe-card")).toBeVisible();
  // The waveform is the last thing on the card to arrive, so a painted one is
  // proof that everything this sound needed has been asked for.
  const waveform = page.getByTestId("swipe-card").getByTestId("waveform");
  await expect.poll(async () => Number(await waveform.getAttribute("data-buckets"))).toBeGreaterThan(0);

  const silence = paths.filter((p) => p.endsWith("/silence"));
  const spans = paths.filter((p) => p.endsWith("/spans"));
  expect(silence, `silence was asked for again: ${silence.join(", ")}`).toHaveLength(0);
  expect(spans, `spans were asked for again: ${spans.join(", ")}`).toHaveLength(0);
  expect(paths).toEqual(["/api/swipe"]);
});
