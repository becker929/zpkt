"use client";

/**
 * Triage state for the whole application: the progress counter, and the one
 * place that writes a discard.
 *
 * Every view routes its discards through `run`, so three things hold everywhere
 * without each view arranging them: the counter is re-read after a change, the
 * views that show rows are told to re-fetch, and the last action stays undoable
 * until the next one replaces it.
 *
 * The other decision — taking a sound into a project — is a write to a project
 * file and goes through `lib/api.ts`. It is made one sound at a time, in the
 * swipe view, so it needs none of the batching here.
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

import { bulk, fetchTriage, setDeleted } from "@/lib/api";
import type { BulkAction, BulkResult, TriageCounts } from "@/lib/types";

/** The action that undoes each action. */
const INVERSE: Record<BulkAction, BulkAction> = {
  delete: "restore",
  restore: "delete",
};

/** What the undo strip offers, and what it will send if taken. */
export interface UndoOffer {
  /** What just happened, in the user's words. */
  label: string;
  action: BulkAction;
  hashes: string[];
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
    options?: { label?: string; undoable?: boolean },
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
  return action === "delete" ? `discarded ${what}` : `restored ${what}`;
}

export function TriageProvider({ children }: { children: ReactNode }) {
  const [counts, setCounts] = useState<TriageCounts | null>(null);
  const [version, setVersion] = useState(0);
  const [undo, setUndo] = useState<UndoOffer | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

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
  }, [version]);

  /** Send one decision, by the cheapest route that carries it. */
  const send = useCallback(async (action: BulkAction, hashes: string[]): Promise<BulkResult | null> => {
    if (hashes.length === 0) return null;
    if (hashes.length === 1) {
      await setDeleted(hashes[0], action === "delete");
      return { action, requested: 1, unique: 1, matched: 1, changed: 1, unchanged: 0, skipped: 0 };
    }
    return bulk(hashes, action);
  }, []);

  const run = useCallback<TriageApi["run"]>(
    async (action, hashes, options = {}) => {
      if (hashes.length === 0) return null;
      setError(null);
      try {
        const result = await send(action, hashes);
        // A new action replaces the standing offer, whether or not this one is
        // itself undoable. Undo always means "the thing that just happened".
        setUndo(
          options.undoable === false
            ? null
            : {
                label: options.label ?? describe(action, result?.changed ?? hashes.length),
                action: INVERSE[action],
                hashes,
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
      await send(offer.action, offer.hashes);
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
