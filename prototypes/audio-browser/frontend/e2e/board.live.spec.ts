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
 * Nothing here writes. No test in this file creates a project, discards a
 * sound, or changes the index in any way.
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

  // As many columns as the server reports, and no more. `enrich` has no view
  // yet and this server does not serve it as a column; drawing one anyway
  // would be an occupancy that came from nowhere.
  const body = (await boardRoute.json()) as {
    columns: Array<{ column: string; cap: number; count: number }>;
  };
  await expect(page.getByTestId("board-column")).toHaveCount(body.columns.length);
  // Every cap on screen came from the server's own answer.
  for (const column of body.columns) {
    const node = page.locator(`[data-testid="board-column"][data-column="${column.column}"]`);
    await expect(node).toHaveAttribute("data-cap", String(column.cap));
    await expect(node).toHaveAttribute("data-count", String(column.count));
  }
});

test("the swipe view names a real bench or none at all", async ({ page }) => {
  const serving = (await page.request.get("/api/projects")).ok();

  await page.goto("/");
  if (!serving) {
    // "Not here" and "none yet" mean opposite things and must not read alike.
    await expect(page.getByTestId("bench")).toHaveCount(0);
    await expect(page.getByTestId("swipe-no-project")).toContainText("/api/projects");
    // Nothing can be taken, and the button says so rather than failing on press.
    await expect(page.getByTestId("swipe-take")).toBeDisabled();
    return;
  }

  // The bench, when there is one, is a project the server actually holds.
  const bench = page.getByTestId("bench");
  if ((await bench.count()) === 0) {
    await expect(page.getByTestId("swipe-no-project")).toBeVisible();
    return;
  }
  const id = await bench.getAttribute("data-project-id");
  const response = await page.request.get(`/api/projects/${id}`);
  expect(response.ok(), `the bench named ${id}, which the server does not have`).toBe(true);
});

test("the queue is either real or says it is not", async ({ page }) => {
  // The swipe queue route is written by a separate effort. Until it serves, the
  // queue is worked out from the routes that do exist. Both are real; what is
  // never allowed is a sound on screen that came from nowhere.
  await page.goto("/");
  const swipe = page.getByTestId("swipe");

  const absent = page.getByTestId("swipe-absent");
  if ((await absent.count()) > 0) {
    await expect(absent).toContainText("/api/swipe");
    await expect(page.getByTestId("swipe-card")).toHaveCount(0);
    return;
  }

  await expect(swipe).toBeVisible();
  const source = await swipe.getAttribute("data-source");
  expect(["route", "derived"]).toContain(source);

  // Whatever is on screen is a sound the server knows, and it is undecided.
  const hash = await swipe.getAttribute("data-hash");
  if (!hash) {
    await expect(page.getByTestId("swipe-done")).toBeVisible();
    return;
  }
  const detail = (await (await page.request.get(`/api/files/${hash}`)).json()) as { deleted: boolean };
  expect(detail.deleted, "the queue offered a sound that was already discarded").toBe(false);
});
