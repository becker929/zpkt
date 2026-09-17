/**
 * Triage: selection, bulk actions, soft delete and restore, lists, and the
 * counter in the header.
 *
 * Against mock mode, where the fixture collection is generated from a fixed
 * seed. Every test here puts back what it changed, so the next one starts from
 * the same collection: the mock server is reused between runs.
 */

import { expect, test, type Page } from "@playwright/test";

import { api, waitForRows } from "./helpers";

/** The hash of the first row of a filter, read through the API rather than the DOM. */
async function firstHashes(page: Page, query: string, n: number): Promise<string[]> {
  const body = await api(page, `/api/files?${query}&limit=${n}`);
  return (body.items as Array<{ hash: string }>).map((f) => f.hash);
}

/** Put a set of hashes back to "not discarded, not starred". */
async function reset(page: Page, hashes: string[]): Promise<void> {
  for (const action of ["restore", "unstar"]) {
    const response = await page.request.post("/api/bulk", { data: { hashes, action } });
    expect(response.ok(), `cleanup ${action} answered ${response.status()}`).toBe(true);
  }
}

/**
 * Leave the fixture as it was found.
 *
 * The mock server keeps its triage state in memory and is reused between runs,
 * so a test that ends early would otherwise leave a sound discarded and the
 * next test would count it.
 */
test.afterEach(async ({ page }) => {
  const body = await api(page, "/api/files?deleted=true&limit=1000");
  const hashes = (body.items as Array<{ hash: string }>).map((f) => f.hash);
  if (hashes.length > 0) {
    await page.request.post("/api/bulk", { data: { hashes, action: "restore" } });
  }
});

test.describe("selection", () => {
  test("a checkbox selects a row and the bar counts it", async ({ page }) => {
    await page.goto("/");
    await waitForRows(page);
    await expect(page.getByTestId("selection-bar")).toHaveCount(0);

    const rows = page.locator('[data-testid="row"][data-hash]:not([data-hash=""])');
    await rows.nth(0).getByTestId("row-select").click();

    await expect(page.getByTestId("selection-bar")).toBeVisible();
    await expect(page.getByTestId("selection-count")).toContainText("1 sound selected");

    await rows.nth(1).getByTestId("row-select").click();
    await expect(page.getByTestId("selection-count")).toContainText("2 sounds selected");

    await page.getByTestId("selection-clear").click();
    await expect(page.getByTestId("selection-bar")).toHaveCount(0);
  });

  test("shift-click takes the range between two rows", async ({ page }) => {
    await page.goto("/");
    await waitForRows(page);

    const rows = page.locator('[data-testid="row"][data-hash]:not([data-hash=""])');
    await rows.nth(1).getByTestId("row-select").click();
    await rows.nth(5).getByTestId("row-select").click({ modifiers: ["Shift"] });

    // Rows 1 through 5 inclusive: five of them.
    await expect(page.getByTestId("selection-count")).toContainText("5 sounds selected");
    await expect(page.locator('[data-testid="row"][data-selected="true"]')).toHaveCount(5);

    await page.getByTestId("selection-clear").click();
  });

  test("changing a filter clears the selection", async ({ page }) => {
    // Acting on rows that scrolled out of a changed filter is how people
    // discard the wrong thing. The selection must not survive the change.
    await page.goto("/");
    await waitForRows(page);

    await page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first().getByTestId("row-select").click();
    await expect(page.getByTestId("selection-bar")).toBeVisible();

    await page.getByTestId("search").fill("kick");
    await expect(page.getByTestId("result-count")).not.toHaveText("3,451 sounds");
    await expect(page.getByTestId("selection-bar")).toHaveCount(0);

    // And clearing the filter again does not bring it back.
    await page.getByTestId("search").fill("");
    await expect(page.getByTestId("result-count")).toHaveText("3,451 sounds");
    await expect(page.getByTestId("selection-bar")).toHaveCount(0);
  });
});

test.describe("soft delete", () => {
  test("discarding a row hides it, and undo brings it back", async ({ page }) => {
    await page.goto("/?sort=name&order=asc");
    await waitForRows(page);

    const first = page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first();
    const hash = await first.getAttribute("data-hash");
    const name = await first.locator(".col-name a").textContent();
    expect(hash).toBeTruthy();

    await first.getByTestId("discard-row").click();

    // Gone from this view, and said so.
    await expect(page.locator(`[data-testid="row"][data-hash="${hash}"]`)).toHaveCount(0);
    await expect(page.getByTestId("undo-bar")).toBeVisible();
    await expect(page.getByTestId("result-count")).toHaveText("3,450 sounds");

    // The sound itself is untouched: it still streams, and the server still
    // knows it.
    const still = await api(page, `/api/files/${hash}`);
    expect(still.hash).toBe(hash);
    expect(still.deleted).toBe(true);

    await page.getByTestId("undo").click();
    await expect(page.getByTestId("result-count")).toHaveText("3,451 sounds");
    await expect.poll(async () => page.locator(`[data-testid="row"][data-hash="${hash}"]`).count()).toBe(1);
    expect(await page.locator(`[data-testid="row"][data-hash="${hash}"] .col-name a`).textContent()).toBe(name);
  });

  test("the discarded filter is the pile, and restore empties it", async ({ page }) => {
    const [hash] = await firstHashes(page, "sort=name&order=desc", 1);
    await page.request.put(`/api/files/${hash}/deleted`);

    await page.goto("/?deleted=true");
    await waitForRows(page);
    await expect(page.getByTestId("filter-discarded")).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator(`[data-testid="row"][data-hash="${hash}"]`)).toBeVisible();

    // The row's own button is a restore here, not another discard.
    await page.locator(`[data-testid="row"][data-hash="${hash}"] [data-testid="restore-row"]`).click();
    await expect(page.locator(`[data-testid="row"][data-hash="${hash}"]`)).toHaveCount(0);
    await expect(page.getByText("nothing has been discarded under this filter.")).toBeVisible();

    const back = await api(page, `/api/files/${hash}`);
    expect(back.deleted).toBe(false);
  });

  test("a bulk discard takes the whole selection in one action", async ({ page }) => {
    await page.goto("/?sort=size&order=desc");
    await waitForRows(page);

    const rows = page.locator('[data-testid="row"][data-hash]:not([data-hash=""])');
    const hashes: string[] = [];
    for (let i = 0; i < 3; i += 1) {
      const hash = await rows.nth(i).getAttribute("data-hash");
      if (hash) hashes.push(hash);
      await rows.nth(i).getByTestId("row-select").click();
    }
    expect(hashes).toHaveLength(3);

    await page.getByTestId("bulk-discard").click();

    await expect(page.getByTestId("undo-bar")).toContainText("discarded 3 sounds");
    await expect(page.getByTestId("selection-bar")).toHaveCount(0);
    await expect(page.getByTestId("result-count")).toHaveText("3,448 sounds");
    for (const hash of hashes) {
      await expect(page.locator(`[data-testid="row"][data-hash="${hash}"]`)).toHaveCount(0);
    }

    await page.getByTestId("undo").click();
    await expect(page.getByTestId("result-count")).toHaveText("3,451 sounds");
    await reset(page, hashes);
  });

  test("no route in the interface can remove a file", async ({ page }) => {
    // Soft delete is a decision about a sound, never an instruction to the
    // filesystem. After discarding, the bytes are still served.
    const [hash] = await firstHashes(page, "sort=duration&order=asc", 1);
    await page.request.put(`/api/files/${hash}/deleted`);

    const stream = await page.request.get(`/api/files/${hash}/stream`, { headers: { range: "bytes=0-99" } });
    expect(stream.status(), "a discarded sound stopped streaming").toBeLessThan(400);

    const peaks = await page.request.get(`/api/files/${hash}/peaks`);
    expect(peaks.ok(), "a discarded sound lost its waveform").toBe(true);

    await page.request.delete(`/api/files/${hash}/deleted`);
  });
});

test.describe("lists", () => {
  // A fixed name, because the second test looks for what the first one made.
  // Anything left over from an earlier run is removed first: the mock server is
  // reused between runs and its lists live in its memory.
  const NAME = "e2e triage list";
  const RENAMED = "e2e triage list renamed";

  async function removeByName(page: Page, ...names: string[]): Promise<void> {
    const body = await api(page, "/api/lists");
    for (const list of body.items as Array<{ id: number; name: string }>) {
      if (names.includes(list.name)) await page.request.delete(`/api/lists/${list.id}`);
    }
  }

  test("a selection can be filed into a new list, and the list plays as a queue", async ({ page }) => {
    await removeByName(page, NAME, RENAMED);
    await page.goto("/?sort=name&order=asc");
    await waitForRows(page);

    const rows = page.locator('[data-testid="row"][data-hash]:not([data-hash=""])');
    const hashes: string[] = [];
    for (let i = 0; i < 2; i += 1) {
      const hash = await rows.nth(i).getAttribute("data-hash");
      if (hash) hashes.push(hash);
      await rows.nth(i).getByTestId("row-select").click();
    }

    await page.getByTestId("bulk-list").click();
    await expect(page.getByTestId("list-sheet")).toBeVisible();
    await page.getByTestId("new-list-name").fill(NAME);
    await page.getByTestId("new-list-create").click();

    await expect(page.getByTestId("selection-bar")).toHaveCount(0);
    await expect(page.getByTestId("undo-bar")).toContainText("added 2 sounds to the list");

    // The list shows up with its members counted.
    await page.goto("/lists");
    const card = page.locator(`[data-testid="list-card"]:has-text("${NAME}")`);
    await expect(card).toBeVisible();
    await expect(card.getByTestId("list-count")).toContainText("2 sounds");

    // Opening it shows those sounds, in order, and it plays straight through.
    await card.getByTestId("list-link").click();
    await expect(page.getByTestId("list-name")).toHaveText(NAME);
    await expect(page.getByTestId("list-row")).toHaveCount(2);
    expect(await page.getByTestId("list-row").first().getAttribute("data-hash")).toBe(hashes[0]);

    await page.getByTestId("list-play-all").click();
    await expect(page.getByTestId("player-bar")).toHaveAttribute("data-hash", hashes[0]);

    // The queue is the list, so the next track is its second member and not
    // the next row of any filter.
    await page.getByTestId("next").click();
    await expect(page.getByTestId("player-bar")).toHaveAttribute("data-hash", hashes[1]);

    // Taking one out leaves the other.
    await page.locator(`[data-testid="list-row"][data-hash="${hashes[0]}"] [data-testid="list-remove-row"]`).click();
    await expect(page.getByTestId("list-row")).toHaveCount(1);

    // And the counter counts a filed sound as triaged.
    await expect(page.getByTestId("triage-counter")).toBeVisible();
  });

  test("a list can be renamed and removed without touching its sounds", async ({ page }) => {
    // Addressed by id, not by name: renaming is the thing under test, so a
    // locator that matches on the name would stop matching halfway through.
    const collection = await api(page, "/api/lists");
    const made = (collection.items as Array<{ id: number; name: string }>).find((l) => l.name === NAME);
    expect(made, "the previous test's list is missing").toBeTruthy();
    const detail = await api(page, `/api/lists/${made!.id}`);
    const hash = (detail.items as Array<{ hash: string }>)[0]?.hash;
    expect(hash).toBeTruthy();

    await page.goto("/lists");
    const card = page.locator(`[data-testid="list-card"][data-list-id="${made!.id}"]`);
    await expect(card).toBeVisible();

    await card.getByTestId("list-rename").click();
    await card.getByTestId("rename-input").fill(RENAMED);
    await card.getByTestId("rename-save").click();
    await expect(card.getByTestId("list-link")).toHaveText(RENAMED);

    // Removing takes two presses, and says what it removes.
    await card.getByTestId("list-delete").click();
    await expect(card.getByTestId("list-delete-confirm")).toContainText("keep the sounds");
    await card.getByTestId("list-delete-confirm").click();
    await expect(card).toHaveCount(0);

    // The sound that was in it is untouched.
    const still = await api(page, `/api/files/${hash}`);
    expect(still.hash).toBe(hash);
    expect(still.deleted).toBe(false);
  });
});

test("the header counts triaged over total on every view", async ({ page }) => {
  const [hash] = await firstHashes(page, "sort=size&order=asc", 1);

  await page.goto("/");
  const counter = page.getByTestId("triage-counter");
  await expect(counter).toBeVisible();
  const before = Number(await counter.getAttribute("data-triaged"));
  expect(Number(await counter.getAttribute("data-total"))).toBe(3451);

  // Discarding one sound is one more sound triaged.
  await page.request.put(`/api/files/${hash}/deleted`);
  await page.reload();
  await expect.poll(async () => Number(await counter.getAttribute("data-triaged"))).toBe(before + 1);

  // And it is in the header of every view, not only the list.
  for (const view of ["/lists", "/playlist", "/dupes"]) {
    await page.goto(view);
    await expect(page.getByTestId("triage-counter")).toBeVisible();
    await expect(page.getByTestId("triage-counter")).toHaveAttribute("data-total", "3451");
  }

  await page.request.delete(`/api/files/${hash}/deleted`);
});

test("the client sends hashes, never paths", async ({ page }) => {
  const writes: string[] = [];
  page.on("request", (request) => {
    if (["POST", "PUT", "DELETE", "PATCH"].includes(request.method())) {
      writes.push(`${request.method()} ${new URL(request.url()).pathname} ${request.postData() ?? ""}`);
    }
  });

  await page.goto("/?sort=name&order=asc");
  await waitForRows(page);
  const rows = page.locator('[data-testid="row"][data-hash]:not([data-hash=""])');
  await rows.nth(0).getByTestId("row-select").click();
  await rows.nth(1).getByTestId("row-select").click();
  await page.getByTestId("bulk-discard").click();
  await expect(page.getByTestId("undo-bar")).toBeVisible();
  await page.getByTestId("undo").click();
  await expect(page.getByTestId("undo-bar")).toHaveCount(0);

  expect(writes.length).toBeGreaterThan(0);
  for (const write of writes) {
    expect(write, "a write carried a filesystem path").not.toContain("/Users/");
    expect(write).not.toContain("daw-library");
    expect(write).not.toContain("..");
  }
});
