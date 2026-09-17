/**
 * Screenshots of the board on the phone.
 *
 * Kept separate from the assertions so a failing check never leaves the
 * pictures half written. Everything this creates is removed again in
 * `afterAll`: the mock server keeps its projects in memory and is reused
 * between runs.
 */

import { expect, test } from "@playwright/test";

import { clearScratchProjects, fillColumn } from "./board-helpers";
import { longPress } from "./helpers";

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

test("the add-to-project sheet on a phone", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("scroller")).toBeVisible();
  await longPress(page, '[data-testid="row"][data-hash]:not([data-hash=""])');
  await page.getByTestId("bulk-project").tap();
  await expect(page.getByTestId("project-sheet")).toBeVisible();
  await page.screenshot({ path: "screenshots/phone-project-sheet.png" });
  // Nothing is added: this only photographs the sheet.
  await page.getByTestId("selection-clear").tap();
});
