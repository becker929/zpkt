"use client";

/**
 * The sound inside one collage region, drawn down the region.
 *
 * A region is a cut from a source, and trimming it means seeing where the
 * sound is inside the cut. This draws the source's peaks for exactly the
 * stretch the region holds, with its measured silence and its YAMNet spans
 * tinted, time running down because time runs down the whole canvas. The
 * peaks are the same thousand buckets every other view draws; a cut of twenty
 * seconds out of five minutes gets the sixty-odd buckets that fall inside it.
 *
 * The size is given, not measured: the region's box is the truth about its
 * length, and this fills it. The box's height already carries the rate — a
 * region slowed to half is twice as tall — and the window is still the cut
 * in source seconds, so the same samples are drawn over the new height and
 * the waveform stretches with the box: what is seen is what plays. A region
 * can be a fifteen-minute source stamped whole, nine thousand pixels tall,
 * or that again slowed four times, so the backing store is capped in device
 * pixels rather than letting a phone allocate a bitmap it cannot hold; the
 * drawing goes a little soft on a very tall region and stays sharp on a
 * short one.
 *
 * The playhead is not drawn here. The region draws it as a band that grows
 * down the box, so playback never redraws a tall canvas sixty times a second.
 */

import { useEffect, useRef } from "react";

import type { SilenceInterval, Span } from "@/lib/types";
import { paintWaveform } from "@/lib/wavePaint";

/** The most device pixels a region's canvas is tall. */
const MAX_CANVAS_PX = 8192;

export interface RegionWaveProps {
  pairs: ReadonlyArray<readonly [number, number]>;
  /** Length of the whole source in seconds. */
  durationS: number | null;
  /** The cut, in source seconds. */
  startS: number;
  endS: number;
  spans?: readonly Span[];
  silence?: readonly SilenceInterval[];
  width: number;
  height: number;
  /**
   * How many times the cut sounds, back to back. One by default.
   *
   * The box holds that many copies of the same material, so the drawing is
   * the same drawing that many times down it, each at a share of the height.
   * Drawing the cut once, stretched over the whole box, would say the sound
   * had been slowed — which is what stretch does and this does not.
   */
  loops?: number;
}

export function RegionWave({
  pairs,
  durationS,
  startS,
  endS,
  spans,
  silence,
  width,
  height,
  loops = 1,
}: RegionWaveProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const times = Number.isInteger(loops) && loops >= 1 ? loops : 1;
    const cssWidth = Math.max(1, Math.round(width));
    const cssHeight = Math.max(1, Math.round(height));
    const dpr = Math.min(window.devicePixelRatio || 1, 2, MAX_CANVAS_PX / cssHeight);
    const w = Math.max(1, Math.round(cssWidth * dpr));
    const h = Math.max(1, Math.round(cssHeight * dpr));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssWidth, cssHeight);
    // One repeat's share of the box. The painter clears what it is about to
    // draw on, and it is handed a translated origin, so each repeat clears
    // and paints its own band and leaves the ones before it alone.
    const band = cssHeight / times;
    for (let n = 0; n < times; n += 1) {
      ctx.save();
      ctx.translate(0, n * band);
      paintWaveform(ctx, cssWidth, band, {
        pairs,
        durationS,
        spans,
        silence,
        window: [startS, endS],
        vertical: true,
      });
      ctx.restore();
    }
  }, [pairs, durationS, startS, endS, spans, silence, width, height, loops]);

  return (
    <canvas
      ref={canvasRef}
      className="region-wave"
      data-testid="region-wave"
      data-buckets={pairs.length}
      data-silent-regions={silence?.length ?? 0}
      data-loops={loops}
      style={{ width, height }}
      aria-hidden="true"
    />
  );
}
