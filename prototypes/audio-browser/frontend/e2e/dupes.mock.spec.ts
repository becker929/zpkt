/**
 * The duplicates view, and the guard that keeps it from pointing at Logic
 * project media.
 *
 * Nothing in this application deletes audio. What this view can still get
 * wrong is telling the user that bytes are free to remove when they are not.
 */

import { expect, test } from "@playwright/test";

import { api } from "./helpers";

test.beforeEach(async ({ page }) => {
  await page.goto("/dupes");
  await expect(page.getByTestId("dupes")).toBeVisible();
});

test("the default view lists no path inside a project bundle", async ({ page }) => {
  await expect(page.getByTestId("dupe-group").first()).toBeVisible();
  await expect(page.getByTestId("path-locked")).toHaveCount(0);

  const paths = await page.getByTestId("dupe-path").locator(".path").allTextContents();
  expect(paths.length).toBeGreaterThan(0);
  for (const path of paths) expect(path).not.toContain(".logicx/");
});

test("what the guard withheld is reported, not hidden silently", async ({ page }) => {
  const guard = page.getByTestId("bundle-guard");
  await expect(guard).toBeVisible();
  await expect(guard).toContainText("not listed");
  await expect(guard).toContainText("corrupts the project");
});

test("the guard's totals match the server's", async ({ page }) => {
  const scoped = await api(page, "/api/dupes?limit=1");
  const raw = await api(page, "/api/dupes?limit=1&include_bundles=true");

  expect(Number(scoped.total)).toBeLessThan(Number(raw.total));
  expect(Number(scoped.wasted_bytes)).toBeLessThan(Number(raw.wasted_bytes));
  expect(Number(scoped.excluded_bundle_groups)).toBe(Number(raw.total) - Number(scoped.total));
  expect(Number(scoped.excluded_bundle_bytes)).toBe(
    Number(raw.wasted_bytes) - Number(scoped.wasted_bytes),
  );
  expect(Number(raw.excluded_bundle_groups)).toBe(0);
});

test("asking to see bundle copies marks every one of them undeletable", async ({ page }) => {
  await page.getByTestId("show-bundles").click();
  await expect(page.getByTestId("bundle-warning")).toBeVisible();
  await expect(page.getByTestId("path-locked").first()).toBeVisible();

  // Every path that sits in a bundle carries the mark, and no path that
  // carries the mark is offered as deletable.
  const rows = page.getByTestId("dupe-path");
  const count = await rows.count();
  expect(count).toBeGreaterThan(0);
  for (let i = 0; i < count; i += 1) {
    const row = rows.nth(i);
    const path = (await row.locator(".path").textContent()) ?? "";
    const deletable = await row.getAttribute("data-deletable");
    expect(deletable).toBe(path.includes(".logicx/") ? "false" : "true");
  }
});

test("the view can go back to what a cleanup could free", async ({ page }) => {
  await page.getByTestId("show-bundles").click();
  await expect(page.getByTestId("path-locked").first()).toBeVisible();
  await page.getByTestId("hide-bundles").click();
  await expect(page.getByTestId("path-locked")).toHaveCount(0);
});

test("no button on the page offers to delete anything", async ({ page }) => {
  // The user decides removals by ear, by hand. If a delete control is ever
  // added, this is where it shows up.
  const labels = await page.getByRole("button").allTextContents();
  for (const label of labels) {
    expect(label.toLowerCase()).not.toMatch(/\bdelete\b|\bremove\b|\bclean up\b|\btrash\b/);
  }
});

test("a group links to the sound's detail page", async ({ page }) => {
  const group = page.getByTestId("dupe-group").first();
  const hash = await group.getAttribute("data-hash");
  await group.getByRole("link").click();
  await expect(page.getByTestId("detail")).toHaveAttribute("data-hash", hash ?? "");
});
