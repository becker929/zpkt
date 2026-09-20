"use client";

/**
 * Collage: the view where something is made.
 *
 * Time runs down the screen and tracks run across it. It starts with nothing:
 * no lanes, no ruler, no grid, and no number of seconds anywhere. Time exists
 * because a sound was stamped into it, and a track exists because something
 * was stamped there.
 *
 * Five gestures so far. Choose a sound from the project's frozen set, tap
 * the blank to stamp it, hear it back. Then trim: every region shows the
 * sound inside it; a tap on a region plays it and takes it up, and the region
 * taken up carries a thumb-sized handle at each end that drags. Then snip: a
 * mode, entered by a button, in which a drag across a region cuts that part
 * out and leaves two regions. Then stretch: a mode entered by a button once
 * a handle is selected, in which dragging that handle changes how fast the
 * region plays instead of where its cut is. Then balance: a mode entered by a
 * button once a region is taken up, in which a drag *across* the region's box
 * moves how loud it is, and the block's fill takes on that weight so loudness
 * is seen rather than read. Only one mode is ever on, and the default is
 * trim. Every change is written whole to `PUT /api/projects/{id}/collage`, so
 * a reload shows what was on screen. A region plays through Web Audio from a
 * bounded slice the server cuts; nothing decodes a whole file.
 *
 * Then repeat: a mode entered by a button once a region is taken up, in which
 * a drag *down* the region's box makes the material sound again, back to
 * back, and a drag up takes a repeat away. The box grows to hold them and
 * draws a divider where each one begins, so the repeats are counted by eye.
 * Its drag runs along the box because that is the way the box grows; balance
 * runs across it for the same reason turned sideways.
 *
 * Then three that need no mode at all. Move: a tap takes a region up, and a
 * drag on the body of the region in hand carries it — down or up for when it
 * sounds, across for which track — while a tap on that same body still plays
 * it and puts nothing anywhere. Every other region's body is canvas, and
 * canvas scrolls, which is what a thumb does here most of the time. Copy: a button puts
 * the region taken up on a clipboard, and the next tap on the blank stamps it
 * there, which is the stamp path with a region on it instead of a sound.
 * Remove a track: its button, held, takes the track and everything on it, with
 * the column drawn in amber over the hold, and the tracks beyond it close up.
 * A track the last region simply *leaves* closes up the same way, in the same
 * change, so no blank column is ever left that no gesture can aim at.
 *
 * The geometry is in `lib/collage.ts` and is pure. This file is the shell
 * around it: fetches, the audio context, the pointer, and the DOM.
 *
 * And a transport, which is where the cutting gestures were going: play
 * sounds every region at its own moment, at its own rate, through a bus that
 * saturates rather than tearing, and a line moves down the canvas while it
 * does. Playing is not a mode — every gesture stays where it was while the
 * piece sounds. An edit takes its region out of the pass being heard, with
 * one exception: a level moves under the ear, because balance is set against
 * what is already sounding. Beside play is a loop, which starts the piece
 * again from the top when it reaches the end. That is how the piece is
 * listened to and not part of it, so it is not in the model, not in the file
 * and not in the digest; it is remembered on the machine it was set on.
 */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useBoard } from "@/components/BoardProvider";
import { usePlayer } from "@/components/PlayerProvider";
import { RegionWave } from "@/components/RegionWave";
import { Waveform } from "@/components/Waveform";
import {
  ApiRefusal,
  collageRouteIsMissing,
  fetchPeaks,
  fetchProject,
  fetchSilence,
  fetchSpans,
  putCollage,
  type ProjectDetail,
} from "@/lib/api";
import {
  HANDLE_H,
  PX_PER_S,
  TOP_PAD,
  TRACK_W,
  balance,
  balancedTo,
  canvasSize,
  closeEmptyTracks,
  collageProject,
  dragOffsetPx,
  draggedTo,
  gainStop,
  gainWeight,
  grabZone,
  handleZones,
  hueFor,
  loopStop,
  loopedTo,
  loopsOf,
  moveStop,
  moveTo,
  offsetOf,
  paste,
  regionBox,
  regionLengthS,
  removeTrack,
  repeat,
  repeatDividers,
  repeatLengthS,
  snip,
  sourceAt,
  stamp,
  stretch,
  stretchStop,
  stretchedTo,
  trackCount,
  trim,
  type End,
  type GainStop,
  type LoopStop,
  type MoveStop,
  type StretchStop,
} from "@/lib/collage";
import { CollagePlayer } from "@/lib/collagePlayer";
import { HOLD_MS, Hold } from "@/lib/hold";
import { formatCount } from "@/lib/format";
import type { Region } from "@/lib/project";
import { MIN_GAP_S, skippable } from "@/lib/silence";
import { SlicePlayer } from "@/lib/slicePlayer";
import type { FileRow, SilenceInterval, Span } from "@/lib/types";

type SaveState = "idle" | "saving" | "saved" | "failed" | "absent";

/**
 * How many changes undo keeps.
 *
 * Every stamp and every trim is one step. Twenty is more than a session of
 * cutting one source down produces before the result is heard, and small
 * enough that the button can say how many are left without the number being
 * a lie about how far back it goes.
 */
const UNDO_DEPTH = 20;

/** Pixels from the canvas's edge inside which a drag scrolls it. */
const SCROLL_EDGE = 48;

/** Pixels the canvas scrolls per frame while a drag is at its edge. */
const SCROLL_STEP = 8;

/** A box shorter than this has no room for its name. The name is still spoken. */
const LABEL_MIN_H = 26;

/** How far a pointer may travel between down and up and still be a tap. */
const TAP_SLOP = 8;

/**
 * What the bar says when a lift would have taken the whole region and the
 * thumb had not held still on it.
 *
 * The hold itself is `Hold` in `lib/hold.ts`, which both destructive gestures
 * on this surface use: a snip that covers a whole region, and removing a
 * track. The band saying what a lift will do sits under the thumb on a short
 * region, so the wait is what keeps a sweep from taking material.
 */
const SNIP_HOLD_HINT = "to take the whole region out, drag across it, then hold still on it before letting go";

/** What the bar says when a track's button was pressed and let go of too soon. */
const TRACK_HOLD_HINT = "to remove a track and everything on it, press its button and hold it";

/**
 * What the bar says when an edit takes a region out of the pass being heard.
 *
 * The piece is scheduled once, at the tap, so a region cut, snipped,
 * stretched or undone while it sounds stops instead of carrying on as
 * material that no longer exists. On the canvas that is invisible: a block
 * that went quiet looks the same as a block that finished. Without this line
 * the rule reads as a fault, and the fix — play again — is not obvious.
 */
const QUIET_HINT = "that change has gone quiet: it is heard the next time you play";

/**
 * What the bar says when what went quiet mid-play is not coming back.
 *
 * A removed track takes its regions out of the pass the same way an edit
 * does, but "it is heard the next time you play" would be a lie about
 * material that no longer exists. Same rule, said truthfully.
 */
const GONE_HINT = "what went has gone quiet with it: the rest of the piece plays on";

/** True of either line, so the pass ending clears whichever one it left. */
function isQuietHint(line: string | null): boolean {
  return line === QUIET_HINT || line === GONE_HINT;
}

/** What is known about one source, for drawing the regions cut from it. */
interface SourceData {
  pairs: Array<[number, number]>;
  silence: SilenceInterval[];
  spans: Span[];
}

/**
 * What is taken up. One region at a time, and at most one of its handles.
 *
 * A tap on a region takes it up: it is raised above its neighbours and grows
 * its two handles. A handle is selected on its own when it is touched, so
 * the keyboard and stretch know which end is meant. `end` is null while the
 * region is up and neither handle has been touched.
 */
interface Selection {
  id: string;
  end: End | null;
}

/** What a drag on a handle does: move the cut, or move the rate. */
type DragKind = "trim" | "stretch";

/** A drag in progress: the region as it was, and as it would be if released now. */
interface Drag {
  id: string;
  end: End;
  kind: DragKind;
  preview: Region;
  /** Where the stretch stopped short of the thumb, if it did. Null for a trim. */
  stopped: StretchStop;
}

/**
 * Which gesture a drag on a region is.
 *
 * Only one is ever on. Trim is the default: a tap takes a region up and its
 * handles drag. Snip is entered by a button and left by the same button or
 * by finishing a snip; while it is on there are no handles, and a drag down
 * a region paints the part being cut out. Stretch is entered by a button
 * once a handle is selected, and left by the same button, by finishing a
 * stretch, or by letting go of the handle; while it is on only the selected
 * handle shows, and dragging it moves the region's rate, not its cut.
 * Balance is entered by a button once a region is taken up, and left by the
 * same button or by putting the region down; while it is on there are no
 * handles either, and a drag *across* the region's box moves its level.
 *
 * Balance is the one mode a finished drag does not end. A cut is made once
 * and heard; a level is found by going past it and coming back, so ending the
 * mode on every lift would put a button tap in the middle of the gesture.
 * Taking another region up keeps balance on, aimed at that region, for the
 * same reason: balancing fifteen voices against each other is one job.
 */
type Mode = "trim" | "snip" | "stretch" | "balance" | "repeat";

/**
 * Where the preference that the transport loops is remembered.
 *
 * Looping the transport is how the piece is listened to and not part of the
 * piece, so it is not in the model, not in the file and not in the digest. It
 * still has to survive a reload, because the way somebody is listening does
 * not change because a page came back: this is a setting on the machine it is
 * being listened on.
 */
const LOOP_PREFERENCE = "collage.transport.loop";

/**
 * What the transport is doing.
 *
 * `loading` is the gap between the tap and the first sound, while every
 * region's first piece is fetched. It is a state and not a silence: a piece
 * that cannot start within a breath says so rather than starting late.
 * Playing is not one of the modes above — the gestures stay available while
 * the piece sounds.
 */
type Piece = "idle" | "loading" | "playing";

/** A snip in progress: the span being cut out, in pixels down the region's box. */
interface SnipBand {
  id: string;
  top: number;
  height: number;
  /** True when the span has run on to cover the whole region. */
  whole: boolean;
  /** True once a whole band has been held still long enough that a lift removes the region. */
  armed: boolean;
}

/**
 * A move in progress: where the region would be if the thumb lifted now.
 *
 * The box is drawn there while the thumb holds it, so what is on screen is
 * what a lift would write — including the slide down past a neighbour, which
 * is the one thing a move does that the thumb did not ask for.
 */
interface Moving {
  id: string;
  track: number;
  at_s: number;
  /** Which wall the move has met, if either. */
  stopped: MoveStop;
}

/**
 * A track being held towards removal, and whether the hold has finished.
 *
 * While this is set the column and everything on it is drawn in amber, which
 * is the language a whole-region snip already speaks: this is what goes.
 */
interface Doomed {
  track: number;
  armed: boolean;
}

/** A balance in progress: the region being weighed, and the level it is at now. */
interface Balancing {
  id: string;
  /** The level the region would keep if the thumb lifted now. */
  gain: number;
  /** Which wall the thumb has run into, if either. */
  stopped: GainStop;
}

/**
 * A repeat in progress: the region, and how many times it would sound if the
 * thumb lifted now.
 *
 * The box is drawn at that count while the thumb holds it, with a divider
 * where each repeat begins, so what is on screen is what a lift would write.
 */
interface Repeating {
  id: string;
  loops: number;
  /** Which wall the thumb has run into, if any. */
  stopped: LoopStop;
}

/* The picker ----------------------------------------------------------------- */

/**
 * The project's frozen set, one row each, to be heard before being chosen.
 *
 * Tapping a row plays it through the shared player: streamed, silence
 * skipped, spans tinted, exactly as the swipe view hears a sound. The row's
 * length is drawn as a bar against the longest sound in the set — a length,
 * not a number.
 */
function Picker({
  rows,
  onChoose,
  onClose,
}: {
  rows: FileRow[];
  onChoose(row: FileRow): void;
  onClose(): void;
}) {
  const player = usePlayer();
  const [highlight, setHighlight] = useState<FileRow | null>(null);
  const [spans, setSpans] = useState<Span[]>([]);

  const longest = useMemo(() => rows.reduce((m, r) => Math.max(m, r.duration_s ?? 0), 0), [rows]);
  const isCurrent = highlight !== null && player.current?.hash === highlight.hash;

  useEffect(() => {
    if (!highlight) {
      setSpans([]);
      return;
    }
    const controller = new AbortController();
    setSpans([]);
    fetchSpans(highlight.hash, undefined, controller.signal)
      .then(setSpans)
      .catch(() => setSpans([]));
    return () => controller.abort();
  }, [highlight]);

  const hear = (row: FileRow) => {
    setHighlight(row);
    if (player.current?.hash === row.hash) {
      player.toggle();
      return;
    }
    player.play(row);
  };

  // Leaving the picker leaves the preview behind. There is no player bar on
  // this view to stop it from, so it stops here.
  const leave = (then?: () => void) => {
    if (player.playing) player.toggle();
    onClose();
    then?.();
  };

  return (
    <div className="collage-sheet" role="dialog" aria-label="choose a sound" data-testid="collage-picker">
      <div className="collage-sheet-head">
        <span className="collage-sheet-title">choose a sound</span>
        <button
          type="button"
          className="collage-sheet-close"
          aria-label="close"
          data-testid="picker-close"
          onClick={() => leave()}
        >
          ✕
        </button>
      </div>

      {highlight ? (
        <div className="collage-preview" data-testid="picker-preview" data-hash={highlight.hash}>
          <Waveform
            pairs={isCurrent ? (player.peaks?.pairs ?? []) : []}
            durationS={(isCurrent ? player.duration : 0) || highlight.duration_s}
            progressS={isCurrent ? player.time : 0}
            spans={spans}
            silence={isCurrent ? player.silentRegions : []}
            height={56}
            onSeek={(s) => (isCurrent ? player.seek(s) : undefined)}
            seekable={!highlight.transcoded}
            placeholder=""
          />
        </div>
      ) : null}

      <ul className="collage-pick-list" data-testid="picker-list">
        {rows.map((row) => {
          const share = longest > 0 ? Math.max(((row.duration_s ?? 0) / longest) * 100, 2) : 0;
          const playing = player.current?.hash === row.hash && player.playing;
          return (
            <li key={row.hash}>
              <button
                type="button"
                className={`collage-pick-row${highlight?.hash === row.hash ? " highlighted" : ""}`}
                data-testid="picker-row"
                data-hash={row.hash}
                data-playing={playing}
                aria-pressed={highlight?.hash === row.hash}
                onClick={() => hear(row)}
              >
                <span className="collage-pick-glyph" aria-hidden="true">
                  {playing ? "⏸" : "▶"}
                </span>
                <span className="collage-pick-body">
                  <span className="collage-pick-name">{row.filename}</span>
                  <span className="collage-len" aria-hidden="true">
                    <span className="collage-len-fill" style={{ width: `${share}%` }} />
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      <button
        type="button"
        className="collage-pick-use"
        data-testid="picker-use"
        disabled={highlight === null}
        onClick={() => {
          if (highlight) leave(() => onChoose(highlight));
        }}
      >
        {highlight ? (
          <>
            stamp this one
            <span className="collage-pick-use-sub">{highlight.filename}</span>
          </>
        ) : (
          "tap a sound to hear it"
        )}
      </button>
    </div>
  );
}

/* The view ----------------------------------------------------------------- */

export default function CollagePage() {
  const board = useBoard();
  const player = usePlayer();
  const project = collageProject(board.projects);

  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [regions, setRegions] = useState<Region[]>([]);
  /** Earlier arrangements, newest last, so a change can be taken back. */
  const [history, setHistory] = useState<Region[][]>([]);
  const [chosen, setChosen] = useState<FileRow | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [hint, setHint] = useState<string | null>(null);
  const [save, setSave] = useState<SaveState>("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [playError, setPlayError] = useState<string | null>(null);
  const [sources, setSources] = useState<Map<string, SourceData>>(() => new Map());
  const [selected, setSelected] = useState<Selection | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [mode, setMode] = useState<Mode>("trim");
  const [band, setBand] = useState<SnipBand | null>(null);
  const [balancing, setBalancing] = useState<Balancing | null>(null);
  const [repeating, setRepeating] = useState<Repeating | null>(null);
  const [moving, setMoving] = useState<Moving | null>(null);
  const [doomed, setDoomed] = useState<Doomed | null>(null);
  /**
   * The region on the clipboard, or null.
   *
   * A snapshot, not a reference: a copy taken from a region that is then
   * trimmed, moved, or removed with its track is still the copy that was
   * taken. Pasting it makes a new region with a new id and the same
   * everything else.
   */
  const [clipboard, setClipboard] = useState<Region | null>(null);
  const [piece, setPiece] = useState<Piece>("idle");
  /**
   * Whether the transport starts the piece again when it reaches the end.
   *
   * False on the first render whatever the machine remembers, because the
   * server renders this page too and it knows nothing about this machine: a
   * first render that disagreed with the server's would be a hydration
   * mismatch, which on this project is a failed test. The preference is read
   * a moment later, in an effect, which is a render the server never made.
   */
  const [loopPiece, setLoopPiece] = useState(false);
  /**
   * Which way the playhead has gone off the window, or null while it is on it.
   *
   * HW011 is thirty-six minutes, which is twenty-one thousand pixels; the line
   * leaves the bottom of a phone in under a minute. The canvas is never moved
   * for it — a canvas that scrolled itself would take the region out from
   * under a thumb in the middle of a trim — so instead there is a way back to
   * it, offered only while it is gone and taken only when it is tapped.
   */
  const [follow, setFollow] = useState<"above" | "below" | null>(null);

  const spaceRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const sliceRef = useRef<SlicePlayer | null>(null);
  const pieceRef = useRef<CollagePlayer | null>(null);
  const playheadRef = useRef<HTMLSpanElement | null>(null);
  /**
   * Where the playhead is, in seconds from the top of the piece.
   *
   * Kept in a ref and written straight to the element's transform, because
   * the line moves every frame and the canvas it moves over holds every
   * region's waveform. A render that happened mid-play — a trim, a stamp —
   * reads it back, so the line is drawn where it already was.
   */
  const elapsedRef = useRef(0);
  /** What `follow` holds, read from the frame loop without waiting for a render. */
  const followRef = useRef<"above" | "below" | null>(null);
  /**
   * What went wrong with the mix this pass, by region.
   *
   * `dropped` is a region whose slice the server would not give, with the
   * reason it gave; `late` is a region whose slice arrived after its moment.
   * Both are per region and both are counted, because "one region dropped
   * out" said over a piece that lost nine of fifteen is a lie a phone gives
   * no other way of catching.
   */
  const troubleRef = useRef<{ dropped: Map<string, string>; late: Set<string> }>({
    dropped: new Map(),
    late: new Set(),
  });
  /** The arrangement as the pointer handlers see it, without re-binding them. */
  const regionsRef = useRef<Region[]>([]);
  regionsRef.current = regions;
  /** Which region is being previewed on its own, read without re-binding. */
  const playingIdRef = useRef<string | null>(null);
  playingIdRef.current = playingId;

  /* Loading ----------------------------------------------------------------- */

  const projectId = project?.id ?? null;
  useEffect(() => {
    if (!projectId) {
      setDetail(null);
      setRegions([]);
      return;
    }
    const controller = new AbortController();
    setLoadError(null);
    fetchProject(projectId, controller.signal)
      .then((next) => {
        if (controller.signal.aborted) return;
        setDetail(next);
        setRegions(next?.collage?.regions ?? []);
        setHistory([]);
        setSelected(null);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setLoadError(err instanceof Error ? err.message : String(err));
      });
    return () => controller.abort();
  }, [projectId]);

  const rowsByHash = useMemo(() => {
    const map = new Map<string, FileRow>();
    for (const row of detail?.items ?? []) map.set(row.hash, row);
    return map;
  }, [detail]);

  /**
   * What each source looks like, fetched once per source however many
   * regions cut from it.
   *
   * Peaks, measured silence and spans, the three things already drawn on
   * every waveform. A source whose peaks cannot be fetched still gets an
   * entry, empty, so the region draws its box and nothing asks again.
   */
  const wantedRef = useRef<Set<string>>(new Set());
  const sourceAbortRef = useRef<AbortController | null>(null);
  useEffect(() => {
    // One controller for the life of the view. Leaving aborts every fetch in
    // flight; a stamp part-way through a fetch does not.
    const controller = new AbortController();
    sourceAbortRef.current = controller;
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const controller = sourceAbortRef.current;
    if (!controller) return;
    for (const hash of new Set(regions.map((r) => r.hash))) {
      if (wantedRef.current.has(hash)) continue;
      wantedRef.current.add(hash);
      void Promise.all([
        fetchPeaks(hash, controller.signal).catch(() => ({ pairs: [] as Array<[number, number]> })),
        fetchSilence(hash, MIN_GAP_S, controller.signal).catch(() => null),
        fetchSpans(hash, undefined, controller.signal).catch(() => [] as Span[]),
      ]).then(([peaks, silence, spans]) => {
        if (controller.signal.aborted) {
          // Forgotten, so a view mounted again asks again.
          wantedRef.current.delete(hash);
          return;
        }
        setSources((prev) => {
          const next = new Map(prev);
          next.set(hash, {
            pairs: peaks.pairs,
            silence: silence ? skippable(silence.intervals, MIN_GAP_S, silence.duration_s) : [],
            spans,
          });
          return next;
        });
      });
    }
  }, [regions]);

  /* Saving ------------------------------------------------------------------ */

  /**
   * Write the latest arrangement, one request at a time.
   *
   * Two changes in quick succession must not race: each write replaces the
   * whole description, so the later of two out-of-order arrivals would store
   * the older state. Writes are queued, and a queued write always sends what
   * is latest, so a burst of changes ends in one request carrying all of them.
   */
  const latestRef = useRef<Region[]>([]);
  const sentRef = useRef<Region[] | null>(null);
  const flushingRef = useRef(false);

  const flush = useCallback(async () => {
    if (flushingRef.current || !projectId) return;
    flushingRef.current = true;
    try {
      while (sentRef.current !== latestRef.current) {
        const sending = latestRef.current;
        setSave("saving");
        try {
          const result = await putCollage(projectId, sending);
          sentRef.current = sending;
          if (result === null) {
            setSave("absent");
          } else {
            setSave("saved");
            setSaveError(null);
          }
        } catch (err) {
          sentRef.current = sending;
          setSave("failed");
          setSaveError(err instanceof ApiRefusal ? err.detail : err instanceof Error ? err.message : String(err));
        }
      }
    } finally {
      flushingRef.current = false;
    }
  }, [projectId]);

  /**
   * Let a level be heard at once, wherever it is sounding.
   *
   * The piece ramps the voice it holds for that region; a region being
   * previewed on its own ramps too. Both are safe to ask when nothing is
   * sounding. This is what makes balance a gesture done by ear: the level
   * follows the thumb across the box rather than waiting for the next play.
   */
  const hearGain = useCallback((id: string, gain: number) => {
    pieceRef.current?.setGain(id, gain);
    if (playingIdRef.current === id) sliceRef.current?.setGain(gain);
  }, []);

  /**
   * A region whose material changed goes quiet for the rest of the pass; a
   * region whose level changed is heard at the new level at once.
   *
   * The piece is scheduled once, when play is tapped, and editing does not
   * reschedule it: a region cut or slowed under the ear would have to be
   * stopped and restarted mid-sound, and the rest of the mix would carry on
   * around the seam. So the rule is the one the single-region gesture already
   * uses — the sound being changed stops — applied to one voice of the mix
   * instead of to all of it. Everything untouched plays on. What was edited
   * is heard on the next play, which is one tap away.
   *
   * A level is the one thing that rule does not fit. Nothing about the
   * material moves, so there is no seam to make: the gain the voice already
   * runs through is ramped to the new value. And balance is set by ear against
   * the rest of the mix, so a gesture that silenced the region being balanced
   * would have taken away the only thing it was for.
   */
  const silenceEdited = useCallback(
    (was: readonly Region[], next: readonly Region[]) => {
      let quieted = false;
      // True when everything that went quiet went quiet by being taken away.
      // Nothing of it comes back on the next play, so the line that says so
      // has to say something else.
      let allGone = true;
      for (const before of was) {
        const now = next.find((r) => r.id === before.id);
        const same =
          now !== undefined &&
          now.hash === before.hash &&
          now.start_s === before.start_s &&
          now.end_s === before.end_s &&
          now.at_s === before.at_s &&
          now.rate === before.rate &&
          // How many times it comes round is how long it lasts, so a repeat
          // taken away or added under the ear leaves a voice already
          // scheduled to sound past the region's new end, or to stop short
          // of it. That is a change to the material's extent and it goes
          // quiet like every other one.
          loopsOf(now) === loopsOf(before);
        if (same && now.gain === before.gain) continue;
        if (same) {
          hearGain(before.id, now.gain);
          continue;
        }
        if (pieceRef.current?.silence(before.id)) {
          quieted = true;
          if (now !== undefined) allGone = false;
        }
      }
      // A region that goes quiet looks exactly like a region that has ended,
      // and on a phone the block that stopped is usually under the thumb that
      // stopped it. Saying it is the difference between a rule and a fault.
      if (quieted) setHint(allGone ? GONE_HINT : QUIET_HINT);
    },
    [hearGain],
  );

  const commitRegions = useCallback(
    (next: Region[]) => {
      silenceEdited(regionsRef.current, next);
      setRegions(next);
      regionsRef.current = next;
      latestRef.current = next;
      void flush();
    },
    [flush, silenceEdited],
  );

  /**
   * A change: what was there goes on the undo stack, and the new arrangement
   * is written.
   *
   * A track the change emptied closes up here, in the same step, so no
   * gesture has to remember to do it and none of them can disagree. It is one
   * change and one undo step: the stack holds the arrangement as it was,
   * regions and numbering together, so taking it back puts both back at once.
   * Undo itself does not come through here, which is what keeps it exact.
   */
  const change = useCallback(
    (next: Region[]) => {
      // Read now, not inside the updater: by the time the updater runs the
      // ref already holds what replaced this.
      const was = regionsRef.current;
      setHistory((h) => [...h, was].slice(-UNDO_DEPTH));
      commitRegions(closeEmptyTracks(next));
    },
    [commitRegions],
  );

  /* Playing a region -------------------------------------------------------- */

  const stopRegion = useCallback(() => {
    sliceRef.current?.stop();
    setPlayingId(null);
    setProgress(0);
  }, []);

  const toggleRegion = useCallback(
    (region: Region) => {
      if (playingId === region.id) {
        stopRegion();
        return;
      }
      // One thing at a time. A preview left running in the picker would
      // otherwise play under the region.
      if (player.playing) player.toggle();
      setPlayError(null);
      if (!sliceRef.current) sliceRef.current = new SlicePlayer();
      const started = sliceRef.current.play(region, {
        onProgress: setProgress,
        onEnd: () => {
          setPlayingId(null);
          setProgress(0);
        },
        onError: (message) => {
          setPlayingId(null);
          setProgress(0);
          setPlayError(`could not play that region: ${message}`);
        },
      });
      if (!started) {
        setPlayError("could not play that region: this browser cannot play audio this way");
        return;
      }
      setPlayingId(region.id);
      setProgress(0);
    },
    [playingId, player, stopRegion],
  );

  /* Playing the piece ------------------------------------------------------- */

  const stopPiece = useCallback(() => {
    pieceRef.current?.stop();
    elapsedRef.current = 0;
    followRef.current = null;
    setFollow(null);
    setPiece("idle");
    // Whatever the last pass went quiet about is over with the pass.
    setHint((was) => (isQuietHint(was) ? null : was));
  }, []);

  /**
   * Bring the canvas to the line, once and only when asked.
   *
   * The line is put in the middle of the window rather than at its edge, so
   * what is about to sound is in view as well as what just did.
   */
  const goToLine = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const y = TOP_PAD + elapsedRef.current * PX_PER_S;
    const furthest = Math.max(0, canvas.scrollHeight - canvas.clientHeight);
    canvas.scrollTo({ top: Math.max(0, Math.min(furthest, y - canvas.clientHeight / 2)) });
    followRef.current = null;
    setFollow(null);
  }, []);

  /**
   * What the mix lost this pass, said in one line and counted.
   *
   * A region that dropped out is silent for good; a region that fell behind
   * is sounding, late. Neither is visible on the canvas — a region that goes
   * quiet looks exactly like a region that ended — so both are said here.
   */
  const sayTrouble = useCallback(() => {
    const { dropped, late } = troubleRef.current;
    const many = (n: number) => (n === 1 ? "one region" : `${formatCount(n)} regions`);
    const parts: string[] = [];
    if (dropped.size > 0) {
      const reason = Array.from(dropped.values()).pop();
      parts.push(`${many(dropped.size)} dropped out of the mix: ${reason}`);
    }
    if (late.size > 0) {
      parts.push(`${many(late.size)} fell behind the piece: the sound arrived after its moment, so it plays late.`);
    }
    setPlayError(parts.length > 0 ? parts.join(" · ") : null);
  }, []);

  /**
   * Play the whole collage from the top, or stop it.
   *
   * Every region is scheduled at its own moment, at its own rate, through one
   * destination that sums them. Play starts at the top; there is no play from
   * a tapped point. The tap itself is the user gesture iOS requires, and the
   * context is resumed inside it.
   *
   * One thing sounds at a time: a region being previewed, or a sound left
   * playing in the picker, stops before the piece begins.
   */
  /**
   * Whether a pass that plays out should be followed by another.
   *
   * Read from a ref rather than from the state, because the handler that asks
   * was made when the pass was scheduled and would otherwise be holding
   * whatever the preference was then. Turning the loop on part-way through a
   * pass loops that pass; turning it off part-way lets it be the last one.
   */
  const loopPieceRef = useRef(false);
  loopPieceRef.current = loopPiece;
  /** Start the piece again from the top, as the loop needs it to be called. */
  const againRef = useRef<() => void>(() => {});

  const startPiece = useCallback(() => {
    const playable = regionsRef.current.filter((region) => rowsByHash.has(region.hash));
    if (playable.length === 0) {
      setPlayError("nothing here can be played: the index does not resolve these sounds.");
      return;
    }
    if (player.playing) player.toggle();
    stopRegion();
    setPlayError(null);
    setHint((was) => (isQuietHint(was) ? null : was));
    if (!pieceRef.current) pieceRef.current = new CollagePlayer();
    elapsedRef.current = 0;
    followRef.current = null;
    setFollow(null);
    troubleRef.current = { dropped: new Map(), late: new Set() };
    const started = pieceRef.current.play(playable, {
      onStart: () => setPiece("playing"),
      onElapsed: (elapsedS) => {
        elapsedRef.current = elapsedS;
        const line = playheadRef.current;
        if (line) line.style.transform = `translateY(${TOP_PAD + elapsedS * PX_PER_S}px)`;
        // Whether the line is still on the window. Read every frame and
        // written only when the answer changes, so a scroll under a thumb is
        // noticed at once and nothing re-renders while it is not.
        const canvas = canvasRef.current;
        if (canvas) {
          const y = TOP_PAD + elapsedS * PX_PER_S;
          const where =
            y < canvas.scrollTop ? "above" : y > canvas.scrollTop + canvas.clientHeight ? "below" : null;
          if (where !== followRef.current) {
            followRef.current = where;
            setFollow(where);
          }
        }
      },
      // The piece has played out. The line goes back to the top by leaving:
      // there is nothing on the canvas again but the regions.
      //
      // Unless the transport is looping, in which case it goes back to the
      // top by starting again. That is a fresh pass and not a continuation:
      // every region's first piece is fetched again, so there is a breath
      // between the end and the next beginning and the transport says
      // `loading…` during it. Looping the transport is how the piece is
      // listened to, so a breath at the seam is a cost the listening pays;
      // a region's own repeats have no seam at all, which is the difference
      // between a thing in the piece and a thing around it.
      onEnd: () => {
        elapsedRef.current = 0;
        followRef.current = null;
        setFollow(null);
        setPiece("idle");
        if (loopPieceRef.current && regionsRef.current.length > 0) againRef.current();
      },
      onError: (message) => {
        elapsedRef.current = 0;
        followRef.current = null;
        setFollow(null);
        setPiece("idle");
        setPlayError(`could not play the collage: ${message}`);
      },
      onRegionError: (id, message) => {
        troubleRef.current.dropped.set(id, message);
        sayTrouble();
      },
      onRegionLate: (id) => {
        troubleRef.current.late.add(id);
        sayTrouble();
      },
    });
    if (!started) {
      setPlayError("this browser cannot play audio this way");
      return;
    }
    setPiece("loading");
  }, [player, rowsByHash, sayTrouble, stopRegion]);
  againRef.current = startPiece;

  /** Play the whole collage from the top, or stop it. */
  const togglePiece = useCallback(() => {
    if (piece !== "idle") {
      stopPiece();
      return;
    }
    startPiece();
  }, [piece, startPiece, stopPiece]);

  /**
   * Remember the transport's loop, and read it back on the next visit.
   *
   * A machine that cannot store it — a private window that refuses, an old
   * WebView — loses the setting and nothing else: the toggle still works for
   * as long as the page is open, which is what it is for.
   */
  useEffect(() => {
    try {
      if (window.localStorage.getItem(LOOP_PREFERENCE) === "on") setLoopPiece(true);
    } catch {
      /* no storage on this machine */
    }
  }, []);

  const toggleLoopPiece = useCallback(() => {
    setLoopPiece((was) => {
      const next = !was;
      try {
        window.localStorage.setItem(LOOP_PREFERENCE, next ? "on" : "off");
      } catch {
        /* no storage on this machine */
      }
      return next;
    });
  }, []);

  // Leaving the view stops the region and the piece, and releases both audio
  // contexts, so nothing keeps sounding from a view that is gone. The shared
  // player is left alone; it belongs to every view.
  useEffect(() => {
    return () => {
      sliceRef.current?.close();
      sliceRef.current = null;
      pieceRef.current?.close();
      pieceRef.current = null;
    };
  }, []);

  /* Taps -------------------------------------------------------------------- */

  /**
   * A tap is a pointer going down and coming up on the same thing without
   * travelling. Read from the pointer events, not from `click`.
   *
   * WebKit synthesises a tap's click at a point of its own choosing: it looks
   * around the finger for the best target and moves the click there. Beside
   * a thumb-sized handle, a region ten pixels tall never wins, and a tap
   * squarely inside it selects the handle instead. The pointer events carry
   * the finger's true position and true target, so taps are read from those.
   * A pan ends in `pointercancel`, never `pointerup`, so a scroll cannot read
   * as a tap.
   */
  const tapRef = useRef<{ id: number; x: number; y: number; on: EventTarget } | null>(null);
  const beginTap = useCallback((event: React.PointerEvent) => {
    tapRef.current = { id: event.pointerId, x: event.clientX, y: event.clientY, on: event.currentTarget };
  }, []);
  const endTap = useCallback((event: React.PointerEvent): boolean => {
    const began = tapRef.current;
    tapRef.current = null;
    return (
      began !== null &&
      began.id === event.pointerId &&
      began.on === event.currentTarget &&
      Math.hypot(event.clientX - began.x, event.clientY - began.y) < TAP_SLOP
    );
  }, []);
  const dropTap = useCallback(() => {
    tapRef.current = null;
  }, []);

  /**
   * Open the picker, and stop the piece first.
   *
   * The picker is a sheet over the whole screen, and tapping a row in it
   * plays that sound. One thing sounds at a time, and auditioning a source
   * against a piece still sounding under the sheet is two.
   */
  const openPicker = useCallback(() => {
    stopPiece();
    setPickerOpen(true);
  }, [stopPiece]);

  /* Stamping ---------------------------------------------------------------- */

  const onCanvasTap = useCallback(
    (clientX: number, clientY: number) => {
      const space = spaceRef.current;
      if (!space || !detail) return;
      // A tap on the blank puts down whatever was taken up. With a sound
      // chosen it stamps as well: every tap on a region takes that region
      // up, so a tap that only let go would make the stamp after every
      // listen a dead tap. Undo takes back a stamp that was not meant.
      const wasUp = selected !== null && regions.some((r) => r.id === selected.id);
      if (wasUp) setSelected(null);
      // In snip or stretch mode the blank only lets go. Stamping belongs to
      // the default mode, where the bar says what a tap on the blank does;
      // here the bar says which mode is on, and a stray tap must not stamp
      // a whole source. Letting go of the handle is the end of stretch.
      if (mode !== "trim") return;
      if (!chosen && !clipboard) {
        if (wasUp) return;
        setHint("choose a sound first, then tap the blank to stamp it");
        openPicker();
        return;
      }
      const rect = space.getBoundingClientRect();
      const x = clientX - rect.left;
      const y = clientY - rect.top;
      // A copy on the clipboard is what this tap puts down, ahead of any
      // sound still chosen in the picker: the copy was armed last, the bar
      // says so where the chosen sound is usually named, and one tap is all
      // it is for. The clipboard empties with it, so the tap after this one
      // means what it meant before.
      const region = clipboard
        ? paste(regions, clipboard, x, y)
        : stamp(regions, chosen!.hash, chosen!.duration_s ?? 0, x, y);
      const next = [...regions, region];
      if (clipboard) setClipboard(null);
      setHint(null);
      change(next);
      // The first stamp starts time at zero wherever the thumb was, so the
      // canvas goes to the top to show it.
      const canvas = canvasRef.current;
      if (regions.length === 0) {
        canvas?.scrollTo({ top: 0, left: 0 });
        return;
      }
      // A stamp can land somewhere the thumb was not: slid down past a
      // neighbour, or on a new track whose column is mostly past the right
      // edge of a phone. What was just made has to be on screen.
      if (canvas) {
        const box = regionBox(region);
        const right = box.left + box.width;
        const bottom = box.top + Math.min(box.height, HANDLE_H);
        const left = right > canvas.scrollLeft + canvas.clientWidth ? right - canvas.clientWidth : canvas.scrollLeft;
        const top = bottom > canvas.scrollTop + canvas.clientHeight ? bottom - canvas.clientHeight : canvas.scrollTop;
        if (left !== canvas.scrollLeft || top !== canvas.scrollTop) canvas.scrollTo({ left, top });
      }
    },
    [detail, chosen, clipboard, regions, selected, mode, change, openPicker],
  );

  const undo = useCallback(() => {
    if (history.length === 0) return;
    const previous = history[history.length - 1];
    stopRegion();
    // What was taken up stays up if it is still there, so a trim taken back
    // can be tried again from the same handle. A region undone out of
    // existence takes its selection with it on the next render.
    setHistory((h) => h.slice(0, -1));
    commitRegions(previous);
  }, [history, commitRegions, stopRegion]);

  /* Trimming ---------------------------------------------------------------- */

  /**
   * The drag, as the pointer handlers see it.
   *
   * Kept in a ref rather than state so a move does not have to wait for a
   * render to know where it started. `lastY` is where the thumb is now; the
   * canvas may scroll under it, so the offset is worked out fresh each time
   * from the thumb and the scroll together.
   */
  const dragRef = useRef<{
    id: string;
    end: End;
    kind: DragKind;
    pointerId: number;
    originY: number;
    originScroll: number;
    lastY: number;
    region: Region;
    durationS: number | null;
    /** The region as it would be if the thumb lifted now. */
    preview: Region;
  } | null>(null);
  const scrollFrameRef = useRef(0);

  const previewFromPointer = useCallback(() => {
    const d = dragRef.current;
    const canvas = canvasRef.current;
    if (!d) return;
    const dy = d.lastY - d.originY + ((canvas?.scrollTop ?? 0) - d.originScroll);
    let stopped: StretchStop = null;
    if (d.kind === "stretch") {
      // The same drag as a trim, read the other way: the thumb asks for a
      // length, and the rate follows. The cut does not move.
      const wanted = stretchedTo(d.region, d.end, dy);
      d.preview = stretch(d.region, regionsRef.current, d.end, wanted);
      stopped = stretchStop(d.region, regionsRef.current, d.end, wanted);
    } else {
      d.preview = trim(d.region, regionsRef.current, d.durationS, d.end, draggedTo(d.region, d.end, dy));
    }
    setDrag({ id: d.id, end: d.end, kind: d.kind, preview: d.preview, stopped });
  }, []);

  /**
   * The snip, as the pointer handlers see it.
   *
   * The same shape as a trim drag, with the thumb's place measured down the
   * region's box rather than from a handle: `originOffset` is where the thumb
   * landed inside the box, and the span runs from there to where it is now.
   * `result` is what would replace the region if the thumb lifted now.
   */
  const snipRef = useRef<{
    region: Region;
    pointerId: number;
    originY: number;
    originScroll: number;
    originOffset: number;
    lastY: number;
    result: ReturnType<typeof snip>;
    /** The wait a whole band has to survive before a lift removes the region. */
    hold: Hold;
  } | null>(null);

  const bandFromPointer = useCallback(() => {
    const s = snipRef.current;
    const canvas = canvasRef.current;
    if (!s) return;
    const offset = s.originOffset + (s.lastY - s.originY) + ((canvas?.scrollTop ?? 0) - s.originScroll);
    s.result = snip(s.region, regionsRef.current, sourceAt(s.region, s.originOffset), sourceAt(s.region, offset));
    const whole = s.result !== null && s.result.result.length === 0;
    // The hold. It begins when the band becomes whole and the thumb stops,
    // and begins again if the thumb moves a tap's worth; a band that stops
    // being whole disarms at once. The canvas scrolling under a still thumb
    // does not move the thumb, so a hold at the screen's edge still counts.
    if (whole) s.hold.keep(s.lastY);
    else s.hold.cancel();
    if (!s.result) {
      setBand(null);
      return;
    }
    // The band is the span that will go, after any run to an edge: what is
    // striped is exactly what a lift would remove, never less.
    const top = offsetOf(s.region, s.result.from_s);
    const bottom = offsetOf(s.region, s.result.to_s);
    setBand({ id: s.region.id, top, height: bottom - top, whole, armed: s.hold.armed });
  }, []);

  /**
   * The move, as the pointer handlers see it.
   *
   * Both axes are read, because both mean something: down the screen is when
   * the region sounds and across it is which track it is on. The canvas may
   * scroll under the thumb either way, so the travel is measured against the
   * canvas and not against the glass. `preview` is where a lift would put it,
   * which is where the box is drawn while the thumb holds it.
   */
  const moveRef = useRef<{
    region: Region;
    pointerId: number;
    originX: number;
    originY: number;
    originTop: number;
    originLeft: number;
    lastX: number;
    lastY: number;
    /** True once the thumb has travelled far enough that this is a move and not a tap. */
    started: boolean;
    preview: Region;
  } | null>(null);

  const updateMove = useCallback(() => {
    const m = moveRef.current;
    const canvas = canvasRef.current;
    if (!m) return;
    const dx = m.lastX - m.originX + ((canvas?.scrollLeft ?? 0) - m.originLeft);
    const dy = m.lastY - m.originY + ((canvas?.scrollTop ?? 0) - m.originTop);
    m.preview = moveTo(m.region, regionsRef.current, dx, dy);
    setMoving({
      id: m.region.id,
      track: m.preview.track,
      at_s: m.preview.at_s,
      stopped: moveStop(m.region, regionsRef.current, dx, dy),
    });
  }, []);

  /**
   * Scroll the canvas while the thumb sits at its edge.
   *
   * A source stamped whole is several screens tall, and the sound in it can
   * be anywhere. Holding the handle at the bottom of the screen carries on
   * down through the region, so one drag can reach it. A snip's thumb scrolls
   * the same way, and so does a move — which also carries the canvas sideways,
   * because the track being moved to may be off the side of a phone.
   */
  const scrollAtEdge = useCallback(() => {
    const step = () => {
      const y = dragRef.current?.lastY ?? snipRef.current?.lastY ?? moveRef.current?.lastY;
      const canvas = canvasRef.current;
      if (y === undefined || !canvas) {
        scrollFrameRef.current = 0;
        return;
      }
      const rect = canvas.getBoundingClientRect();
      let by = 0;
      if (y < rect.top + SCROLL_EDGE) by = -SCROLL_STEP;
      else if (y > rect.bottom - SCROLL_EDGE) by = SCROLL_STEP;
      // Sideways is a move's business alone: a trim and a snip run down the
      // screen, and carrying the canvas across under either of them would
      // take the region out from under the thumb for nothing.
      const x = moveRef.current?.lastX;
      let across = 0;
      if (x !== undefined) {
        if (x < rect.left + SCROLL_EDGE) across = -SCROLL_STEP;
        else if (x > rect.right - SCROLL_EDGE) across = SCROLL_STEP;
      }
      if (by === 0 && across === 0) {
        scrollFrameRef.current = 0;
        return;
      }
      const before = canvas.scrollTop;
      const beforeLeft = canvas.scrollLeft;
      canvas.scrollTop = Math.max(0, Math.min(canvas.scrollHeight - canvas.clientHeight, before + by));
      canvas.scrollLeft = Math.max(0, Math.min(canvas.scrollWidth - canvas.clientWidth, beforeLeft + across));
      if (canvas.scrollTop !== before || canvas.scrollLeft !== beforeLeft) {
        previewFromPointer();
        bandFromPointer();
        updateMove();
      }
      scrollFrameRef.current = requestAnimationFrame(step);
    };
    if (!scrollFrameRef.current) scrollFrameRef.current = requestAnimationFrame(step);
  }, [previewFromPointer, bandFromPointer, updateMove]);

  const endDrag = useCallback(
    (apply: boolean) => {
      const d = dragRef.current;
      dragRef.current = null;
      if (scrollFrameRef.current) cancelAnimationFrame(scrollFrameRef.current);
      scrollFrameRef.current = 0;
      setDrag(null);
      if (!apply || !d) return;
      const was = regionsRef.current.find((r) => r.id === d.id);
      if (
        !was ||
        (was.start_s === d.preview.start_s &&
          was.end_s === d.preview.end_s &&
          was.rate === d.preview.rate &&
          was.at_s === d.preview.at_s)
      ) {
        return;
      }
      // One write per drag, carrying the whole arrangement.
      change(regionsRef.current.map((r) => (r.id === d.id ? d.preview : r)));
      // A finished stretch is the end of stretch mode: the handle is still
      // selected, so the button brings it back for another. The box's
      // dragged end is drawn where the thumb is either way — stretching the
      // start moves `at_s` up to the thumb — so nothing has to scroll.
      if (d.kind === "stretch") {
        setMode("trim");
        return;
      }
      // Trimming the start keeps the region where it sounds, so the cut the
      // thumb just made is about to be drawn at the top of the box, not
      // where the thumb is. The canvas moves by the same distance, so the
      // handle stays under the thumb instead of jumping away from it.
      const canvas = canvasRef.current;
      if (d.end === "start" && canvas) {
        const offset = dragOffsetPx(was, d.preview, "start");
        canvas.scrollTop = Math.max(0, canvas.scrollTop - offset);
      }
    },
    [change],
  );

  const startDrag = useCallback(
    (event: React.PointerEvent<HTMLDivElement>, region: Region, end: End) => {
      const canvas = canvasRef.current;
      event.preventDefault();
      event.stopPropagation();
      try {
        event.currentTarget.setPointerCapture(event.pointerId);
      } catch {
        /* a pointer that has already gone */
      }
      // The slice being played is the cut, or the rate, being changed. It
      // stops, so what is heard next is what the drag made.
      if (playingId === region.id) stopRegion();
      const kind: DragKind = mode === "stretch" ? "stretch" : "trim";
      dragRef.current = {
        id: region.id,
        end,
        kind,
        pointerId: event.pointerId,
        originY: event.clientY,
        originScroll: canvas?.scrollTop ?? 0,
        lastY: event.clientY,
        region,
        durationS: rowsByHash.get(region.hash)?.duration_s ?? null,
        preview: region,
      };
      setDrag({ id: region.id, end, kind, preview: region, stopped: null });
    },
    [mode, playingId, rowsByHash, stopRegion],
  );

  const moveDrag = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const d = dragRef.current;
      if (!d || d.pointerId !== event.pointerId) return;
      event.preventDefault();
      d.lastY = event.clientY;
      previewFromPointer();
      scrollAtEdge();
    },
    [previewFromPointer, scrollAtEdge],
  );

  /* Snipping ---------------------------------------------------------------- */

  /**
   * Let go of a snip. Applied, it is one change: the region is replaced by
   * what the snip left, the mode goes back to trim, and the first thing left
   * is taken up so its handles are live at once. Not applied, nothing moves.
   *
   * A drag that would cut nothing, or that would take the whole region
   * without the thumb having held on it, changes nothing and leaves snip on:
   * the button said one snip, and none was made yet. The second case says
   * so under the canvas, because the band that would have said it was under
   * the thumb.
   */
  const endSnip = useCallback(
    (apply: boolean) => {
      const s = snipRef.current;
      snipRef.current = null;
      // Read before letting go of the hold: giving up on it disarms it.
      const armed = s?.hold.armed ?? false;
      s?.hold.cancel();
      if (scrollFrameRef.current) cancelAnimationFrame(scrollFrameRef.current);
      scrollFrameRef.current = 0;
      setBand(null);
      if (!apply || !s) return;
      const result = s.result;
      if (!result) return;
      if (result.result.length === 0 && !armed) {
        setHint(SNIP_HOLD_HINT);
        return;
      }
      const was = regionsRef.current;
      const index = was.findIndex((r) => r.id === s.region.id);
      if (index < 0) return;
      // A snip is a change, and a finished snip is the end of snip mode.
      setMode("trim");
      setHint(null);
      // The slice being played is the cut being changed. It stops.
      if (playingId === s.region.id) stopRegion();
      const next = [...was.slice(0, index), ...result.result, ...was.slice(index + 1)];
      change(next);
      const first = result.result[0];
      setSelected(first ? { id: first.id, end: null } : null);
    },
    [change, playingId, stopRegion],
  );

  const startSnip = useCallback(
    (event: React.PointerEvent<HTMLDivElement>, region: Region) => {
      // One snip at a time. A second finger down while one is snipping is
      // not a second snip.
      if (snipRef.current || dragRef.current) return;
      const canvas = canvasRef.current;
      event.preventDefault();
      event.stopPropagation();
      try {
        event.currentTarget.setPointerCapture(event.pointerId);
      } catch {
        /* a pointer that has already gone */
      }
      const rect = event.currentTarget.getBoundingClientRect();
      snipRef.current = {
        region,
        pointerId: event.pointerId,
        originY: event.clientY,
        originScroll: canvas?.scrollTop ?? 0,
        originOffset: event.clientY - rect.top,
        lastY: event.clientY,
        result: null,
        // The band fills over the wait, so the arming has to reach the screen
        // the moment it finishes rather than on the next thumb movement — a
        // thumb that has stopped sends nothing.
        hold: new Hold(() =>
          setBand((was) => (was && was.id === region.id && was.whole ? { ...was, armed: true } : was)),
        ),
      };
    },
    [],
  );

  const moveSnip = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const s = snipRef.current;
      if (!s || s.pointerId !== event.pointerId) return;
      event.preventDefault();
      s.lastY = event.clientY;
      bandFromPointer();
      scrollAtEdge();
    },
    [bandFromPointer, scrollAtEdge],
  );

  /* Moving ------------------------------------------------------------------ */

  /**
   * Let go of a move. Applied, it is one change and one undo step: the region
   * lands where the box was drawn, which is where the thumb asked for it or
   * just after whatever was already there. Not applied — a drag the browser
   * took the pointer away from, or one that came back to where it began —
   * nothing is written.
   *
   * Only `track` and `at_s` move. The cut, the rate, the level and the fades
   * are not in reach of this gesture: a move is the one gesture that cannot
   * change what a region is, only where it is.
   */
  const endMove = useCallback(
    (apply: boolean) => {
      const m = moveRef.current;
      moveRef.current = null;
      if (scrollFrameRef.current) cancelAnimationFrame(scrollFrameRef.current);
      scrollFrameRef.current = 0;
      setMoving(null);
      if (!apply || !m) return;
      const was = regionsRef.current.find((r) => r.id === m.region.id);
      if (!was || (was.track === m.preview.track && was.at_s === m.preview.at_s)) return;
      const { track, at_s } = m.preview;
      change(regionsRef.current.map((r) => (r.id === m.region.id ? { ...r, track, at_s } : r)));
    },
    [change],
  );

  /**
   * Take hold of the body of the region in hand.
   *
   * No mode: on the region taken up the handles mean trim and the body is
   * free. What the thumb does next decides which gesture this was — a lift
   * where it landed is the tap that plays the region, and travel is a move.
   * On a region not taken up the body is canvas and this is never reached.
   */
  const startMove = useCallback((event: React.PointerEvent<HTMLDivElement>, region: Region) => {
    // One gesture per thumb, and never on top of another thumb's.
    if (moveRef.current || balanceRef.current || repeatRef.current || snipRef.current || dragRef.current) return;
    const canvas = canvasRef.current;
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      /* a pointer that has already gone */
    }
    moveRef.current = {
      region,
      pointerId: event.pointerId,
      originX: event.clientX,
      originY: event.clientY,
      originTop: canvas?.scrollTop ?? 0,
      originLeft: canvas?.scrollLeft ?? 0,
      lastX: event.clientX,
      lastY: event.clientY,
      started: false,
      preview: region,
    };
  }, []);

  /** How far a move's thumb has travelled across the canvas, in pixels. */
  const moveTravel = useCallback((event: React.PointerEvent<HTMLDivElement>): number => {
    const m = moveRef.current;
    const canvas = canvasRef.current;
    if (!m) return 0;
    const dx = event.clientX - m.originX + ((canvas?.scrollLeft ?? 0) - m.originLeft);
    const dy = event.clientY - m.originY + ((canvas?.scrollTop ?? 0) - m.originTop);
    return Math.hypot(dx, dy);
  }, []);

  const whileMoving = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const m = moveRef.current;
      if (!m || m.pointerId !== event.pointerId) return;
      // Nothing moves until the thumb has travelled further than a tap. A
      // thumb that lands and shifts three pixels before lifting is choosing
      // to listen, not to rearrange, and a box sliding under it would say
      // otherwise. Past that the move is under way and stays under way, so a
      // thumb that comes back to where it started can still put the region
      // back exactly where it was.
      if (!m.started) {
        if (moveTravel(event) < TAP_SLOP) return;
        m.started = true;
      }
      event.preventDefault();
      m.lastX = event.clientX;
      m.lastY = event.clientY;
      updateMove();
      scrollAtEdge();
    },
    [moveTravel, scrollAtEdge, updateMove],
  );

  /* Balancing --------------------------------------------------------------- */

  /**
   * The balance, as the pointer handlers see it.
   *
   * Only `x` is read. Along the box is time and stays free; across it is the
   * level, so a thumb that wanders up and down while it drags sideways moves
   * nothing but the level, and `at_s` is not in reach of this gesture at all.
   * The canvas's sideways scroll is taken off the same way a trim takes off
   * its vertical one, so the drag is measured across the box rather than
   * across the glass.
   */
  const balanceRef = useRef<{
    region: Region;
    pointerId: number;
    originX: number;
    originScroll: number;
    lastX: number;
    /** The level the region would keep if the thumb lifted now. */
    gain: number;
  } | null>(null);

  const gainFromPointer = useCallback(() => {
    const b = balanceRef.current;
    const canvas = canvasRef.current;
    if (!b) return;
    const dx = b.lastX - b.originX + ((canvas?.scrollLeft ?? 0) - b.originScroll);
    const wanted = balancedTo(b.region, dx);
    b.gain = balance(b.region, wanted).gain;
    setBalancing({ id: b.region.id, gain: b.gain, stopped: gainStop(b.region, wanted) });
    // Heard as it moves, not on the lift. Balance is the one gesture whose
    // whole answer is what it sounds like against the rest.
    hearGain(b.region.id, b.gain);
  }, [hearGain]);

  /**
   * Let go of a balance. Applied, it is one change and one undo step, exactly
   * as a trim or a stretch is; the mode stays on, because a level is found by
   * going past it and coming back. A drag that left the level where it was,
   * or one the browser took the pointer away from, writes nothing — and what
   * the ear was given while it moved goes back to what the file holds.
   */
  const endBalance = useCallback(
    (apply: boolean) => {
      const b = balanceRef.current;
      balanceRef.current = null;
      setBalancing(null);
      if (!b) return;
      const was = regionsRef.current.find((r) => r.id === b.region.id);
      if (!apply || !was || was.gain === b.gain) {
        if (was) hearGain(was.id, was.gain);
        return;
      }
      // One write per drag, carrying the whole arrangement. Only `gain`
      // moves: whatever else happened to the region stays as it is.
      change(regionsRef.current.map((r) => (r.id === b.region.id ? { ...r, gain: b.gain } : r)));
    },
    [change, hearGain],
  );

  const startBalance = useCallback((event: React.PointerEvent<HTMLDivElement>, region: Region) => {
    // One balance at a time, and never on top of another gesture's thumb.
    if (balanceRef.current || repeatRef.current || snipRef.current || dragRef.current) return;
    const canvas = canvasRef.current;
    event.preventDefault();
    event.stopPropagation();
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      /* a pointer that has already gone */
    }
    balanceRef.current = {
      region,
      pointerId: event.pointerId,
      originX: event.clientX,
      originScroll: canvas?.scrollLeft ?? 0,
      lastX: event.clientX,
      gain: region.gain,
    };
  }, []);

  const moveBalance = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const b = balanceRef.current;
      if (!b || b.pointerId !== event.pointerId) return;
      event.preventDefault();
      b.lastX = event.clientX;
      gainFromPointer();
    },
    [gainFromPointer],
  );

  /* Repeating ---------------------------------------------------------------- */

  /**
   * The repeat, as the pointer handlers see it.
   *
   * Only `y` is read: a repeat is added at the bottom of the box, so the
   * gesture runs the way the box grows. A thumb's height of travel is one
   * more repeat, the same movement on a ten-pixel region and on a nine
   * thousand pixel one. The canvas's own scroll is taken off, so the count
   * follows the thumb across the box rather than across the glass.
   */
  const repeatRef = useRef<{
    region: Region;
    pointerId: number;
    originY: number;
    originScroll: number;
    lastY: number;
    /** How many times the region would sound if the thumb lifted now. */
    loops: number;
  } | null>(null);

  const loopsFromPointer = useCallback(() => {
    const r = repeatRef.current;
    const canvas = canvasRef.current;
    if (!r) return;
    const dy = r.lastY - r.originY + ((canvas?.scrollTop ?? 0) - r.originScroll);
    const wanted = loopedTo(r.region, dy);
    r.loops = loopsOf(repeat(r.region, regionsRef.current, wanted));
    setRepeating({
      id: r.region.id,
      loops: r.loops,
      stopped: loopStop(r.region, regionsRef.current, wanted),
    });
  }, []);

  /**
   * Let go of a repeat. Applied, it is one change and one undo step, exactly
   * as a stretch or a balance is; the mode stays on, because a count is found
   * by going past it and coming back, and because the repeats being counted
   * are only audible on the next play. A drag that left the count where it
   * was, or one the browser took the pointer away from, writes nothing.
   */
  const endRepeat = useCallback(
    (apply: boolean) => {
      const r = repeatRef.current;
      repeatRef.current = null;
      setRepeating(null);
      if (!apply || !r) return;
      const was = regionsRef.current.find((region) => region.id === r.region.id);
      if (!was || loopsOf(was) === r.loops) return;
      // One write per drag, carrying the whole arrangement. Only `loops`
      // moves: the cut, the rate, the level and the moment stay as they are.
      change(regionsRef.current.map((region) => (region.id === r.region.id ? { ...region, loops: r.loops } : region)));
    },
    [change],
  );

  const startRepeat = useCallback((event: React.PointerEvent<HTMLDivElement>, region: Region) => {
    // One repeat at a time, and never on top of another gesture's thumb.
    if (repeatRef.current || moveRef.current || balanceRef.current || snipRef.current || dragRef.current) return;
    const canvas = canvasRef.current;
    event.preventDefault();
    event.stopPropagation();
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      /* a pointer that has already gone */
    }
    repeatRef.current = {
      region,
      pointerId: event.pointerId,
      originY: event.clientY,
      originScroll: canvas?.scrollTop ?? 0,
      lastY: event.clientY,
      loops: loopsOf(region),
    };
  }, []);

  const moveRepeat = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const r = repeatRef.current;
      if (!r || r.pointerId !== event.pointerId) return;
      event.preventDefault();
      r.lastY = event.clientY;
      loopsFromPointer();
      // No edge scroll. The canvas walking under a still thumb would add a
      // repeat a frame, with nothing moving to say so; a drag reaches the
      // edge of the screen and stops, and the next drag carries on from the
      // count the last one left.
    },
    [loopsFromPointer],
  );

  /* Removing a track --------------------------------------------------------- */

  /**
   * The track being held towards removal, and the wait it has to survive.
   *
   * Removing a track takes every region on it, which is the only gesture on
   * this surface that takes more than one thing at once. So it is armed the
   * way a whole-region snip is, by the same `Hold`: the button has to be
   * pressed and kept pressed, and while it is the column and everything in it
   * is drawn in amber. A press that lets go early removes nothing and says
   * what would have.
   */
  const trackHoldRef = useRef<{ hold: Hold; track: number; pointerId: number } | null>(null);

  /**
   * Whether this pointer is the one holding the track button.
   *
   * A phone has more than one thumb, and a phone held in one hand is steadied
   * with the other. Without this, a second touch anywhere on the button
   * finishes the first thumb's hold on its own lift — taking a track and
   * everything on it — or, before the wait is up, throws away a hold the
   * first thumb is still patiently keeping. The destructive gesture belongs
   * to the thumb that armed it.
   */
  const holdingTrack = useCallback((pointerId: number): boolean => {
    const held = trackHoldRef.current;
    return held !== null && held.pointerId === pointerId;
  }, []);

  const endTrackHold = useCallback(
    (apply: boolean) => {
      const held = trackHoldRef.current;
      trackHoldRef.current = null;
      // Read before letting go of the hold: giving up on it disarms it.
      const armed = held?.hold.armed ?? false;
      held?.hold.cancel();
      setDoomed(null);
      if (!held || !apply) return;
      if (!armed) {
        setHint(TRACK_HOLD_HINT);
        return;
      }
      const was = regionsRef.current;
      const going = was.filter((region) => region.track === held.track);
      if (going.length === 0) return;
      // A region being previewed on its own is about to stop existing.
      if (playingIdRef.current !== null && going.some((region) => region.id === playingIdRef.current)) {
        stopRegion();
      }
      setHint(null);
      setSelected(null);
      setMode("trim");
      change(removeTrack(was, held.track));
    },
    [change, stopRegion],
  );

  const startTrackHold = useCallback(
    (at: number, pointerId: number) => {
      if (trackHoldRef.current) return;
      const region = selected ? regionsRef.current.find((r) => r.id === selected.id) : undefined;
      if (!region) return;
      // The thumb on this button is not the thumb that started anything else,
      // so whatever else was in flight is let go of without being applied.
      if (dragRef.current) endDrag(false);
      if (snipRef.current) endSnip(false);
      if (balanceRef.current) endBalance(false);
      if (repeatRef.current) endRepeat(false);
      if (moveRef.current) endMove(false);
      const track = region.track;
      const hold = new Hold(() =>
        setDoomed((was) => (was && was.track === track ? { ...was, armed: true } : was)),
      );
      trackHoldRef.current = { hold, track, pointerId };
      hold.keep(at);
      setDoomed({ track, armed: false });
      setHint(null);
    },
    [endBalance, endDrag, endMove, endRepeat, endSnip, selected],
  );

  /** The thumb is still on the button. Moving it a tap's worth starts the wait again. */
  const whileTrackHold = useCallback((at: number) => {
    const held = trackHoldRef.current;
    if (!held) return;
    held.hold.keep(at);
    setDoomed((was) => (was && was.armed !== held.hold.armed ? { ...was, armed: held.hold.armed } : was));
  }, []);

  /* Copying ------------------------------------------------------------------ */

  /**
   * Put the region taken up on the clipboard.
   *
   * Nothing is written and nothing on the canvas changes: what changes is what
   * the next tap on the blank will do. The bar says so where the sound being
   * stamped is usually named, and the same tap that cancels a mode cancels
   * this.
   */
  const copyRegion = useCallback(() => {
    const region = selected ? regionsRef.current.find((r) => r.id === selected.id) : undefined;
    if (!region) return;
    setClipboard(region);
    setHint("now tap the blank where the copy should go");
  }, [selected]);

  /**
   * Change mode. Never two at once: a drag in flight under the other mode is
   * let go without being applied, because the thumb that started it is not
   * the one that pressed the button.
   */
  const switchMode = useCallback(
    (next: Mode) => {
      if (dragRef.current) endDrag(false);
      if (snipRef.current) endSnip(false);
      if (balanceRef.current) endBalance(false);
      if (repeatRef.current) endRepeat(false);
      if (moveRef.current) endMove(false);
      setMode(next);
      // Whatever snip had to say is over with it.
      if (next === "trim") setHint((was) => (was === SNIP_HOLD_HINT ? null : was));
    },
    [endBalance, endDrag, endMove, endRepeat, endSnip],
  );

  // Snip is a gesture on a region. With none left, there is nothing for it
  // to be on: the mode ends, and the bar offers a sound to stamp again.
  const noRegions = regions.length === 0;
  useEffect(() => {
    if (noRegions && mode === "snip") setMode("trim");
  }, [noRegions, mode]);

  // Stretch is a gesture on a handle. It can only begin with one selected,
  // and once that handle is let go of — the blank tapped, another region
  // taken up, the region undone away — there is nothing for it to be on,
  // and the mode ends. A region cut from a sound the index cannot resolve
  // has no handles, so it cannot be stretched either.
  const handleUp =
    selected !== null &&
    selected.end !== null &&
    regions.some((r) => r.id === selected.id && rowsByHash.has(r.hash));
  useEffect(() => {
    if (mode === "stretch" && !handleUp) setMode("trim");
  }, [mode, handleUp]);

  // Balance is a gesture on a whole region, so it needs one taken up and
  // nothing more. Putting the region down — the blank tapped, Escape, the
  // region undone away — ends the mode; taking a *different* region up does
  // not, because balancing one voice against another is one job and a button
  // tap between them would be in the way. A region cut from a sound the index
  // cannot resolve is not drawn from any material, so it is left alone here
  // as it is by every other gesture.
  const regionUp =
    selected !== null && regions.some((r) => r.id === selected.id && rowsByHash.has(r.hash));
  useEffect(() => {
    if (mode === "balance" && !regionUp) setMode("trim");
  }, [mode, regionUp]);

  // Repeat is a gesture on a whole region too, and it asks the same thing:
  // one taken up, nothing more. It leaves the same way balance does, and it
  // stays on across taking another region up, because setting how many times
  // each of several regions comes round is one job.
  useEffect(() => {
    if (mode === "repeat" && !regionUp) setMode("trim");
  }, [mode, regionUp]);

  // Copying a region and removing its track ask nothing of the material: one
  // carries the row of numbers that describes a region, the other takes a
  // lane away. So they need a region taken up and nothing more, and a region
  // cut from a sound the index cannot resolve is as copyable as any other.
  const takenUp = selected !== null && regions.some((r) => r.id === selected.id);
  useEffect(() => {
    if (!takenUp && trackHoldRef.current) endTrackHold(false);
  }, [takenUp, endTrackHold]);

  // A hold never outlives the view.
  useEffect(() => {
    return () => {
      snipRef.current?.hold.cancel();
      trackHoldRef.current?.hold.cancel();
    };
  }, []);

  /**
   * Keep what was just taken up in view when the bar grows a row for it.
   *
   * The four gestures that are about one region arrive in the bar the moment
   * a region is taken up, and the bar takes that row off the bottom of the
   * canvas. A region tapped in the last inch of the screen would go behind
   * the bar with the tap that took it, so the tap would read as having done
   * nothing at all. The canvas comes down by however much is needed and never
   * by more, and never at any other time: a canvas that moved itself while a
   * thumb was working would be worse than the row it is making room for.
   */
  const upId = selected?.id ?? null;
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || upId === null) return;
    const region = regionsRef.current.find((r) => r.id === upId);
    if (!region) return;
    const box = regionBox(region);
    // A thumb's worth of the top of the box: what a tap on a short region
    // landed on, and what a tall region shows of itself first.
    const want = box.top + Math.min(box.height, HANDLE_H);
    const bottom = canvas.scrollTop + canvas.clientHeight;
    if (want <= bottom) return;
    const furthest = Math.max(0, canvas.scrollHeight - canvas.clientHeight);
    canvas.scrollTop = Math.min(furthest, canvas.scrollTop + (want - bottom));
  }, [upId]);

  // Turning the phone, or the browser taking the pointer for itself, ends the
  // drag without applying it: the thumb is no longer where the handle is.
  // Escape lets go of the handle on a keyboard, and of an armed paste.
  useEffect(() => {
    const onResize = () => {
      if (dragRef.current) endDrag(false);
      if (snipRef.current) endSnip(false);
      if (balanceRef.current) endBalance(false);
      if (repeatRef.current) endRepeat(false);
      if (moveRef.current) endMove(false);
      if (trackHoldRef.current) endTrackHold(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (dragRef.current) endDrag(false);
      if (snipRef.current) endSnip(false);
      if (balanceRef.current) endBalance(false);
      if (repeatRef.current) endRepeat(false);
      if (moveRef.current) endMove(false);
      if (trackHoldRef.current) endTrackHold(false);
      setClipboard(null);
      setSelected(null);
    };
    window.addEventListener("resize", onResize);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("resize", onResize);
      window.removeEventListener("keydown", onKey);
    };
  }, [endBalance, endDrag, endMove, endRepeat, endSnip, endTrackHold]);

  /**
   * A keyboard nudge: a tenth of a second, or a whole one with shift. In
   * trim mode that moves the cut; in stretch mode it moves the box's length
   * from the selected end, and the rate follows.
   */
  const nudge = useCallback(
    (region: Region, end: End, direction: 1 | -1, big: boolean) => {
      const rate = region.rate > 0 ? region.rate : 1;
      let next: Region;
      if (mode === "stretch") {
        const step = (big ? 1 : 0.1) * (end === "end" ? direction : -direction);
        next = stretch(region, regionsRef.current, end, regionLengthS(region) + step);
      } else {
        // A tenth of a second of the *box*, so the nudge is the same distance
        // on screen whether or not the region repeats: a cut on a region that
        // sounds four times grows the box four times over.
        const step = ((big ? 1 : 0.1) * rate * direction) / loopsOf(region);
        const t = (end === "start" ? region.start_s : region.end_s) + step;
        next = trim(region, regionsRef.current, rowsByHash.get(region.hash)?.duration_s ?? null, end, t);
      }
      if (
        next.start_s === region.start_s &&
        next.end_s === region.end_s &&
        next.rate === region.rate &&
        next.at_s === region.at_s
      ) {
        return;
      }
      if (playingId === region.id) stopRegion();
      change(regionsRef.current.map((r) => (r.id === region.id ? next : r)));
    },
    [change, mode, playingId, rowsByHash, stopRegion],
  );

  /* What is on screen ------------------------------------------------------- */

  if (board.status === "loading") return <div className="notice">loading…</div>;

  if (board.status === "absent") {
    return (
      <div className="collage-empty" data-testid="collage-absent">
        <p>
          projects are not being served: <code>/api/projects</code> answered “not here”, so there is no
          project to open.
        </p>
      </div>
    );
  }

  if (board.status === "error") {
    return (
      <div className="collage-empty" data-testid="collage-error">
        <p className="error">could not read the board: {board.error}</p>
      </div>
    );
  }

  if (!project) {
    return (
      <div className="collage-empty" data-testid="collage-none">
        <p>nothing is in collage.</p>
        <p className="dim">
          a project arrives here by being committed out of stored, which freezes its sound set. that is
          what makes cutting from it safe. <Link href="/board">the board</Link>.
        </p>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="collage-empty" data-testid="collage-error">
        <p className="error">could not open {project.name}: {loadError}</p>
      </div>
    );
  }

  if (!detail) return <div className="notice">loading…</div>;

  // The arrangement as it is drawn: the region being moved is at the place a
  // lift would put it, not the place the file still has it. The canvas is
  // sized from that, so a region carried onto the column beside the last
  // track has somewhere to be drawn while the thumb holds it there.
  //
  // The same goes for a region under a repeat: it is drawn at the count a
  // lift would write, so the box and its dividers grow under the thumb and
  // the canvas has room for them.
  const shownRegions = regions.map((r) => {
    if (moving && r.id === moving.id) return { ...r, track: moving.track, at_s: moving.at_s };
    if (repeating && r.id === repeating.id) return { ...r, loops: repeating.loops };
    return r;
  });
  const size = canvasSize(shownRegions);
  const tracks = trackCount(regions);
  const unresolved = regions.filter((r) => !rowsByHash.has(r.hash)).length;
  // A selection outlives the region it named only until the next render.
  const selection = selected && regions.some((r) => r.id === selected.id) ? selected : null;

  const saveLine = (() => {
    switch (save) {
      case "saving":
        return "saving…";
      case "saved":
        return "saved";
      case "failed":
        return `not saved: ${saveError ?? "the server refused"}`;
      case "absent":
        return "the server does not save collages yet. what is stamped here is lost on reload.";
      default:
        return collageRouteIsMissing() ? "the server does not save collages yet." : "";
    }
  })();

  return (
    <div
      className="collage"
      data-testid="collage"
      data-project-id={project.id}
      data-regions={regions.length}
      data-tracks={tracks}
      data-selected={selection ? (selection.end ? `${selection.id}:${selection.end}` : selection.id) : ""}
      data-dragging={drag !== null}
      data-mode={mode}
      data-snipping={band !== null}
      data-balancing={balancing !== null}
      data-repeating={repeating ? repeating.id : ""}
      data-piece-loop={loopPiece ? "on" : "off"}
      data-moving={moving ? moving.id : ""}
      data-doomed={doomed ? (doomed.armed ? "armed" : "holding") : ""}
      data-clipboard={clipboard ? clipboard.id : ""}
      data-piece={piece}
    >
      <div className="collage-head">
        <span className="collage-name" data-testid="collage-project">
          {project.name}
        </span>
        <span className="collage-count mono dim" data-testid="collage-count">
          {regions.length === 0
            ? "nothing stamped"
            : `${formatCount(regions.length)} ${regions.length === 1 ? "region" : "regions"} on ${formatCount(tracks)} ${tracks === 1 ? "track" : "tracks"}`}
        </span>
        {saveLine ? (
          <span className={`collage-save ${save}`} data-testid="collage-save" data-state={save}>
            {saveLine}
          </span>
        ) : null}
      </div>

      {unresolved > 0 ? (
        <div className="collage-note" data-testid="collage-unresolved">
          {formatCount(unresolved)} {unresolved === 1 ? "region cuts" : "regions cut"} from a sound the index no
          longer resolves. {unresolved === 1 ? "It is" : "They are"} drawn, and cannot be played, trimmed, snipped,
          stretched or balanced.
        </div>
      ) : null}

      {playError ? (
        <div className="error collage-note" data-testid="collage-play-error">
          {playError}
        </div>
      ) : null}

      {/* The canvas. Genuinely empty until something is stamped: no lanes, no
          ticks. It scrolls down through time and across through tracks. The
          stage around it exists only so the way back to the line can sit over
          it without scrolling away with it. */}
      <div className="collage-stage">
        <div className="collage-canvas" ref={canvasRef} data-testid="collage-canvas">
          <div
            className="collage-space"
            ref={spaceRef}
            data-testid="collage-space"
            style={{ width: size.width, height: size.height, minWidth: "100%", minHeight: "100%" }}
            onPointerDown={beginTap}
            onPointerUp={(event) => {
              if (endTap(event)) onCanvasTap(event.clientX, event.clientY);
            }}
            onPointerCancel={dropTap}
          >
            {/* Where the piece has got to. A line, not a number, and only while
                something is sounding: with the piece stopped the canvas holds
                nothing but its regions again. It moves down at the piece's own
                rate, so a region slowed to a quarter — four times as tall for
                the same material — takes four times as long to cross. */}
            {piece === "playing" ? (
              <span
                className="collage-playhead"
                data-testid="collage-playhead"
                ref={playheadRef}
                style={{ transform: `translateY(${TOP_PAD + elapsedRef.current * PX_PER_S}px)` }}
                aria-hidden="true"
              />
            ) : null}

            {/* The track a thumb is holding towards removal, and the column it
                fills. Amber, which on this surface means "this is what goes",
                and drawn only while the thumb holds the button: nothing per
                track exists otherwise, because a track is not a lane waiting
                to be filled. It takes no touch. */}
            {doomed ? (
              <span
                className={`collage-doomed${doomed.armed ? " armed" : ""}`}
                data-testid="collage-doomed"
                data-track={doomed.track}
                data-armed={doomed.armed}
                style={{ left: doomed.track * TRACK_W, width: TRACK_W, ["--hold-ms" as string]: `${HOLD_MS}ms` }}
                aria-hidden="true"
              />
            ) : null}

            {regions.map((region) => {
              const shifting = moving && moving.id === region.id ? moving : null;
              // How many times this block sounds, as it is drawn: what a lift
              // would write while a repeat is under way, and what the file
              // holds otherwise.
              const looping = repeating && repeating.id === region.id ? repeating : null;
              const shownLoops = looping ? looping.loops : loopsOf(region);
              const drawn: Region = {
                ...region,
                loops: shownLoops,
                ...(shifting ? { track: shifting.track, at_s: shifting.at_s } : {}),
              };
              const box = regionBox(drawn);
              // Where each repeat after the first begins, down the box. Empty
              // for a region that sounds once, which is every region until
              // this gesture is used on it.
              const dividers = repeatDividers(drawn);
              // One repeat's height: what the waveform is drawn at, and what
              // a snip band is repeated down the box by.
              const repeatPx = repeatLengthS(region) * PX_PER_S;
              const row = rowsByHash.get(region.hash);
              const source = sources.get(region.hash);
              const playing = playingId === region.id;
              const isSelectedRegion = selection?.id === region.id;
              const grab = grabZone(region, regions);
              const zones = handleZones(region);
              const dragging = drag && drag.id === region.id ? drag : null;
              const offset = dragging ? dragOffsetPx(region, dragging.preview, dragging.end) : 0;
              const snipBand = band && band.id === region.id ? band : null;
              // In snip mode a region's grab is where a snip begins, and only
              // there: the flanks and the blank still scroll, as they do under
              // a raised handle in trim mode.
              const snippable = mode === "snip" && row !== undefined;
              // Balance is on the region taken up, and on no other: the button
              // was pressed with that one in hand. Its grab is where the drag
              // across begins.
              const balanceable = mode === "balance" && isSelectedRegion && row !== undefined;
              // Repeat is on the region taken up, as balance is, and its
              // drag runs down the grab rather than across it.
              const repeatable = mode === "repeat" && isSelectedRegion && row !== undefined;
              // Move is not a mode and asks nothing of the material, but it
              // is a gesture on the region *in hand*, as stretch, balance,
              // copy and removing a track all are. A thumb on a region's body
              // is claimed by the move only once that region has been taken
              // up; on every other region the body is canvas, and canvas
              // scrolls.
              //
              // That is not a nicety. A thumb on this surface scrolls far
              // more often than it rearranges — the piece runs down the
              // screen for as long as it lasts, and HW011 lasts thirty-six
              // minutes — and a body that moves is a body that cannot scroll,
              // because the same gesture cannot be two things. Measured on
              // the phone with three tracks of regions, claiming every body
              // put a third of the canvas beyond scrolling, in three dead
              // columns sitting exactly over the blocks the eye is on.
              // Claiming only the one in hand leaves at most one such column,
              // and none at all until something is taken up.
              //
              // A region whose sound the index cannot resolve still has a
              // place, so it can still be taken up and given another one.
              const movable = mode === "trim" && isSelectedRegion;
              // On the track a thumb is holding towards removal. Drawn in the
              // band a whole-region snip uses, because it means the same
              // thing: let go now and this goes.
              const going = doomed !== null && region.track === doomed.track ? doomed : null;
              // The level the block draws at: what a lift would keep while a
              // balance is under way, and what the file holds otherwise. The
              // fill carries it as weight, so loudness is seen rather than read.
              const weighing = balancing && balancing.id === region.id ? balancing : null;
              const shownGain = weighing ? weighing.gain : region.gain;
              const name = row ? row.filename : "a sound the index does not resolve";
              // As many lines of the name as the block has room for. A block
              // too short for one line has no label; the name is still spoken.
              const lines = Math.max(1, Math.floor((box.height - 12) / 14.3));
              // A `div` with the button role, not a `button`: WebKit will not
              // stick a label inside a button, and the label has to stay in view
              // on a region taller than the screen.
              return (
                <div
                  key={region.id}
                  role="button"
                  tabIndex={0}
                  className={`region${playing ? " playing" : ""}${row ? "" : " unresolved"}${isSelectedRegion ? " selected" : ""}${shifting ? " shifting" : ""}`}
                  data-testid="region"
                  data-region-id={region.id}
                  data-track={shifting ? shifting.track : region.track}
                  data-hash={region.hash}
                  data-playing={playing}
                  data-selected={isSelectedRegion}
                  data-gain={shownGain}
                  data-loops={shownLoops}
                  data-shifting={shifting !== null}
                  aria-label={row ? `${playing ? "stop" : "play"} ${row.filename}` : name}
                  aria-pressed={playing}
                  style={{
                    left: box.left,
                    top: box.top,
                    width: box.width,
                    height: box.height,
                    ["--hue" as string]: hueFor(region.hash),
                    // How heavy the block draws. Lightness and solidity move
                    // together, so the difference is there on a screen with no
                    // colour in it; a half is the untouched level, which is
                    // what every block looked like before balance existed.
                    ["--weight" as string]: gainWeight(shownGain),
                  }}
                  onPointerDown={(event) => {
                    event.stopPropagation();
                    // A second thumb landing while another is mid-gesture is
                    // not a tap and must not be treated as one. It happens: a
                    // phone held in one hand is balanced with the other, and a
                    // palm or a resting finger finds the block being dragged.
                    // A tap on a block plays it, so without this the stray
                    // touch stops the very sound the balance is being judged
                    // against — or starts one over a piece already sounding.
                    // Whichever gesture is under way keeps the pointer it has.
                    // A thumb holding the track button is mid-gesture too,
                    // and what it is holding is a column of these blocks.
                    if (
                      moveRef.current ||
                      balanceRef.current ||
                      repeatRef.current ||
                      snipRef.current ||
                      dragRef.current ||
                      trackHoldRef.current
                    ) {
                      dropTap();
                      return;
                    }
                    beginTap(event);
                    const onGrab = (event.target as HTMLElement).dataset.testid === "region-grab";
                    if (snippable && onGrab) startSnip(event, region);
                    if (balanceable && onGrab) startBalance(event, region);
                    if (repeatable && onGrab) startRepeat(event, region);
                    // No mode: the body is free, so a thumb on it is already a
                    // move waiting to see whether it travels. A lift where it
                    // landed is still the tap that plays the region.
                    if (movable && onGrab) startMove(event, region);
                  }}
                  onPointerMove={(event) => {
                    moveSnip(event);
                    moveBalance(event);
                    moveRepeat(event);
                    whileMoving(event);
                  }}
                  onPointerUp={(event) => {
                    event.stopPropagation();
                    const m = moveRef.current;
                    if (m && m.pointerId === event.pointerId) {
                      // A thumb that went nowhere is a tap: the region plays
                      // and stays where it is. Anything further is a move, and
                      // it lands where the box has been drawn since it passed
                      // that mark.
                      endMove(m.started);
                      if (m.started) {
                        dropTap();
                        return;
                      }
                    }
                    const b = balanceRef.current;
                    if (b && b.pointerId === event.pointerId) {
                      // Across is the level and along is time, so only the
                      // sideways travel decides whether this was a drag or a
                      // tap. A thumb that went nowhere across plays the region
                      // and leaves its level exactly where it was.
                      const scrolledX = (canvasRef.current?.scrollLeft ?? 0) - b.originScroll;
                      const movedAcross = Math.abs(event.clientX - b.originX + scrolledX) >= TAP_SLOP;
                      endBalance(movedAcross);
                      if (movedAcross) {
                        dropTap();
                        return;
                      }
                    }
                    const r = repeatRef.current;
                    if (r && r.pointerId === event.pointerId) {
                      // Down the box is the count and across it is nothing,
                      // so only the travel along decides whether this was a
                      // drag or a tap. A thumb that went nowhere plays the
                      // region and leaves its count exactly where it was.
                      const scrolledY = (canvasRef.current?.scrollTop ?? 0) - r.originScroll;
                      const movedAlong = Math.abs(event.clientY - r.originY + scrolledY) >= TAP_SLOP;
                      endRepeat(movedAlong);
                      if (movedAlong) {
                        dropTap();
                        return;
                      }
                    }
                    const s = snipRef.current;
                    if (s && s.pointerId === event.pointerId) {
                      // A thumb that did not travel is a tap, whatever mode is
                      // on: it plays, and nothing is cut. Travel counts the
                      // canvas scrolling under a thumb held at its edge.
                      const scrolled = (canvasRef.current?.scrollTop ?? 0) - s.originScroll;
                      const travelled = Math.abs(event.clientY - s.originY + scrolled) >= TAP_SLOP;
                      endSnip(travelled);
                      if (travelled) {
                        dropTap();
                        return;
                      }
                    }
                    if (!endTap(event)) return;
                    // A tap takes the region up and plays it. Taking it up
                    // again keeps whichever handle was already selected.
                    // While the piece is playing a tap only takes the region
                    // up: the piece is what is being listened to, and one
                    // region on top of it would be two things at once. That is
                    // also what keeps trim, snip and stretch reachable mid-play,
                    // since each of them begins with taking a region up.
                    setSelected((was) => (was?.id === region.id ? was : { id: region.id, end: null }));
                    if (row && piece === "idle") toggleRegion(region);
                  }}
                  onPointerCancel={(event) => {
                    event.stopPropagation();
                    if (snipRef.current?.pointerId === event.pointerId) endSnip(false);
                    if (balanceRef.current?.pointerId === event.pointerId) endBalance(false);
                    if (repeatRef.current?.pointerId === event.pointerId) endRepeat(false);
                    if (moveRef.current?.pointerId === event.pointerId) endMove(false);
                    dropTap();
                  }}
                  onKeyDown={(event) => {
                    // In balance mode the arrows across the screen are the
                    // gesture, on a keyboard as on a phone: a twentieth of the
                    // range, or a fifth with shift. Nothing is printed.
                    if (balanceable && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
                      event.preventDefault();
                      event.stopPropagation();
                      const step = (event.shiftKey ? 0.4 : 0.1) * (event.key === "ArrowRight" ? 1 : -1);
                      const next = balance(region, region.gain + step);
                      if (next !== region) {
                        change(regionsRef.current.map((r) => (r.id === region.id ? next : r)));
                      }
                      return;
                    }
                    // In repeat mode the arrows down the screen are the
                    // gesture, on a keyboard as on a phone: one more time
                    // round, or four with shift, because reaching the ceiling
                    // by thumb is seven screens of dragging and by arrow it
                    // would otherwise be sixty-three presses. Down is more,
                    // as it is under a thumb, because every repeat is added
                    // at the bottom. Nothing is printed; the dividers say it.
                    if (repeatable && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
                      event.preventDefault();
                      event.stopPropagation();
                      const step = (event.shiftKey ? 4 : 1) * (event.key === "ArrowDown" ? 1 : -1);
                      const next = repeat(region, regionsRef.current, loopsOf(region) + step);
                      if (next !== region) {
                        change(regionsRef.current.map((r) => (r.id === region.id ? next : r)));
                      }
                      return;
                    }
                    if (event.key !== "Enter" && event.key !== " ") return;
                    event.preventDefault();
                    event.stopPropagation();
                    setSelected((was) => (was?.id === region.id ? was : { id: region.id, end: null }));
                    if (row && piece === "idle") toggleRegion(region);
                  }}
                >
                  {/* The grab: where a thumb can take hold of a region whose
                      box is thinner than a thumb. A hit area, not a drawing;
                      it never crosses the middle of the gap to a neighbour. */}
                  <span
                    className="region-grab"
                    data-testid="region-grab"
                    style={{
                      top: grab.top,
                      height: grab.height,
                      // A thumb on the grab is always doing something to the
                      // region — snipping, weighing, or moving it — so it is
                      // never scrolling. The canvas is scrolled from the
                      // blank and from the flanks either side of the grab,
                      // which is where a thumb aiming to scroll a track goes.
                      touchAction:
                        snippable || balanceable || repeatable || movable ? "none" : undefined,
                    }}
                    aria-hidden="true"
                  />
                  {source ? (
                    <RegionWave
                      pairs={source.pairs}
                      durationS={row?.duration_s ?? null}
                      startS={region.start_s}
                      endS={region.end_s}
                      silence={source.silence}
                      spans={source.spans}
                      width={box.width}
                      height={box.height}
                      loops={shownLoops}
                    />
                  ) : null}

                  {/* Where each repeat begins. A line, not a count: the eye
                      reads how many times the material comes round off the
                      block itself, and nothing anywhere says the number. */}
                  {dividers.map((at, n) => (
                    <span
                      key={n}
                      className="region-repeat"
                      data-testid="region-repeat"
                      style={{ top: at }}
                      aria-hidden="true"
                    />
                  ))}
                  {playing ? (
                    <span className="region-progress" style={{ height: `${progress * 100}%` }} aria-hidden="true" />
                  ) : null}
                  {box.height >= LABEL_MIN_H ? (
                    <span className="region-label">
                      <span className="region-label-text" style={{ WebkitLineClamp: lines }}>
                        {row ? row.filename : "not in the index"}
                      </span>
                    </span>
                  ) : null}

                  {/* What the drag would do, drawn before it does it: the part
                      being cut away goes dim, and the part being taken in is
                      outlined. A stretch says it the same way, since what it
                      changes is also the box's extent. The box itself keeps
                      its true length until the thumb lifts, and then there is
                      one write. */}
                  {dragging && offset !== 0 ? (
                    dragging.end === "start" ? (
                      offset > 0 ? (
                        <span className="region-cut" data-testid="region-cut" style={{ top: 0, height: offset }} aria-hidden="true" />
                      ) : (
                        <span className="region-more" data-testid="region-more" style={{ top: offset, height: -offset }} aria-hidden="true" />
                      )
                    ) : offset > 0 ? (
                      <span className="region-more" data-testid="region-more" style={{ top: box.height, height: offset }} aria-hidden="true" />
                    ) : (
                      <span className="region-cut" data-testid="region-cut" style={{ top: box.height + offset, height: -offset }} aria-hidden="true" />
                    )
                  ) : null}

                  {/* What the snip would take out, drawn before it does: the
                      same stripes a trim uses for the part being cut away,
                      with a line at each end of the span. The band is the
                      whole of what a lift would remove, including any run to
                      an edge, so a region about to vanish is striped whole. */}
                  {/* A snip is a cut in the material, and every repeat is
                      that same material, so the band appears in each of them
                      at the same place: what goes, goes from all of them. */}
                  {snipBand
                    ? Array.from({ length: shownLoops }, (_, n) => (
                        <span
                          key={n}
                          className={`region-snip${snipBand.whole ? " whole" : ""}${snipBand.armed ? " armed" : ""}`}
                          data-testid="region-snip"
                          data-whole={snipBand.whole}
                          data-armed={snipBand.armed}
                          data-repeat={n}
                          style={{
                            top: snipBand.top + n * repeatPx,
                            height: snipBand.height,
                            ["--hold-ms" as string]: `${HOLD_MS}ms`,
                          }}
                          aria-hidden="true"
                        />
                      ))
                    : null}

                  {/* What removing the track would take: this region, whole,
                      in the same band a whole-region snip paints. One
                      language for one meaning, and it fills over the hold so
                      a thumb can watch it arrive. */}
                  {going ? (
                    <span
                      className={`region-snip whole${going.armed ? " armed" : ""}`}
                      data-testid="region-doomed"
                      data-armed={going.armed}
                      style={{ top: 0, height: box.height, ["--hold-ms" as string]: `${HOLD_MS}ms` }}
                      aria-hidden="true"
                    />
                  ) : null}

                  {/* The handles. Only on the region taken up, and only in trim
                      and stretch: outside its box, a thumb tall, one at each
                      end, raised over the neighbours. A thumb on one drags it
                      straight away, and a tap on one selects it. In stretch
                      mode only the selected one shows: the other end is the
                      anchor, and a handle on it would say it could move. Snip,
                      balance and repeat are gestures on the box itself, so
                      none of them draws a handle to reach past. A region cut from a sound
                      the index cannot resolve has nothing to trim against, and
                      gets none. */}
                  {row && isSelectedRegion && mode !== "snip" && mode !== "balance" && mode !== "repeat"
                    ? ([zones.start, zones.end] as const)
                        .filter((zone) => mode === "trim" || zone.end === selection?.end)
                        .map((zone) => {
                        const isSelected = selection?.end === zone.end;
                        const moving = dragging !== null && dragging.end === zone.end;
                        const stretching = mode === "stretch";
                        return (
                          <div
                            key={zone.end}
                            role="button"
                            tabIndex={0}
                            className={`handle ${zone.end}${stretching ? " stretch" : ""}${isSelected ? " selected" : ""}${moving ? " moving" : ""}`}
                            data-testid="handle"
                            data-end={zone.end}
                            data-region-id={region.id}
                            data-selected={isSelected}
                            data-kind={stretching ? "stretch" : "trim"}
                            aria-label={`${stretching ? "stretch" : "trim"} the ${zone.end} of ${row.filename}`}
                            aria-pressed={isSelected}
                            style={{
                              top: zone.top,
                              height: zone.height,
                              transform: moving && offset !== 0 ? `translateY(${offset}px)` : undefined,
                              // The thumb on a handle is trimming, never scrolling.
                              touchAction: "none",
                            }}
                            onPointerDown={(event) => {
                              event.stopPropagation();
                              if (!isSelected) setSelected({ id: region.id, end: zone.end });
                              startDrag(event, region, zone.end);
                            }}
                            onPointerMove={moveDrag}
                            onPointerUp={(event) => {
                              event.stopPropagation();
                              if (dragRef.current?.pointerId === event.pointerId) endDrag(true);
                            }}
                            onPointerCancel={(event) => {
                              event.stopPropagation();
                              if (dragRef.current?.pointerId === event.pointerId) endDrag(false);
                            }}
                            onKeyDown={(event) => {
                              if (event.key === "Enter" || event.key === " ") {
                                event.preventDefault();
                                event.stopPropagation();
                                setSelected({ id: region.id, end: zone.end });
                                return;
                              }
                              if (!isSelected || (event.key !== "ArrowUp" && event.key !== "ArrowDown")) return;
                              event.preventDefault();
                              event.stopPropagation();
                              nudge(region, zone.end, event.key === "ArrowDown" ? 1 : -1, event.shiftKey);
                            }}
                          >
                            <span className="handle-grip" aria-hidden="true" />
                          </div>
                        );
                      })
                    : null}
                </div>
              );
            })}
          </div>
        </div>

        {/* The way back to the line, offered only while the piece plays and the
            line is off the window. It moves the canvas when it is tapped and
            never otherwise, so a thumb in the middle of a trim is never
            interrupted by the canvas walking out from under it. It says which
            way the line went, and nothing else: no position, no time. */}
        {piece === "playing" && follow !== null ? (
          <button
            type="button"
            className={`collage-follow ${follow}`}
            data-testid="collage-follow"
            data-where={follow}
            onClick={goToLine}
          >
            <span className="collage-follow-glyph" aria-hidden="true">
              {follow === "above" ? "↑" : "↓"}
            </span>
            <span className="collage-follow-body">
              <span className="collage-follow-name">the playhead is {follow}</span>
              <span className="collage-follow-sub">tap to go to it</span>
            </span>
          </button>
        ) : null}
      </div>

      {hint ? (
        <div className="collage-hint" data-testid="collage-hint" role="status">
          {hint}
        </div>
      ) : null}

      {/* The bar the thumb lives on.

          Across the top, one big target: what is being stamped, or the way to
          choose it. In snip, stretch or balance mode that target says which
          mode is on instead, and puts it off; under a moving thumb or a held
          track button it says what letting go will do.

          Under it, one row that is always there — the transport, snip, and
          undo once there is something to take back — and a second row that
          exists only while a region is in hand, holding the four gestures
          that are about that region: stretch it, balance it, copy it, remove
          its track. Those four can do nothing with nothing taken up, and four
          greyed-out boxes on a phone teach nobody anything: a `title` is not
          read by a thumb. They cost a whole row of the canvas, which on this
          view is where the work happens, so they are offered when they can be
          used and not before. Tap a region and they arrive, all four about
          the thing just tapped. */}
      <div className="collage-bar" data-mode={mode} data-rows={takenUp ? 3 : 2}>
        {doomed ? (
          /* A thumb is on the track button. This says what letting go will do
             now, and what it would do if the thumb stayed: the column it
             names is drawn in the same amber behind it. It is not a target —
             the thumb that would press it is already holding the button. */
          <div
            className={`collage-mode track whole${doomed.armed ? " armed" : ""}`}
            data-testid="collage-mode"
            data-band={doomed.armed ? "armed" : "whole"}
            role="status"
          >
            <span className="collage-choose-name">
              {doomed.armed ? "let go to remove this track" : "keep holding to remove this track"}
            </span>
            <span className="collage-choose-sub">
              everything on it goes · one undo brings it all back
            </span>
          </div>
        ) : moving ? (
          /* A region is under a thumb. Where it would land is drawn on the
             canvas; this says whether it landed where it was asked to. */
          <div
            className={`collage-mode move${moving.stopped ? " stopped" : ""}`}
            data-testid="collage-mode"
            data-bound={moving.stopped ?? ""}
            role="status"
          >
            <span className="collage-choose-name">
              {moving.stopped === "settled"
                ? "there is something there: it will sit after it"
                : moving.stopped === "top"
                  ? "this is the first moment"
                  : "let go to put it here"}
            </span>
            <span className="collage-choose-sub">
              along the track is when it sounds · across is which track
            </span>
          </div>
        ) : mode === "repeat" ? (
          <button
            type="button"
            className={`collage-mode repeat${repeating?.stopped ? " stopped" : ""}`}
            data-testid="collage-mode"
            data-bound={repeating?.stopped ?? ""}
            onClick={() => switchMode("trim")}
          >
            {/* How many times it would come round is on the block, as
                dividers. This says only whether the drag got what it asked
                for, and never a count. */}
            <span className="collage-choose-name">
              {repeating?.stopped === "once"
                ? "it has to sound at least once"
                : repeating?.stopped === "room"
                  ? "no more room on the track"
                  : repeating?.stopped === "most"
                    ? "as many times as it goes"
                    : repeating
                      ? "let go to keep it"
                      : "repeat is on"}
            </span>
            <span className="collage-choose-sub">
              drag down the region to add a repeat, up to take one away · tap here to stop
            </span>
          </button>
        ) : mode === "balance" ? (
          <button
            type="button"
            className={`collage-mode balance${balancing?.stopped ? " stopped" : ""}`}
            data-testid="collage-mode"
            data-bound={balancing?.stopped ?? ""}
            onClick={() => switchMode("trim")}
          >
            {/* Where the drag has got to, in words, because the block whose
                weight says it is under the thumb. Never a level. */}
            <span className="collage-choose-name">
              {balancing?.stopped === "quiet"
                ? "as quiet as it goes"
                : balancing?.stopped === "loud"
                  ? "as loud as it goes"
                  : balancing
                    ? "let go to keep it"
                    : "balance is on"}
            </span>
            <span className="collage-choose-sub">
              drag across the region: right is louder, left is quieter · tap here to stop
            </span>
          </button>
        ) : mode === "stretch" ? (
          <button
            type="button"
            className={`collage-mode stretch${drag?.stopped ? " stopped" : ""}`}
            data-testid="collage-mode"
            data-bound={drag?.stopped ?? ""}
            onClick={() => switchMode("trim")}
          >
            {/* Where the drag has stopped, in words, because the handle that
                stopped is under the thumb. Never a number. */}
            <span className="collage-choose-name">
              {drag?.stopped === "slow"
                ? "as slow as it goes"
                : drag?.stopped === "fast"
                  ? "as fast as it goes"
                  : drag?.stopped === "room"
                    ? "no more room on the track"
                    : drag?.stopped === "top"
                      ? "this is the first moment"
                      : drag
                        ? "let go to keep it"
                        : "stretch is on"}
            </span>
            <span className="collage-choose-sub">
              drag the handle: longer plays slower, shorter plays faster · tap here to stop
            </span>
          </button>
        ) : mode === "snip" ? (
          <button
            type="button"
            className={`collage-mode${band?.whole ? " whole" : ""}${band?.armed ? " armed" : ""}`}
            data-testid="collage-mode"
            data-band={band ? (band.armed ? "armed" : band.whole ? "whole" : "part") : ""}
            onClick={() => switchMode("trim")}
          >
            {/* What a lift would do, in words, because the band that shows
                it is under the thumb: on a short region, entirely so. */}
            <span className="collage-choose-name">
              {band?.armed
                ? "let go to take the whole region out"
                : band?.whole
                  ? "hold still to take the whole region out"
                  : band
                    ? "let go to cut the striped part out"
                    : "snip is on"}
            </span>
            <span className="collage-choose-sub">drag down a region to cut that part out · tap here to stop</span>
          </button>
        ) : clipboard ? (
          /* A copy is waiting for somewhere to go. It stands where the sound
             being stamped is usually named, because it is the same gesture
             and the same tap: the blank is where it lands. Tapping here puts
             the copy down again without stamping it. */
          <button
            type="button"
            className="collage-mode paste"
            data-testid="collage-paste"
            data-region-id={clipboard.id}
            onClick={() => {
              setClipboard(null);
              setHint(null);
            }}
          >
            <span className="collage-choose-name">
              a copy of {rowsByHash.get(clipboard.hash)?.filename ?? "that region"} is ready
            </span>
            <span className="collage-choose-sub">tap the blank to put it there · tap here to cancel</span>
          </button>
        ) : (
          <button
            type="button"
            className={`collage-choose${chosen ? " chosen" : ""}`}
            data-testid="collage-choose"
            data-hash={chosen?.hash ?? ""}
            onClick={() => {
              setHint(null);
              openPicker();
            }}
          >
            {chosen ? (
              <>
                <span className="collage-choose-name">{chosen.filename}</span>
                <span className="collage-choose-sub">tap the blank to stamp it · tap here to change</span>
              </>
            ) : (
              <>
                <span className="collage-choose-name">choose a sound</span>
                <span className="collage-choose-sub">
                  {formatCount(detail.items.length)} in {project.name}
                </span>
              </>
            )}
          </button>
        )}
        {/* The row that is always under the statement: the two things that
            are about the canvas rather than about any one region, and the way
            back from anything at all. Undo keeps its place in this row
            whatever else the bar is showing, because it is the way out of a
            held delete and a thumb must not have to hunt for it. */}
        <div className="collage-bar-row" data-testid="collage-bar-row">
        {/* The transport. Two words and nothing else: no position, no
            length, no speed, no level. It refuses with nothing stamped,
            because there is no piece yet. While the first pieces are being
            fetched it says so, and tapping it again gives up on them. */}
        <button
          type="button"
          className={`collage-play${piece === "playing" ? " on" : ""}${piece === "loading" ? " loading" : ""}`}
          data-testid="collage-play"
          data-state={piece}
          aria-pressed={piece !== "idle"}
          disabled={regions.length === 0}
          title={piece === "idle" ? "play the whole collage from the top" : "stop"}
          onClick={togglePiece}
        >
          {piece === "idle" ? "play" : "stop"}
          <span className="collage-snip-sub">
            {piece === "loading" ? "loading…" : piece === "playing" ? "on" : "off"}
          </span>
        </button>
        {/* Looping the transport, which is how the piece is listened to and
            not part of it: nothing about the arrangement changes, nothing is
            written, and the commit freezes exactly what it would have frozen
            with this off. It sits beside play because that is what it is
            about, and it is remembered on this machine, so coming back to a
            piece you were looping loops it again. It is never disabled: the
            way somebody wants to listen is theirs to set before there is
            anything to listen to. */}
        <button
          type="button"
          className={`collage-loop${loopPiece ? " on" : ""}`}
          data-testid="collage-loop"
          data-state={loopPiece ? "on" : "off"}
          aria-pressed={loopPiece}
          title={
            loopPiece
              ? "the piece starts again from the top when it reaches the end"
              : "loop: start the piece again from the top when it reaches the end"
          }
          onClick={toggleLoopPiece}
        >
          loop
          <span className="collage-snip-sub">{loopPiece ? "on" : "off"}</span>
        </button>
        <button
          type="button"
          className={`collage-snip${mode === "snip" ? " on" : ""}`}
          data-testid="collage-snip"
          aria-pressed={mode === "snip"}
          disabled={regions.length === 0}
          title="snip: drag down a region to cut that part out, leaving two regions"
          onClick={() => switchMode(mode === "snip" ? "trim" : "snip")}
        >
          snip
          <span className="collage-snip-sub">{mode === "snip" ? "on" : "off"}</span>
        </button>
        {history.length > 0 ? (
          <button
            type="button"
            className="collage-undo"
            data-testid="collage-undo"
            data-depth={history.length}
            title={`take back the last change. the last ${UNDO_DEPTH} are kept.`}
            onClick={undo}
          >
            undo
            <span className="collage-undo-sub">
              {formatCount(history.length)} {history.length === 1 ? "step" : "steps"}
            </span>
          </button>
        ) : null}
        </div>

        {/* The row about the region in hand. It is here because something was
            taken up, and it goes when that is put down: four gestures, all of
            them on that one region, and no row of dead buttons when there is
            nothing for them to be about. */}
        {takenUp ? (
        <div className="collage-bar-row in-hand" data-testid="collage-in-hand">
        {/* Stretch needs a handle: it is the end the box grows or shrinks
            from. Until one is selected the button refuses, and says what
            to do first. */}
        <button
          type="button"
          className={`collage-stretch${mode === "stretch" ? " on" : ""}`}
          data-testid="collage-stretch"
          aria-pressed={mode === "stretch"}
          disabled={!handleUp}
          title={
            handleUp
              ? "stretch: drag the selected handle to make the region play slower or faster"
              : "stretch: tap a region, then one of its handles, first"
          }
          onClick={() => switchMode(mode === "stretch" ? "trim" : "stretch")}
        >
          stretch
          <span className="collage-snip-sub">{mode === "stretch" ? "on" : "off"}</span>
        </button>
        {/* Balance needs a region, not a handle: the whole block is what the
            drag runs across. Until one is taken up the button refuses, and
            says what to do first. */}
        <button
          type="button"
          className={`collage-balance${mode === "balance" ? " on" : ""}`}
          data-testid="collage-balance"
          aria-pressed={mode === "balance"}
          disabled={!regionUp}
          title={
            regionUp
              ? "balance: drag across the region to make it louder or quieter"
              : "balance: tap a region first"
          }
          onClick={() => switchMode(mode === "balance" ? "trim" : "balance")}
        >
          balance
          <span className="collage-snip-sub">{mode === "balance" ? "on" : "off"}</span>
        </button>
        {/* Repeat needs a region, as balance does, and its drag runs down the
            block rather than across it: down the screen is time, and every
            repeat is added at the bottom, so the box grows the way the thumb
            goes. A thumb's height is one more time round, the same movement
            on a ten-pixel block and on a nine-thousand-pixel one. */}
        <button
          type="button"
          className={`collage-repeat${mode === "repeat" ? " on" : ""}`}
          data-testid="collage-repeat"
          aria-pressed={mode === "repeat"}
          disabled={!regionUp}
          title={
            regionUp
              ? "repeat: drag down the region to make it sound again, back to back"
              : "repeat: tap a region first"
          }
          onClick={() => switchMode(mode === "repeat" ? "trim" : "repeat")}
        >
          repeat
          <span className="collage-snip-sub">{mode === "repeat" ? "on" : "off"}</span>
        </button>
        {/* Copy takes the region taken up and holds it, ready for the next tap
            on the blank. Nothing is written by pressing it; what changes is
            what that tap will do, which the wide statement above then says. */}
        <button
          type="button"
          className={`collage-copy${clipboard ? " on" : ""}`}
          data-testid="collage-copy"
          aria-pressed={clipboard !== null}
          disabled={!takenUp}
          title={
            takenUp
              ? "copy: take a copy of this region, then tap the blank to put it there"
              : "copy: tap a region first"
          }
          onClick={copyRegion}
        >
          copy
          <span className="collage-snip-sub">{clipboard ? "ready" : "off"}</span>
        </button>
        {/* Removing a track takes every region on it, so this one is not a tap.
            It has to be pressed and held, and while it is, the column it would
            take is drawn in amber on the canvas and the statement above says
            what letting go will do. A press let go of early removes nothing. */}
        <button
          type="button"
          className={`collage-track${doomed ? " holding" : ""}${doomed?.armed ? " armed" : ""}`}
          data-testid="collage-track"
          data-armed={doomed?.armed ?? false}
          disabled={!takenUp}
          aria-label="remove this track and everything on it"
          title={
            takenUp
              ? "remove this track and everything on it: press and hold"
              : "remove a track: tap a region on it first"
          }
          style={{ touchAction: "none", ["--hold-ms" as string]: `${HOLD_MS}ms` }}
          onPointerDown={(event) => {
            event.preventDefault();
            try {
              event.currentTarget.setPointerCapture(event.pointerId);
            } catch {
              /* a pointer that has already gone */
            }
            startTrackHold(event.clientY, event.pointerId);
          }}
          onPointerMove={(event) => {
            // A thumb that leaves the button has changed its mind. Touch
            // captures the pointer to the button it landed on, so leaving is
            // not something the browser will say: it is asked here, and only
            // when the thumb actually moves, so a button that shifts under a
            // still thumb never cancels anything by itself. A second thumb
            // wandering over the button is not the thumb that is holding it
            // and has no say in either direction.
            if (!holdingTrack(event.pointerId)) return;
            const rect = event.currentTarget.getBoundingClientRect();
            const on =
              event.clientX >= rect.left &&
              event.clientX <= rect.right &&
              event.clientY >= rect.top &&
              event.clientY <= rect.bottom;
            if (!on) endTrackHold(false);
            else whileTrackHold(event.clientY);
          }}
          onPointerUp={(event) => {
            if (holdingTrack(event.pointerId)) endTrackHold(true);
          }}
          onPointerCancel={(event) => {
            if (holdingTrack(event.pointerId)) endTrackHold(false);
          }}
          onPointerLeave={(event) => {
            if (holdingTrack(event.pointerId)) endTrackHold(false);
          }}
          onKeyDown={(event) => {
            if (event.key !== "Enter" && event.key !== " ") return;
            event.preventDefault();
            // A keyboard has no pointer, so the hold it starts belongs to a
            // thumb that cannot exist and no touch can finish it.
            startTrackHold(0, -1);
          }}
          onKeyUp={(event) => {
            if (event.key !== "Enter" && event.key !== " ") return;
            event.preventDefault();
            if (holdingTrack(-1)) endTrackHold(true);
          }}
        >
          <span>track</span>
          <span className="collage-snip-sub">{doomed ? (doomed.armed ? "let go" : "holding") : "hold"}</span>
        </button>
        </div>
        ) : null}
      </div>

      {pickerOpen ? (
        <Picker
          rows={detail.items}
          onChoose={(row) => {
            setChosen(row);
            setHint("now tap the blank where it should go");
            // Choosing a sound is choosing to stamp, which is the default
            // mode's gesture.
            switchMode("trim");
          }}
          onClose={() => setPickerOpen(false)}
        />
      ) : null}
    </div>
  );
}
