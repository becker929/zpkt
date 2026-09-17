"use client";

/**
 * One list, played as a queue.
 *
 * The rows are the list's own running order, not a filter, so the player is
 * handed the rows themselves and steps through them. Playback runs on past the
 * end of a track into the next one, exactly as the playlist view does.
 *
 * A list is hand-made and small, so the whole thing is fetched at once and the
 * rows are not virtualised. The collection view is the one that has to hold
 * 3,451 rows.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Length, TotalLength } from "@/components/Length";
import { Marquee } from "@/components/Marquee";
import { SelectionBar } from "@/components/SelectionBar";
import { usePlayer } from "@/components/PlayerProvider";
import { useTriage } from "@/components/TriageProvider";
import { fetchList } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { useLongPress } from "@/lib/useLongPress";
import { useSelection } from "@/lib/useSelection";
import { EMPTY_QUERY, type ListDetail } from "@/lib/types";

export default function ListPage() {
  const params = useParams<{ id: string }>();
  const id = Number(typeof params.id === "string" ? params.id : "");
  const player = usePlayer();
  const triage = useTriage();

  const [list, setList] = useState<ListDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [focused, setFocused] = useState<number | null>(null);
  const selection = useSelection(`list:${id}`);

  const load = useCallback(
    (signal?: AbortSignal) => {
      if (!Number.isFinite(id)) return;
      fetchList(id, 1000, signal)
        .then((next) => {
          setList(next);
          setError(null);
        })
        .catch((err: unknown) => {
          if (signal?.aborted) return;
          setError(err instanceof Error ? err.message : String(err));
        });
    },
    [id],
  );

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
    // Re-read after any triage action: a sound taken out of this list, or
    // discarded from it, has to leave the running order.
  }, [load, triage.version, player.favoriteVersion]);

  const rows = list?.items ?? [];

  const playFrom = useCallback(
    (index: number) => {
      const row = rows[index];
      if (!row) return;
      player.play(row, { query: EMPTY_QUERY, index, total: rows.length, rows });
    },
    [player, rows],
  );

  const press = useLongPress((index) => {
    const row = rows[index];
    if (row) selection.toggle(row.hash, index);
  });

  if (error) {
    return (
      <div className="detail">
        <div className="error" data-testid="list-error">
          could not load this list: {error}
        </div>
        <p>
          <Link href="/lists">back to the lists</Link>
        </p>
      </div>
    );
  }

  if (!list) return <div className="notice">loading…</div>;

  return (
    <>
      <div className="controls">
        <div className="controls-primary">
          <span className="list-title" data-testid="list-name">
            {list.name}
          </span>
          <div className="result-count" data-testid="list-total">
            {formatCount(list.member_count)} sounds ·{" "}
            <TotalLength soundingS={list.sounding_s} wallS={list.duration_s} />
          </div>
          <div className="controls-extra">
            <button
              type="button"
              className="chip"
              data-testid="list-play-all"
              disabled={rows.length === 0}
              onClick={() => playFrom(0)}
            >
              ▶ play from the top
            </button>
          </div>
        </div>
      </div>

      <div className="table-head playlist-head">
        <div className="col-select" aria-hidden="true" />
        <div className="col-idx">#</div>
        <div className="col-name">{list.name} — plays straight through</div>
        <div className="col-dur">length</div>
        <div className="col-del">drop</div>
        <div className="col-fav">fav</div>
      </div>

      <div className="scroller" data-testid="list-scroller">
        {rows.length === 0 ? (
          <div className="notice" data-testid="list-empty">
            this list is empty. select sounds in the list view and add them here.
          </div>
        ) : null}

        {rows.map((row, index) => {
          const isCurrent = player.current?.hash === row.hash;
          const picked = selection.has(row.hash);
          const favorite = player.favoriteOverrides[row.hash] ?? row.favorite;
          return (
            <div
              key={row.hash}
              className={`row playlist-row${isCurrent ? " playing" : ""}${picked ? " picked" : ""}${
                selection.active ? " selecting" : ""
              }`}
              data-testid="list-row"
              data-index={index}
              data-hash={row.hash}
              data-selected={picked}
              tabIndex={0}
              onFocus={() => setFocused(index)}
              onBlur={() => setFocused((f) => (f === index ? null : f))}
              {...press.bind(index)}
              onPointerDownCapture={() => setFocused(index)}
              onClick={(e) => {
                if (press.consume()) return;
                if (e.shiftKey) {
                  selection.extendTo(index, (i) => rows[i]?.hash ?? null);
                  return;
                }
                if (selection.active) {
                  selection.toggle(row.hash, index);
                  return;
                }
                playFrom(index);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  if (selection.active) selection.toggle(row.hash, index);
                  else playFrom(index);
                }
                if (e.key.toLowerCase() === "x") {
                  e.preventDefault();
                  selection.toggle(row.hash, index);
                }
              }}
            >
              <div className="col-select">
                <input
                  type="checkbox"
                  checked={picked}
                  data-testid="row-select"
                  aria-label={picked ? `deselect ${row.filename}` : `select ${row.filename}`}
                  onChange={() => undefined}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (e.shiftKey) selection.extendTo(index, (i) => rows[i]?.hash ?? null);
                    else selection.toggle(row.hash, index);
                  }}
                />
              </div>
              <div className="col-idx mono">{index + 1}</div>
              <div className="col-name">
                {isCurrent ? <span className="now-dot" /> : null}
                <Link href={`/sounds/${row.hash}`} onClick={(e) => e.stopPropagation()}>
                  <Marquee text={row.filename} active={isCurrent || focused === index} />
                </Link>
              </div>
              <div className="col-dur mono">
                <Length soundingS={row.sounding_s} wallS={row.duration_s} />
              </div>
              <div className="col-del">
                <button
                  type="button"
                  className="drop"
                  data-testid="list-remove-row"
                  aria-label={`take ${row.filename} out of ${list.name}`}
                  title="take this out of the list. the sound is untouched."
                  onClick={(e) => {
                    e.stopPropagation();
                    void triage.run("remove_from_list", [row.hash], {
                      listId: list.id,
                      label: `removed ${row.filename} from ${list.name}`,
                    });
                  }}
                >
                  −
                </button>
              </div>
              <div className="col-fav">
                <button
                  type="button"
                  className={`fav${favorite ? " on" : ""}`}
                  data-testid="favorite-toggle"
                  aria-pressed={favorite}
                  aria-label={favorite ? "remove favorite" : "add favorite"}
                  onClick={(e) => {
                    e.stopPropagation();
                    void player.toggleFavorite({ ...row, favorite });
                  }}
                >
                  {favorite ? "★" : "☆"}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      <SelectionBar selection={selection} listId={list.id} />
    </>
  );
}
