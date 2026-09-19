"use client";

/**
 * The queue of undecided sounds, as the swipe view consumes it.
 *
 * A small buffer is held so that answering one sound reveals the next without
 * waiting for a request. The buffer is refilled from the top of the set, never
 * from an offset: every sound handed over gets answered before the next one
 * arrives, so the top of the set is always fresh and nothing can be skipped.
 *
 * `remaining` is the server's count less the decisions made since it was read.
 * It is never invented: when nothing could be read at all the status says
 * `absent` and the view says so rather than drawing a zero.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { fetchSwipeQueue } from "./api";
import type { FileRow, SwipeCarried, SwipeSource } from "./types";
import type { ProjectSummary } from "./project";

/** How many sounds are held ahead of the one on screen. */
const BATCH = 12;

export type SwipeStatus = "loading" | "ready" | "absent" | "error";

export interface SwipeQueueHandle {
  status: SwipeStatus;
  /**
   * A refill is in flight.
   *
   * A server that hands over one sound at a time leaves the buffer empty
   * between answers. "Nothing is undecided" and "the next one has not arrived
   * yet" are opposite claims, and the view must not print the first while the
   * second is true.
   */
  filling: boolean;
  /** The sound to answer, or null when there is none. */
  current: FileRow | null;
  /** The one after it, so its peaks can be warmed. */
  upcoming: FileRow | null;
  /**
   * What the queue answer carried about `current`, or null when it carried
   * nothing about it.
   *
   * It is matched to the sound on screen by hash before it is handed over. A
   * buffer with an answered sound filtered out of the front has a different
   * sound there, and the previous sound's measurement is not that sound's.
   */
  carried: SwipeCarried | null;
  /** The project a take would go into, as the server named it. */
  project: ProjectSummary | null;
  /** Undecided sounds left, this one included. Null when nothing is known. */
  remaining: number | null;
  source: SwipeSource | null;
  error: string | null;
  /**
   * This sound has been answered. Drop it and show the next.
   *
   * Called after the write succeeds, so a refusal leaves the sound on screen
   * rather than silently losing it out of the queue.
   */
  answered(hash: string): void;
  refresh(): void;
}

export function useSwipeQueue(): SwipeQueueHandle {
  const [buffer, setBuffer] = useState<FileRow[]>([]);
  const [filling, setFilling] = useState(true);
  const [status, setStatus] = useState<SwipeStatus>("loading");
  const [remaining, setRemaining] = useState<number | null>(null);
  const [carried, setCarried] = useState<SwipeCarried | null>(null);
  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [source, setSource] = useState<SwipeSource | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  /** Hashes answered since the last read, so the count stays honest. */
  const answeredRef = useRef<Set<string>>(new Set());
  const loadingRef = useRef(false);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  const fill = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    setFilling(true);
    // Answers made while this request is in flight are not in its answer.
    const before = answeredRef.current.size;
    try {
      const queue = await fetchSwipeQueue(BATCH);
      if (queue === null) {
        setStatus("absent");
        setSource(null);
        setRemaining(null);
        setCarried(null);
        setProject(null);
        return;
      }
      const missed = answeredRef.current.size - before;
      // The sound on screen is still undecided, so it is still at the top of
      // the set and keeps its place. Rows are keyed by hash, so nothing on
      // screen is rebuilt and nothing restarts.
      setBuffer(queue.items.filter((row) => !answeredRef.current.has(row.hash)));
      setRemaining(Math.max(queue.remaining - missed, 0));
      setCarried(queue.carried);
      setProject(queue.project);
      setSource(queue.source);
      setStatus("ready");
      setError(null);
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      loadingRef.current = false;
      setFilling(false);
    }
  }, []);

  useEffect(() => {
    void fill();
  }, [fill, version]);

  const answered = useCallback(
    (hash: string) => {
      answeredRef.current.add(hash);
      setRemaining((n) => (n === null ? null : Math.max(n - 1, 0)));
      setBuffer((rows) => rows.filter((row) => row.hash !== hash));
      // Read the queue again after every answer. A server that hands over one
      // sound at a time has nothing left in the buffer now, and one that hands
      // over a batch is cheap to re-read. `fill` drops the call when a request
      // is already in flight.
      void fill();
    },
    [fill],
  );

  return useMemo(() => {
    const current = buffer[0] ?? null;
    return {
      status,
      filling,
      current,
      upcoming: buffer[1] ?? null,
      // Only when it describes the sound actually on screen.
      carried: current && carried && carried.hash === current.hash ? carried : null,
      project,
      remaining,
      source,
      error,
      answered,
      refresh,
    };
  }, [status, filling, buffer, carried, project, remaining, source, error, answered, refresh]);
}
