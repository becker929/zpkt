"use client";

/**
 * Waveform drawn on a canvas from server-computed peaks.
 *
 * The audio is never decoded in the browser. Some files in this collection run
 * to hundreds of megabytes, and decoding one client-side stalls the tab. The
 * server sends 1,000 int8 minimum/maximum pairs per sound and this component
 * draws exactly those.
 *
 * `spans` tints labelled regions, and every caller passes the spans of exactly
 * one classifier: three opinions tinted over each other say nothing about any
 * of them. Boundaries and labels are separate concerns, so a span carries its
 * own start, end, and label and this component makes no assumption that spans
 * tile the whole file or that they are sorted.
 *
 * The drawing itself is `paintWaveform` in `lib/wavePaint.ts`, shared with
 * the collage, which draws the same thing down a region instead of across a
 * bar.
 */

import { useCallback, useEffect, useRef } from "react";

import type { SilenceInterval, Span } from "@/lib/types";
import { paintWaveform } from "@/lib/wavePaint";

export interface WaveformProps {
  /** [minimum, maximum] pairs, each in -128..127. Empty while loading. */
  pairs: Array<[number, number]>;
  /** Length of the sound in seconds. Used to place progress and spans. */
  durationS: number | null;
  /** Playhead position in seconds. */
  progressS?: number;
  /** Labelled regions to tint. Stage 3 supplies these. */
  spans?: Span[];
  /**
   * Measured gaps of at least the skip floor, tinted so the listener can see
   * what the player is about to jump over and can aim a scrub at it.
   */
  silence?: SilenceInterval[];
  height?: number;
  /** Called with a time in seconds when the user clicks or drags the waveform. */
  onSeek?: (seconds: number) => void;
  /**
   * False when the stream cannot be seeked, which is the case for audio the
   * server transcodes on the fly. The waveform still draws and still calls
   * `onSeek`, so the player can explain the refusal, but the cursor and the
   * title say up front that dragging will not move the playhead.
   */
  seekable?: boolean;
  /** Shown when there are no peaks yet. */
  placeholder?: string;
  className?: string;
}

export function Waveform({
  pairs,
  durationS,
  progressS = 0,
  spans,
  silence,
  height = 120,
  onSeek,
  seekable = true,
  placeholder = "loading peaks…",
  className,
}: WaveformProps) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const draggingRef = useRef(false);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const cssWidth = Math.max(wrap.clientWidth, 1);
    const cssHeight = height;
    if (canvas.width !== Math.round(cssWidth * dpr) || canvas.height !== Math.round(cssHeight * dpr)) {
      canvas.width = Math.round(cssWidth * dpr);
      canvas.height = Math.round(cssHeight * dpr);
    }

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    paintWaveform(ctx, cssWidth, cssHeight, { pairs, durationS, progressS, spans, silence });
  }, [pairs, durationS, progressS, spans, silence, height]);

  useEffect(() => {
    draw();
  }, [draw]);

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => draw());
    observer.observe(wrap);
    return () => observer.disconnect();
  }, [draw]);

  const seekFromEvent = useCallback(
    (clientX: number) => {
      const wrap = wrapRef.current;
      if (!wrap || !onSeek || !durationS || durationS <= 0) return;
      const rect = wrap.getBoundingClientRect();
      const ratio = Math.min(Math.max((clientX - rect.left) / rect.width, 0), 1);
      onSeek(ratio * durationS);
    },
    [onSeek, durationS],
  );

  useEffect(() => {
    if (!onSeek) return;
    const move = (event: PointerEvent) => {
      if (draggingRef.current) seekFromEvent(event.clientX);
    };
    const up = () => {
      draggingRef.current = false;
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [onSeek, seekFromEvent]);

  return (
    <div
      ref={wrapRef}
      className={`waveform${seekable ? "" : " no-seek"}${className ? ` ${className}` : ""}`}
      style={{ height }}
      data-testid="waveform"
      data-buckets={pairs.length}
      data-silent-regions={silence?.length ?? 0}
      data-seekable={seekable ? "true" : "false"}
      title={seekable ? undefined : "this stream cannot be seeked"}
      onPointerDown={(event) => {
        if (!onSeek) return;
        draggingRef.current = true;
        seekFromEvent(event.clientX);
      }}
    >
      <canvas ref={canvasRef} />
      {pairs.length === 0 ? <div className="empty">{placeholder}</div> : null}
    </div>
  );
}
