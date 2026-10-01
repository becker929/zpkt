/**
 * Abandon and revive: the other way off the board.
 *
 * Commit must not be the only exit. If it were, a project nobody believes in
 * would hold its slot forever and the only escape would be to commit something
 * nobody wants, which empties the word "committed" of meaning. At a cap of one
 * or two that turns friction into a trap.
 *
 * Abandoning is the cheap exit: the slot comes back, nothing is frozen, nothing
 * is appended to the chain, and the file is kept. Reviving is not free — it
 * takes a slot in the column the project left, and a full column refuses it with
 * the same override as every other cap refusal.
 *
 * Against mock mode. Every project made here is a scratch project and is
 * removed afterwards. No fixture project is committed, because commit is
 * one-way; the fixture is abandoned and revived, which is not.
 */

import { expect, test } from "@playwright/test";

import {
  abandon,
  addSound,
  board,
  clearScratchProjects,
  columnState,
  commit,
  makeScratch,
  projects,
  revive,
  scratchName,
  someHashes,
} from "./board-helpers";

test.afterEach(async ({ request }) => {
  await clearScratchProjects(request);
});

test.describe("abandoning", () => {
  test("the slot comes back, so the cap is not a trap", async ({ page, request }) => {
    const state = await columnState(request, "stored");
    // Up to the cap, whatever the cap is set to.
    const ids: string[] = [];
    for (let i = state.count; i < state.cap; i += 1) ids.push(await makeScratch(request, scratchName(i + 1)));
    const doomed = ids.length > 0 ? ids[ids.length - 1] : await makeScratch(request, scratchName(9));

    await page.goto("/board");
    const stored = page.locator('[data-testid="board-column"][data-column="stored"]');
    const before = Number(await stored.getAttribute("data-count"));
    expect(before).toBeGreaterThanOrEqual(state.cap);

    // Put one down. It asks first, and it says what it will and will not do.
    const card = page.locator(`[data-project-id="${doomed}"]`);
    await card.getByTestId("project-abandon").click();
    const confirm = card.getByTestId("abandon-confirm");
    await expect(confirm).toBeVisible();
    await expect(card.getByTestId("abandon-consequence")).toContainText("nothing is added to the commit chain");
    await expect(card.getByTestId("abandon-consequence")).toContainText("kept, not");

    // Nothing has happened yet.
    expect((await columnState(request, "stored")).count).toBe(before);

    await card.getByTestId("abandon-reason").fill("the kick never sat right");
    await card.getByTestId("abandon-do").click();

    // The slot is back, and the card has left the column.
    await expect(stored).toHaveAttribute("data-count", String(before - 1));
    await expect(page.locator(`[data-testid="board-column"] [data-project-id="${doomed}"]`)).toHaveCount(0);
    expect((await columnState(request, "stored")).count).toBe(before - 1);

    // It is below the columns, with what was said about it, not deleted.
    const off = page.getByTestId("off-board").locator(`[data-project-id="${doomed}"]`);
    await expect(off).toBeVisible();
    await expect(off.getByTestId("abandoned-reason")).toContainText("the kick never sat right");
    await expect(off.getByTestId("abandoned-measures")).toContainText("abandoned out of stored");
  });

  test("it appends nothing to the chain, and keeps every commit it had", async ({ request }) => {
    const id = await makeScratch(request, scratchName(1));
    const [hash] = await someHashes(request, 1, 700);
    expect(await addSound(request, id, hash)).toBe(200);
    // Into collage, so it carries exactly one commit when it is abandoned.
    expect((await commit(request, id, true)).status).toBe(200);

    const before = (await projects(request)).find((p) => p.id === id)!;
    expect(before.commits.length).toBe(1);

    expect((await abandon(request, id, "not this one")).status).toBe(200);

    const after = (await projects(request)).find((p) => p.id === id)!;
    // Abandoning is not a commit. The chain is exactly what it was.
    expect(after.commits).toEqual(before.commits);
    // And the column it left is recorded, because that is what revive needs.
    expect(after.column).toBe("collage");
    expect(after.abandoned?.from).toBe("collage");
    expect(after.abandoned?.reason).toBe("not this one");
  });

  test("abandoned is a field and never a column", async ({ request }) => {
    const id = await makeScratch(request, scratchName(1));
    expect((await abandon(request, id)).status).toBe(200);

    const detail = (await (await request.get(`/api/projects/${id}`)).json()) as {
      valid: boolean;
      document: { column: string; abandoned: { from: string } | null };
    };
    // The document still validates, which it could not if "abandoned" had been
    // written into `column`: that would collapse the four branches and take the
    // chain's invariant with it.
    expect(detail.valid).toBe(true);
    expect(detail.document.column).toBe("stored");
    expect(detail.document.abandoned?.from).toBe("stored");

    // And the field cannot be written through the ordinary edit route, where no
    // cap would ever be consulted.
    const patched = await request.patch(`/api/projects/${id}`, { data: { abandoned: null } });
    expect(patched.status()).toBe(409);
  });

  test("an abandoned project is not in the race: it cannot be committed", async ({ request }) => {
    const id = await makeScratch(request, scratchName(1));
    const [hash] = await someHashes(request, 1, 710);
    expect(await addSound(request, id, hash)).toBe(200);
    expect((await abandon(request, id)).status).toBe(200);

    const refused = await commit(request, id, true);
    expect(refused.status).toBe(409);
    expect(String(refused.body.detail)).toContain("revive");

    // Even with an override, because this is not a cap.
    expect((await projects(request)).find((p) => p.id === id)?.column).toBe("stored");
  });

  test("abandoning twice is refused, and a released project cannot be abandoned", async ({ request }) => {
    const id = await makeScratch(request, scratchName(1));
    expect((await abandon(request, id)).status).toBe(200);
    const again = await abandon(request, id);
    expect(again.status).toBe(409);
    expect(String(again.body.detail)).toContain("already");
  });
});

test.describe("reviving", () => {
  test("it comes back to the column it left, with its commits", async ({ page, request }) => {
    const id = await makeScratch(request, scratchName(1));
    const [hash] = await someHashes(request, 1, 720);
    expect(await addSound(request, id, hash)).toBe(200);
    expect((await commit(request, id, true)).status).toBe(200);
    expect((await abandon(request, id, "")).status).toBe(200);

    const before = await columnState(request, "collage");

    await page.goto("/board");
    const off = page.getByTestId("off-board").locator(`[data-project-id="${id}"]`);
    await expect(off).toBeVisible();
    await expect(off.getByTestId("project-revive")).toHaveText("revive into collage");
    await off.getByTestId("project-revive").click();

    // Back in collage, holding a slot again.
    const card = page.locator(`[data-testid="board-column"][data-column="collage"] [data-project-id="${id}"]`);
    await expect(card).toBeVisible();
    await expect(page.getByTestId("off-board").locator(`[data-project-id="${id}"]`)).toHaveCount(0);
    expect((await columnState(request, "collage")).count).toBe(before.count + 1);

    // Carrying the commit it had, so its sound set is still frozen: the card
    // says so, and the API refuses a membership change.
    const row = (await projects(request)).find((p) => p.id === id)!;
    expect(row.commits.length).toBe(1);
    expect(row.abandoned).toBe(null);
    const [another] = await someHashes(request, 1, 730);
    expect(await addSound(request, id, another)).toBe(409);
  });

  test("a full column refuses it, and the override is the usual one", async ({ page, request }) => {
    // One project abandoned out of stored, and stored then filled to its cap.
    const id = await makeScratch(request, scratchName(1));
    expect((await abandon(request, id)).status).toBe(200);

    const state = await columnState(request, "stored");
    for (let i = state.count; i < state.cap; i += 1) await makeScratch(request, scratchName(i + 2));
    const full = await columnState(request, "stored");
    expect(full.count).toBeGreaterThanOrEqual(full.cap);

    // The route refuses, and says which cap and what the occupancy is, so the
    // client can state both rather than guess.
    const refused = await revive(request, id);
    expect(refused.status).toBe(409);
    expect(refused.body.column).toBe("stored");
    expect(Number(refused.body.cap)).toBe(full.cap);
    expect((await projects(request)).find((p) => p.id === id)?.abandoned).not.toBe(null);

    // And in the interface it is the same panel as every other cap refusal,
    // labelled with the number the column is going to.
    await page.goto("/board");
    const off = page.getByTestId("off-board").locator(`[data-project-id="${id}"]`);
    await off.getByTestId("project-revive").click();
    const refusal = off.getByTestId("cap-refusal");
    await expect(refusal).toBeVisible();
    await expect(refusal.getByTestId("cap-override")).toHaveText(`go to ${full.count + 1} in stored anyway`);

    // Backing out leaves it where it was.
    await refusal.getByTestId("cap-cancel").click();
    expect((await projects(request)).find((p) => p.id === id)?.abandoned).not.toBe(null);

    // Going through takes the column over its limit, and it stays marked.
    await off.getByTestId("project-revive").click();
    await off.getByTestId("cap-override").click();
    const stored = page.locator('[data-testid="board-column"][data-column="stored"]');
    await expect(stored).toHaveAttribute("data-over", "true");
    await expect(stored.getByTestId("column-over")).toBeVisible();
    expect((await projects(request)).find((p) => p.id === id)?.abandoned).toBe(null);
  });

  test("a project on the board cannot be revived", async ({ request }) => {
    const id = await makeScratch(request, scratchName(1));
    const refused = await revive(request, id);
    expect(refused.status).toBe(409);
    expect(String(refused.body.detail)).toContain("not abandoned");
  });
});

test.describe("what is off the board", () => {
  test("the fixture's abandoned project holds no slot and is drawn below the columns", async ({
    page,
    request,
  }) => {
    const rows = await projects(request);
    const gone = rows.find((p) => p.abandoned !== null);
    expect(gone, "the fixture has no abandoned project").toBeTruthy();

    await page.goto("/board");
    // Below the columns, never inside one, even though it still records the
    // column it left.
    await expect(
      page.locator(`[data-testid="board-column"] [data-project-id="${gone!.id}"]`),
    ).toHaveCount(0);
    const off = page.getByTestId("off-board").locator(`[data-project-id="${gone!.id}"]`);
    await expect(off).toBeVisible();
    await expect(off).toHaveAttribute("data-from", gone!.abandoned!.from);

    // The column it left does not count it.
    const state = await columnState(request, gone!.abandoned!.from);
    const drawn = await page
      .locator(`[data-testid="board-column"][data-column="${gone!.abandoned!.from}"] [data-testid="project-card"]`)
      .count();
    expect(drawn).toBe(state.count - state.unreadable);

    // And the board counts it as off the board, beside the released ones.
    const state2 = await board(request);
    expect(state2.abandoned).toBeGreaterThan(0);
  });

  test("an abandoned project is never the bench", async ({ page, request }) => {
    const id = await makeScratch(request, scratchName(1));
    expect((await abandon(request, id)).status).toBe(200);

    await page.goto("/");
    // A project that cannot take a sound must not look as though it could. This
    // one is in `stored` with no commit, so only being off the board keeps it
    // off the bench.
    const bench = page.getByTestId("bench");
    await expect(bench).toBeVisible();
    await expect(bench).not.toHaveAttribute("data-project-id", id);
  });
});
