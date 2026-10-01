/**
 * Answering sounds from a phone.
 *
 * This project runs under an iPhone device descriptor: WebKit at 393 by 852
 * with touch and a device pixel ratio of 3. A narrow desktop window has a
 * mouse, so it would let a hover target and a checkbox column pass as working
 * when neither exists under a thumb.
 *
 * What is checked here is what only a touch device can show: that the swipe
 * view can be worked one-thumbed, that its two answers sit where a thumb can
 * reach them, that a long press still starts a selection on the views that
 * have rows, and that the counter stays in the header when the collection
 * totals are folded away.
 */

import { expect, test, type ConsoleMessage, type Page } from "@playwright/test";

import { api, waitForRows } from "./helpers";

/** A view with rows in it. Nothing lists the undecided collection any more. */
const ROWS = "/search?q=kick";

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

test.afterEach(async ({ page }) => {
  const body = await api(page, "/api/files?deleted=true&limit=1000");
  const hashes = (body.items as Array<{ hash: string }>).map((f) => f.hash);
  if (hashes.length > 0) {
    await page.request.post("/api/bulk", { data: { hashes, action: "restore" } });
  }
});

test("the whole swipe view fits on the phone, and both answers are under the thumb", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("swipe-card")).toBeVisible();

  const viewport = page.viewportSize();
  expect(viewport).not.toBeNull();

  for (const id of ["swipe-discard", "swipe-take"]) {
    const box = await page.getByTestId(id).boundingBox();
    expect(box, `no box for ${id}`).not.toBeNull();
    // Inside the screen on both axes, and clear of the home indicator.
    expect(box!.x, `${id} runs off the left`).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width, `${id} runs off the right`).toBeLessThanOrEqual(viewport!.width + 1);
    expect(box!.y + box!.height, `${id} hangs below the viewport`).toBeLessThanOrEqual(viewport!.height + 1);
    // Bigger than the 44 pixel minimum: these two are pressed more than
    // anything else in the application.
    expect(box!.height, `${id} is too small for a thumb`).toBeGreaterThanOrEqual(56);
    // In the bottom third, which is the only part of an 852 pixel screen a
    // thumb reaches without moving the hand.
    expect(box!.y, `${id} is out of thumb reach`).toBeGreaterThan(viewport!.height * 0.6);
  }

  // Nothing is scrolled off: the card, the transport and the answers all fit.
  const card = await page.getByTestId("swipe-card").boundingBox();
  expect(card!.y + card!.height).toBeLessThanOrEqual(viewport!.height + 1);
  await expect(page.getByTestId("swipe-play")).toBeVisible();
});

test("the one-thumbed loop: listen, answer, and the next sound arrives", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("swipe-card")).toBeVisible();

  const hash = await page.getByTestId("swipe").getAttribute("data-hash");
  expect(hash).toBeTruthy();

  await page.getByTestId("swipe-discard").tap();
  await expect.poll(async () => page.getByTestId("swipe").getAttribute("data-hash")).not.toBe(hash);

  // Undo is a thumb-sized target too, and it is where the answer just was.
  const undo = page.getByTestId("swipe-undo");
  await expect(undo).toBeVisible();
  const box = await undo.boundingBox();
  expect(box!.height).toBeGreaterThanOrEqual(30);
  await undo.tap();
  await expect(page.getByTestId("swipe-last")).toHaveCount(0);
});

test("a sideways drag answers the sound", async ({ page }) => {
  await page.goto("/");
  const card = page.getByTestId("swipe-card");
  await expect(card).toBeVisible();
  const hash = await page.getByTestId("swipe").getAttribute("data-hash");

  const box = await card.boundingBox();
  const y = box!.y + box!.height / 2;
  const from = box!.x + box!.width * 0.7;

  // Far enough left to pass the threshold, in steps, as a thumb moves.
  await card.dispatchEvent("pointerdown", { pointerType: "touch", clientX: from, clientY: y, bubbles: true });
  for (const dx of [20, 60, 110, 150]) {
    await card.dispatchEvent("pointermove", {
      pointerType: "touch",
      clientX: from - dx,
      clientY: y,
      bubbles: true,
    });
  }
  // The card says what letting go would do before it does it.
  await expect(card).toHaveAttribute("data-intent", "discard");
  await card.dispatchEvent("pointerup", { pointerType: "touch", clientX: from - 150, clientY: y, bubbles: true });

  await expect.poll(async () => page.getByTestId("swipe").getAttribute("data-hash")).not.toBe(hash);
  expect((await api(page, `/api/files/${hash}`)).deleted).toBe(true);
});

test("a long press starts a selection and a tap then picks rows", async ({ page }) => {
  await page.goto(ROWS);
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
  await page.goto(ROWS);
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
  for (const id of ["bulk-discard", "selection-clear"]) {
    const box = await page.getByTestId(id).boundingBox();
    expect(box, `no box for ${id}`).not.toBeNull();
    expect(box!.height, `${id} is too small for a thumb`).toBeGreaterThanOrEqual(36);
  }

  await page.getByTestId("selection-clear").tap();
});

test("a row keeps a discard button a thumb can hit", async ({ page }) => {
  await page.goto(ROWS);
  await waitForRows(page);

  const row = page.locator('[data-testid="row"][data-hash]:not([data-hash=""])').first();
  const rowBox = await row.boundingBox();
  const discard = await row.getByTestId("discard-row").boundingBox();
  expect(discard).not.toBeNull();

  // Inside the viewport, not pushed off the end of an overflowing row.
  const viewport = page.viewportSize();
  expect(discard!.x + discard!.width).toBeLessThanOrEqual(viewport!.width);
  expect(discard!.height).toBeGreaterThanOrEqual(24);

  // The name takes most of the row, because the name is what a row says.
  const name = await row.locator(".col-name").boundingBox();
  expect(name!.width / rowBox!.width).toBeGreaterThan(0.5);
});

test("the header keeps the progress counter on a phone", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("swipe-card")).toBeVisible();

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
  for (const label of ["swipe", "decided", "search", "board"]) {
    const link = page.getByRole("link", { name: label, exact: true });
    await expect(link).toBeVisible();
    const linkBox = await link.boundingBox();
    expect(linkBox!.x + linkBox!.width, `${label} runs off the header`).toBeLessThanOrEqual(viewport!.width + 1);
  }
});

test("the decided view hydrates without a mismatch under both filters", async ({ context }) => {
  const page = await context.newPage();
  const errors = watchConsole(page);
  await page.goto("/decided");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("filter-discarded").tap();
  await page.waitForTimeout(500);
  expect(errors, "the decided view logged console errors").toEqual([]);
  await page.close();
});
