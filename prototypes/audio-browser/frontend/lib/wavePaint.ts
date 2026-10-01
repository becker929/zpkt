/**
 * Painting a waveform from server-computed peaks.
 *
 * One painter, two orientations. `Waveform` draws a sound across the screen
 * with time running right; a collage region draws a stretch of a sound down
 * the screen with time running down. Both are the same drawing turned on its
 * side, so both are drawn here, and the tint for a silent stretch or a
 * labelled span is the same colour in every view.
 *
 * `window` is the stretch of the sound to draw, in seconds. The whole sound
 * when it is left out; a region's cut when a region asks. Peaks, spans and
 * silence are all in whole-sound seconds and are mapped through the window
 * here, so a caller never rescales anything.
 *
 * This is the one effectful thing in `lib/`: it draws on a context it is
 * handed. It reads nothing else and keeps nothing.
 */

import type { SilenceInterval, Span } from "./types";

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

export interface PaintOptions {
  /** [minimum, maximum] pairs, each in -128..127. Empty while loading. */
  pairs: ReadonlyArray<readonly [number, number]>;
  /** Length of the whole sound in seconds. Used to place everything. */
  durationS: number | null;
  /** Playhead position in whole-sound seconds. Nothing is drawn when absent. */
  progressS?: number;
  spans?: readonly Span[];
  silence?: readonly SilenceInterval[];
  /** The stretch of the sound drawn, in seconds. The whole sound by default. */
  window?: readonly [number, number];
  /** Time runs down rather than across. */
  vertical?: boolean;
}

/**
 * Draw into a context whose transform already maps CSS pixels to device
 * pixels. `cssWidth` and `cssHeight` are the drawing's size in CSS pixels.
 */
export function paintWaveform(
  ctx: CanvasRenderingContext2D,
  cssWidth: number,
  cssHeight: number,
  options: PaintOptions,
): void {
  const { pairs, durationS, spans, silence, vertical = false } = options;
  ctx.clearRect(0, 0, cssWidth, cssHeight);

  // "Along" is the axis time runs on; "across" is the other one.
  const along = vertical ? cssHeight : cssWidth;
  const across = vertical ? cssWidth : cssHeight;
  const box = (a0: number, c0: number, aLen: number, cLen: number) => {
    if (vertical) ctx.fillRect(c0, a0, cLen, aLen);
    else ctx.fillRect(a0, c0, aLen, cLen);
  };

  const whole = durationS !== null && durationS > 0 ? durationS : 0;
  const w0 = options.window ? Math.max(0, options.window[0]) : 0;
  const w1 = options.window ? Math.max(w0, options.window[1]) : whole;
  const span = w1 - w0;
  const toAlong = (t: number) => (span > 0 ? ((t - w0) / span) * along : 0);

  const progressS = options.progressS;
  const playedAlong =
    progressS !== undefined && span > 0 ? Math.min(Math.max(toAlong(progressS), 0), along) : 0;

  // Span tints sit underneath the waveform so the shape stays readable.
  if (spans && spans.length > 0 && span > 0) {
    for (const item of spans) {
      const start = Math.max(w0, Math.min(item.start_s, w1));
      const end = Math.max(start, Math.min(item.end_s, w1));
      if (end <= start) continue;
      const a0 = toAlong(start);
      const a1 = toAlong(end);
      ctx.fillStyle = SPAN_COLORS[item.label] ?? FALLBACK_SPAN_COLOR;
      box(a0, 0, Math.max(a1 - a0, 1), across);
    }
  }

  // Silent stretches sit over the span tints and under the waveform, so a
  // region can be both labelled and silent and still be read as both.
  if (silence && silence.length > 0 && span > 0) {
    for (const gap of silence) {
      const start = Math.max(w0, Math.min(gap.start_s, w1));
      const end = Math.max(start, Math.min(gap.end_s, w1));
      if (end <= start) continue;
      const a0 = toAlong(start);
      const a1 = toAlong(end);
      ctx.fillStyle = SILENCE_FILL;
      box(a0, 0, Math.max(a1 - a0, 1), across);
      ctx.fillStyle = SILENCE_EDGE;
      box(a0, 0, 1, across);
      box(Math.max(a1 - 1, a0), 0, 1, across);
    }
  }

  // Centre line.
  const mid = across / 2;
  ctx.fillStyle = "rgba(255, 255, 255, 0.08)";
  box(0, mid, along, 1);

  if (pairs.length > 0) {
    // The buckets inside the window. The whole sound when there is no window,
    // in which case this is every bucket.
    const b0 = whole > 0 && options.window ? Math.floor((w0 / whole) * pairs.length) : 0;
    const b1 =
      whole > 0 && options.window
        ? Math.max(b0 + 1, Math.min(pairs.length, Math.ceil((w1 / whole) * pairs.length)))
        : pairs.length;
    const visible = b1 - b0;

    // One column of pixels per bucket, or per pixel when there are more
    // buckets than pixels. int8 peaks map onto -128..127.
    const columns = Math.max(1, Math.min(Math.floor(along), visible));
    const colLen = along / columns;
    for (let c = 0; c < columns; c += 1) {
      const from = b0 + Math.floor((c * visible) / columns);
      const to = Math.max(from + 1, b0 + Math.floor(((c + 1) * visible) / columns));
      let lo = 0;
      let hi = 0;
      for (let i = from; i < to && i < pairs.length; i += 1) {
        if (pairs[i][0] < lo) lo = pairs[i][0];
        if (pairs[i][1] > hi) hi = pairs[i][1];
      }
      const cTop = mid - (hi / 128) * (mid - 1);
      const cBottom = mid - (lo / 128) * (mid - 1);
      const a = c * colLen;
      ctx.fillStyle = progressS !== undefined && a + colLen <= playedAlong ? "#56b6ff" : "#6fd3c7";
      box(a, cTop, Math.max(colLen - 0.5, 0.6), Math.max(cBottom - cTop, 1));
    }
  }

  // Playhead.
  if (progressS !== undefined && span > 0) {
    ctx.fillStyle = "rgba(255, 255, 255, 0.85)";
    box(Math.min(playedAlong, along - 1), 0, 1, across);
  }
}
