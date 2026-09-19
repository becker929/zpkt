/**
 * Triage: selection, bulk discard and restore, and the counter in the header.
 *
 * There are two decisions about a sound and this covers one of them. The other
 * — taking it into a project — is made one sound at a time and is covered by
 * `swipe.mock.spec.ts`.
 *
 * Against mock mode, where the fixture collection is generated from a fixed
 * seed. Every test here puts back what it changed, so the next one starts from
 * the same collection: the mock server is reused between runs.
 */

import { expect, test, type Page } from "@playwright/test";

import { api, undecided, waitForRows } from "./helpers";

/** A view with rows in it. Nothing lists the undecided collection any more. */
const ROWS = "/search?q=kick";

/** The hash of the first row of a filter, read through the API rather than the DOM. */
async function firstHashes(page: Page, query: string, n: number): Promise<string[]> {
  const body = await api(page, `/api/files?${query}&limit=${n}`);
  return (body.items as Array<{ hash: string }>).map((f) => f.hash);
}

/**
 * Leave the fixture as it was found.
 *
 * The mock server keeps its state in memory and is reused between runs, so a
 * test that ended early would otherwise leave a sound discarded and the next
 * test would count it.
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
    await page.goto(ROWS);
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
    await page.goto(ROWS);
    await waitForRows(page);

    const rows = page.locator('[data-testid="row"][data-hash]:not([data-hash=""])');
    await rows.nth(1).getByTestId("row-select").click();
    await rows.nth(5).getByTestId("row-select").click({ modifiers: ["Shift"] });

    // Rows 1 through 5 inclusive: five of them.
    await expect(page.getByTestId("selection-count")).toContainText("5 sounds selected");
    await expect(page.locator('[data-testid="row"][data-selected="true"]')).toHaveCount(5);

    await page.getByTestId("selection-clear").click();
  });

  test("changing the query clears the selection", async ({ page }) => {
    // Acting on rows that scrolled out of a changed filter is how people
    // discard the wrong thing. The selection must not survive the change.
    await page.goto(ROWS);
    await waitForRows(page);

    await page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first().getByTestId("row-select").click();
    await expect(page.getByTestId("selection-bar")).toBeVisible();

    await page.getByTestId("search").fill("hat");
    await expect(page.getByTestId("search")).toHaveValue("hat");
    await expect
      .poll(async () => {
        const names = await page.locator('[data-testid="row"] .col-name a').allTextContents();
        return names.length > 0 && names.every((n) => n.toLowerCase().includes("hat"));
      })
      .toBe(true);
    await expect(page.getByTestId("selection-bar")).toHaveCount(0);
  });
});

test.describe("soft delete", () => {
  test("discarding a row marks it, and undo brings it back", async ({ page }) => {
    await page.goto(ROWS);
    await waitForRows(page);

    const first = page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first();
    const hash = await first.getAttribute("data-hash");
    expect(hash).toBeTruthy();

    await first.getByTestId("discard-row").click();
    await expect(page.getByTestId("undo-bar")).toBeVisible();

    // The sound itself is untouched: it still streams, and the server still
    // knows it.
    const still = await api(page, `/api/files/${hash}`);
    expect(still.hash).toBe(hash);
    expect(still.deleted).toBe(true);

    await page.getByTestId("undo").click();
    await expect.poll(async () => (await api(page, `/api/files/${hash}`)).deleted).toBe(false);
  });

  test("a bulk discard takes the whole selection in one action", async ({ page }) => {
    await page.goto(ROWS);
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
    for (const hash of hashes) {
      expect((await api(page, `/api/files/${hash}`)).deleted).toBe(true);
    }

    await page.getByTestId("undo").click();
    await expect.poll(async () => (await api(page, `/api/files/${hashes[0]}`)).deleted).toBe(false);
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

test("the header counts decided over total on every view", async ({ page }) => {
  const [hash] = await firstHashes(page, "sort=name&order=asc", 1);

  await page.goto("/");
  const counter = page.getByTestId("triage-counter");
  await expect(counter).toBeVisible();
  const before = Number(await counter.getAttribute("data-decided"));
  expect(Number(await counter.getAttribute("data-total"))).toBe(3451);

  // Discarding one sound is one more sound decided.
  await page.request.put(`/api/files/${hash}/deleted`);
  await page.reload();
  await expect.poll(async () => Number(await counter.getAttribute("data-decided"))).toBe(before + 1);

  // And it is in the header of every view, not only the swipe view.
  for (const view of ["/decided", "/search", "/board"]) {
    await page.goto(view);
    await expect(page.getByTestId("triage-counter")).toBeVisible();
    await expect(page.getByTestId("triage-counter")).toHaveAttribute("data-total", "3451");
  }

  await page.request.delete(`/api/files/${hash}/deleted`);
});

test("a sound in a project counts as decided", async ({ page }) => {
  // Decided means answered, and there are two answers. A taken sound is as
  // decided as a discarded one.
  const before = (await api(page, "/api/triage")) as { decided: number; taken: number };
  const hash = (await undecided(page, 1))[0];

  await page.request.put(`/api/projects/2026-09-16-rust-and-rebar/sounds/${hash}`);
  try {
    const after = (await api(page, "/api/triage")) as { decided: number; taken: number };
    expect(after.decided).toBe(before.decided + 1);
    expect(after.taken).toBe(before.taken + 1);
  } finally {
    await page.request.delete(`/api/projects/2026-09-16-rust-and-rebar/sounds/${hash}`);
  }
});
