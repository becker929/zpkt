/**
 * Adversarial tests for the board: the ways the cap and the commit boundary can
 * be got around.
 *
 * These were written to break the feature, not to describe it. Each one names a
 * way the discipline stops being felt. They run against mock mode, and every
 * project they make is a scratch project that is removed afterwards.
 */

import { expect, test } from "@playwright/test";

import {
  addSound,
  clearScratchProjects,
  commit,
  fillColumn,
  makeScratch,
  projects,
  scratchName,
  someHashes,
} from "./board-helpers";

test.afterEach(async ({ request }) => {
  await clearScratchProjects(request);
});

/** sRGB relative luminance, per WCAG. */
function luminance(rgb: [number, number, number]): number {
  const [r, g, b] = rgb.map((v) => {
    const c = v / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function parseRgb(value: string): [number, number, number] {
  const found = value.match(/-?[\d.]+/g);
  expect(found, `could not read a colour out of "${value}"`).toBeTruthy();
  return [Number(found![0]), Number(found![1]), Number(found![2])];
}

function contrast(a: string, b: string): number {
  const la = luminance(parseRgb(a));
  const lb = luminance(parseRgb(b));
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

test.describe("the commit boundary under a second tab", () => {
  test("a stale tab cannot commit the next stage by pressing the same button again", async ({
    browser,
    request,
  }) => {
    const id = await makeScratch(request, scratchName(1));
    const [hash] = await someHashes(request, 1, 900);
    expect(await addSound(request, id, hash)).toBe(200);

    const context = await browser.newContext();
    const stale = await context.newPage();
    const fresh = await context.newPage();

    // Both tabs are looking at the project while it is still in `stored`.
    await stale.goto("/board");
    await fresh.goto("/board");
    const staleCard = stale.locator(`[data-project-id="${id}"]`);
    const freshCard = fresh.locator(`[data-project-id="${id}"]`);
    await expect(staleCard).toHaveAttribute("data-column", "stored");
    await expect(freshCard).toHaveAttribute("data-column", "stored");

    // One tab commits. The project is now in `collage` and its sound set is
    // frozen.
    await freshCard.getByTestId("project-commit").click();
    await freshCard.getByTestId("commit-do").click();
    await expect(fresh.locator(`[data-project-id="${id}"]`)).toHaveAttribute("data-column", "collage");

    // The other tab still shows the old card and still offers to freeze the
    // sound set. Pressing it must not freeze the arrangement instead: that is a
    // different artifact, a different column, and a stage nobody worked.
    await staleCard.getByTestId("project-commit").click();
    await staleCard.getByTestId("commit-do").click();

    // It must not claim it did what it said it would, and it must say what
    // happened rather than quietly moving the card two columns along.
    await expect(staleCard.getByTestId("project-receipt")).toHaveCount(0);
    await expect(staleCard.getByTestId("commit-blocked")).toBeVisible();
    await expect(staleCard.getByTestId("refusal-detail")).toContainText("already in collage");
    // No way through is offered: this is not a cap, it is a stage nobody worked.
    await expect(staleCard.getByTestId("cap-override")).toHaveCount(0);

    // And the project must not have skipped `collage`.
    const after = (await projects(request)).find((p) => p.id === id);
    expect(after?.column, "a stale tab promoted the project a second time").toBe("collage");
    const detail = (await (await request.get(`/api/projects/${id}`)).json()) as {
      document: { commits: unknown[] };
    };
    expect(detail.document.commits.length, "a second stage was frozen that nobody worked").toBe(1);

    await context.close();
  });

  test("the commit route refuses a commit aimed at a stage the project has left", async ({
    request,
  }) => {
    const id = await makeScratch(request, scratchName(1));
    const [hash] = await someHashes(request, 1, 950);
    expect(await addSound(request, id, hash)).toBe(200);

    // The tab that wins.
    expect((await commit(request, id, true)).status).toBe(200);

    // The tab that was looking at `stored`. It asks to freeze the sound set,
    // and the sound set has already been frozen by somebody else.
    const late = await request.post(`/api/projects/${id}/commit`, {
      data: { override: true, expect_column: "stored" },
    });
    expect(late.status(), "a commit aimed at stored was applied to collage instead").toBe(409);
    expect(String(((await late.json()) as { detail: string }).detail)).toContain("stored");

    expect((await projects(request)).find((p) => p.id === id)?.column).toBe("collage");
  });
});

test.describe("an over-limit column without colour", () => {
  test("the slot outside the cap is told apart from a full slot in greyscale", async ({
    page,
    request,
  }) => {
    await fillColumn(request, 3);
    await page.goto("/board");

    const meter = page.locator('[data-testid="board-column"][data-column="stored"] [data-testid="occupancy"]');
    await expect(meter).toHaveAttribute("data-over", "true");
    await expect(meter.locator(".pip")).toHaveCount(4);

    const inside = meter.locator(".pip").nth(0);
    const beyond = meter.locator(".pip").nth(3);
    await expect(beyond).toHaveClass(/beyond/);

    const read = async (locator: typeof inside) =>
      locator.evaluate((node) => {
        const style = getComputedStyle(node);
        return {
          background: style.backgroundColor,
          border: style.borderTopColor,
          width: style.width,
          height: style.height,
          borderRadius: style.borderTopLeftRadius,
          borderWidth: style.borderTopWidth,
        };
      });

    const a = await read(inside);
    const b = await read(beyond);

    // The two boxes differ only by hue. On a phone in sunlight, in greyscale, or
    // to the eight percent of men who cannot separate those two hues, the fourth
    // box is a fourth full slot and nothing is wrong.
    const shapeDiffers =
      a.width !== b.width ||
      a.height !== b.height ||
      a.borderRadius !== b.borderRadius ||
      a.borderWidth !== b.borderWidth;
    const lightnessDiffers = contrast(a.background, b.background) >= 3;

    expect(
      shapeDiffers || lightnessDiffers,
      `the slot beyond the cap is only a different hue: ${a.background} against ${b.background}, ` +
        `contrast ${contrast(a.background, b.background).toFixed(2)}:1, same size and same corner`,
    ).toBe(true);
  });

  test("the header's compact meter marks the over column without relying on colour", async ({
    page,
    request,
  }) => {
    await fillColumn(request, 3);
    // The header carries the meter on every view, so check it somewhere that is
    // not the board.
    await page.goto("/decided");

    const counter = page.getByTestId("board-counter");
    await expect(counter).toHaveAttribute("data-over", "true");

    // The compact meter drops the figure, so the boxes are the whole reading.
    // Four boxes with nothing else different would say "a full column of four",
    // not "a column of three with one too many in it".
    const meter = counter.locator('[data-column="stored"] [data-testid="occupancy"]');
    await expect(meter.locator(".pip")).toHaveCount(4);

    const shape = (index: number) =>
      meter
        .locator(".pip")
        .nth(index)
        .evaluate((node) => {
          const style = getComputedStyle(node);
          return `${style.borderTopLeftRadius}/${style.boxShadow}`;
        });

    expect(
      await shape(3),
      "the slot outside the cap is drawn the same as a slot inside it",
    ).not.toBe(await shape(0));

    // The exact reading is still available to a screen reader and on a hover.
    await expect(meter).toHaveAttribute("aria-label", "over its limit: 4 of 3");
  });
});

test.describe("what the cap does not count", () => {
  test("a column already over its limit still names the real number it is going to", async ({
    page,
    request,
  }) => {
    // Four in stored already, so the next refusal has to say five, not four.
    await fillColumn(request, 3);
    await page.goto("/board");
    await page.getByTestId("new-project-name").fill(scratchName(9));
    await page.getByTestId("new-project-create").click();

    await expect(page.getByTestId("cap-override")).toHaveText("go to 5 in stored anyway");
    await expect(page.getByTestId("refusal-detail")).toContainText("stored holds 4 of 3");
  });
});
