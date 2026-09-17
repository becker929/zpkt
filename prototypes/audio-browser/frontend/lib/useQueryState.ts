"use client";

/**
 * The filter lives in the URL.
 *
 * The list view and the playlist view show the same filtered set, and the
 * playlist is defined as "whatever the list is showing". Keeping the filter in
 * the query string means both views read one source, a filtered view can be
 * linked or reloaded, and going back from a sound's detail page returns to the
 * same set.
 */

import { useCallback, useEffect, useMemo, useRef } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { EMPTY_QUERY, type DeletedFilter, type Query, type SortKey, type SortOrder } from "./types";

const SORT_KEYS: SortKey[] = ["name", "duration", "size", "sounding"];
const DELETED_VALUES: DeletedFilter[] = ["false", "true", "any"];

export function queryFromParams(params: URLSearchParams): Query {
  const sort = params.get("sort") as SortKey | null;
  const order = params.get("order") as SortOrder | null;
  const deleted = params.get("deleted") as DeletedFilter | null;
  return {
    // An unrecognised value hides discarded sounds, which is the safe
    // direction: a link can never surprise the user with the discard pile.
    deleted: deleted && DELETED_VALUES.includes(deleted) ? deleted : EMPTY_QUERY.deleted,
    q: params.get("q") ?? "",
    ext: params.get("ext") ?? "",
    favorite: params.get("favorite") === "1",
    min_dur: params.get("min_dur") ?? "",
    max_dur: params.get("max_dur") ?? "",
    sort: sort && SORT_KEYS.includes(sort) ? sort : EMPTY_QUERY.sort,
    order: order === "desc" ? "desc" : "asc",
  };
}

export function paramsFromQuery(query: Query): URLSearchParams {
  const params = new URLSearchParams();
  if (query.q) params.set("q", query.q);
  if (query.ext) params.set("ext", query.ext);
  if (query.favorite) params.set("favorite", "1");
  if (query.min_dur) params.set("min_dur", query.min_dur);
  if (query.max_dur) params.set("max_dur", query.max_dur);
  if (query.sort !== EMPTY_QUERY.sort) params.set("sort", query.sort);
  if (query.order !== EMPTY_QUERY.order) params.set("order", query.order);
  if (query.deleted !== EMPTY_QUERY.deleted) params.set("deleted", query.deleted);
  return params;
}

export function useQueryState(): [Query, (next: Partial<Query>) => void] {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const query = useMemo(
    () => queryFromParams(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );

  // `router.replace` does not update `searchParams` before the next call to
  // `update`. Merging into the rendered snapshot would therefore drop a change
  // whenever two filters are set in quick succession: choosing a format and
  // then a duration bound would lose the format. Merge into a running copy
  // instead, and resynchronise whenever the URL actually changes.
  const pendingRef = useRef<Query>(query);
  const lastSuffixRef = useRef<string>(paramsFromQuery(query).toString());

  useEffect(() => {
    pendingRef.current = query;
    lastSuffixRef.current = paramsFromQuery(query).toString();
  }, [query]);

  const update = useCallback(
    (next: Partial<Query>) => {
      const merged = { ...pendingRef.current, ...next };
      pendingRef.current = merged;
      const suffix = paramsFromQuery(merged).toString();
      // Replacing the URL already shown changes nothing, but it is still a
      // navigation: it interrupts whatever else is navigating at that moment.
      // Setting a filter and then opening another view would cancel the view.
      if (suffix === lastSuffixRef.current) return;
      lastSuffixRef.current = suffix;
      router.replace(suffix ? `${pathname}?${suffix}` : pathname, { scroll: false });
    },
    [pathname, router],
  );

  return [query, update];
}
