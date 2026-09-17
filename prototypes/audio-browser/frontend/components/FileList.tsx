"use client";

/**
 * The list view's table.
 *
 * Virtualised with `@tanstack/react-virtual`: the scroller is sized for the
 * whole filtered set but only the visible window plus a small overscan exists
 * in the DOM. Rendering 3,451 rows outright stalls the tab, and the collection
 * is only going to grow.
 *
 * Clicking a row loads it into the player without leaving the list. The name is
 * a link to the sound's detail page.
 *
 * On a narrow screen the row drops the columns that can be recovered elsewhere
 * (the index number, the path count and the size) and gives the name half the
 * width, so the part of a row that carries the meaning is the part that gets
 * the space. What the size column leaves behind is a discard button, so a
 * thumb can star or discard a sound without opening anything. The name scrolls
 * itself when it still does not fit, but only on the row that is playing or
 * focused. See `Marquee`.
 *
 * Selection works two ways, because the two devices have different hands.
 * A pointer gets a checkbox column and shift-click for a range. A thumb gets a
 * long press, after which a tap toggles a row instead of playing it.
 */

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";

import { Length } from "@/components/Length";
import { Marquee } from "@/components/Marquee";
import { usePlayer } from "@/components/PlayerProvider";
import { useTriage } from "@/components/TriageProvider";
import { formatBytes } from "@/lib/format";
import { NARROW, useMediaQuery } from "@/lib/useMediaQuery";
import { useLongPress } from "@/lib/useLongPress";
import type { FilesHandle } from "@/lib/useFiles";
import type { SelectionHandle } from "@/lib/useSelection";
import type { Query, SortKey } from "@/lib/types";

const ROW_HEIGHT = 34;

/** Taller rows on a phone: a 34 pixel target is too small for a thumb. */
const ROW_HEIGHT_NARROW = 46;

export function FileList({
  files,
  query,
  update,
  selection,
}: {
  files: FilesHandle;
  query: Query;
  update: (next: Partial<Query>) => void;
  selection: SelectionHandle;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const player = usePlayer();
  const triage = useTriage();
  const narrow = useMediaQuery(NARROW);
  /** The row the user is on. Only this one and the playing one scroll their name. */
  const [focused, setFocused] = useState<number | null>(null);

  /** A press on a row picks it. See `useLongPress`. */
  const press = useLongPress((index) => {
    const row = files.rowAt(index);
    if (row) selection.toggle(row.hash, index);
  });

  const rowHeight = narrow ? ROW_HEIGHT_NARROW : ROW_HEIGHT;

  const virtualizer = useVirtualizer({
    count: files.total,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    overscan: 12,
  });

  // The measured row height changes when the viewport crosses the breakpoint,
  // so the scroller has to be re-sized. `files.total` is zero at hydration, so
  // this never changes what the first render puts in the HTML.
  useEffect(() => {
    virtualizer.measure();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rowHeight]);

  const items = virtualizer.getVirtualItems();

  // Fetch the pages the visible window sits on.
  useEffect(() => {
    if (items.length === 0) {
      if (files.total > 0) files.ensureRange(0, 40);
      return;
    }
    files.ensureRange(items[0].index, items[items.length - 1].index);
  }, [items, files]);

  const sortBy = (key: SortKey) => {
    update({ sort: key, order: query.sort === key && query.order === "asc" ? "desc" : "asc" });
  };

  const arrow = (key: SortKey) => (query.sort === key ? (query.order === "asc" ? " ▲" : " ▼") : "");

  /** A row index to its hash, for a shift-click range. Null while its page loads. */
  const hashAt = useCallback((index: number) => files.rowAt(index)?.hash ?? null, [files]);

  const showingDiscarded = query.deleted === "true";

  return (
    <>
      <div className={`table-head${selection.active ? " selecting" : ""}`}>
        <div className="col-select" aria-hidden="true" />
        <div className="col-idx">#</div>
        <div className="col-name">
          <button type="button" className={query.sort === "name" ? "sorted" : ""} onClick={() => sortBy("name")}>
            name{arrow("name")}
          </button>
        </div>
        <div className="col-dur">
          <button
            type="button"
            className={query.sort === "duration" ? "sorted" : ""}
            onClick={() => sortBy("duration")}
          >
            length{arrow("duration")}
          </button>
        </div>
        <div className="col-fmt">format</div>
        <div className="col-size">
          <button type="button" className={query.sort === "size" ? "sorted" : ""} onClick={() => sortBy("size")}>
            size{arrow("size")}
          </button>
        </div>
        <div className="col-alias">paths</div>
        <div className="col-del">{showingDiscarded ? "back" : "drop"}</div>
        <div className="col-fav">fav</div>
      </div>

      <div className="scroller" ref={scrollRef} data-testid="scroller">
        {files.error ? <div className="error">could not load the list: {files.error}</div> : null}
        {!files.error && !files.loading && files.total === 0 ? (
          <div className="notice">
            {showingDiscarded ? "nothing has been discarded under this filter." : "nothing matches this filter."}
          </div>
        ) : null}

        <div style={{ height: virtualizer.getTotalSize(), width: "100%", position: "relative" }}>
          {items.map((item) => {
            const row = files.rowAt(item.index);
            const isCurrent = row !== null && player.current?.hash === row.hash;
            const isFocused = focused === item.index;
            const picked = row !== null && selection.has(row.hash);
            return (
              <div
                key={item.key}
                className={`row${row ? "" : " pending"}${isCurrent ? " playing" : ""}${
                  picked ? " picked" : ""
                }${selection.active ? " selecting" : ""}`}
                data-testid="row"
                data-index={item.index}
                data-hash={row?.hash ?? ""}
                data-selected={picked}
                tabIndex={0}
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  height: item.size,
                  transform: `translateY(${item.start}px)`,
                }}
                onFocus={() => setFocused(item.index)}
                onBlur={() => setFocused((f) => (f === item.index ? null : f))}
                {...press.bind(item.index)}
                onPointerDownCapture={() => setFocused(item.index)}
                onKeyDown={(e) => {
                  if (!row) return;
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    if (selection.active) selection.toggle(row.hash, item.index);
                    else player.play(row, { query, index: item.index, total: files.total });
                  }
                  // A keyboard has no long press, so `x` is the way in.
                  if (e.key.toLowerCase() === "x") {
                    e.preventDefault();
                    selection.toggle(row.hash, item.index);
                  }
                }}
                onClick={(e) => {
                  if (!row) return;
                  // The press already selected this row; the tap that ends it
                  // must not also do something.
                  if (press.consume()) return;
                  if (e.shiftKey) {
                    selection.extendTo(item.index, hashAt);
                    return;
                  }
                  if (selection.active) {
                    selection.toggle(row.hash, item.index);
                    return;
                  }
                  player.play(row, { query, index: item.index, total: files.total });
                }}
              >
                <div className="col-select">
                  {row ? (
                    <input
                      type="checkbox"
                      checked={picked}
                      data-testid="row-select"
                      aria-label={picked ? `deselect ${row.filename}` : `select ${row.filename}`}
                      onChange={() => undefined}
                      onClick={(e) => {
                        e.stopPropagation();
                        if (e.shiftKey) selection.extendTo(item.index, hashAt);
                        else selection.toggle(row.hash, item.index);
                      }}
                    />
                  ) : null}
                </div>
                <div className="col-idx mono">{item.index + 1}</div>
                <div className="col-name">
                  {row ? (
                    <Link href={`/sounds/${row.hash}`} onClick={(e) => e.stopPropagation()}>
                      <Marquee text={row.filename} active={isCurrent || isFocused} />
                    </Link>
                  ) : (
                    "…"
                  )}
                </div>
                <div className="col-dur mono">
                  {row ? <Length soundingS={row.sounding_s} wallS={row.duration_s} /> : ""}
                </div>
                <div className="col-fmt mono">{row ? row.ext.replace(".", "") : ""}</div>
                <div className="col-size mono">{row ? formatBytes(row.size_bytes) : ""}</div>
                <div className="col-alias">
                  {row ? (
                    <span className={`alias-badge${row.alias_count > 1 ? "" : " single"}`}>{row.alias_count}</span>
                  ) : null}
                </div>
                <div className="col-del">
                  {row ? (
                    <button
                      type="button"
                      className={`drop${row.deleted ? " on" : ""}`}
                      data-testid={row.deleted ? "restore-row" : "discard-row"}
                      aria-label={row.deleted ? `restore ${row.filename}` : `discard ${row.filename}`}
                      title={
                        row.deleted
                          ? "put this sound back in the list"
                          : "not this one. it stops appearing; nothing is removed from disk."
                      }
                      onClick={(e) => {
                        e.stopPropagation();
                        void triage.run(row.deleted ? "restore" : "delete", [row.hash]);
                      }}
                    >
                      {row.deleted ? "↩" : "✕"}
                    </button>
                  ) : null}
                </div>
                <div className="col-fav">
                  {row ? (
                    <button
                      type="button"
                      className={`fav${row.favorite ? " on" : ""}`}
                      data-testid="favorite-toggle"
                      aria-pressed={row.favorite}
                      aria-label={row.favorite ? "remove favorite" : "add favorite"}
                      onClick={(e) => {
                        e.stopPropagation();
                        void player.toggleFavorite(row);
                      }}
                    >
                      {row.favorite ? "★" : "☆"}
                    </button>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
