/**
 * The swipe view: one sound, looping, and two answers.
 *
 * Against mock mode, where the fixture collection is generated from a fixed
 * seed. Every test puts back what it changed — the mock server keeps its state
 * in memory and is reused between runs, so a sound left discarded or a project
 * left holding an extra sound would change the next run's counts.
 */

import { expect, test, type Page } from "@playwright/test";

import { STREAM_URL, api, paintedPixels } from "./helpers";

/** The project the fixture puts on the bench. */
const BENCH = "2026-09-16-rust-and-rebar";

async function restore(page: Page, hash: string): Promise<void> {
  const response = await page.request.delete(`/api/files/${hash}/deleted`);
  expect(response.ok(), `restoring ${hash} answered ${response.status()}`).toBe(true);
}

async function untake(page: Page, hash: string): Promise<void> {
  await page.request.delete(`/api/projects/${BENCH}/sounds/${hash}`);
}

/** Start playback if the browser refused to start it on its own. */
async function ensurePlaying(page: Page): Promise<void> {
  const paused = await page.getByTestId("audio").evaluate((node) => (node as HTMLAudioElement).paused);
  if (paused) await page.getByTestId("swipe-play").click();
  await expect
    .poll(async () => page.getByTestId("audio").evaluate((node) => (node as HTMLAudioElement).paused))
    .toBe(false);
}

test("swipe is the primary tab and fills the view with one sound", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("swipe-card")).toBeVisible();
  await expect(page.getByTestId("swipe-name")).not.toBeEmpty();

  // One sound, not a list of them.
  await expect(page.getByTestId("swipe-card")).toHaveCount(1);
  await expect(page.getByTestId("row")).toHaveCount(0);

  // The queue came from the route, not from the fallback derivation.
  await expect(page.getByTestId("swipe")).toHaveAttribute("data-source", "route");

  // The audio element is handed a hash, never a path. This is the whole
  // defence against path traversal, so it is checked in the browser too.
  const src = await page.getByTestId("audio").evaluate((node) => (node as HTMLAudioElement).src);
  expect(new URL(src).pathname).toMatch(STREAM_URL);
  expect(src).not.toContain("daw-library");
  expect(src).not.toContain("..");
});

test("the sound loops rather than advancing when it ends", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("swipe-card")).toBeVisible();
  const hash = await page.getByTestId("swipe").getAttribute("data-hash");
  await ensurePlaying(page);

  // Put the playhead just before the end. Nothing but a decision may move the
  // view on, so the same sound has to still be here afterwards, playing.
  await page.getByTestId("audio").evaluate((node) => {
    const audio = node as HTMLAudioElement;
    if (Number.isFinite(audio.duration) && audio.duration > 0.5) {
      audio.currentTime = Math.max(audio.duration - 0.15, 0);
    }
  });

  await expect
    .poll(async () => page.getByTestId("audio").evaluate((node) => (node as HTMLAudioElement).currentTime))
    .toBeLessThan(0.5);
  await expect(page.getByTestId("swipe")).toHaveAttribute("data-hash", hash ?? "");
  await expect(page.getByTestId("swipe-loop")).toBeVisible();
});

test("there are two answers and no third", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("swipe-card")).toBeVisible();

  const actions = page.locator(".swipe-actions button");
  await expect(actions).toHaveCount(2);
  await expect(page.getByTestId("swipe-discard")).toBeVisible();
  await expect(page.getByTestId("swipe-take")).toBeVisible();

  // Nothing offers a way to put the decision off.
  await expect(page.getByTestId("favorite-toggle")).toHaveCount(0);
  await expect(page.getByText(/^skip$/)).toHaveCount(0);
});

test("discarding answers the sound and the next one arrives", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("swipe-card")).toBeVisible();
  const hash = await page.getByTestId("swipe").getAttribute("data-hash");
  expect(hash).toBeTruthy();

  await page.getByTestId("swipe-discard").click();

  // A different sound, and the answered one is recorded as discarded.
  await expect.poll(async () => page.getByTestId("swipe").getAttribute("data-hash")).not.toBe(hash);
  const state = await api(page, `/api/files/${hash}`);
  expect(state.deleted).toBe(true);

  // Nothing was removed from disk. The bytes are still served.
  const stream = await page.request.get(`/api/files/${hash}/stream`, { headers: { range: "bytes=0-99" } });
  expect(stream.status(), "a discarded sound stopped streaming").toBeLessThan(400);

  // Undo is offered, and takes it back.
  await expect(page.getByTestId("swipe-last")).toContainText("discarded");
  await page.getByTestId("swipe-undo").click();
  await expect(page.getByTestId("swipe-last")).toHaveCount(0);
  const back = await api(page, `/api/files/${hash}`);
  expect(back.deleted).toBe(false);
});

test("taking a sound puts it into the project on the bench", async ({ page }) => {
  const before = await api(page, `/api/projects/${BENCH}`);
  const beforeCount = (before.summary as { sound_count: number }).sound_count;

  await page.goto("/");
  await expect(page.getByTestId("bench")).toHaveAttribute("data-project-id", BENCH);
  await expect(page.getByTestId("bench-count")).toHaveText(String(beforeCount));

  const hash = await page.getByTestId("swipe").getAttribute("data-hash");
  expect(hash).toBeTruthy();
  await page.getByTestId("swipe-take").click();

  await expect.poll(async () => page.getByTestId("swipe").getAttribute("data-hash")).not.toBe(hash);
  await expect(page.getByTestId("bench-count")).toHaveText(String(beforeCount + 1));

  const after = await api(page, `/api/projects/${BENCH}`);
  expect((after.items as Array<{ hash: string }>).map((row) => row.hash)).toContain(hash);

  // A taken sound is answered, so the queue does not offer it again.
  const queue = await api(page, "/api/swipe?limit=50");
  expect((queue.items as Array<{ hash: string }>).map((row) => row.hash)).not.toContain(hash);

  await untake(page, hash!);
});

test("the bench is marked encumbered once it holds more than the threshold", async ({ page }) => {
  // Sixteen sounds is a track. Seventeen is collecting. The mark is friction
  // and not a limit, so adding has to keep working while it is on.
  const pool = await api(page, "/api/swipe?limit=40");
  const hashes = (pool.items as Array<{ hash: string }>).map((row) => row.hash).slice(0, 17);
  expect(hashes.length).toBe(17);
  for (const hash of hashes) {
    const response = await page.request.put(`/api/projects/${BENCH}/sounds/${hash}`);
    expect(response.ok(), `adding ${hash} answered ${response.status()}`).toBe(true);
  }

  try {
    await page.goto("/");
    await expect(page.getByTestId("bench")).toHaveAttribute("data-encumbered", "true");
    await expect(page.getByTestId("bench-encumbered")).toBeVisible();

    // Still usable: taking one more goes through.
    await expect(page.getByTestId("swipe-take")).toBeEnabled();

    // And the board says so in the same words.
    await page.goto("/board");
    const card = page.locator(`[data-testid="project-card"][data-project-id="${BENCH}"]`);
    await expect(card).toHaveAttribute("data-encumbered", "true");
    await expect(card.getByTestId("project-encumbered")).toBeVisible();
  } finally {
    for (const hash of hashes) await untake(page, hash);
  }

  await page.goto("/");
  await expect(page.getByTestId("bench")).toHaveAttribute("data-encumbered", "false");
});

test("the waveform asks one classifier for its spans", async ({ page }) => {
  // The bakeoff found the three methods do not agree. Tinting all of them over
  // each other says nothing, so exactly one is asked for by name.
  const asked: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.endsWith("/spans")) asked.push(url.search);
  });

  await page.goto("/");
  await expect(page.getByTestId("swipe-card")).toBeVisible();
  await expect.poll(async () => asked.length).toBeGreaterThan(0);
  for (const search of asked) expect(search).toBe("?method=yamnet");
});

test("the waveform is painted, not merely present", async ({ page }) => {
  await page.goto("/");
  const waveform = page.getByTestId("swipe-card").getByTestId("waveform");
  await expect(waveform).toBeVisible();
  await expect.poll(async () => Number(await waveform.getAttribute("data-buckets"))).toBeGreaterThan(0);
  await expect.poll(async () => paintedPixels(waveform)).toBeGreaterThan(500);
});

test("nothing anywhere lists the undecided collection", async ({ page }) => {
  // Search says nothing until it is asked something.
  await page.goto("/search");
  await expect(page.getByTestId("search-idle")).toBeVisible();
  await expect(page.getByTestId("row")).toHaveCount(0);

  // The decided view holds decisions, and starts on what was taken.
  await page.goto("/decided");
  await expect(page.getByTestId("decided")).toHaveAttribute("data-answer", "taken");

  // The surfaces that used to show it are gone.
  for (const route of ["/lists", "/playlist", "/dupes"]) {
    const response = await page.request.get(route);
    expect(response.status(), `${route} still answers`).toBe(404);
  }
  for (const route of ["/api/lists", "/api/dupes"]) {
    const response = await page.request.get(route);
    expect(response.status(), `${route} still answers`).toBe(404);
  }
});

test("the client sends hashes, never paths", async ({ page }) => {
  const writes: string[] = [];
  page.on("request", (request) => {
    if (["POST", "PUT", "DELETE", "PATCH"].includes(request.method())) {
      writes.push(`${request.method()} ${new URL(request.url()).pathname} ${request.postData() ?? ""}`);
    }
  });

  await page.goto("/");
  await expect(page.getByTestId("swipe-card")).toBeVisible();
  const hash = await page.getByTestId("swipe").getAttribute("data-hash");
  await page.getByTestId("swipe-discard").click();
  await expect(page.getByTestId("swipe-last")).toBeVisible();

  expect(writes.length).toBeGreaterThan(0);
  for (const write of writes) {
    expect(write, "a write carried a filesystem path").not.toContain("/Users/");
    expect(write).not.toContain("daw-library");
    expect(write).not.toContain("..");
  }

  await restore(page, hash!);
});

/**
 * Leave the fixture as it was found.
 *
 * The mock server is reused between runs, so a test that ended early would
 * leave a sound discarded and the next run would count it.
 */
test.afterEach(async ({ page }) => {
  const body = await api(page, "/api/files?deleted=true&limit=1000");
  const hashes = (body.items as Array<{ hash: string }>).map((f) => f.hash);
  if (hashes.length > 0) {
    await page.request.post("/api/bulk", { data: { hashes, action: "restore" } });
  }
});
