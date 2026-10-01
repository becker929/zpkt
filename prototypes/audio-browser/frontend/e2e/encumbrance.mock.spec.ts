/**
 * The encumbrance mark follows the server, not the client.
 *
 * `GET /api/board` reports the threshold, because the server is the one that
 * owns the rule. A client holding its own copy agrees right up to the day
 * somebody changes the server's value, and from then on the interface says one
 * thing while the thing enforcing it says another.
 *
 * Checked by serving a different threshold and watching the mark move, rather
 * than by reading the two numbers and finding them equal.
 */

import { expect, test, type Page } from "@playwright/test";

/** The project the fixture puts on the bench. */
const BENCH = "2026-09-16-rust-and-rebar";

/** Serve the mock board with its threshold replaced. */
async function boardWithEncumbrance(page: Page, encumbrance: number | null): Promise<void> {
  await page.route("**/api/board", async (route) => {
    // The handler outlives any one request. A board request still in flight
    // when the page moves on has its response disposed underneath us, and
    // reading it then throws inside the handler and fails a test that already
    // had its answer. Let such a request go rather than speaking for it.
    let body: Record<string, unknown>;
    try {
      body = (await (await route.fetch()).json()) as Record<string, unknown>;
    } catch {
      await route.continue().catch(() => undefined);
      return;
    }
    if (encumbrance === null) delete body.encumbrance;
    else body.encumbrance = encumbrance;
    await route
      .fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) })
      .catch(() => undefined);
  });
}

async function benchCount(page: Page): Promise<number> {
  const response = await page.request.get(`/api/projects/${BENCH}`);
  expect(response.ok(), `the bench answered ${response.status()}`).toBe(true);
  const body = (await response.json()) as { summary: { sound_count: number } };
  return body.summary.sound_count;
}

test("a threshold below the bench's count marks it, whatever the client's own default is", async ({
  page,
}) => {
  const count = await benchCount(page);
  expect(count, "the fixture bench holds nothing, so no threshold can be under it").toBeGreaterThan(0);

  // Under the count, and far under the 16 the client would use on its own.
  await boardWithEncumbrance(page, count - 1);
  await page.goto("/");
  await expect(page.getByTestId("bench")).toHaveAttribute("data-project-id", BENCH);
  await expect(page.getByTestId("bench")).toHaveAttribute("data-encumbered", "true");
  await expect(page.getByTestId("bench-encumbered")).toBeVisible();

  // The board says it in the same words, from the same number.
  await page.goto("/board");
  const card = page.locator(`[data-testid="project-card"][data-project-id="${BENCH}"]`);
  await expect(card).toHaveAttribute("data-encumbered", "true");
});

test("a threshold at the bench's count leaves it unmarked", async ({ page }) => {
  // The mark is "more than", so a project sitting exactly on the threshold is
  // not over it.
  const count = await benchCount(page);
  await boardWithEncumbrance(page, count);
  await page.goto("/");
  await expect(page.getByTestId("bench")).toHaveAttribute("data-project-id", BENCH);
  await expect(page.getByTestId("bench")).toHaveAttribute("data-encumbered", "false");
  await expect(page.getByTestId("bench-encumbered")).toHaveCount(0);
});

test("a board that states no threshold marks nothing", async ({ page }) => {
  // A threshold nobody stated is not a threshold to draw against. The client
  // used to fall back to a number of its own here, which is the whole defect:
  // a mark shown against the client's opinion reads exactly like a mark shown
  // against the rule in force.
  await boardWithEncumbrance(page, null);
  await page.goto("/");
  await expect(page.getByTestId("bench")).toHaveAttribute("data-project-id", BENCH);
  await expect(page.getByTestId("bench")).toHaveAttribute("data-encumbered", "false");
  await expect(page.getByTestId("bench-encumbered")).toHaveCount(0);
});
