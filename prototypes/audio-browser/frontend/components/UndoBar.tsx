"use client";

/**
 * What just happened, and the offer to take it back.
 *
 * Discarding removes a sound from the view, so the row that would show what
 * was done is gone by the time the user looks for it. This strip says it
 * instead, and stands until the next action replaces it. There is no timer:
 * a decision made on a phone in a noisy room should not expire while the user
 * is listening to the next sound.
 *
 * It sits above the player bar in the column flow, never over it.
 */

import { useTriage } from "@/components/TriageProvider";

export function UndoBar() {
  const triage = useTriage();

  if (triage.error) {
    return (
      <div className="undobar failed" data-testid="triage-error">
        <span>that did not save: {triage.error}</span>
        <button type="button" className="chip" data-testid="triage-error-dismiss" onClick={() => triage.dismissError()}>
          dismiss
        </button>
      </div>
    );
  }

  if (!triage.undo) return null;

  return (
    <div className="undobar" data-testid="undo-bar">
      <span data-testid="undo-label">{triage.undo.label}</span>
      <button type="button" className="chip" data-testid="undo" onClick={() => void triage.takeUndo()}>
        undo
      </button>
      <button type="button" className="chip dim" data-testid="undo-dismiss" onClick={() => triage.dismissUndo()}>
        dismiss
      </button>
    </div>
  );
}
