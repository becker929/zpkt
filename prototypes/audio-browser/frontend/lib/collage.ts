/**
 * The collage's geometry, as pure functions.
 *
 * Time runs down the screen and tracks run across it. Everything here turns a
 * tap into a region, a region into a box, or a drag into a trim, and nothing
 * here touches the DOM, the network, or a clock. The view is the effectful
 * shell around this.
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

/**
 * How tall a handle is: a thumb.
 *
 * A region is drawn at its true length, and a one-second region is ten pixels
 * of sound. Ten pixels cannot be trimmed with a thumb, so each end of a region
 * carries a handle this tall, drawn outside the region's own extent. The
 * handle is the affordance; the box is the truth.
 */
export const HANDLE_H = 44;

/**
 * Blank above the first moment.
 *
 * A thumb and a little: the first region's top handle sits in it, so trimming
 * the start of the first sound is as easy as trimming any other end.
 */
export const TOP_PAD = 56;

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

/**
 * The shortest cut, in source seconds.
 *
 * A quarter of a second. Under that a region is a click rather than a sound:
 * too short to carry any of the noise and texture this material is made of,
 * and short enough that the slice the server cuts for it is a few thousand
 * frames of nothing much. A trim stops here rather than letting a drag run a
 * region down to nothing, and so no drag can ever write a cut the server
 * refuses (one that ends before it begins).
 */
export const MIN_REGION_S = 0.25;

/** Which end of a region a handle belongs to. */
export type End = "start" | "end";

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

/** The box a region is drawn in, in pixels inside the canvas. */
export interface RegionBox {
  left: number;
  top: number;
  width: number;
  height: number;
}

/**
 * Where a region is drawn. Height is duration, exactly.
 *
 * Nothing pads a short region up to a thumb: two short cuts of different
 * lengths look different, and once a region can be trimmed its box has to
 * tell the truth about what the trim did. The handles are what make a short
 * region reachable, and they sit outside this box.
 */
export function regionBox(region: Region): RegionBox {
  return {
    left: region.track * TRACK_W,
    top: TOP_PAD + region.at_s * PX_PER_S,
    width: TRACK_W,
    height: regionLengthS(region) * PX_PER_S,
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
 * right after it. Simultaneity is what a second track is for. Overlap is
 * measured in sound: boxes are drawn at true length, so the sound's gap is
 * the box's gap.
 */
export function settle(regions: readonly Region[], track: number, at_s: number, length_s: number): number {
  const lane = regions
    .filter((region) => region.track === track)
    .map((region) => ({ from: region.at_s, to: region.at_s + regionLengthS(region) }))
    .sort((a, b) => a.from - b.from);
  let at = at_s;
  for (const other of lane) {
    if (at < other.to && at + length_s > other.from) at = other.to;
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
 * The cut is the whole source until it is trimmed. Rate, gain and the fades
 * are at their untouched values, present from the first stamp so no later
 * stage has to ask whether an old region carries them.
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

/* Neighbours ---------------------------------------------------------------- */

/** The region that sounds next after this one on its track, or null. */
export function nextOnTrack(region: Region, regions: readonly Region[]): Region | null {
  let next: Region | null = null;
  for (const other of regions) {
    if (other.id === region.id || other.track !== region.track) continue;
    if (other.at_s < region.at_s) continue;
    if (other.at_s === region.at_s && other.id <= region.id) continue;
    if (next === null || other.at_s < next.at_s) next = other;
  }
  return next;
}

/** The region that sounds last before this one on its track, or null. */
export function prevOnTrack(region: Region, regions: readonly Region[]): Region | null {
  let prev: Region | null = null;
  for (const other of regions) {
    if (other.id === region.id || other.track !== region.track) continue;
    if (other.at_s > region.at_s) continue;
    if (other.at_s === region.at_s && other.id >= region.id) continue;
    if (prev === null || other.at_s > prev.at_s) prev = other;
  }
  return prev;
}

/* Grabs and handles --------------------------------------------------------- */

/** A stretch of the track, in pixels relative to the top of a region's box. */
export interface Zone {
  /** Offset from the top of the region's box. Negative means above it. */
  top: number;
  height: number;
}

/**
 * Where a region can be taken hold of.
 *
 * A box is drawn at its true length, and a one-second region is ten pixels of
 * sound: nothing a thumb can land on. So every region has a grab, a hit area
 * and not a drawing, that reaches out from the box until it is a thumb tall.
 * Two regions close on one track split the gap between them down the middle,
 * so no two grabs ever overlap and a tap between two regions goes to the
 * nearer one. What a grab cannot take on one side it takes on the other, up
 * to that side's share; the first region on a track has the blank above time
 * to reach into.
 */
export function grabZone(region: Region, regions: readonly Region[]): Zone {
  const box = regionBox(region);
  const prev = prevOnTrack(region, regions);
  const next = nextOnTrack(region, regions);
  const roomAbove = prev === null ? box.top : (region.at_s - (prev.at_s + regionLengthS(prev))) * PX_PER_S;
  const roomBelow = next === null ? Infinity : (next.at_s - (region.at_s + regionLengthS(region))) * PX_PER_S;
  const shareAbove = Math.max(0, prev === null ? roomAbove : roomAbove / 2);
  const shareBelow = Math.max(0, roomBelow / 2);
  const deficit = Math.max(0, HANDLE_H - box.height);
  let above = Math.min(deficit / 2, shareAbove);
  const below = Math.min(deficit - above, shareBelow);
  above = Math.min(deficit - below, shareAbove);
  return { top: -above, height: box.height + above + below };
}

/** Where a handle is drawn, in pixels relative to its region's box. */
export interface HandleZone extends Zone {
  end: End;
}

/**
 * Where a region's two handles sit, when it is the selected region.
 *
 * Only the selected region has handles. They live outside its box, a full
 * thumb tall whatever sits beside them, and the view raises the selected
 * region above its neighbours for as long as it is selected: the region
 * being worked on is on top, and a neighbour's grab is under it until a tap
 * on the blank puts it down. Nothing is ever squeezed thinner than a thumb,
 * and no two handles on the canvas overlap, because there are only two.
 */
export function handleZones(region: Region): { start: HandleZone; end: HandleZone } {
  const box = regionBox(region);
  return {
    start: { end: "start", top: -HANDLE_H, height: HANDLE_H },
    end: { end: "end", top: box.height, height: HANDLE_H },
  };
}

/* Trim ---------------------------------------------------------------------- */

/**
 * How far each end of a region may be moved, in source seconds.
 *
 * Three walls. The source's own bounds: a cut cannot begin before the sound
 * does or end after it. The other end: a cut is never shorter than
 * `MIN_REGION_S`. And the next region on the track: a region keeps its place
 * in time when it is trimmed, so any growth appears at its bottom, and the
 * bottom stops where the neighbour begins.
 *
 * `sourceDurationS` is null for a sound the index no longer resolves. Such a
 * region cannot be played, and it cannot be trimmed either: nothing is known
 * about where its sound ends.
 */
export interface TrimBounds {
  minStart: number;
  maxStart: number;
  minEnd: number;
  maxEnd: number;
}

export function trimBounds(
  region: Region,
  regions: readonly Region[],
  sourceDurationS: number | null,
): TrimBounds | null {
  if (sourceDurationS === null || !(sourceDurationS > 0)) return null;
  const rate = region.rate > 0 ? region.rate : 1;
  const next = nextOnTrack(region, regions);
  // The most source the region may hold, given the room below it on the track.
  const roomS = next === null ? Infinity : Math.max(0, next.at_s - region.at_s) * rate;
  const minStart = Math.max(0, region.end_s - roomS);
  const maxStart = region.end_s - MIN_REGION_S;
  const minEnd = region.start_s + MIN_REGION_S;
  const maxEnd = Math.min(sourceDurationS, region.start_s + roomS);
  return {
    minStart,
    maxStart: Math.max(maxStart, minStart),
    minEnd,
    maxEnd: Math.max(maxEnd, minEnd),
  };
}

/**
 * One end of a region moved to `t` source seconds, held inside its bounds.
 *
 * `at_s` is not touched. Trimming changes what is cut from the source, not
 * when the region sounds: a sparse source stamped at the top of the collage
 * stays at the top once it has been cut down to the part that sounds. The
 * region comes back unchanged when nothing about it may move.
 */
export function trim(
  region: Region,
  regions: readonly Region[],
  sourceDurationS: number | null,
  end: End,
  t: number,
): Region {
  const bounds = trimBounds(region, regions, sourceDurationS);
  if (bounds === null || !Number.isFinite(t)) return region;
  if (end === "start") {
    return { ...region, start_s: round3(clamp(t, bounds.minStart, bounds.maxStart)) };
  }
  return { ...region, end_s: round3(clamp(t, bounds.minEnd, bounds.maxEnd)) };
}

/**
 * Where a handle sits during a drag, in canvas pixels from where it started.
 *
 * The handle follows the thumb until the trim hits a wall, and then it stays
 * on the wall while the thumb carries on. That is how the source's end, the
 * other handle and the neighbour below are all shown: as somewhere the handle
 * will not go.
 */
export function dragOffsetPx(region: Region, trimmed: Region, end: End): number {
  const rate = region.rate > 0 ? region.rate : 1;
  const delta = end === "start" ? trimmed.start_s - region.start_s : trimmed.end_s - region.end_s;
  return (delta / rate) * PX_PER_S;
}

/** The source time a handle dragged `dy` canvas pixels is asking for. */
export function draggedTo(region: Region, end: End, dy: number): number {
  const rate = region.rate > 0 ? region.rate : 1;
  const from = end === "start" ? region.start_s : region.end_s;
  return from + (dy / PX_PER_S) * rate;
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

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(Math.max(n, lo), Math.max(hi, lo));
}

function round3(n: number): number {
  return Math.round(n * 1000) / 1000;
}
