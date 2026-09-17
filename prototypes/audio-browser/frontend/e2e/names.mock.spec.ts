/**
 * What a project is called, and what its id ends up being.
 *
 * The id is a filename, so it has to be safe: lower case letters, digits and
 * single hyphens, and nothing that differs only by case. That is not a licence
 * to throw the name away. `техно 909` is a name, and an id of `909` says nothing
 * about the project it belongs to; a folder of those is a folder nobody can
 * read.
 *
 * Every project made here is deleted afterwards by id, because a name in
 * another script does not start with the scratch prefix and the usual cleanup
 * would not find it.
 */

import { expect, test, type APIRequestContext } from "@playwright/test";

import { abandon, addSound, commit, projects, someHashes } from "./board-helpers";

/** Create with the cap overridden, and give back the id it was filed under. */
async function create(request: APIRequestContext, name: string): Promise<string> {
  const response = await request.post("/api/projects", { data: { name, override: true } });
  expect(response.ok(), `creating “${name}” answered ${response.status()}`).toBe(true);
  return ((await response.json()) as { id: string }).id;
}

async function remove(request: APIRequestContext, ids: string[]): Promise<void> {
  for (const id of ids) await request.delete(`/api/projects/${id}`);
}

/** The date in front of every id: today, as the server writes it. */
const DATE = /^\d{4}-\d{2}-\d{2}-/;

test.describe("ids from names that are not Latin", () => {
  test("a Cyrillic name is read into Latin letters rather than thrown away", async ({ request }) => {
    const made: string[] = [];
    try {
      const id = await create(request, "техно 909");
      made.push(id);
      // Not `2026-09-17-909`, which keeps the digits and loses the word.
      expect(id).toMatch(DATE);
      expect(id.replace(DATE, "")).toBe("tekhno-909");
    } finally {
      await remove(request, made);
    }
  });

  test("a Greek name keeps its sound too", async ({ request }) => {
    const made: string[] = [];
    try {
      const id = await create(request, "θάλασσα 2");
      made.push(id);
      expect(id.replace(DATE, "")).toBe("thalassa-2");
    } finally {
      await remove(request, made);
    }
  });

  test("a name with no Latin reading is named by its characters, not called “project”", async ({
    request,
  }) => {
    const made: string[] = [];
    try {
      const id = await create(request, "🔥🔥🔥");
      made.push(id);
      // `project` would be a meaningless id, and the second one of them would be
      // `project-2`: a directory of projects nobody can tell apart.
      expect(id.replace(DATE, "")).not.toBe("project");
      expect(id.replace(DATE, "")).toBe("u1f525");

      // Derived from the name, so a different name is a different id.
      const other = await create(request, "🎛️");
      made.push(other);
      expect(other).not.toBe(id);
      expect(other.replace(DATE, "")).not.toBe("project");
    } finally {
      await remove(request, made);
    }
  });

  test("an accented Latin name loses its marks and nothing else", async ({ request }) => {
    const made: string[] = [];
    try {
      const id = await create(request, "béton armé");
      made.push(id);
      expect(id.replace(DATE, "")).toBe("beton-arme");
    } finally {
      await remove(request, made);
    }
  });

  test("two names that reduce to one id get different files", async ({ request }) => {
    const made: string[] = [];
    try {
      const first = await create(request, "техно 909");
      made.push(first);
      const second = await create(request, "tekhno 909");
      made.push(second);
      expect(second).not.toBe(first);
      expect(second.startsWith(first)).toBe(true);
    } finally {
      await remove(request, made);
    }
  });
});

test.describe("saying a name is already taken", () => {
  test("it compares every project, not only the ones in this column", async ({ page, request }) => {
    const made: string[] = [];
    try {
      // One committed out of `stored`, so it is in `collage` and not on screen
      // in the column the name is being typed into.
      const promoted = await create(request, "conveyor of rust");
      made.push(promoted);
      const [hash] = await someHashes(request, 1, 800);
      expect(await addSound(request, promoted, hash)).toBe(200);
      expect((await commit(request, promoted, true)).status).toBe(200);
      expect((await projects(request)).find((p) => p.id === promoted)?.column).toBe("collage");

      await page.goto("/board");
      await page.getByTestId("new-project-name").fill("conveyor of rust");
      const note = page.getByTestId("duplicate-name");
      await expect(note).toBeVisible();
      await expect(note).toHaveAttribute("data-clash", promoted);
      await expect(note).toContainText("collage");

      // A project nobody can see is the one most likely to be started twice, so
      // an abandoned one is compared as well — and the note offers the way back
      // rather than only warning.
      const gone = await create(request, "slag and ash");
      made.push(gone);
      expect((await abandon(request, gone, "")).status).toBe(200);

      await page.reload();
      await page.getByTestId("new-project-name").fill("slag and ash");
      await expect(note).toHaveAttribute("data-clash", gone);
      await expect(note).toContainText("revive");

      // Case and surrounding space do not make it a different name to a reader.
      await page.getByTestId("new-project-name").fill("  Slag And Ash  ");
      await expect(note).toHaveAttribute("data-clash", gone);

      // And a name nothing is called says nothing.
      await page.getByTestId("new-project-name").fill("slag and ashes");
      await expect(page.getByTestId("duplicate-name")).toHaveCount(0);
    } finally {
      await remove(request, made);
    }
  });
});
