/**
 * The board, the caps, and commit.
 *
 * Against mock mode, where the fixture is generated from a fixed seed and the
 * projects live in the dev server's memory. Every test here puts back what it
 * made, because the server is reused between runs and a project left behind is
 * a slot the next run does not have.
 *
 * No test commits a fixture project. Commit is one-way and there is no route
 * that reverses it, so a test that froze `rust and rebar` would have changed
 * the fixture for good.
 */

import { expect, test } from "@playwright/test";

import {
  addSound,
  board,
  clearScratchProjects,
  columnState,
  commit,
  fillCollageToCap,
  fillColumn,
  makeScratch,
  projects,
  scratchName,
  someHashes,
} from "./board-helpers";
import { waitForRows } from "./helpers";

test.afterEach(async ({ request }) => {
  await clearScratchProjects(request);
});

test.describe("the board", () => {
  test("three columns, each showing its cap as occupancy rather than as a tooltip", async ({ page }) => {
    await page.goto("/board");
    const columns = page.getByTestId("board-column");
    await expect(columns).toHaveCount(3);
    await expect(columns.nth(0)).toHaveAttribute("data-column", "stored");
    await expect(columns.nth(1)).toHaveAttribute("data-column", "collage");
    await expect(columns.nth(2)).toHaveAttribute("data-column", "enrich");

    // The occupancy is drawn: one box per slot, filled for each project in it.
    const stored = columns.nth(0);
    const meter = stored.getByTestId("occupancy");
    await expect(meter).toBeVisible();
    await expect(meter).toHaveAttribute("data-cap", "3");
    await expect(meter.locator(".pip")).toHaveCount(3);
    await expect(meter.locator(".pip.filled")).toHaveCount(1);

    // And it is written out as well, on screen, not behind a hover.
    await expect(meter.locator(".meter-figure")).toHaveText("1/3");
    await expect(stored).toHaveAttribute("data-over", "false");
  });

  test("a released project is off the board and holds no slot", async ({ page, request }) => {
    const state = await columnState(request, "enrich");
    await page.goto("/board");

    await expect(page.getByTestId("released")).toBeVisible();
    await expect(page.getByTestId("released-project")).toHaveCount(1);

    // It is in no column, and the columns it passed through do not count it.
    const released = page.getByTestId("released-project").first();
    const id = await released.getAttribute("data-project-id");
    await expect(page.locator(`[data-testid="board-column"] [data-project-id="${id}"]`)).toHaveCount(0);
    await expect(page.locator('[data-testid="board-column"][data-column="enrich"]')).toHaveAttribute(
      "data-count",
      String(state.count),
    );
  });

  test("a project file that does not match the schema is named, and still holds its slot", async ({
    page,
    request,
  }) => {
    await page.goto("/board");
    const strip = page.getByTestId("unreadable");
    await expect(strip).toBeVisible();

    // Two fixtures: one whose column is not a column, and one whose commit
    // chain names collage before stored and then names it twice. Neither can be
    // read, and neither is hidden.
    await expect(strip.getByTestId("unreadable-project")).toHaveCount(2);
    await expect(strip.locator('[data-project-id="hand-edited-by-mistake"]')).toContainText("column");
    await expect(strip.locator('[data-project-id="chain-out-of-order"]')).toContainText("commits");

    // A slot is held by the file being in the column, not by the file being
    // right. `chain-out-of-order` is nonsense that still says it is in `enrich`,
    // so `enrich` counts it: skipping it would mean one junk key freed a slot,
    // which is a way past the cap that needs no override and leaves no trace.
    // `hand-edited-by-mistake` names no column anybody can read, so there is no
    // column to hold it in and it holds nothing.
    const enrich = await columnState(request, "enrich");
    expect(enrich.unreadable).toBe(1);
    await expect(
      page.locator('[data-testid="board-column"][data-column="enrich"]'),
    ).toHaveAttribute("data-count", String(enrich.count));

    // The column says so on screen, so the meter and the cards below it do not
    // look like a mistake: the count is one more than the cards drawn.
    const note = page
      .locator('[data-testid="board-column"][data-column="enrich"]')
      .getByTestId("column-unreadable");
    await expect(note).toBeVisible();
    await expect(note).toHaveAttribute("data-count", "1");
    const cards = await page
      .locator('[data-testid="board-column"][data-column="enrich"] [data-testid="project-card"]')
      .count();
    expect(cards).toBe(enrich.count - enrich.unreadable);

    // Every column's count is its cards plus the files it cannot read, and
    // every readable on-board project is drawn in exactly one column. Derived
    // from the index rather than frozen, so triaging the fixture cannot make
    // this fail for a reason that has nothing to do with the rule.
    const rows = await projects(request);
    const onBoard = rows.filter((p) => p.column !== "released" && p.abandoned === null);
    const counts = await page
      .getByTestId("board-column")
      .evaluateAll((nodes) => nodes.map((n) => Number(n.getAttribute("data-count"))));
    const state = await board(request);
    const held = state.columns.reduce((total, c) => total + c.unreadable, 0);
    expect(counts.reduce((a, b) => a + b, 0)).toBe(onBoard.length + held);
  });
});

test.describe("the cap", () => {
  test("starting one past the cap is refused, states the cap, and needs an explicit override", async ({
    page,
    request,
  }) => {
    // Two more takes stored to its cap of three.
    await fillColumn(request, 2);
    await page.goto("/board");

    const stored = page.locator('[data-testid="board-column"][data-column="stored"]');
    await expect(stored.getByTestId("occupancy")).toHaveAttribute("data-count", "3");

    await page.getByTestId("new-project-name").fill(scratchName(9));
    await page.getByTestId("new-project-create").click();

    // Refused, and the refusal says the cap out loud rather than just failing.
    const refusal = page.getByTestId("cap-refusal");
    await expect(refusal).toBeVisible();
    await expect(page.getByTestId("refusal-detail")).toContainText("stored holds 3 of 3");

    // The way through is labelled with what it will do, not "confirm".
    const override = page.getByTestId("cap-override");
    await expect(override).toHaveText("go to 4 in stored anyway");

    // And nothing happened until it is pressed.
    expect((await columnState(request, "stored")).count).toBe(3);

    await override.click();
    await expect(refusal).toHaveCount(0);
    await expect(stored.getByTestId("occupancy")).toHaveAttribute("data-count", "4");
    expect((await columnState(request, "stored")).count).toBe(4);
  });

  test("an overridden column stays visibly wrong until the count comes back down", async ({
    page,
    request,
  }) => {
    await fillColumn(request, 3);
    await page.goto("/board");

    const stored = page.locator('[data-testid="board-column"][data-column="stored"]');
    await expect(stored).toHaveAttribute("data-over", "true");
    await expect(stored.getByTestId("column-over")).toBeVisible();

    // The slots outside the cap are drawn, and drawn as a fault.
    const meter = stored.getByTestId("occupancy");
    await expect(meter.locator(".pip")).toHaveCount(4);
    await expect(meter.locator(".pip.beyond")).toHaveCount(1);
    await expect(meter.locator(".meter-figure")).toHaveText("4/3");

    // And it is said at the top of the board, every time it is opened.
    await expect(page.getByTestId("board-alarm")).toContainText("stored is over its limit: 4 of 3");

    // Reloading does not clear it. This is the point: it is felt every time.
    await page.reload();
    await expect(page.getByTestId("board-alarm")).toBeVisible();
    await expect(
      page.locator('[data-testid="board-column"][data-column="stored"]'),
    ).toHaveAttribute("data-over", "true");
  });

  test("the header carries the occupancy beside the triage ratio, and marks an over column", async ({
    page,
    request,
  }) => {
    await page.goto("/");
    await waitForRows(page);
    const counter = page.getByTestId("board-counter");
    await expect(counter).toBeVisible();
    await expect(counter).toHaveAttribute("data-over", "false");
    // Side by side with the triage ratio: the same discipline at two scales.
    await expect(page.getByTestId("triage-counter")).toBeVisible();

    await fillColumn(request, 3);
    await page.reload();
    await waitForRows(page);
    await expect(page.getByTestId("board-counter")).toHaveAttribute("data-over", "true");
  });
});

test.describe("commit", () => {
  test("it says what it does before it does it", async ({ page, request }) => {
    const id = await makeScratch(request, scratchName(1));
    const [hash] = await someHashes(request, 1, 300);
    expect(await addSound(request, id, hash)).toBe(200);

    await page.goto("/board");
    const card = page.locator(`[data-project-id="${id}"]`);
    await card.getByTestId("project-commit").click();

    const confirm = page.getByTestId("commit-confirm");
    await expect(confirm).toBeVisible();
    // Not "are you sure". It names the thing that becomes permanent.
    await expect(page.getByTestId("commit-consequence")).toContainText("freezes the sound set");
    await expect(page.getByTestId("commit-consequence")).toContainText("can never change again");
    await expect(page.getByTestId("commit-consequence")).toContainText("nothing in this app reopens");
    await expect(card.getByTestId("commit-do")).toHaveText("freeze these 1 sound");

    // Cancelling changes nothing.
    await card.getByTestId("commit-cancel").click();
    await expect(confirm).toHaveCount(0);
    expect((await projects(request)).find((p) => p.id === id)?.column).toBe("stored");
  });

  test("committing out of stored freezes membership, at the API and not only in the interface", async ({
    page,
    request,
  }) => {
    const id = await makeScratch(request, scratchName(1));
    const hashes = await someHashes(request, 2, 400);
    expect(await addSound(request, id, hashes[0])).toBe(200);

    await page.goto("/board");
    const card = page.locator(`[data-project-id="${id}"]`);
    await card.getByTestId("project-commit").click();
    await card.getByTestId("commit-do").click();

    // It moved to collage, and it took a slot there.
    await expect(
      page.locator(`[data-testid="board-column"][data-column="collage"] [data-project-id="${id}"]`),
    ).toBeVisible();
    await expect(page.locator(`[data-project-id="${id}"]`)).toHaveAttribute("data-frozen", "true");
    await expect(page.locator(`[data-project-id="${id}"]`).getByTestId("project-chain")).toContainText(
      "sound set frozen",
    );

    // The server refuses membership changes from now on, whatever any tab thinks.
    const added = await request.put(`/api/projects/${id}/sounds/${hashes[1]}`);
    expect(added.status()).toBe(409);
    expect(((await added.json()) as { detail: string }).detail).toContain("frozen");

    const removed = await request.delete(`/api/projects/${id}/sounds/${hashes[0]}`);
    expect(removed.status()).toBe(409);
  });

  test("a commit into a full column is refused, names the column, and is overridable", async ({
    page,
    request,
  }) => {
    await fillCollageToCap(request);
    const id = await makeScratch(request, scratchName(1));
    const [hash] = await someHashes(request, 1, 500);
    expect(await addSound(request, id, hash)).toBe(200);

    await page.goto("/board");
    const card = page.locator(`[data-project-id="${id}"]`);
    await card.getByTestId("project-commit").click();
    await card.getByTestId("commit-do").click();

    // The blocking column is named, with its own figures.
    const refusal = card.getByTestId("cap-refusal");
    await expect(refusal).toBeVisible();
    await expect(refusal).toHaveAttribute("data-column", "collage");
    await expect(card.getByTestId("refusal-detail")).toContainText("collage holds 3 of 3");
    await expect(card.getByTestId("cap-override")).toHaveText("go to 4 in collage anyway");

    // Still in stored: the refusal happened before anything was written.
    expect((await projects(request)).find((p) => p.id === id)?.column).toBe("stored");

    await card.getByTestId("cap-override").click();
    await expect(
      page.locator('[data-testid="board-column"][data-column="collage"]'),
    ).toHaveAttribute("data-over", "true");
    expect((await projects(request)).find((p) => p.id === id)?.column).toBe("collage");
  });

  test("an empty project cannot be committed, in the interface or at the API", async ({
    page,
    request,
  }) => {
    const id = await makeScratch(request, scratchName(1));

    await page.goto("/board");
    const card = page.locator(`[data-project-id="${id}"]`);
    await expect(card.getByTestId("project-commit")).toBeDisabled();
    await expect(card.getByTestId("nothing-to-freeze")).toBeVisible();

    // And the API refuses it on its own, with a reason and with no override
    // offered: freezing an empty sound set is not a discipline, it is nonsense.
    const refused = await commit(request, id, false);
    expect(refused.status).toBe(422);
    expect(String(refused.body.detail)).toContain("nothing to freeze");
    const overridden = await commit(request, id, true);
    expect(overridden.status).toBe(422);
  });

  test("committing out of enrich releases the project off the board", async ({ request }) => {
    const id = await makeScratch(request, scratchName(1));
    const [hash] = await someHashes(request, 1, 600);
    expect(await addSound(request, id, hash)).toBe(200);
    expect((await commit(request, id, true)).status).toBe(200);
    expect((await commit(request, id, true)).status).toBe(200);

    const before = await columnState(request, "enrich");
    expect((await commit(request, id, true)).status).toBe(200);

    expect((await projects(request)).find((p) => p.id === id)?.column).toBe("released");
    expect((await columnState(request, "enrich")).count).toBe(before.count - 1);

    // One-way: there is nothing left to freeze.
    const again = await commit(request, id, true);
    expect(again.status).toBe(409);
    expect(String(again.body.detail)).toContain("released");
  });
});

test.describe("the browser's end of it", () => {
  test("the selection bar offers only projects whose sound set is still open", async ({
    page,
    request,
  }) => {
    const open = await makeScratch(request, scratchName(1));
    const closed = await makeScratch(request, scratchName(2));
    const [hash] = await someHashes(request, 1, 700);
    expect(await addSound(request, closed, hash)).toBe(200);
    expect((await commit(request, closed, true)).status).toBe(200);

    await page.goto("/");
    await waitForRows(page);
    await page
      .locator('[data-testid="row"][data-hash]:not([data-hash=""])')
      .first()
      .getByTestId("row-select")
      .click();
    await page.getByTestId("bulk-project").click();

    const sheet = page.getByTestId("project-sheet");
    await expect(sheet).toBeVisible();
    await expect(sheet.locator(`[data-project-id="${open}"]`)).toBeVisible();
    // Committed out of stored, so it cannot take a sound and is not offered as
    // though it could.
    await expect(sheet.locator(`[data-project-id="${closed}"]`)).toHaveCount(0);
    // Nor is the fixture project that sits in collage.
    await expect(sheet.locator('[data-project-id="2026-09-12-conveyor-belt"]')).toHaveCount(0);
  });

  test("a selection goes into a project and the board follows", async ({ page, request }) => {
    const id = await makeScratch(request, scratchName(1));

    await page.goto("/");
    await waitForRows(page);
    const rows = page.locator('[data-testid="row"][data-hash]:not([data-hash=""])');
    await rows.nth(0).getByTestId("row-select").click();
    await rows.nth(2).getByTestId("row-select").click({ modifiers: ["Shift"] });
    await expect(page.getByTestId("selection-count")).toContainText("3 sounds selected");

    await page.getByTestId("bulk-project").click();
    await page.getByTestId("project-sheet").locator(`[data-project-id="${id}"]`).click();

    await expect(page.getByTestId("selection-bar")).toHaveCount(0);
    expect((await projects(request)).find((p) => p.id === id)?.sound_count).toBe(3);

    await page.goto("/board");
    await expect(page.locator(`[data-project-id="${id}"]`)).toHaveAttribute("data-sounds", "3");
  });

  test("a project committed in another tab reports honestly instead of claiming success", async ({
    page,
    request,
  }) => {
    const id = await makeScratch(request, scratchName(1));

    await page.goto("/");
    await waitForRows(page);
    await page
      .locator('[data-testid="row"][data-hash]:not([data-hash=""])')
      .first()
      .getByTestId("row-select")
      .click();
    await page.getByTestId("bulk-project").click();
    await expect(page.getByTestId("project-sheet").locator(`[data-project-id="${id}"]`)).toBeVisible();

    // The other tab. The page on screen still shows the project as open.
    const [hash] = await someHashes(request, 1, 800);
    expect(await addSound(request, id, hash)).toBe(200);
    expect((await commit(request, id, true)).status).toBe(200);

    await page.getByTestId("project-sheet").locator(`[data-project-id="${id}"]`).click();

    // It does not say it worked. It says what the server said.
    const problem = page.getByTestId("sheet-problem");
    await expect(problem).toBeVisible();
    await expect(problem).toContainText("added 0 of 1");
    await expect(problem).toContainText("frozen");
    expect((await projects(request)).find((p) => p.id === id)?.sound_count).toBe(1);

    await page.getByTestId("selection-clear").click();
  });

  test("two projects with the same name get different ids and both are shown", async ({
    page,
    request,
  }) => {
    const first = await makeScratch(request, scratchName(1));
    const second = await makeScratch(request, scratchName(1));
    expect(second).not.toBe(first);
    expect(second.startsWith(first)).toBe(true);

    await page.goto("/board");
    await expect(page.locator(`[data-project-id="${first}"]`)).toBeVisible();
    await expect(page.locator(`[data-project-id="${second}"]`)).toBeVisible();
    // The id is on the card, which is the only thing telling them apart.
    await expect(page.locator(`[data-project-id="${second}"]`).getByTestId("project-id")).toHaveText(second);

    // And typing the name again says so before the second one is made.
    await page.getByTestId("new-project-name").fill(scratchName(1));
    await expect(page.getByTestId("duplicate-name")).toBeVisible();
  });
});

test.describe("what the digest is for", () => {
  test("a file edited after its commit is marked, and is still in its column", async ({ page }) => {
    // The fixture holds one: frozen over three sounds, and the file now has
    // four. Nothing in the app did that; somebody edited the file.
    await page.goto("/board");
    const card = page.locator('[data-project-id="2026-09-08-slag-heap"]');
    await expect(card).toBeVisible();
    await expect(card.getByTestId("project-tamper")).toContainText("no longer hashes to the digest");

    // It is a real project in a real column. A bad digest is not a bad file:
    // the document matches the schema, so it is not in the unreadable strip.
    await expect(card).toHaveAttribute("data-column", "enrich");
    await expect(
      page.getByTestId("unreadable").locator('[data-project-id="2026-09-08-slag-heap"]'),
    ).toHaveCount(0);
  });

  test("a sound set that was never touched is not marked", async ({ page }) => {
    await page.goto("/board");
    const card = page.locator('[data-project-id="2026-09-12-conveyor-belt"]');
    await expect(card).toBeVisible();
    await expect(card.getByTestId("project-tamper")).toHaveCount(0);
  });
});
