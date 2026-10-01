"use client";

/**
 * Long press as the way into selection on a phone.
 *
 * A row on a touch screen has one gesture and two jobs: a tap plays the sound,
 * and a press picks it. There is no room for a checkbox on a 393 pixel row
 * that already carries a name, a length, a discard and a star, and a thumb
 * would miss it anyway.
 *
 * Only touch presses count. A mouse gets the checkbox column instead, where a
 * click is precise and shift-click gives a range.
 */

import { useCallback, useEffect, useRef } from "react";
import type { MouseEvent, PointerEvent } from "react";

/**
 * How long a thumb has to rest on a row before it is a selection.
 *
 * Short enough not to feel like waiting, long enough that a tap meant for
 * playback never turns into one.
 */
export const LONG_PRESS_MS = 450;

/** How far a finger may drift during a press before it counts as a scroll. */
const SLOP = 10;

export interface LongPressBinding {
  onPointerDown(event: PointerEvent): void;
  onPointerMove(event: PointerEvent): void;
  onPointerUp(): void;
  onPointerCancel(): void;
  onContextMenu(event: MouseEvent): void;
}

export interface LongPressHandle {
  /** Handlers for one row. `index` is passed back so a range has an anchor. */
  bind(index: number): LongPressBinding;
  /**
   * True when the press that is ending already did its work.
   *
   * The click that follows a long press must do nothing, or a press would
   * select a row and start playing it at the same time. Calling this clears
   * the flag.
   */
  consume(): boolean;
}

export function useLongPress(onLongPress: (index: number) => void): LongPressHandle {
  const pressRef = useRef<{ timer: number; x: number; y: number } | null>(null);
  const firedRef = useRef(false);
  const callbackRef = useRef(onLongPress);
  callbackRef.current = onLongPress;

  const cancel = useCallback(() => {
    if (pressRef.current) window.clearTimeout(pressRef.current.timer);
    pressRef.current = null;
  }, []);

  useEffect(() => cancel, [cancel]);

  const bind = useCallback(
    (index: number): LongPressBinding => ({
      onPointerDown(event) {
        firedRef.current = false;
        cancel();
        if (event.pointerType !== "touch") return;
        const timer = window.setTimeout(() => {
          pressRef.current = null;
          firedRef.current = true;
          callbackRef.current(index);
          // A short tick confirms the press without a sound, which matters
          // when the point of the session is listening.
          navigator.vibrate?.(20);
        }, LONG_PRESS_MS);
        pressRef.current = { timer, x: event.clientX, y: event.clientY };
      },
      onPointerMove(event) {
        const press = pressRef.current;
        if (!press) return;
        if (Math.abs(event.clientX - press.x) > SLOP || Math.abs(event.clientY - press.y) > SLOP) cancel();
      },
      onPointerUp() {
        cancel();
      },
      onPointerCancel() {
        cancel();
        firedRef.current = false;
      },
      onContextMenu(event) {
        // The browser's own menu would otherwise land on top of the selection
        // the press just made.
        if (firedRef.current) event.preventDefault();
      },
    }),
    [cancel],
  );

  const consume = useCallback(() => {
    const fired = firedRef.current;
    firedRef.current = false;
    return fired;
  }, []);

  return { bind, consume };
}
