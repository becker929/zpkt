/**
 * The decided view: a record of answers, not a catalogue.
 *
 * It holds only sounds that have been taken into a project or discarded, so
 * there is no way through it to a sound that has never been heard. Three
 * filters: which of the two answers, which project a taken sound went into,
 * and the name.
 */

import { expect, test, type Page } from "@playwright/test";

import { api, isUndecided, undecided, waitForHydration } from "./helpers";

/** The project the fixture puts on the bench, and the one behind it. */
const BENCH = "2026-09-16-rust-and-rebar";
const COMMITTED = "2026-09-12-conveyor-belt";

async function rows(page: Page) {
  return page.locator('[data-testid="row"][data-hash]:not([data-hash=""])');
}

test("it opens on what was taken, grouped by the project it went into", async ({ page }) => {
  await page.goto("/decided");
  await expect(page.getByTestId("decided")).toHaveAttribute("data-answer", "taken");

  const project = await api(page, `/api/projects/${BENCH}`);
  const hashes = (project.items as Array<{ hash: string }>).map((row) => row.hash);
  expect(hashes.length).toBeGreaterThan(0);

  for (const hash of hashes) {
    await expect(page.locator(`[data-testid="row"][data-hash="${hash}"]`)).toBeVisible();
  }
  await expect(page.getByTestId("row-project").first()).toBeVisible();
});

test("the project filter narrows it to one project", async ({ page }) => {
  await page.goto("/decided");
  await expect((await rows(page)).first()).toBeVisible();

  await page.getByTestId("filter-project").selectOption(COMMITTED);
  await expect
    .poll(async () => {
      const ids = await page.locator('[data-testid="row"]').evaluateAll((nodes) =>
        nodes.map((node) => (node as HTMLElement).dataset.projectId),
      );
      return ids.length > 0 && ids.every((id) => id === COMMITTED);
    })
    .toBe(true);

  // Its sound set was frozen when it committed, so nothing here offers to take
  // a sound back out of it.
  await expect(page.getByTestId("frozen-row").first()).toBeVisible();
  await expect(page.getByTestId("untake-row")).toHaveCount(0);
});

test("a sound can be taken back out of a project whose set is still open", async ({ page }) => {
  const before = await api(page, `/api/projects/${BENCH}`);
  const hash = (before.items as Array<{ hash: string }>)[0].hash;

  await page.goto("/decided");
  const row = page.locator(`[data-testid="row"][data-hash="${hash}"]`);
  await expect(row).toBeVisible();
  await row.getByTestId("untake-row").click();
  await expect(row).toHaveCount(0);

  // It is undecided again, so the queue would offer it.
  expect(await isUndecided(page, hash)).toBe(true);

  // Put it back the way it was found.
  const response = await page.request.put(`/api/projects/${BENCH}/sounds/${hash}`);
  expect(response.ok()).toBe(true);
});

test("the name filter narrows what is shown", async ({ page }) => {
  await page.goto("/decided");
  await waitForHydration(page);
  await expect((await rows(page)).first()).toBeVisible();

  await page.getByTestId("decided-search").fill("zzzz-no-such-sound");
  await expect(page.getByTestId("decided-search")).toHaveValue("zzzz-no-such-sound");
  await expect(page.getByTestId("taken-empty")).toContainText("zzzz-no-such-sound");
});

test("the discarded filter shows the discard pile, and restore empties it", async ({ page }) => {
  const hash = (await undecided(page, 1))[0];
  await page.request.put(`/api/files/${hash}/deleted`);

  await page.goto("/decided");
  await page.getByTestId("filter-discarded").click();
  await expect(page.getByTestId("decided")).toHaveAttribute("data-answer", "discarded");
  await expect(page.locator(`[data-testid="row"][data-hash="${hash}"]`)).toBeVisible();

  // The row's own button is a restore here, not another discard.
  await page.locator(`[data-testid="row"][data-hash="${hash}"] [data-testid="restore-row"]`).click();
  await expect(page.locator(`[data-testid="row"][data-hash="${hash}"]`)).toHaveCount(0);

  const back = await api(page, `/api/files/${hash}`);
  expect(back.deleted).toBe(false);
});

test("nothing undecided appears under either filter", async ({ page }) => {
  const unanswered = await undecided(page, 5);
  expect(unanswered.length).toBeGreaterThan(0);

  await page.goto("/decided");
  for (const hash of unanswered) {
    await expect(page.locator(`[data-testid="row"][data-hash="${hash}"]`)).toHaveCount(0);
  }

  await page.getByTestId("filter-discarded").click();
  await expect(page.getByTestId("decided")).toHaveAttribute("data-answer", "discarded");
  for (const hash of unanswered) {
    await expect(page.locator(`[data-testid="row"][data-hash="${hash}"]`)).toHaveCount(0);
  }
});

test.afterEach(async ({ page }) => {
  const body = await api(page, "/api/files?deleted=true&limit=1000");
  const hashes = (body.items as Array<{ hash: string }>).map((f) => f.hash);
  if (hashes.length > 0) {
    await page.request.post("/api/bulk", { data: { hashes, action: "restore" } });
  }
});
