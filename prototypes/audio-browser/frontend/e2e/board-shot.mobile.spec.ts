/**
 * Screenshots of the board on the phone.
 *
 * Kept separate from the assertions so a failing check never leaves the
 * pictures half written. Everything this creates is removed again in
 * `afterAll`: the mock server keeps its projects in memory and is reused
 * between runs.
 */

import { expect, test } from "@playwright/test";

import { abandon, clearScratchProjects, fillColumn, makeScratch, scratchName } from "./board-helpers";

test.afterAll(async ({ request }) => {
  await clearScratchProjects(request);
});

test("the board on a phone", async ({ page }) => {
  await page.goto("/board");
  await expect(page.getByTestId("board-columns")).toBeVisible();
  await page.screenshot({ path: "screenshots/phone-board.png", fullPage: true });
});

test("a column over its limit on a phone", async ({ page, request }) => {
  // The fixture leaves one project in stored, so three more takes it to four
  // against a cap of three: one over, which is the state worth photographing.
  await fillColumn(request, 3);
  await page.goto("/board");
  await expect(page.getByTestId("board-alarm")).toBeVisible();
  await page.screenshot({ path: "screenshots/phone-board-over.png", fullPage: true });
});

test("the commit confirmation on a phone", async ({ page }) => {
  await page.goto("/board");
  const card = page.locator('[data-testid="project-card"][data-project-id="2026-09-16-rust-and-rebar"]');
  await expect(card).toBeVisible();
  await card.getByTestId("project-commit").click();
  await expect(page.getByTestId("commit-confirm")).toBeVisible();
  await page.screenshot({ path: "screenshots/phone-board-commit.png", fullPage: true });
});

test("what is off the board, on a phone", async ({ page, request }) => {
  // One more abandoned beside the fixture's, so the picture shows the section
  // as it reads in use: a project let go a moment ago, and one let go weeks ago.
  const id = await makeScratch(request, scratchName(1));
  expect((await abandon(request, id, "the kick never sat right")).status).toBe(200);

  await page.goto("/board");
  const off = page.getByTestId("off-board");
  await expect(off).toBeVisible();
  await off.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "screenshots/phone-board-off.png", fullPage: true });
});

test("the abandon confirmation on a phone", async ({ page }) => {
  await page.goto("/board");
  const card = page.locator('[data-testid="project-card"][data-project-id="2026-09-16-rust-and-rebar"]');
  await expect(card).toBeVisible();
  await card.getByTestId("project-abandon").click();
  await expect(card.getByTestId("abandon-confirm")).toBeVisible();
  await page.screenshot({ path: "screenshots/phone-board-abandon.png", fullPage: true });
  // Nothing is abandoned: this only photographs the question.
  await card.getByTestId("abandon-cancel").click();
});

test("the bench, as the swipe view shows it", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("bench")).toBeVisible();
  await page.screenshot({ path: "screenshots/phone-bench.png" });
});
