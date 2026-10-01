"use client";

/**
 * The bar that appears once rows are selected.
 *
 * It sits in the normal column flow, directly above the player bar, and the
 * scroller above it shrinks by its height. Nothing is floated over the player:
 * the transport is how a sound gets played, so it must stay reachable.
 *
 * Two actions, because there are two decisions about a sound and one of them —
 * taking it into a project — is made one sound at a time in the swipe view.
 * Every action here is addressed by hash. The bar never sees a path.
 */

import { useState } from "react";

import { plural, useTriage } from "@/components/TriageProvider";
import type { SelectionHandle } from "@/lib/useSelection";

export function SelectionBar({
  selection,
  /** `deleted` is the discard pile, where the action is restore. */
  mode = "default",
}: {
  selection: SelectionHandle;
  mode?: "default" | "deleted";
}) {
  const triage = useTriage();
  const [busy, setBusy] = useState(false);

  const act = async (action: Parameters<typeof triage.run>[0]) => {
    if (busy || selection.hashes.length === 0) return;
    setBusy(true);
    await triage.run(action, selection.hashes);
    setBusy(false);
    selection.clear();
  };

  if (!selection.active) return null;

  return (
    <div className="selection" data-testid="selection-bar" data-count={selection.size}>
      <div className="selection-row">
        <span className="count mono" data-testid="selection-count">
          {plural(selection.size, "sound")} selected
          {selection.full ? " · that is the most one action can take" : ""}
        </span>

        <div className="selection-actions">
          {mode === "deleted" ? (
            <button
              type="button"
              className="chip restore"
              data-testid="bulk-restore"
              disabled={busy}
              onClick={() => void act("restore")}
            >
              ↩ restore
            </button>
          ) : (
            <button
              type="button"
              className="chip discard"
              data-testid="bulk-discard"
              disabled={busy}
              onClick={() => void act("delete")}
            >
              ✕ discard
            </button>
          )}
          <button type="button" className="chip" data-testid="selection-clear" onClick={() => selection.clear()}>
            done
          </button>
        </div>
      </div>
    </div>
  );
}
