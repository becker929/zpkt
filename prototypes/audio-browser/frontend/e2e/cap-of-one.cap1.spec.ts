/**
 * The board with the cap turned down to one.
 *
 * The cap is meant to be turned down, and one is the setting it is really for:
 * one thing in stored, one in collage, one in enrich, and the only way to start
 * another is to finish the one in front of you. This runs against a second mock
 * server started with `NEXT_PUBLIC_COLUMN_CAP=1`, so the change under test is
 * the one line in `lib/boardConfig.ts` and nothing else.
 *
 * It also covers the case of a cap lowered underneath a board that was already
 * fuller than it: the fixture has one project per column, so at a cap of one
 * every column is exactly full, and one override puts a column over without any
 * data having changed.
 */

import { expect, test } from "@playwright/test";

import { clearScratchProjects, columnState, makeScratch, scratchName } from "./board-helpers";

test.afterEach(async ({ request }) => {
  await clearScratchProjects(request);
});

test("a cap of one is what the board draws and what the server enforces", async ({ page, request }) => {
  expect((await columnState(request, "stored")).cap).toBe(1);

  await page.goto("/board");
  const stored = page.locator('[data-testid="board-column"][data-column="stored"]');
  const meter = stored.getByTestId("occupancy");
  await expect(meter).toHaveAttribute("data-cap", "1");
  await expect(meter.locator(".pip")).toHaveCount(1);
  await expect(meter.locator(".meter-figure")).toHaveText("1/1");
  await expect(stored).toHaveAttribute("data-over", "false");

  // Full, so a second one is refused before it is written.
  await page.getByTestId("new-project-name").fill(scratchName(1));
  await page.getByTestId("new-project-create").click();
  await expect(page.getByTestId("refusal-detail")).toContainText("stored holds 1 of 1");
  await expect(page.getByTestId("cap-override")).toHaveText("go to 2 in stored anyway");
  expect((await columnState(request, "stored")).count).toBe(1);
});

test("a cap under the count shows as over without anything having been written", async ({
  page,
  request,
}) => {
  await makeScratch(request, scratchName(1));

  await page.goto("/board");
  const stored = page.locator('[data-testid="board-column"][data-column="stored"]');
  await expect(stored).toHaveAttribute("data-over", "true");
  await expect(page.getByTestId("board-alarm")).toContainText("stored is over its limit: 2 of 1");

  // Two slots drawn for a cap of one, the second one marked as a fault.
  const meter = stored.getByTestId("occupancy");
  await expect(meter.locator(".pip")).toHaveCount(2);
  await expect(meter.locator(".pip.beyond")).toHaveCount(1);
});

test("at a cap of one, collage being occupied gates every commit out of stored", async ({ request }) => {
  const id = await makeScratch(request, scratchName(1));
  const files = await request.get("/api/files?limit=1&sort=name");
  const hash = ((await files.json()) as { items: Array<{ hash: string }> }).items[0].hash;
  expect((await request.put(`/api/projects/${id}/sounds/${hash}`)).status()).toBe(200);

  const refused = await request.post(`/api/projects/${id}/commit`, { data: {} });
  expect(refused.status()).toBe(409);
  const body = (await refused.json()) as { detail: string; column: string; cap: number };
  expect(body.detail).toContain("collage holds 1 of 1");
  expect(body.column).toBe("collage");
  expect(body.cap).toBe(1);
});
