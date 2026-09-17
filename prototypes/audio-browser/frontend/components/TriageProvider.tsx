"use client";

/**
 * Triage state for the whole application: the progress counter, and the one
 * place that writes a decision about a sound.
 *
 * Every view routes its actions through `run`, so three things hold everywhere
 * without each view arranging them: the counter is re-read after a change, the
 * views that show rows are told to re-fetch, and the last action stays undoable
 * until the next one replaces it.
 *
 * Nothing here can remove a file. Discarding writes a row keyed on a hash;
 * restore removes that row. There is deliberately no path from this module to
 * the filesystem.
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

import { usePlayer } from "@/components/PlayerProvider";
import { bulk, fetchTriage, setDeleted, setFavorite, setListMember } from "@/lib/api";
import type { BulkAction, BulkResult, TriageCounts } from "@/lib/types";

/** The action that undoes each action. */
const INVERSE: Record<BulkAction, BulkAction> = {
  star: "unstar",
  unstar: "star",
  delete: "restore",
  restore: "delete",
  add_to_list: "remove_from_list",
  remove_from_list: "add_to_list",
};

/** What the undo strip offers, and what it will send if taken. */
export interface UndoOffer {
  /** What just happened, in the user's words. */
  label: string;
  action: BulkAction;
  hashes: string[];
  listId?: number;
}

export interface TriageApi {
  counts: TriageCounts | null;
  /** Bumped after every change, so a view can re-fetch its rows. */
  version: number;
  undo: UndoOffer | null;
  /** The last write that failed, or null. */
  error: string | null;
  /**
   * Apply one decision to one or more hashes.
   *
   * A single hash goes to its own route; more than one goes to `/api/bulk`,
   * which the server applies in a single transaction. Both are addressed by
   * hash and neither touches a path.
   */
  run(
    action: BulkAction,
    hashes: string[],
    options?: { listId?: number; label?: string; undoable?: boolean },
  ): Promise<BulkResult | null>;
  /** Take the standing undo offer. */
  takeUndo(): Promise<void>;
  dismissUndo(): void;
  dismissError(): void;
  refresh(): void;
}

const TriageContext = createContext<TriageApi | null>(null);

export function useTriage(): TriageApi {
  const ctx = useContext(TriageContext);
  if (!ctx) throw new Error("useTriage must be used inside TriageProvider");
  return ctx;
}

/** "3 sounds" but "1 sound". */
export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? one : many}`;
}

function describe(action: BulkAction, n: number): string {
  const what = plural(n, "sound");
  switch (action) {
    case "delete":
      return `discarded ${what}`;
    case "restore":
      return `restored ${what}`;
    case "star":
      return `starred ${what}`;
    case "unstar":
      return `unstarred ${what}`;
    case "add_to_list":
      return `added ${what} to the list`;
    case "remove_from_list":
      return `removed ${what} from the list`;
  }
}

export function TriageProvider({ children }: { children: ReactNode }) {
  const player = usePlayer();
  const [counts, setCounts] = useState<TriageCounts | null>(null);
  const [version, setVersion] = useState(0);
  /** Bumped when only the counter needs re-reading, not every row on screen. */
  const [countsTick, setCountsTick] = useState(0);
  const [undo, setUndo] = useState<UndoOffer | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  // Starring is the one decision that has its own path through the player, so
  // that a tapped star lights up before the request finishes. The counter has
  // to follow it, because a starred sound is a triaged sound.
  useEffect(() => {
    if (player.favoriteVersion > 0) setCountsTick((t) => t + 1);
  }, [player.favoriteVersion]);

  // Re-read the counter after every change. A 404 means the triage routes are
  // not serving yet, and the header simply shows no counter.
  useEffect(() => {
    const controller = new AbortController();
    fetchTriage(controller.signal)
      .then((next) => {
        if (!controller.signal.aborted) setCounts(next);
      })
      .catch(() => {
        if (!controller.signal.aborted) setCounts(null);
      });
    return () => controller.abort();
  }, [version, countsTick]);

  /** Send one decision, by the cheapest route that carries it. */
  const send = useCallback(
    async (action: BulkAction, hashes: string[], listId?: number): Promise<BulkResult | null> => {
      if (hashes.length === 0) return null;
      if (hashes.length === 1) {
        const hash = hashes[0];
        if (action === "star" || action === "unstar") await setFavorite(hash, action === "star");
        else if (action === "delete" || action === "restore") await setDeleted(hash, action === "delete");
        else if (listId !== undefined) await setListMember(listId, hash, action === "add_to_list");
        else return null;
        return {
          action,
          list_id: listId ?? null,
          requested: 1,
          unique: 1,
          matched: 1,
          changed: 1,
          unchanged: 0,
          skipped: 0,
        };
      }
      return bulk(hashes, action, listId);
    },
    [],
  );

  const run = useCallback<TriageApi["run"]>(
    async (action, hashes, options = {}) => {
      if (hashes.length === 0) return null;
      setError(null);
      try {
        const result = await send(action, hashes, options.listId);
        // A new action replaces the standing offer, whether or not this one is
        // itself undoable. Undo always means "the thing that just happened".
        setUndo(
          options.undoable === false
            ? null
            : {
                label: options.label ?? describe(action, result?.changed ?? hashes.length),
                action: INVERSE[action],
                hashes,
                listId: options.listId,
              },
        );
        setVersion((v) => v + 1);
        return result;
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setVersion((v) => v + 1);
        return null;
      }
    },
    [send],
  );

  const takeUndo = useCallback(async () => {
    const offer = undo;
    if (!offer) return;
    setUndo(null);
    setError(null);
    try {
      await send(offer.action, offer.hashes, offer.listId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
    setVersion((v) => v + 1);
  }, [send, undo]);

  const dismissUndo = useCallback(() => setUndo(null), []);
  const dismissError = useCallback(() => setError(null), []);

  const api = useMemo<TriageApi>(
    () => ({ counts, version, undo, error, run, takeUndo, dismissUndo, dismissError, refresh }),
    [counts, version, undo, error, run, takeUndo, dismissUndo, dismissError, refresh],
  );

  return <TriageContext.Provider value={api}>{children}</TriageContext.Provider>;
}
