/**
 * Helpers for the board tests.
 *
 * Every project these make is named with a known prefix and is removed again
 * afterwards. The mock server keeps its projects in memory and is reused
 * between runs, so a test that left three behind would push the next run over
 * the cap before it started. `clearScratchProjects` is what puts the fixture
 * back.
 *
 * Nothing here touches the real index. The mock server has its own collection
 * in memory; the project files it serves exist nowhere on disk.
 */

import { expect, type APIRequestContext } from "@playwright/test";

/** Every project a test makes is named with this in front of it. */
export const SCRATCH_PREFIX = "scratch";

export function scratchName(n: number): string {
  return `${SCRATCH_PREFIX} ${n}`;
}

interface ProjectRow {
  id: string;
  name: string;
  column: string;
  sound_count: number;
  /** Non-null means off the board, holding no slot. `column` says where it was. */
  abandoned: { at: string; from: string; reason: string } | null;
  commits: Array<{ column: string; at: string; digest: string }>;
}

export async function projects(request: APIRequestContext): Promise<ProjectRow[]> {
  const response = await request.get("/api/projects");
  expect(response.ok(), `/api/projects answered ${response.status()}`).toBe(true);
  return ((await response.json()) as { items: ProjectRow[] }).items;
}

export async function board(request: APIRequestContext) {
  const response = await request.get("/api/board");
  expect(response.ok(), `/api/board answered ${response.status()}`).toBe(true);
  return (await response.json()) as {
    columns: Array<{
      column: string;
      cap: number;
      count: number;
      /** How many of `count` are files the schema rejects. They hold their slots. */
      unreadable: number;
      over: boolean;
    }>;
    released: number;
    abandoned: number;
    unreadable: number;
  };
}

export async function columnState(request: APIRequestContext, column: string) {
  const state = await board(request);
  const found = state.columns.find((c) => c.column === column);
  expect(found, `no ${column} column on the board`).toBeTruthy();
  return found!;
}

/** Hashes from the fixture collection, read through the API rather than the DOM. */
export async function someHashes(request: APIRequestContext, n: number, offset = 0): Promise<string[]> {
  const response = await request.get(`/api/files?limit=${n}&offset=${offset}&sort=name`);
  return ((await response.json()) as { items: Array<{ hash: string }> }).items.map((f) => f.hash);
}

/** Make one project, going over the cap if it has to. Returns its id. */
export async function makeScratch(request: APIRequestContext, name: string): Promise<string> {
  const response = await request.post("/api/projects", { data: { name, override: true } });
  expect(response.ok(), `creating "${name}" answered ${response.status()}`).toBe(true);
  return ((await response.json()) as { id: string }).id;
}

export async function addSound(request: APIRequestContext, id: string, hash: string): Promise<number> {
  const response = await request.put(`/api/projects/${id}/sounds/${hash}`);
  return response.status();
}

export async function commit(
  request: APIRequestContext,
  id: string,
  override = false,
): Promise<{ status: number; body: Record<string, unknown> }> {
  const response = await request.post(`/api/projects/${id}/commit`, {
    data: override ? { override: true } : {},
  });
  return { status: response.status(), body: (await response.json()) as Record<string, unknown> };
}

/** Leave the board without promoting anything. No cap stands in the way. */
export async function abandon(
  request: APIRequestContext,
  id: string,
  reason = "",
): Promise<{ status: number; body: Record<string, unknown> }> {
  const response = await request.post(`/api/projects/${id}/abandon`, { data: { reason } });
  return { status: response.status(), body: (await response.json()) as Record<string, unknown> };
}

/** Come back to the column it left. Takes a slot, so a full column refuses it. */
export async function revive(
  request: APIRequestContext,
  id: string,
  override = false,
): Promise<{ status: number; body: Record<string, unknown> }> {
  const response = await request.post(`/api/projects/${id}/revive`, {
    data: override ? { override: true } : {},
  });
  return { status: response.status(), body: (await response.json()) as Record<string, unknown> };
}

/**
 * Put `howMany` extra projects into `stored`, overriding the cap each time.
 *
 * Used to make a column visibly over its limit so the board can be checked in
 * that state.
 */
export async function fillColumn(request: APIRequestContext, howMany: number): Promise<string[]> {
  const ids: string[] = [];
  for (let i = 0; i < howMany; i += 1) {
    ids.push(await makeScratch(request, scratchName(i + 1)));
  }
  return ids;
}

/**
 * Push `collage` up to exactly its cap, so the next commit out of `stored` is
 * gated by it. Returns the ids it made, all of which are scratch projects.
 */
export async function fillCollageToCap(request: APIRequestContext): Promise<string[]> {
  const state = await columnState(request, "collage");
  const needed = Math.max(0, state.cap - state.count);
  const hashes = await someHashes(request, needed + 1, 200);
  const ids: string[] = [];
  for (let i = 0; i < needed; i += 1) {
    const id = await makeScratch(request, `${SCRATCH_PREFIX} filler ${i + 1}`);
    ids.push(id);
    expect(await addSound(request, id, hashes[i])).toBe(200);
    const result = await commit(request, id, true);
    expect(result.status, `filling collage: commit answered ${result.status}`).toBe(200);
  }
  return ids;
}

/**
 * Remove every project a test made, in every column, including released ones.
 *
 * `DELETE /api/projects/{id}` is mock-only housekeeping and no part of the
 * interface calls it. It removes a project file and no audio.
 */
export async function clearScratchProjects(request: APIRequestContext): Promise<void> {
  for (const project of await projects(request)) {
    if (!project.name.startsWith(SCRATCH_PREFIX)) continue;
    const response = await request.delete(`/api/projects/${project.id}`);
    expect(
      response.ok(),
      `cleaning up ${project.id} answered ${response.status()}`,
    ).toBe(true);
  }
}
