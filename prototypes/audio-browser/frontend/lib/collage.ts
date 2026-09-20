/**
 * The collage's geometry, as pure functions.
 *
 * Time runs down the screen and tracks run across it. Everything here turns a
 * tap into a region, a region into a box, or a drag into a trim, a snip or a
 * stretch, and nothing here touches the DOM, the network, or a clock. The view
 * is the effectful shell around this.
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
 * The handle follows the thumb until the drag hits a wall, and then it stays
 * on the wall while the thumb carries on. That is how the source's end, the
 * other handle, the rate's bounds and the neighbour on the track are all
 * shown: as somewhere the handle will not go.
 *
 * Measured as the change in the box's length, so it serves a trim and a
 * stretch alike: a trim changes the length by moving the cut, a stretch by
 * moving the rate, and either way the dragged end is where the box now
 * stops. The other end is the one that held still.
 */
export function dragOffsetPx(region: Region, changed: Region, end: End): number {
  const delta = regionLengthS(changed) - regionLengthS(region);
  return (end === "end" ? delta : -delta) * PX_PER_S;
}

/** The source time a handle dragged `dy` canvas pixels is asking for. */
export function draggedTo(region: Region, end: End, dy: number): number {
  const rate = region.rate > 0 ? region.rate : 1;
  const from = end === "start" ? region.start_s : region.end_s;
  return from + (dy / PX_PER_S) * rate;
}

/* Stretch ------------------------------------------------------------------- */

/**
 * The slowest and the fastest a region may play.
 *
 * Two octaves each way. Past that varispeed stops being a stretch and becomes
 * a different instrument. A stretch stops here; nothing prints the number.
 * A region written outside these — by hand, or by an earlier tool — may be
 * brought back towards them and never taken further out.
 */
export const RATE_MIN = 0.25;
export const RATE_MAX = 4;

/**
 * Where a stretch stopped short of what the thumb asked for, if it did.
 *
 * Four walls, and the view says which one in words: `slow` and `fast` are
 * the rate's own bounds, `room` is the neighbour on the track, and `top` is
 * the first moment, which is what a start handle meets when nothing sounds
 * above it. `null` is a drag that got what it asked for.
 */
export type StretchStop = "slow" | "fast" | "room" | "top" | null;

/**
 * The walls a stretch of one end meets: the slowest and the fastest that end
 * may take the region, and which wall holds the slow side.
 *
 * Null when the region cannot be stretched at all — an empty cut, or an end
 * with no room on its side.
 */
interface StretchWalls {
  slowest: number;
  fastest: number;
  /** The first moment the region may begin at, for a start handle. */
  floor: number;
  /** What holds the slow side: the rate's own bound, a neighbour, or time. */
  slowWall: "slow" | "room" | "top";
}

function stretchWalls(region: Region, regions: readonly Region[], end: End): StretchWalls | null {
  const cut = region.end_s - region.start_s;
  if (!(cut > 0)) return null;
  const rate = region.rate > 0 ? region.rate : 1;
  const length = cut / rate;
  let room: number;
  let floor = 0;
  let crowded: "room" | "top";
  if (end === "end") {
    const next = nextOnTrack(region, regions);
    room = next === null ? Infinity : next.at_s - region.at_s;
    crowded = "room";
  } else {
    const prev = prevOnTrack(region, regions);
    floor = prev === null ? 0 : Math.max(0, prev.at_s + regionLengthS(prev));
    room = region.at_s + length - floor;
    crowded = prev === null ? "top" : "room";
  }
  if (!(room > 0)) return null;
  // The slowest the rate may go is whichever binds first: the bound itself
  // (or the region's own rate, when it was written slower than the bound),
  // or the rate at which the box exactly fills the room it has.
  const byBound = Math.min(RATE_MIN, rate);
  const bySpace = cut / room;
  const slowest = Math.max(byBound, bySpace);
  const fastest = Math.max(RATE_MAX, rate);
  if (slowest > fastest) return null;
  return { slowest, fastest, floor, slowWall: bySpace > byBound ? crowded : "slow" };
}

/**
 * Which wall a stretch to `lengthS` collage seconds would meet, if any.
 *
 * Asked and answered in rates, not in lengths. A rate is rounded to six
 * places before it is stored, and the length that comes back out of a
 * rounded rate differs from the length asked for by an amount that grows
 * with the cut: a quarter of a millisecond on a fifteen-minute source. Read
 * as a shortfall in length, that rounding is indistinguishable from a wall,
 * and the bar would announce one on nearly every drag of real material. The
 * rate the thumb is asking for is either outside the bounds or it is not.
 */
export function stretchStop(
  region: Region,
  regions: readonly Region[],
  end: End,
  lengthS: number,
): StretchStop {
  if (!Number.isFinite(lengthS)) return null;
  const walls = stretchWalls(region, regions, end);
  if (walls === null) return null;
  const cut = region.end_s - region.start_s;
  const wanted = lengthS > 0 ? cut / lengthS : Infinity;
  // A hair either side of a wall is arithmetic, not a wall.
  const slack = 1e-9;
  if (wanted > walls.fastest * (1 + slack)) return "fast";
  if (wanted < walls.slowest * (1 - slack)) return walls.slowWall;
  return null;
}

/**
 * The length, in collage seconds, a handle dragged `dy` canvas pixels in
 * stretch mode is asking for. The box grows from the end being dragged, so
 * the bottom handle lengthens it going down and the top handle going up.
 */
export function stretchedTo(region: Region, end: End, dy: number): number {
  const length = regionLengthS(region);
  return end === "end" ? length + dy / PX_PER_S : length - dy / PX_PER_S;
}

/**
 * A region made `lengthS` collage seconds long by changing its rate.
 *
 * Stretch changes `rate` and nothing else about the material: the cut into
 * the source, `start_s` to `end_s`, is untouched, so the same sound plays
 * slower or faster. The box's height is `(end_s − start_s) / rate`, so
 * asking for a length is asking for a rate.
 *
 * The end that is not dragged stays where it is in time. Dragging the end
 * handle keeps `at_s`: the region begins when it did and runs on longer or
 * stops sooner. Dragging the start handle keeps the region's *last* moment
 * instead, so `at_s` moves: the cut cannot change, the bottom is anchored,
 * and the only thing left that can move is when the region begins. In trim
 * mode the same drag would move the cut and hold `at_s`; that is the whole
 * difference between the two modes.
 *
 * Bounds: the rate stays inside `RATE_MIN`..`RATE_MAX` (or, for a region
 * already outside them, on the far side of its own rate), and the box stays
 * off its neighbours on the track: the end handle stops where the next
 * region begins, the start handle where the previous one ends, or at the
 * first moment. The region comes back unchanged when nothing may move.
 */
export function stretch(region: Region, regions: readonly Region[], end: End, lengthS: number): Region {
  if (!Number.isFinite(lengthS)) return region;
  const walls = stretchWalls(region, regions, end);
  if (walls === null) return region;
  const cut = region.end_s - region.start_s;
  const rate = region.rate > 0 ? region.rate : 1;
  const length = cut / rate;
  const wanted = lengthS > 0 ? cut / lengthS : walls.fastest;
  // Six places, so a file stays tidy; then the bounds again, exactly, so a
  // rounded rate never puts the box a hair over a neighbour.
  const next = clamp(round6(wanted), walls.slowest, walls.fastest);
  if (next === rate) return region;
  if (end === "end") return { ...region, rate: next };
  const at = Math.max(walls.floor, region.at_s + length - cut / next);
  return { ...region, rate: next, at_s: round3(at) };
}

/* Snip ---------------------------------------------------------------------- */

/** The source time at `offsetPx` down from the top of a region's box. */
export function sourceAt(region: Region, offsetPx: number): number {
  const rate = region.rate > 0 ? region.rate : 1;
  return region.start_s + (offsetPx / PX_PER_S) * rate;
}

/** How far down a region's box the source time `t` is drawn, in pixels. */
export function offsetOf(region: Region, t: number): number {
  const rate = region.rate > 0 ? region.rate : 1;
  return ((t - region.start_s) / rate) * PX_PER_S;
}

/** What a snip does: the regions that replace the one snipped, and the span it took out. */
export interface Snip {
  /** Two regions, one, or none, in the order they sound. */
  result: Region[];
  /** The span removed, in source seconds, after any extension to an edge. */
  from_s: number;
  to_s: number;
}

/**
 * A span cut out of the middle of a region.
 *
 * What is left is two regions: the material before the span and the material
 * after it. Both keep the source, the track, the rate, the gain and the fades
 * of the region they came from, and both keep their place in time. The first
 * keeps the region's id and its `at_s`. The second gets the next free id, and
 * its `at_s` is where its material was already sounding: snipping a gap out
 * leaves that gap in time, not a splice. Nothing is deleted from the source;
 * both halves still reference it.
 *
 * Neither half may be shorter than `MIN_REGION_S`. A span that would leave a
 * half shorter than that takes the half with it: the removal runs on to that
 * edge of the region. At the end that is a trim of the end. At the start the
 * surviving material still stays where it sounded, so the box's top moves
 * down to it, which is what the drawn span said would happen. A span that
 * leaves nothing on either side removes the region from the collage. The
 * source is untouched either way, and undo brings the region back.
 *
 * `from_s` and `to_s` are clamped to the region's own cut. Null when the span
 * is empty, so a tap is never a snip.
 */
export function snip(region: Region, regions: readonly Region[], fromS: number, toS: number): Snip | null {
  if (!Number.isFinite(fromS) || !Number.isFinite(toS)) return null;
  let a = round3(clamp(Math.min(fromS, toS), region.start_s, region.end_s));
  let b = round3(clamp(Math.max(fromS, toS), region.start_s, region.end_s));
  if (!(b > a)) return null;
  if (a - region.start_s < MIN_REGION_S) a = region.start_s;
  if (region.end_s - b < MIN_REGION_S) b = region.end_s;
  const rate = region.rate > 0 ? region.rate : 1;
  const before = a > region.start_s ? { ...region, end_s: a } : null;
  const afterAt = round3(region.at_s + (b - region.start_s) / rate);
  const after = b < region.end_s ? { ...region, start_s: b, at_s: afterAt } : null;
  const result: Region[] = [];
  if (before) result.push(before);
  if (after) result.push(before ? { ...after, id: nextRegionId(regions) } : after);
  return { result, from_s: a, to_s: b };
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

function round6(n: number): number {
  return Math.round(n * 1e6) / 1e6;
}
