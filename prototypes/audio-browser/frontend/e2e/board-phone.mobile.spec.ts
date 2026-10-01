/**
 * The board on the phone.
 *
 * This runs under an iPhone device descriptor: WebKit at 393 by 852, touch, and
 * a device pixel ratio of 3. A narrow desktop window is a different browser and
 * would not show a bar sliding under the iOS toolbar or a column squeezed to a
 * sliver.
 *
 * The board is the one view where the phone layout is not a reduction of the
 * desktop one. Three columns side by side on 393 pixels is not a board, so the
 * columns stack, each one full width and readable.
 */

import { expect, test, type ConsoleMessage, type Page } from "@playwright/test";

import {
  abandon,
  addSound,
  clearScratchProjects,
  columnState,
  commit,
  fillColumn,
  makeScratch,
  projects,
  scratchName,
  someHashes,
} from "./board-helpers";

const IGNORED = [/webpack-hmr/, /Failed to load resource/i];

function watchConsole(page: Page): string[] {
  const seen: string[] = [];
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (IGNORED.some((pattern) => pattern.test(text))) return;
    seen.push(text.split("\n")[0]);
  });
  page.on("pageerror", (err) => seen.push(`pageerror: ${err.message}`));
  return seen;
}

test.afterEach(async ({ request }) => {
  await clearScratchProjects(request);
});

test("the columns stack and each one is the full width of the screen", async ({ page }) => {
  await page.goto("/board");
  const columns = page.getByTestId("board-column");
  await expect(columns).toHaveCount(3);

  const viewport = page.viewportSize();
  expect(viewport).not.toBeNull();

  const boxes = [];
  for (let i = 0; i < 3; i += 1) {
    const box = await columns.nth(i).boundingBox();
    expect(box, `no box on column ${i}`).not.toBeNull();
    boxes.push(box!);
  }

  for (const box of boxes) {
    // Wide enough to read a project name in, not a third of a phone.
    expect(box.width).toBeGreaterThan(viewport!.width * 0.75);
    expect(box.width).toBeLessThanOrEqual(viewport!.width);
  }

  // Stacked, not side by side.
  expect(boxes[1].y).toBeGreaterThan(boxes[0].y + boxes[0].height - 1);
  expect(boxes[2].y).toBeGreaterThan(boxes[1].y + boxes[1].height - 1);
});

test("an over-limit column reads as wrong on the phone too", async ({ page, request }) => {
  await fillColumn(request, 3);
  const errors = watchConsole(page);
  await page.goto("/board");

  const stored = page.locator('[data-testid="board-column"][data-column="stored"]');
  await expect(stored).toHaveAttribute("data-over", "true");
  await expect(stored.getByTestId("column-over")).toBeVisible();
  await expect(page.getByTestId("board-alarm")).toBeVisible();

  // The alarm is inside the screen, not off the side of it.
  const viewport = page.viewportSize();
  const box = await page.getByTestId("board-alarm").boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport!.width + 1);

  await page.waitForTimeout(400);
  expect(errors, "the board logged console errors").toEqual([]);
});

test("the header meter is on the phone as well, and marks the over column", async ({ page, request }) => {
  await page.goto("/");
  const counter = page.getByTestId("board-counter");
  await expect(counter).toBeVisible();

  const viewport = page.viewportSize();
  const box = await counter.boundingBox();
  expect(box, "no box on the header meter").not.toBeNull();
  expect(box!.x + box!.width, "the header meter runs off the side of the phone").toBeLessThanOrEqual(
    viewport!.width + 1,
  );

  await fillColumn(request, 3);
  await page.reload();
  await expect(page.getByTestId("board-counter")).toHaveAttribute("data-over", "true");
});

test("commit can be driven with a thumb, and says what it freezes", async ({ page, request }) => {
  const id = await makeScratch(request, scratchName(1));
  const [hash] = await someHashes(request, 1, 900);
  expect(await addSound(request, id, hash)).toBe(200);

  await page.goto("/board");
  const card = page.locator(`[data-project-id="${id}"]`);
  await card.getByTestId("project-commit").tap();

  const confirm = page.getByTestId("commit-confirm");
  await expect(confirm).toBeVisible();
  await expect(page.getByTestId("commit-consequence")).toContainText("freezes the sound set");

  // The two buttons are big enough to hit and are both on screen.
  const viewport = page.viewportSize();
  for (const id_ of ["commit-do", "commit-cancel"]) {
    const box = await card.getByTestId(id_).boundingBox();
    expect(box, `no box on ${id_}`).not.toBeNull();
    expect(box!.height, `${id_} is too small for a thumb`).toBeGreaterThanOrEqual(28);
    expect(box!.x + box!.width).toBeLessThanOrEqual(viewport!.width + 1);
  }

  await card.getByTestId("commit-do").tap();
  await expect(
    page.locator(`[data-testid="board-column"][data-column="collage"] [data-project-id="${id}"]`),
  ).toBeVisible();
});

test("abandon can be driven with a thumb, and the reason box fits the screen", async ({
  page,
  request,
}) => {
  const id = await makeScratch(request, scratchName(1));
  const before = (await columnState(request, "stored")).count;
  const errors = watchConsole(page);

  await page.goto("/board");
  const card = page.locator(`[data-project-id="${id}"]`);
  await card.getByTestId("project-abandon").tap();

  const confirm = card.getByTestId("abandon-confirm");
  await expect(confirm).toBeVisible();
  await expect(card.getByTestId("abandon-consequence")).toContainText("slot back");

  // Everything in the panel is thumb sized and on screen, including the box
  // for the reason, which is the part a phone keyboard has to reach.
  const viewport = page.viewportSize();
  for (const testId of ["abandon-reason", "abandon-do", "abandon-cancel"]) {
    const box = await card.getByTestId(testId).boundingBox();
    expect(box, `no box on ${testId}`).not.toBeNull();
    expect(box!.height, `${testId} is too small for a thumb`).toBeGreaterThanOrEqual(28);
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width, `${testId} runs off the side of the phone`).toBeLessThanOrEqual(
      viewport!.width + 1,
    );
  }

  await card.getByTestId("abandon-reason").fill("not this one");
  await card.getByTestId("abandon-do").tap();

  // The slot is back and the project is below the columns, where it can be
  // brought back from.
  const stored = page.locator('[data-testid="board-column"][data-column="stored"]');
  await expect(stored).toHaveAttribute("data-count", String(before - 1));
  const off = page.getByTestId("off-board").locator(`[data-project-id="${id}"]`);
  await expect(off).toBeVisible();

  const revive = off.getByTestId("project-revive");
  const box = await revive.boundingBox();
  expect(box, "no box on the revive button").not.toBeNull();
  expect(box!.height).toBeGreaterThanOrEqual(28);
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport!.width + 1);

  await revive.tap();
  await expect(
    page.locator(`[data-testid="board-column"][data-column="stored"] [data-project-id="${id}"]`),
  ).toBeVisible();
  expect((await projects(request)).find((p) => p.id === id)?.abandoned).toBe(null);

  await page.waitForTimeout(400);
  expect(errors, "abandoning logged console errors").toEqual([]);
});

test("the fixture's abandoned project reads as off the board on a phone", async ({ page, request }) => {
  const id = await makeScratch(request, scratchName(1));
  expect((await abandon(request, id, "")).status).toBe(200);

  await page.goto("/board");
  const off = page.getByTestId("off-board");
  await expect(off).toBeVisible();

  // Below the columns, not beside them, and inside the screen.
  const columns = await page.getByTestId("board-column").last().boundingBox();
  const panel = await off.boundingBox();
  expect(panel!.y).toBeGreaterThan(columns!.y);
  const viewport = page.viewportSize();
  expect(panel!.x).toBeGreaterThanOrEqual(0);
  expect(panel!.x + panel!.width).toBeLessThanOrEqual(viewport!.width + 1);
});

test("a thumb takes a sound into the bench without opening anything", async ({ page, request }) => {
  const id = await makeScratch(request, scratchName(1));

  await page.goto("/");
  await expect(page.getByTestId("bench")).toHaveAttribute("data-project-id", id);

  const take = page.getByTestId("swipe-take");
  const viewport = page.viewportSize();
  const box = await take.boundingBox();
  expect(box, "no box on the take button").not.toBeNull();
  // Inside the screen, and a target a thumb cannot miss.
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport!.width + 1);
  expect(box!.height).toBeGreaterThanOrEqual(44);

  await take.tap();
  await expect(page.getByTestId("bench-count")).toHaveText("1");

  const after = await request.get(`/api/projects/${id}`);
  expect(((await after.json()) as { summary: { sound_count: number } }).summary.sound_count).toBe(1);
});

test("the swipe view says when the project routes are not serving, rather than looking empty", async ({
  page,
}) => {
  // An absent route and an empty board must not read the same. Stand in front
  // of the index and answer "not here", which is what a server without these
  // routes does.
  await page.route("**/api/projects", (route) => route.fulfill({ status: 404, body: "{}" }));
  await page.route("**/api/board", (route) => route.fulfill({ status: 404, body: "{}" }));
  // A server that is not serving the project routes does not name a project in
  // its queue answer either, so the stand-in takes it out of there as well.
  await page.route("**/api/swipe*", async (route) => {
    const response = await route.fetch();
    const body = (await response.json()) as Record<string, unknown>;
    body.project = null;
    await route.fulfill({ response, json: body });
  });

  await page.goto("/");
  // No meter at all, rather than a meter reading zero.
  await expect(page.getByTestId("board-counter")).toHaveCount(0);

  // No bench, and the reason named. Discarding still works; taking does not
  // pretend to.
  await expect(page.getByTestId("bench")).toHaveCount(0);
  await expect(page.getByTestId("swipe-no-project")).toContainText("/api/projects");
  await expect(page.getByTestId("swipe-take")).toBeDisabled();
  await expect(page.getByTestId("swipe-discard")).toBeEnabled();

  await page.goto("/board");
  await expect(page.getByTestId("board-absent")).toBeVisible();
  await expect(page.getByTestId("board-column")).toHaveCount(0);
  await expect(page.getByTestId("occupancy")).toHaveCount(0);
});
