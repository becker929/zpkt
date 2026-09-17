/**
 * The board against the real stack.
 *
 * The project routes are written by a separate effort. Until they serve, the
 * FastAPI server answers 404 for them, and what this checks is that the
 * interface says so rather than drawing an empty board: zero of three is a
 * claim, and an interface that has not been told anything is not entitled to
 * make it.
 *
 * It passes either way. Once the routes serve, the same test checks that the
 * board draws real columns instead. What it never allows is the third thing:
 * an occupancy on screen that came from nowhere.
 *
 * This test only reads. It creates no project and writes nothing to the index.
 */

import { expect, test } from "@playwright/test";

test("the board is either real or says it is not", async ({ page }) => {
  const boardRoute = await page.request.get("/api/board");
  const serving = boardRoute.ok();

  await page.goto("/board");
  await expect(page.getByTestId("board")).toBeVisible();

  if (!serving) {
    await expect(page.getByTestId("board-absent")).toBeVisible();
    // Nothing fabricated: no columns, no meters, no counts.
    await expect(page.getByTestId("board-column")).toHaveCount(0);
    await expect(page.getByTestId("occupancy")).toHaveCount(0);
    await expect(page.getByTestId("board-counter")).toHaveCount(0);
    return;
  }

  await expect(page.getByTestId("board-column")).toHaveCount(3);
  // Every cap on screen came from the server's own answer.
  const body = (await boardRoute.json()) as {
    columns: Array<{ column: string; cap: number; count: number }>;
  };
  for (const column of body.columns) {
    const node = page.locator(`[data-testid="board-column"][data-column="${column.column}"]`);
    await expect(node).toHaveAttribute("data-cap", String(column.cap));
    await expect(node).toHaveAttribute("data-count", String(column.count));
  }
});

test("the selection bar does not offer a project it cannot add to", async ({ page }) => {
  const serving = (await page.request.get("/api/projects")).ok();

  await page.goto("/");
  await expect(page.getByTestId("scroller")).toBeVisible();
  await page
    .locator('[data-testid="row"][data-hash]:not([data-hash=""])')
    .first()
    .getByTestId("row-select")
    .click();
  await page.getByTestId("bulk-project").click();

  const sheet = page.getByTestId("project-sheet");
  await expect(sheet).toBeVisible();
  if (!serving) {
    // "Not here" and "none yet" mean opposite things and must not read alike.
    await expect(page.getByTestId("project-sheet-absent")).toBeVisible();
    await expect(page.getByTestId("project-sheet-empty")).toHaveCount(0);
    await expect(sheet.getByTestId("sheet-project")).toHaveCount(0);
  }

  // Nothing was added, and nothing was written. Put the selection down again.
  await page.getByTestId("selection-clear").click();
  await expect(page.getByTestId("selection-bar")).toHaveCount(0);
});
