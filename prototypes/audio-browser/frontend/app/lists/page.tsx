"use client";

/**
 * Lists view: every list, with what is in it.
 *
 * A list is the third answer to "what is this sound". Starred means keep,
 * discarded means not this one, and a list means filed: the kick that belongs
 * with the other kicks, the take to come back to. Each one is a running order,
 * so opening it plays it straight through.
 *
 * Deleting a list removes the filing, not the sounds, and nothing anywhere
 * here removes a file.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { TotalLength } from "@/components/Length";
import { usePlayer } from "@/components/PlayerProvider";
import { useTriage } from "@/components/TriageProvider";
import { createList, deleteList, fetchList, fetchLists, renameList } from "@/lib/api";
import { formatBytes, formatCount } from "@/lib/format";
import { EMPTY_QUERY, type SoundList } from "@/lib/types";

export default function ListsPage() {
  const player = usePlayer();
  const triage = useTriage();
  const [lists, setLists] = useState<SoundList[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  /** The list whose name is being edited, and the name being typed. */
  const [editing, setEditing] = useState<{ id: number; name: string } | null>(null);
  /** A list whose delete button has been pressed once. The second press does it. */
  const [confirming, setConfirming] = useState<number | null>(null);

  const load = useCallback((signal?: AbortSignal) => {
    fetchLists(signal)
      .then((next) => {
        setLists(next);
        setError(null);
      })
      .catch((err: unknown) => {
        if (signal?.aborted) return;
        setLists([]);
        setError(err instanceof Error ? err.message : String(err));
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
    // Re-read after any triage action: adding to a list from the selection bar
    // changes what is on this page.
  }, [load, triage.version]);

  const create = async () => {
    const wanted = name.trim();
    if (!wanted || busy) return;
    setBusy(true);
    try {
      await createList(wanted);
      setName("");
      setError(null);
      load();
    } catch {
      setError(`could not make a list called "${wanted}". a list with that name may exist.`);
    } finally {
      setBusy(false);
    }
  };

  const saveName = async () => {
    if (!editing) return;
    const wanted = editing.name.trim();
    if (!wanted) return;
    setBusy(true);
    try {
      await renameList(editing.id, wanted);
      setEditing(null);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: number) => {
    setBusy(true);
    try {
      await deleteList(id);
      setConfirming(null);
      triage.refresh();
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  /** Load a list and start it from the top. The list is the queue. */
  const playList = async (id: number) => {
    const detail = await fetchList(id);
    const first = detail.items[0];
    if (!first) return;
    player.play(first, {
      query: EMPTY_QUERY,
      index: 0,
      total: detail.items.length,
      rows: detail.items,
    });
  };

  return (
    <div className="detail" data-testid="lists">
      <h1>lists</h1>
      <p className="lede">
        A list is a hand-made running order. Opening one plays it straight through. Removing a list
        removes the filing and nothing else: every sound in it stays exactly where it is.
      </p>

      <form
        className="new-list"
        onSubmit={(e) => {
          e.preventDefault();
          void create();
        }}
      >
        <input
          type="text"
          value={name}
          placeholder="new list…"
          aria-label="new list name"
          data-testid="lists-new-name"
          maxLength={120}
          onChange={(e) => setName(e.target.value)}
        />
        <button type="submit" className="chip" data-testid="lists-new-create" disabled={busy || !name.trim()}>
          make a list
        </button>
      </form>

      {error ? (
        <div className="error" data-testid="lists-error">
          {error}
        </div>
      ) : null}

      {lists === null ? <div className="notice">loading…</div> : null}
      {lists !== null && lists.length === 0 && !error ? (
        <div className="notice" data-testid="lists-empty">
          no lists yet. select some sounds in the list view and file them here.
        </div>
      ) : null}

      <ul className="cards" data-testid="list-cards">
        {(lists ?? []).map((list) => (
          <li key={list.id} className="card" data-testid="list-card" data-list-id={list.id}>
            {editing?.id === list.id ? (
              <form
                className="card-head"
                onSubmit={(e) => {
                  e.preventDefault();
                  void saveName();
                }}
              >
                <input
                  type="text"
                  value={editing.name}
                  aria-label="list name"
                  data-testid="rename-input"
                  maxLength={120}
                  onChange={(e) => setEditing({ id: list.id, name: e.target.value })}
                />
                <button type="submit" className="chip" data-testid="rename-save" disabled={busy}>
                  save
                </button>
                <button type="button" className="chip" onClick={() => setEditing(null)}>
                  cancel
                </button>
              </form>
            ) : (
              <div className="card-head">
                <Link href={`/lists/${list.id}`} className="card-name" data-testid="list-link">
                  {list.name}
                </Link>
                <span className="mono dim" data-testid="list-count">
                  {formatCount(list.member_count)} sounds ·{" "}
                  <TotalLength soundingS={list.sounding_s} wallS={list.duration_s} /> ·{" "}
                  {formatBytes(list.size_bytes)}
                </span>
              </div>
            )}

            <div className="card-actions">
              <button
                type="button"
                className="chip"
                data-testid="list-play"
                disabled={list.member_count === 0}
                onClick={() => void playList(list.id)}
              >
                ▶ play
              </button>
              <button
                type="button"
                className="chip"
                data-testid="list-rename"
                onClick={() => setEditing({ id: list.id, name: list.name })}
              >
                rename
              </button>
              {confirming === list.id ? (
                <button
                  type="button"
                  className="chip discard"
                  data-testid="list-delete-confirm"
                  disabled={busy}
                  onClick={() => void remove(list.id)}
                >
                  remove the list, keep the sounds
                </button>
              ) : (
                <button
                  type="button"
                  className="chip"
                  data-testid="list-delete"
                  onClick={() => setConfirming(list.id)}
                >
                  remove list
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
