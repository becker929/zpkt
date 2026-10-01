"use client";

/**
 * Which rows are selected, and the rules about when they stop being selected.
 *
 * Selection is held as hashes, never as row indices: a row index means nothing
 * once the set behind it changes. `resetKey` is the identity of the current
 * view, normally the URL the list is fetching. When it changes the selection is
 * dropped, because the rows it named have scrolled out of a different filter
 * and acting on them is how people discard the wrong thing.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { MAX_BULK_HASHES } from "./types";

export interface SelectionHandle {
  /** Selected hashes, in the order they were picked. */
  hashes: string[];
  size: number;
  /** True once anything is selected. The row's tap then toggles instead of playing. */
  active: boolean;
  /** True when the selection has reached the server's cap on one batch. */
  full: boolean;
  has(hash: string): boolean;
  toggle(hash: string, index?: number): void;
  add(hashes: string[]): void;
  /**
   * Select every row between the last picked one and this one.
   *
   * `resolve` turns an index into a hash, or null when that row's page is not
   * loaded. A range over rows that have never been fetched takes the rows that
   * are there; it does not invent the rest.
   */
  extendTo(index: number, resolve: (index: number) => string | null): void;
  clear(): void;
}

export function useSelection(resetKey: string): SelectionHandle {
  const [hashes, setHashes] = useState<string[]>([]);
  const anchorRef = useRef<number | null>(null);
  const keyRef = useRef(resetKey);

  // A changed filter drops the selection. Only a real change: the first render
  // must not clear, or a selection could never survive its own re-render.
  useEffect(() => {
    if (keyRef.current === resetKey) return;
    keyRef.current = resetKey;
    anchorRef.current = null;
    setHashes([]);
  }, [resetKey]);

  const set = useMemo(() => new Set(hashes), [hashes]);

  const has = useCallback((hash: string) => set.has(hash), [set]);

  const toggle = useCallback((hash: string, index?: number) => {
    if (index !== undefined) anchorRef.current = index;
    setHashes((prev) =>
      prev.includes(hash) ? prev.filter((h) => h !== hash) : prev.concat(hash).slice(0, MAX_BULK_HASHES),
    );
  }, []);

  const add = useCallback((incoming: string[]) => {
    setHashes((prev) => {
      const seen = new Set(prev);
      const out = prev.slice();
      for (const hash of incoming) {
        if (seen.has(hash)) continue;
        if (out.length >= MAX_BULK_HASHES) break;
        seen.add(hash);
        out.push(hash);
      }
      return out;
    });
  }, []);

  const extendTo = useCallback(
    (index: number, resolve: (index: number) => string | null) => {
      const from = anchorRef.current ?? index;
      const [start, end] = from <= index ? [from, index] : [index, from];
      const picked: string[] = [];
      for (let i = start; i <= end; i += 1) {
        const hash = resolve(i);
        if (hash) picked.push(hash);
      }
      anchorRef.current = index;
      add(picked);
    },
    [add],
  );

  const clear = useCallback(() => {
    anchorRef.current = null;
    setHashes([]);
  }, []);

  return useMemo(
    () => ({
      hashes,
      size: hashes.length,
      active: hashes.length > 0,
      full: hashes.length >= MAX_BULK_HASHES,
      has,
      toggle,
      add,
      extendTo,
      clear,
    }),
    [hashes, has, toggle, add, extendTo, clear],
  );
}
