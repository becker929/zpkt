/**
 * The board with a cap that is not a cap.
 *
 * This runs against a mock server started with `NEXT_PUBLIC_COLUMN_CAP=two`,
 * which is what somebody typing `2` gets wrong. The setting cannot be read, and
 * what happens then is a decision with only two answers: run loose, or run
 * tight.
 *
 * It runs tight. Almost everybody who edits this value is turning the cap down,
 * and a typo in that edit must not hand back the loosest board in the
 * application while looking exactly like the board that was asked for. A board
 * that is tighter than expected is felt immediately and says why; a board that
 * is looser than expected is silent, and the discipline is gone without anybody
 * noticing.
 *
 * Nothing is blocked by it. A cap of one still takes an override, as every cap
 * does: friction, not restriction.
 */

import { expect, test } from "@playwright/test";

import { clearScratchProjects, columnState, scratchName } from "./board-helpers";

test.afterEach(async ({ request }) => {
  await clearScratchProjects(request);
});

test("a cap nobody can read tightens rather than loosens", async ({ request }) => {
  // 1, the tightest setting, and never 3, which is the default and the loosest
  // thing the configuration offers.
  for (const column of ["stored", "collage", "enrich"]) {
    expect((await columnState(request, column)).cap, `${column} fell back to the wrong cap`).toBe(1);
  }
});

test("it says so on every view, not only on the board", async ({ page }) => {
  for (const view of ["/", "/board", "/decided", "/search"]) {
    await page.goto(view);
    const banner = page.getByTestId("cap-problem");
    await expect(banner, `no word of the broken cap on ${view}`).toBeVisible();
    // What was set, what is running instead, and which way the mistake was
    // resolved. "Invalid configuration" would leave somebody to guess all three.
    await expect(banner).toContainText("NEXT_PUBLIC_COLUMN_CAP");
    await expect(banner).toContainText("two");
    await expect(banner).toContainText("running at 1");
    await expect(banner).toContainText("tightens rather than loosens");
  }
});

test("the board still works at the cap it fell back to, override and all", async ({ page, request }) => {
  await page.goto("/board");
  const stored = page.locator('[data-testid="board-column"][data-column="stored"]');
  await expect(stored.getByTestId("occupancy")).toHaveAttribute("data-cap", "1");

  // The fixture already holds one project in stored, so the board is exactly
  // full and the next one is refused. Refused, not blocked: the way through is
  // offered and labelled with what it will do.
  await page.getByTestId("new-project-name").fill(scratchName(1));
  await page.getByTestId("new-project-create").click();
  await expect(page.getByTestId("refusal-detail")).toContainText("stored holds 1 of 1");
  await expect(page.getByTestId("cap-override")).toHaveText("go to 2 in stored anyway");

  await page.getByTestId("cap-override").click();
  await expect(stored).toHaveAttribute("data-over", "true");
  expect((await columnState(request, "stored")).count).toBe(2);
});
