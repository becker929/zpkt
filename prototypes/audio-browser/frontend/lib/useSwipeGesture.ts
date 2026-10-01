"use client";

/**
 * A horizontal drag that answers a sound.
 *
 * Right takes it into the project on the bench, left discards it. There is no
 * third direction, because there is no third action: a sound you do not take
 * is discarded, and discarding is reversible.
 *
 * The buttons under the card do the same two things. The drag is the fast path
 * for a thumb; the buttons are what a keyboard, a screen reader and a test
 * use, and they are always there.
 */

import { useCallback, useRef, useState } from "react";

/** How far the card must travel before letting go acts on it. */
export const SWIPE_THRESHOLD_PX = 84;

/**
 * How far past the threshold the card keeps moving with the thumb.
 *
 * Beyond this it stops following, so the gesture cannot be dragged off screen
 * and left there. The card is an object being pushed, not a scroll.
 */
const MAX_TRAVEL_PX = 160;

export type SwipeIntent = "take" | "discard";

export interface SwipeGesture {
  /** Pixels the card is offset from rest. */
  dx: number;
  /** What letting go now would do, or null when the drag is still short. */
  intent: SwipeIntent | null;
  dragging: boolean;
  bind: {
    onPointerDown(event: React.PointerEvent): void;
    onPointerMove(event: React.PointerEvent): void;
    onPointerUp(event: React.PointerEvent): void;
    onPointerCancel(event: React.PointerEvent): void;
  };
}

export function useSwipeGesture(options: {
  onTake(): void;
  onDiscard(): void;
  /** False while nothing can take a sound. Dragging right then does nothing. */
  canTake: boolean;
  /** False while a write is in flight or there is nothing to answer. */
  enabled: boolean;
}): SwipeGesture {
  const [dx, setDx] = useState(0);
  const [dragging, setDragging] = useState(false);
  const startRef = useRef<{ x: number; y: number; id: number } | null>(null);
  /** True once the drag has proved itself horizontal. */
  const horizontalRef = useRef(false);

  const reset = useCallback(() => {
    startRef.current = null;
    horizontalRef.current = false;
    setDragging(false);
    setDx(0);
  }, []);

  const onPointerDown = useCallback(
    (event: React.PointerEvent) => {
      if (!options.enabled) return;
      startRef.current = { x: event.clientX, y: event.clientY, id: event.pointerId };
      horizontalRef.current = false;
      setDragging(true);
    },
    [options.enabled],
  );

  const onPointerMove = useCallback((event: React.PointerEvent) => {
    const start = startRef.current;
    if (!start || start.id !== event.pointerId) return;
    const moveX = event.clientX - start.x;
    const moveY = event.clientY - start.y;
    // Wait until the drag says which way it is going. A thumb that starts
    // vertically is not answering the sound.
    if (!horizontalRef.current) {
      if (Math.abs(moveX) < 8 && Math.abs(moveY) < 8) return;
      if (Math.abs(moveY) > Math.abs(moveX)) {
        reset();
        return;
      }
      horizontalRef.current = true;
      (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
    }
    const limited = Math.sign(moveX) * Math.min(Math.abs(moveX), MAX_TRAVEL_PX);
    setDx(limited);
  }, [reset]);

  const finish = useCallback(() => {
    const travelled = dx;
    reset();
    if (Math.abs(travelled) < SWIPE_THRESHOLD_PX) return;
    if (travelled > 0) {
      // Dragging right with nothing to take the sound springs back. Refusing
      // here rather than discarding is the safe direction: the gesture meant
      // "keep this", and turning that into "discard it" would be the worst
      // thing this view could do.
      if (options.canTake) options.onTake();
      return;
    }
    options.onDiscard();
  }, [dx, options, reset]);

  return {
    dx,
    intent:
      Math.abs(dx) < SWIPE_THRESHOLD_PX ? null : dx > 0 ? (options.canTake ? "take" : null) : "discard",
    dragging,
    bind: { onPointerDown, onPointerMove, onPointerUp: finish, onPointerCancel: reset },
  };
}
