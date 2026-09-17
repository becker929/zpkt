/**
 * Triage from a phone.
 *
 * This project runs under an iPhone device descriptor: WebKit at 393 by 852
 * with touch and a device pixel ratio of 3. A narrow desktop window has a
 * mouse, so it would let a checkbox column and a hover target pass as working
 * when neither exists under a thumb.
 *
 * What is checked here is what only a touch device can show: that a long press
 * starts a selection, that the bulk bar does not cover the player, that the
 * whole discard-and-move-on loop works one-thumbed, and that the counter stays
 * in the header when the collection totals are folded away.
 */

import { expect, test, type ConsoleMessage, type Page } from "@playwright/test";

import { waitForRows } from "./helpers";

/** Errors from the dev server talking to itself, not from the page. */
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

/**
 * Hold a thumb on a row long enough to select it.
 *
 * `tap` is too short by design. This is a real touch sequence: down, wait,
 * up, which is what the interface has to distinguish from a tap that plays.
 */
async function longPress(page: Page, selector: string): Promise<void> {
  const box = await page.locator(selector).first().boundingBox();
  expect(box, `no box for ${selector}`).not.toBeNull();
  const x = box!.x + box!.width * 0.4;
  const y = box!.y + box!.height / 2;
  await page.locator(selector).first().dispatchEvent("pointerdown", {
    pointerType: "touch",
    clientX: x,
    clientY: y,
    bubbles: true,
  });
  await page.waitForTimeout(700);
  await page.locator(selector).first().dispatchEvent("pointerup", {
    pointerType: "touch",
    clientX: x,
    clientY: y,
    bubbles: true,
  });
}

test("a long press starts a selection and a tap then picks rows", async ({ page }) => {
  await page.goto("/?sort=name&order=asc");
  await waitForRows(page);

  // Nothing is selected, and there is no checkbox column taking room from the
  // name on a 393 pixel row.
  await expect(page.getByTestId("selection-bar")).toHaveCount(0);
  await expect(page.locator('[data-testid="row"] [data-testid="row-select"]').first()).toBeHidden();

  await longPress(page, '[data-testid="row"][data-hash]:not([data-hash=""])');
  await expect(page.getByTestId("selection-bar")).toBeVisible();
  await expect(page.getByTestId("selection-count")).toContainText("1 sound selected");

  // The press must not also have loaded the row into the player.
  await expect(page.getByTestId("player-bar")).toHaveCount(0);

  // Now a tap picks, rather than plays.
  const second = page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').nth(1);
  await second.tap();
  await expect(page.getByTestId("selection-count")).toContainText("2 sounds selected");
  await expect(page.getByTestId("player-bar")).toHaveCount(0);

  // A tap on a picked row lets it go.
  await second.tap();
  await expect(page.getByTestId("selection-count")).toContainText("1 sound selected");

  await page.getByTestId("selection-clear").tap();
  await expect(page.getByTestId("selection-bar")).toHaveCount(0);

  // And once nothing is selected, a tap plays again.
  await page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first().tap();
  await expect(page.getByTestId("player-bar")).toBeVisible();
});

test("the bulk bar never covers the player", async ({ page }) => {
  await page.goto("/");
  await waitForRows(page);
  await page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first().tap();
  await expect(page.getByTestId("player-bar")).toBeVisible();

  await longPress(page, '[data-testid="row"][data-hash]:not([data-hash=""])');
  await expect(page.getByTestId("selection-bar")).toBeVisible();

  const viewport = page.viewportSize();
  const bar = await page.getByTestId("selection-bar").boundingBox();
  const player = await page.getByTestId("player-bar").boundingBox();
  expect(bar).not.toBeNull();
  expect(player).not.toBeNull();

  // The bar sits above the player, and the player is still wholly on screen.
  expect(bar!.y + bar!.height, "the selection bar overlaps the player").toBeLessThanOrEqual(player!.y + 1);
  expect(player!.y + player!.height).toBeLessThanOrEqual(viewport!.height + 1);

  // The transport is still reachable while a decision is being made.
  await expect(page.getByTestId("play-pause")).toBeVisible();
  await page.getByTestId("play-pause").tap();

  // Every action in the bar is a thumb-sized target.
  for (const id of ["bulk-star", "bulk-list", "bulk-discard", "selection-clear"]) {
    const box = await page.getByTestId(id).boundingBox();
    expect(box, `no box for ${id}`).not.toBeNull();
    expect(box!.height, `${id} is too small for a thumb`).toBeGreaterThanOrEqual(36);
  }

  await page.getByTestId("selection-clear").tap();
});

test("the one-thumbed loop: play, discard, undo", async ({ page }) => {
  await page.goto("/?sort=name&order=asc");
  await waitForRows(page);

  const first = page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first();
  const hash = await first.getAttribute("data-hash");
  await first.tap();
  await expect(page.getByTestId("player-bar")).toHaveAttribute("data-hash", hash ?? "");

  // Discard straight from the player bar, where the thumb already is.
  const discard = page.getByTestId("player-discard");
  // A thumb-sized target, beside the star, in the bar that is playing it.
  const box = await discard.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.width).toBeGreaterThanOrEqual(40);
  expect(box!.height).toBeGreaterThanOrEqual(40);
  await discard.tap();

  await expect(page.getByTestId("undo-bar")).toBeVisible();
  await expect(page.locator(`[data-testid="row"][data-hash="${hash}"]`)).toHaveCount(0);
  await expect(page.getByTestId("result-count")).toHaveText("3,450 sounds");

  // The undo strip is above the player too.
  const undo = await page.getByTestId("undo-bar").boundingBox();
  const player = await page.getByTestId("player-bar").boundingBox();
  expect(undo!.y + undo!.height).toBeLessThanOrEqual(player!.y + 1);

  await page.getByTestId("undo").tap();
  await expect(page.getByTestId("result-count")).toHaveText("3,451 sounds");
  await expect.poll(async () => page.locator(`[data-testid="row"][data-hash="${hash}"]`).count()).toBe(1);
});

test("a row keeps a discard and a star a thumb can hit", async ({ page }) => {
  await page.goto("/");
  await waitForRows(page);

  const row = page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first();
  const rowBox = await row.boundingBox();
  const discard = await row.getByTestId("discard-row").boundingBox();
  const star = await row.getByTestId("favorite-toggle").boundingBox();
  expect(discard).not.toBeNull();
  expect(star).not.toBeNull();

  // Both inside the viewport, not pushed off the end of an overflowing row.
  const viewport = page.viewportSize();
  expect(discard!.x + discard!.width).toBeLessThanOrEqual(viewport!.width);
  expect(star!.x + star!.width).toBeLessThanOrEqual(viewport!.width);
  expect(discard!.height).toBeGreaterThanOrEqual(24);

  // The name still has about half the row.
  const name = await row.locator(".col-name").boundingBox();
  const share = name!.width / rowBox!.width;
  expect(share).toBeGreaterThan(0.4);
  expect(share).toBeLessThan(0.62);
});

test("the header keeps the progress counter on a phone", async ({ page }) => {
  await page.goto("/");
  await waitForRows(page);

  // The collection totals are folded away here; the counter that moves stays.
  await expect(page.getByTestId("topbar-stats")).toBeHidden();
  const counter = page.getByTestId("triage-counter");
  await expect(counter).toBeVisible();

  const viewport = page.viewportSize();
  const box = await counter.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x + box!.width, "the counter runs off the side of the header").toBeLessThanOrEqual(
    viewport!.width + 1,
  );

  // Every destination is still reachable, and none of them wrapped off the bar.
  for (const label of ["list", "lists", "playlist", "duplicates"]) {
    const link = page.getByRole("link", { name: label, exact: true });
    await expect(link).toBeVisible();
    const linkBox = await link.boundingBox();
    expect(linkBox!.x + linkBox!.width, `${label} runs off the header`).toBeLessThanOrEqual(viewport!.width + 1);
  }
});

test("the lists views hydrate without a mismatch", async ({ context }) => {
  for (const view of ["/lists", "/lists/1"]) {
    const page = await context.newPage();
    const errors = watchConsole(page);
    await page.goto(view);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);
    expect(errors, `${view} logged console errors`).toEqual([]);
    await page.close();
  }
});

test("a list plays as a queue from a phone", async ({ page }) => {
  await page.goto("/lists");
  const card = page.getByTestId("list-card").first();
  await expect(card).toBeVisible();
  await card.getByTestId("list-link").tap();

  await expect(page.getByTestId("list-row").first()).toBeVisible();
  const first = await page.getByTestId("list-row").first().getAttribute("data-hash");
  await page.getByTestId("list-play-all").tap();
  await expect(page.getByTestId("player-bar")).toHaveAttribute("data-hash", first ?? "");

  // The player bar is on screen, as it must be on every view.
  const viewport = page.viewportSize();
  const box = await page.getByTestId("player-bar").boundingBox();
  expect(box!.y + box!.height).toBeLessThanOrEqual(viewport!.height + 1);
});
