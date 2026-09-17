"use client";

/** Search, format, and duration bounds. Writes straight to the URL. */

import { useEffect, useState } from "react";

import { formatCount } from "@/lib/format";
import type { Query, SortKey, SortOrder } from "@/lib/types";

const EXTENSIONS = [".wav", ".aif", ".aiff", ".mp3", ".m4a", ".flac", ".ogg", ".opus"];

/**
 * How many filters beyond the search box are set.
 *
 * On a phone the extra filters are folded away, so the toggle has to say
 * whether anything is hiding behind it.
 */
function narrowedBy(query: Query): number {
  let n = 0;
  if (query.ext) n += 1;
  if (query.min_dur) n += 1;
  if (query.max_dur) n += 1;
  return n;
}

export function QueryControls({
  query,
  update,
  total,
  loading,
  placeholder = "search filenames…",
  extra,
}: {
  query: Query;
  update: (next: Partial<Query>) => void;
  total: number;
  loading: boolean;
  placeholder?: string;
  extra?: React.ReactNode;
}) {
  // The box keeps its own value so typing stays responsive, then settles into
  // the URL after a pause rather than firing a request per keystroke.
  const [text, setText] = useState(query.q);

  // Open state for the folded filter panel. It only has an effect below the
  // narrow breakpoint; on a wide screen CSS shows every control regardless, so
  // this never changes the desktop layout and never changes the first render.
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setText(query.q);
  }, [query.q]);

  useEffect(() => {
    if (text === query.q) return;
    const timer = setTimeout(() => update({ q: text }), 180);
    return () => clearTimeout(timer);
  }, [text, query.q, update]);

  const active = narrowedBy(query);

  return (
    <div className={`controls${open ? " open" : ""}`} data-testid="controls">
      <div className="controls-primary">
        <input
          type="search"
          placeholder={placeholder}
          value={text}
          aria-label="search filenames"
          data-testid="search"
          onChange={(e) => setText(e.target.value)}
        />

        <div className="result-count" data-testid="result-count">
          {loading ? "loading…" : `${formatCount(total)} sounds`}
        </div>

        {/* The view's own headline action. It stays in the always-visible row
            rather than behind the fold. */}
        {extra ? <div className="controls-extra">{extra}</div> : null}

        <button
          type="button"
          className={`chip filters-toggle${active > 0 ? " on" : ""}`}
          data-testid="filters-toggle"
          aria-expanded={open}
          aria-controls="filter-panel"
          onClick={() => setOpen((v) => !v)}
        >
          filters{active > 0 ? ` (${active})` : ""}
        </button>
      </div>

      <div className="controls-rest" id="filter-panel">
        <select
          value={query.ext}
          aria-label="format"
          data-testid="ext"
          onChange={(e) => update({ ext: e.target.value })}
        >
          <option value="">all formats</option>
          {EXTENSIONS.map((ext) => (
            <option key={ext} value={ext}>
              {ext}
            </option>
          ))}
        </select>

        <label>
          min s
          <input
            className="dur-input"
            type="number"
            min={0}
            value={query.min_dur}
            aria-label="minimum duration in seconds"
            onChange={(e) => update({ min_dur: e.target.value })}
          />
        </label>
        <label>
          max s
          <input
            className="dur-input"
            type="number"
            min={0}
            value={query.max_dur}
            aria-label="maximum duration in seconds"
            onChange={(e) => update({ max_dur: e.target.value })}
          />
        </label>

        <select
          value={`${query.sort}:${query.order}`}
          aria-label="sort"
          data-testid="sort"
          onChange={(e) => {
            const [sort, order] = e.target.value.split(":");
            update({ sort: sort as SortKey, order: order as SortOrder });
          }}
        >
          <option value="name:asc">name A–Z</option>
          <option value="name:desc">name Z–A</option>
          <option value="duration:asc">shortest first</option>
          <option value="duration:desc">longest first</option>
          {/* Sounding length: the file's length with gaps of two seconds or
              more taken out. A five minute stem with forty seconds of sound
              sorts where it belongs. */}
          <option value="sounding:asc">least sound first</option>
          <option value="sounding:desc">most sound first</option>
        </select>
      </div>
    </div>
  );
}
