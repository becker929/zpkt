"use client";

/**
 * A single line of text that scrolls itself only when it does not fit.
 *
 * On a phone the name column is about half of a 390 pixel screen, and the names
 * in this collection are long: `01-banana-pancake_2023-12-05_investigate-rumble_0-kick.wav`
 * is the whole meaning of a row. Clipping it to two characters hides the row's
 * identity, so the text slides far enough to read the end and slides back.
 *
 * Three rules keep that from becoming noise.
 *
 * It measures first. If the text already fits, nothing animates and the element
 * behaves as plain truncated text.
 *
 * It animates only when the caller says this line is the one being looked at.
 * The list passes `active` for the playing row and the focused row, so at most
 * two lines move at a time instead of thirty.
 *
 * It obeys `prefers-reduced-motion: reduce`. When that is set the text never
 * moves; the full name is still reachable through the title attribute and the
 * detail page.
 *
 * The first render has no measurements, so it renders exactly what the server
 * renders: no inline custom properties and `data-running="false"`. Measuring
 * happens in an effect, after hydration.
 */

import { useCallback, useEffect, useRef, useState } from "react";

/** Below this many pixels of overflow, scrolling is more distracting than useful. */
const MIN_OVERFLOW_PX = 6;

/** Reading speed of the slide, in pixels per second. */
const PIXELS_PER_SECOND = 55;

const MIN_DURATION_S = 4;
const MAX_DURATION_S = 26;

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function Marquee({
  text,
  active = false,
  className,
}: {
  text: string;
  /** True when this line is the one the user is on: playing, or focused. */
  active?: boolean;
  className?: string;
}) {
  const boxRef = useRef<HTMLSpanElement | null>(null);
  const trackRef = useRef<HTMLSpanElement | null>(null);
  const [overflow, setOverflow] = useState(0);
  const [reduced, setReduced] = useState(false);

  const measure = useCallback(() => {
    const box = boxRef.current;
    const track = trackRef.current;
    if (!box || !track) return;
    const excess = track.scrollWidth - box.clientWidth;
    setOverflow(excess > MIN_OVERFLOW_PX ? excess : 0);
  }, []);

  // Re-measure when the text changes, when the column is resized, and when the
  // window is (rotating a phone changes every column at once).
  useEffect(() => {
    measure();
    const box = boxRef.current;
    if (!box || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => measure());
    observer.observe(box);
    return () => observer.disconnect();
  }, [measure, text]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReduced(query.matches);
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);

  const running = active && overflow > 0 && !reduced && !prefersReducedMotion();
  const duration = Math.min(
    MAX_DURATION_S,
    Math.max(MIN_DURATION_S, overflow / PIXELS_PER_SECOND + 2.5),
  );

  return (
    <span
      ref={boxRef}
      className={`marquee${className ? ` ${className}` : ""}`}
      data-testid="marquee"
      data-overflow={overflow > 0 ? "true" : "false"}
      data-running={running ? "true" : "false"}
      title={text}
    >
      <span
        ref={trackRef}
        className="marquee-track"
        style={
          running
            ? ({
                "--marquee-shift": `${-overflow}px`,
                "--marquee-duration": `${duration.toFixed(1)}s`,
              } as React.CSSProperties)
            : undefined
        }
      >
        {text}
      </span>
    </span>
  );
}
