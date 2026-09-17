"use client";

/**
 * The board's state, for the whole application.
 *
 * Two views need it: the board itself, and the occupancy meter in the header,
 * which sits beside the triage ratio because they are the same discipline at
 * two scales. Fetching it in one place means a commit made on the board moves
 * the header without a second request and without either view guessing.
 *
 * The project routes are written by a separate effort and may not be serving
 * yet. `status` tells the three apart, and no consumer may collapse them:
 *
 * - `loading`: nothing is known yet.
 * - `absent`: the routes answered "not here". The interface says so.
 * - `ready`: the answer is real, even if it is an empty board.
 *
 * An absent board is not an empty board. Drawing zeroes for one would be
 * inventing a number, and a fabricated occupancy is worse than none.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { fetchBoard, fetchProjects, type ProjectIndex, type UnreadableProject } from "@/lib/api";
import type { Board, ProjectSummary } from "@/lib/project";

export type BoardStatus = "loading" | "absent" | "ready" | "error";

export interface BoardApi {
  status: BoardStatus;
  /** Null unless `status` is `ready` and the server answered with columns. */
  board: Board | null;
  /** Null unless `status` is `ready` and the index answered. */
  projects: ProjectSummary[] | null;
  unreadable: UnreadableProject[];
  error: string | null;
  /** Bumped after every change, so a view can re-read its rows. */
  version: number;
  refresh(): void;
}

const BoardContext = createContext<BoardApi | null>(null);

export function useBoard(): BoardApi {
  const ctx = useContext(BoardContext);
  if (!ctx) throw new Error("useBoard must be used inside BoardProvider");
  return ctx;
}

export function BoardProvider({ children }: { children: ReactNode }) {
  const [board, setBoard] = useState<Board | null>(null);
  const [index, setIndex] = useState<ProjectIndex | null>(null);
  const [status, setStatus] = useState<BoardStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([fetchBoard(controller.signal), fetchProjects(controller.signal)])
      .then(([nextBoard, nextIndex]) => {
        if (controller.signal.aborted) return;
        setBoard(nextBoard);
        setIndex(nextIndex);
        // Both routes absent means the feature is not serving. One of the two
        // absent is still a real answer, and each consumer says what it is
        // missing rather than the whole board going dark.
        setStatus(nextBoard === null && nextIndex === null ? "absent" : "ready");
        setError(null);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setBoard(null);
        setIndex(null);
        setStatus("error");
        setError(err instanceof Error ? err.message : String(err));
      });
    return () => controller.abort();
  }, [version]);

  const api = useMemo<BoardApi>(
    () => ({
      status,
      board,
      projects: index?.items ?? null,
      unreadable: index?.unreadable ?? [],
      error,
      version,
      refresh,
    }),
    [status, board, index, error, version, refresh],
  );

  return <BoardContext.Provider value={api}>{children}</BoardContext.Provider>;
}
