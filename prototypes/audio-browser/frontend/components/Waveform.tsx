"use client";

/**
 * Waveform drawn on a canvas from server-computed peaks.
 *
 * The audio is never decoded in the browser. Some files in this collection run
 * to hundreds of megabytes, and decoding one client-side stalls the tab. The
 * server sends 1,000 int8 minimum/maximum pairs per sound and this component
 * draws exactly those.
 *
 * `spans` tints labelled regions. Stage 3 fills it from the `span` table; until
 * then callers pass nothing and the waveform draws plain. Boundaries and labels
 * are separate concerns, so a span carries its own start, end, and label and
 * this component makes no assumption that spans tile the whole file or that
 * they are sorted.
 */

import { useCallback, useEffect, useRef } from "react";

import type { SilenceInterval, Span } from "@/lib/types";

/** Tint per label. Unknown labels fall back to a neutral grey. */
const SPAN_COLORS: Record<string, string> = {
  speech: "rgba(255, 145, 120, 0.20)",
  music: "rgba(120, 190, 255, 0.20)",
  other: "rgba(150, 160, 175, 0.14)",
};

const FALLBACK_SPAN_COLOR = "rgba(150, 160, 175, 0.14)";

/**
 * Silent stretches, drawn as a flat band with an edge at each end.
 *
 * It has to read as a different kind of thing from a labelled span: a span
 * says what the audio is, a silent band says there is no audio. The edges are
 * what make the band's boundaries visible against a span tint under it.
 */
const SILENCE_FILL = "rgba(120, 132, 155, 0.26)";
const SILENCE_EDGE = "rgba(190, 205, 230, 0.45)";

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
    ctx.clearRect(0, 0, cssWidth, cssHeight);

    const mid = cssHeight / 2;
    const fraction =
      durationS && durationS > 0 ? Math.min(Math.max(progressS / durationS, 0), 1) : 0;
    const playedX = fraction * cssWidth;

    // Span tints sit underneath the waveform so the shape stays readable.
    if (spans && spans.length > 0 && durationS && durationS > 0) {
      for (const span of spans) {
        const start = Math.max(0, Math.min(span.start_s, durationS));
        const end = Math.max(start, Math.min(span.end_s, durationS));
        if (end <= start) continue;
        const x0 = (start / durationS) * cssWidth;
        const x1 = (end / durationS) * cssWidth;
        ctx.fillStyle = SPAN_COLORS[span.label] ?? FALLBACK_SPAN_COLOR;
        ctx.fillRect(x0, 0, Math.max(x1 - x0, 1), cssHeight);
      }
    }

    // Silent stretches sit over the span tints and under the waveform, so a
    // region can be both labelled and silent and still be read as both.
    if (silence && silence.length > 0 && durationS && durationS > 0) {
      for (const gap of silence) {
        const start = Math.max(0, Math.min(gap.start_s, durationS));
        const end = Math.max(start, Math.min(gap.end_s, durationS));
        if (end <= start) continue;
        const x0 = (start / durationS) * cssWidth;
        const x1 = (end / durationS) * cssWidth;
        ctx.fillStyle = SILENCE_FILL;
        ctx.fillRect(x0, 0, Math.max(x1 - x0, 1), cssHeight);
        ctx.fillStyle = SILENCE_EDGE;
        ctx.fillRect(x0, 0, 1, cssHeight);
        ctx.fillRect(Math.max(x1 - 1, x0), 0, 1, cssHeight);
      }
    }

    // Centre line.
    ctx.fillStyle = "rgba(255, 255, 255, 0.08)";
    ctx.fillRect(0, mid, cssWidth, 1);

    if (pairs.length === 0) return;

    // One column of pixels per bucket, or per pixel when there are more
    // buckets than pixels. int8 peaks map onto -128..127.
    const columns = Math.min(Math.floor(cssWidth), pairs.length);
    const colWidth = cssWidth / columns;
    for (let c = 0; c < columns; c += 1) {
      const from = Math.floor((c * pairs.length) / columns);
      const to = Math.max(from + 1, Math.floor(((c + 1) * pairs.length) / columns));
      let lo = 0;
      let hi = 0;
      for (let i = from; i < to; i += 1) {
        if (pairs[i][0] < lo) lo = pairs[i][0];
        if (pairs[i][1] > hi) hi = pairs[i][1];
      }
      const yTop = mid - (hi / 128) * (mid - 1);
      const yBottom = mid - (lo / 128) * (mid - 1);
      const x = c * colWidth;
      ctx.fillStyle = x + colWidth <= playedX ? "#56b6ff" : "#6fd3c7";
      ctx.fillRect(x, yTop, Math.max(colWidth - 0.5, 0.6), Math.max(yBottom - yTop, 1));
    }

    // Playhead.
    if (durationS && durationS > 0) {
      ctx.fillStyle = "rgba(255, 255, 255, 0.85)";
      ctx.fillRect(Math.min(playedX, cssWidth - 1), 0, 1, cssHeight);
    }
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
