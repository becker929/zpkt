"use client";

/**
 * Paged, sparse access to a filtered set of sounds.
 *
 * The list view is virtualised, so only about thirty rows exist in the DOM at
 * once. This hook mirrors that: it holds pages of rows in a map and fetches a
 * page only when the scroller reaches it. A 3,451-row set therefore costs one
 * request per 200 rows actually looked at, not one request for everything.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { fetchFiles, filesUrl } from "./api";
import type { FileRow, Query } from "./types";

export const PAGE_SIZE = 200;

export interface FilesHandle {
  total: number;
  /** True until the first page of the current query has arrived. */
  loading: boolean;
  error: string | null;
  /** The row at an absolute index, or null while its page is in flight. */
  rowAt(index: number): FileRow | null;
  /** Ask for every page covering an index range. Safe to call on every scroll. */
  ensureRange(start: number, end: number): void;
  /**
   * Re-fetch the pages currently held, keeping the total and the scroll
   * position.
   *
   * Used after a discard or a restore changes what the filter selects.
   * Discarding row 1,400 of a set must not throw the view back to the top: the
   * next sound to judge is the one that just moved up into that slot.
   */
  refresh(): void;
}

function queryKey(query: Query): string {
  return filesUrl(query, PAGE_SIZE, 0);
}

export function useFiles(query: Query): FilesHandle {
  const key = queryKey(query);
  const pagesRef = useRef<Map<number, FileRow[]>>(new Map());
  const inFlightRef = useRef<Set<number>>(new Set());
  const keyRef = useRef(key);
  const [, setVersion] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const bump = useCallback(() => setVersion((v) => v + 1), []);

  // A new query discards every cached page and the total that went with it.
  useEffect(() => {
    keyRef.current = key;
    pagesRef.current = new Map();
    inFlightRef.current = new Set();
    setTotal(0);
    setLoading(true);
    setError(null);
    bump();
  }, [key, bump]);

  const loadPage = useCallback(
    async (page: number, force = false) => {
      const forKey = keyRef.current;
      if (!force && (pagesRef.current.has(page) || inFlightRef.current.has(page))) return;
      inFlightRef.current.add(page);
      try {
        const result = await fetchFiles(filesUrl(query, PAGE_SIZE, page * PAGE_SIZE));
        if (keyRef.current !== forKey) return;
        pagesRef.current.set(page, result.items);
        setTotal(result.total);
        setError(null);
        bump();
      } catch (err) {
        if (keyRef.current !== forKey) return;
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        inFlightRef.current.delete(page);
        if (page === 0 && keyRef.current === forKey) setLoading(false);
      }
    },
    [query, bump],
  );

  // The first page also tells us the total, which the virtualiser needs.
  useEffect(() => {
    void loadPage(0);
  }, [loadPage, key]);

  const ensureRange = useCallback(
    (start: number, end: number) => {
      const first = Math.max(0, Math.floor(start / PAGE_SIZE));
      const last = Math.floor(Math.max(start, end) / PAGE_SIZE);
      for (let page = first; page <= last; page += 1) void loadPage(page);
    },
    [loadPage],
  );

  const rowAt = useCallback((index: number): FileRow | null => {
    const page = pagesRef.current.get(Math.floor(index / PAGE_SIZE));
    if (!page) return null;
    return page[index % PAGE_SIZE] ?? null;
  }, []);

  // Re-request exactly the pages already held, and keep showing the old rows
  // until the new ones land. Discarding a sound must not blank the screen or
  // throw the scroller back to the top: the next sound to judge is the one
  // that just moved up into the gap.
  const refresh = useCallback(() => {
    const held = [...pagesRef.current.keys()];
    if (!held.includes(0)) held.push(0);
    inFlightRef.current = new Set();
    for (const page of held) void loadPage(page, true);
  }, [loadPage]);

  return useMemo(
    () => ({ total, loading, error, rowAt, ensureRange, refresh }),
    [total, loading, error, rowAt, ensureRange, refresh],
  );
}
