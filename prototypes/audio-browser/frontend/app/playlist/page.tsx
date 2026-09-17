"use client";

/**
 * Playlist view: the current filtered set, played in order.
 *
 * The playlist is not a separate saved object. It is whatever the filter
 * selects, in the order the list shows, which is why it reads the same query
 * string as the list view. Playback runs on past the end of a track into the
 * next one, and the player fetches the following track's peaks ahead of time so
 * its waveform is drawn the moment it starts.
 */

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useVirtualizer } from "@tanstack/react-virtual";

import { Length } from "@/components/Length";
import { Marquee } from "@/components/Marquee";
import { QueryControls } from "@/components/QueryControls";
import { usePlayer } from "@/components/PlayerProvider";
import { formatBytes } from "@/lib/format";
import { useFiles } from "@/lib/useFiles";
import { NARROW, useMediaQuery } from "@/lib/useMediaQuery";
import { useQueryState } from "@/lib/useQueryState";

const ROW_HEIGHT = 34;
const ROW_HEIGHT_NARROW = 46;

function PlaylistView() {
  const [query, update] = useQueryState();
  const player = usePlayer();
  const files = useFiles(query, player.favoriteOverrides);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const narrow = useMediaQuery(NARROW);
  const [focused, setFocused] = useState<number | null>(null);

  const rowHeight = narrow ? ROW_HEIGHT_NARROW : ROW_HEIGHT;

  const virtualizer = useVirtualizer({
    count: files.total,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    overscan: 12,
  });

  useEffect(() => {
    virtualizer.measure();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rowHeight]);

  const items = virtualizer.getVirtualItems();

  useEffect(() => {
    if (items.length === 0) {
      if (files.total > 0) files.ensureRange(0, 40);
      return;
    }
    files.ensureRange(items[0].index, items[items.length - 1].index);
  }, [items, files]);

  // Follow playback down the list.
  useEffect(() => {
    if (player.index === null) return;
    virtualizer.scrollToIndex(player.index, { align: "center" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [player.index]);

  const playFromTop = () => {
    const row = files.rowAt(0);
    if (row) player.play(row, { query, index: 0, total: files.total });
  };

  return (
    <>
      <QueryControls
        query={query}
        update={update}
        total={files.total}
        loading={files.loading}
        extra={
          <button type="button" className="chip" data-testid="play-all" onClick={playFromTop} disabled={files.total === 0}>
            ▶ play from the top
          </button>
        }
      />

      <div className="table-head playlist-head">
        <div className="col-idx">#</div>
        <div className="col-name">queue — plays straight through</div>
        <div className="col-dur">length</div>
        <div className="col-size">size</div>
        <div className="col-alias">paths</div>
      </div>

      <div className="scroller" ref={scrollRef} data-testid="playlist-scroller">
        {files.error ? <div className="error">could not load the queue: {files.error}</div> : null}
        <div style={{ height: virtualizer.getTotalSize(), width: "100%", position: "relative" }}>
          {items.map((item) => {
            const row = files.rowAt(item.index);
            const isCurrent = player.index === item.index && row !== null && player.current?.hash === row.hash;
            return (
              <div
                key={item.key}
                className={`row playlist-row${row ? "" : " pending"}${isCurrent ? " playing" : ""}`}
                data-testid="playlist-row"
                data-index={item.index}
                tabIndex={0}
                onFocus={() => setFocused(item.index)}
                onBlur={() => setFocused((f) => (f === item.index ? null : f))}
                onPointerDown={() => setFocused(item.index)}
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  height: item.size,
                  transform: `translateY(${item.start}px)`,
                }}
                onClick={() => {
                  if (row) player.play(row, { query, index: item.index, total: files.total });
                }}
              >
                <div className="col-idx mono">{item.index + 1}</div>
                <div className="col-name">
                  {isCurrent ? <span className="now-dot" /> : null}
                  {row ? (
                    <Link href={`/sounds/${row.hash}`} onClick={(e) => e.stopPropagation()}>
                      <Marquee text={row.filename} active={isCurrent || focused === item.index} />
                    </Link>
                  ) : (
                    "…"
                  )}
                </div>
                <div className="col-dur mono">
                  {row ? <Length soundingS={row.sounding_s} wallS={row.duration_s} /> : ""}
                </div>
                <div className="col-size mono">{row ? formatBytes(row.size_bytes) : ""}</div>
                <div className="col-alias">
                  {row ? (
                    <span className={`alias-badge${row.alias_count > 1 ? "" : " single"}`}>{row.alias_count}</span>
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

export default function Page() {
  return (
    <Suspense fallback={<div className="notice">loading…</div>}>
      <PlaylistView />
    </Suspense>
  );
}
