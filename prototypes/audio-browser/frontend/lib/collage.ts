/**
 * The collage's geometry, as pure functions.
 *
 * Time runs down the screen and tracks run across it. Everything here turns a
 * tap into a region or a region into a box, and nothing here touches the DOM,
 * the network, or a clock. The view is the effectful shell around this.
 *
 * No grid. A tap lands where it lands, to the millisecond, and the only thing
 * that moves it is another region already sitting there. No number of seconds
 * leaves this module as text: the view draws every value as a length or a
 * position.
 */

import { onBoard, type ProjectSummary, type Region } from "./project";

/**
 * The project in `collage`, or null when there is none.
 *
 * At a cap of one there is exactly one. On a board running looser, the most
 * recently started one is the bench, as it is for swipe. An abandoned project
 * keeps the column it left and is not here: `onBoard` is the test.
 */
export function collageProject(projects: readonly ProjectSummary[] | null): ProjectSummary | null {
  if (!projects) return null;
  const here = projects.filter((p) => p.column === "collage" && onBoard(p));
  if (here.length === 0) return null;
  return here.reduce((newest, p) => (p.created_at > newest.created_at ? p : newest));
}

/**
 * How tall one second is.
 *
 * Ten pixels a second puts the shortest sound in HW011 (six seconds) at a
 * thumb's height and the longest (fifteen minutes) at nine thousand pixels,
 * which is a scroll and not a problem: scrolling through time is the gesture a
 * thumb already knows on a phone held upright.
 */
export const PX_PER_S = 10;

/**
 * How wide one track is.
 *
 * Wide enough for a thumb with room either side of it, and narrow enough that
 * three sit across a phone. A track is a column; the column beside the last
 * one is where the next track comes into being.
 */
export const TRACK_W = 128;

/** Blank above the first moment, so the top region is not against the edge. */
export const TOP_PAD = 12;

/**
 * The least height a region is drawn at.
 *
 * Height is duration, and a tenth of a second is one pixel. One pixel cannot be
 * tapped, so a region is never drawn shorter than a thumb. The model is not
 * touched by this: the region still ends where the cut ends, and only the box
 * is padded.
 */
export const MIN_REGION_H = 44;

/**
 * Blank below the last region, so there is somewhere to stamp after it.
 *
 * A minute of it. Regions cannot yet be moved, so this is the longest gap a
 * stamp can leave after the last region in one go; a longer one takes a second
 * stamp. This is room, not a ruler: nothing is drawn in it, and it does not
 * read as an invitation to fill because there is nothing there to fill. The
 * view also keeps the blank at least as tall as the canvas itself.
 */
export const BEYOND_PX = 600;

/** How many tracks exist. A track exists because something was stamped there. */
export function trackCount(regions: readonly Region[]): number {
  let count = 0;
  for (const region of regions) count = Math.max(count, region.track + 1);
  return count;
}

/** How long a region sounds for, after its rate. */
export function regionLengthS(region: Pick<Region, "start_s" | "end_s" | "rate">): number {
  return Math.max(0, region.end_s - region.start_s) / (region.rate > 0 ? region.rate : 1);
}

/** When the last region stops sounding. Zero for an empty collage. */
export function extentS(regions: readonly Region[]): number {
  let end = 0;
  for (const region of regions) end = Math.max(end, region.at_s + regionLengthS(region));
  return end;
}

/**
 * How long a region takes up on its track, in seconds: its length, or the
 * least height a box is drawn at, whichever is more.
 *
 * A region shorter than a thumb is drawn a thumb tall, so the room it takes
 * on the track is the room its box takes, not the room its sound takes. Every
 * rule about two regions sharing a track uses this, so two boxes on one track
 * never sit on top of each other.
 */
export function footprintS(region: Pick<Region, "start_s" | "end_s" | "rate">): number {
  return Math.max(regionLengthS(region), MIN_REGION_H / PX_PER_S);
}

/** The box a region is drawn in, in pixels inside the canvas. */
export interface RegionBox {
  left: number;
  top: number;
  width: number;
  height: number;
}

/**
 * Where a region is drawn.
 *
 * Height is duration, padded up to a thumb. The padding stops short of the
 * next region on the same track: a file may hold two short cuts closer
 * together than a thumb (trim will make them), and a padded box drawn over
 * its neighbour would hide the neighbour from the thumb entirely. The box is
 * never shorter than the sound is, whatever follows it.
 */
export function regionBox(region: Region, regions: readonly Region[] = []): RegionBox {
  const trueH = regionLengthS(region) * PX_PER_S;
  let nextStart = Infinity;
  for (const other of regions) {
    if (other === region || other.track !== region.track || other.id === region.id) continue;
    if (other.at_s >= region.at_s + regionLengthS(region) && other.at_s < nextStart) nextStart = other.at_s;
  }
  const room = nextStart === Infinity ? Infinity : (nextStart - region.at_s) * PX_PER_S;
  return {
    left: region.track * TRACK_W,
    top: TOP_PAD + region.at_s * PX_PER_S,
    width: TRACK_W,
    height: Math.max(trueH, Math.min(MIN_REGION_H, room)),
  };
}

/**
 * How big the canvas has to be.
 *
 * One column more than there are tracks, so there is always a place to stamp
 * beside the last one, and one screen more than there is time, so there is
 * always a place to stamp after the last region. Both are blank.
 */
export function canvasSize(regions: readonly Region[]): { width: number; height: number } {
  return {
    width: (trackCount(regions) + 1) * TRACK_W,
    height: TOP_PAD + extentS(regions) * PX_PER_S + BEYOND_PX,
  };
}

/**
 * Which track and which moment a tap means.
 *
 * The track is the column under the thumb, capped at the column beside the
 * last track: on an empty canvas every tap is track zero, and once tracks
 * exist a tap past all of them makes one more, never two. The moment is the
 * tap's height in seconds, except that the first stamp always starts time at
 * zero — time exists because a sound was stamped into it, and the first sound
 * is where it begins.
 */
export function placementAt(
  regions: readonly Region[],
  x: number,
  y: number,
): { track: number; at_s: number } {
  const track = Math.max(0, Math.min(Math.floor(x / TRACK_W), trackCount(regions)));
  const at_s = regions.length === 0 ? 0 : Math.max(0, (y - TOP_PAD) / PX_PER_S);
  return { track, at_s: round3(at_s) };
}

/**
 * The first moment at or after `at_s` where a region this long fits on the
 * track without overlapping one already there.
 *
 * Regions on one track do not overlap. Two blocks in one lane cannot both be
 * tapped, so a stamp that would land on top of a neighbour slides down to sit
 * right after it. Simultaneity is what a second track is for.
 *
 * "Overlap" is measured in boxes, not in sound (`footprintS`): a cut shorter
 * than a thumb is drawn a thumb tall, and a stamp that fits in the sound's
 * gap but not in the box's gap would be drawn over its neighbour.
 */
export function settle(regions: readonly Region[], track: number, at_s: number, length_s: number): number {
  const lane = regions
    .filter((region) => region.track === track)
    .map((region) => ({ from: region.at_s, to: region.at_s + footprintS(region) }))
    .sort((a, b) => a.from - b.from);
  const footprint = Math.max(length_s, MIN_REGION_H / PX_PER_S);
  let at = at_s;
  for (const other of lane) {
    if (at < other.to && at + footprint > other.from) at = other.to;
  }
  return round3(at);
}

/** The next free id in the family `r1`, `r2`, `r3`, … */
export function nextRegionId(regions: readonly Region[]): string {
  let highest = 0;
  for (const region of regions) {
    const match = /^r(\d+)$/.exec(region.id);
    if (match) highest = Math.max(highest, Number(match[1]));
  }
  return `r${highest + 1}`;
}

/**
 * A new region: the whole of one sound, stamped where the tap landed.
 *
 * The cut is the whole source until trim exists. Rate, gain and the fades are
 * at their untouched values, present from the first stamp so no later stage
 * has to ask whether an old region carries them.
 */
export function stamp(
  regions: readonly Region[],
  hash: string,
  duration_s: number,
  x: number,
  y: number,
): Region {
  const { track, at_s } = placementAt(regions, x, y);
  const length = Math.max(duration_s, 0.001);
  return {
    id: nextRegionId(regions),
    hash,
    track,
    start_s: 0,
    end_s: round3(length),
    at_s: settle(regions, track, at_s, length),
    rate: 1,
    gain: 1,
    fade_in_s: 0,
    fade_out_s: 0,
  };
}

/**
 * A hue for a source, so every region cut from one sound shares a colour.
 *
 * Read off the hash, so it is the same on every reload and in every view that
 * draws the same sound.
 */
export function hueFor(hash: string): number {
  const head = parseInt(hash.slice(0, 3), 16);
  return Number.isFinite(head) ? Math.round((head / 4096) * 360) : 200;
}

function round3(n: number): number {
  return Math.round(n * 1000) / 1000;
}
