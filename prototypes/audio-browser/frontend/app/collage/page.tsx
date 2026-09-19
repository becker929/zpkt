"use client";

/**
 * Collage: the view where something is made.
 *
 * Time runs down the screen and tracks run across it. It starts with nothing:
 * no lanes, no ruler, no grid, and no number of seconds anywhere. Time exists
 * because a sound was stamped into it, and a track exists because something
 * was stamped there.
 *
 * Two gestures so far. Choose a sound from the project's frozen set, tap the
 * blank to stamp it, hear it back. Then trim: every region shows the sound
 * inside it; a tap on a region plays it and takes it up, and the region
 * taken up carries a thumb-sized handle at each end that drags. Every
 * change is written whole to `PUT /api/projects/{id}/collage`, so a reload
 * shows what was on screen. A region plays through Web Audio from a bounded
 * slice the server cuts; nothing decodes a whole file.
 *
 * The geometry is in `lib/collage.ts` and is pure. This file is the shell
 * around it: fetches, the audio context, the pointer, and the DOM.
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
  canvasSize,
  collageProject,
  dragOffsetPx,
  draggedTo,
  grabZone,
  handleZones,
  hueFor,
  regionBox,
  stamp,
  trackCount,
  trim,
  type End,
} from "@/lib/collage";
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
 * the keyboard and, later, stretch know which end is meant. `end` is null
 * while the region is up and neither handle has been touched.
 */
interface Selection {
  id: string;
  end: End | null;
}

/** A drag in progress: the region as it was, and as it would be if released now. */
interface Drag {
  id: string;
  end: End;
  preview: Region;
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

  const spaceRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const sliceRef = useRef<SlicePlayer | null>(null);
  /** The arrangement as the pointer handlers see it, without re-binding them. */
  const regionsRef = useRef<Region[]>([]);
  regionsRef.current = regions;

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

  const commitRegions = useCallback(
    (next: Region[]) => {
      setRegions(next);
      regionsRef.current = next;
      latestRef.current = next;
      void flush();
    },
    [flush],
  );

  /** A change: what was there goes on the undo stack, and the new arrangement is written. */
  const change = useCallback(
    (next: Region[]) => {
      // Read now, not inside the updater: by the time the updater runs the
      // ref already holds what replaced this.
      const was = regionsRef.current;
      setHistory((h) => [...h, was].slice(-UNDO_DEPTH));
      commitRegions(next);
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
          setPlayError(message);
        },
      });
      if (!started) {
        setPlayError("this browser cannot play audio this way");
        return;
      }
      setPlayingId(region.id);
      setProgress(0);
    },
    [playingId, player, stopRegion],
  );

  // Leaving the view stops the region and releases the audio context. The
  // shared player is left alone; it belongs to every view.
  useEffect(() => {
    return () => {
      sliceRef.current?.close();
      sliceRef.current = null;
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
      if (!chosen) {
        if (wasUp) return;
        setHint("choose a sound first, then tap the blank to stamp it");
        setPickerOpen(true);
        return;
      }
      const rect = space.getBoundingClientRect();
      const x = clientX - rect.left;
      const y = clientY - rect.top;
      const region = stamp(regions, chosen.hash, chosen.duration_s ?? 0, x, y);
      const next = [...regions, region];
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
    [detail, chosen, regions, selected, change],
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
    d.preview = trim(d.region, regionsRef.current, d.durationS, d.end, draggedTo(d.region, d.end, dy));
    setDrag({ id: d.id, end: d.end, preview: d.preview });
  }, []);

  /**
   * Scroll the canvas while the thumb sits at its edge.
   *
   * A source stamped whole is several screens tall, and the sound in it can
   * be anywhere. Holding the handle at the bottom of the screen carries on
   * down through the region, so one drag can reach it.
   */
  const scrollAtEdge = useCallback(() => {
    const step = () => {
      const d = dragRef.current;
      const canvas = canvasRef.current;
      if (!d || !canvas) {
        scrollFrameRef.current = 0;
        return;
      }
      const rect = canvas.getBoundingClientRect();
      let by = 0;
      if (d.lastY < rect.top + SCROLL_EDGE) by = -SCROLL_STEP;
      else if (d.lastY > rect.bottom - SCROLL_EDGE) by = SCROLL_STEP;
      if (by === 0) {
        scrollFrameRef.current = 0;
        return;
      }
      const before = canvas.scrollTop;
      canvas.scrollTop = Math.max(0, Math.min(canvas.scrollHeight - canvas.clientHeight, before + by));
      if (canvas.scrollTop !== before) previewFromPointer();
      scrollFrameRef.current = requestAnimationFrame(step);
    };
    if (!scrollFrameRef.current) scrollFrameRef.current = requestAnimationFrame(step);
  }, [previewFromPointer]);

  const endDrag = useCallback(
    (apply: boolean) => {
      const d = dragRef.current;
      dragRef.current = null;
      if (scrollFrameRef.current) cancelAnimationFrame(scrollFrameRef.current);
      scrollFrameRef.current = 0;
      setDrag(null);
      if (!apply || !d) return;
      const was = regionsRef.current.find((r) => r.id === d.id);
      if (!was || (was.start_s === d.preview.start_s && was.end_s === d.preview.end_s)) return;
      // One write per drag, carrying the whole arrangement.
      change(regionsRef.current.map((r) => (r.id === d.id ? d.preview : r)));
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
      // The slice being played is the cut being changed. It stops, so what
      // is heard next is what the trim made.
      if (playingId === region.id) stopRegion();
      dragRef.current = {
        id: region.id,
        end,
        pointerId: event.pointerId,
        originY: event.clientY,
        originScroll: canvas?.scrollTop ?? 0,
        lastY: event.clientY,
        region,
        durationS: rowsByHash.get(region.hash)?.duration_s ?? null,
        preview: region,
      };
      setDrag({ id: region.id, end, preview: region });
    },
    [playingId, rowsByHash, stopRegion],
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

  // Turning the phone, or the browser taking the pointer for itself, ends the
  // drag without applying it: the thumb is no longer where the handle is.
  // Escape lets go of the handle on a keyboard.
  useEffect(() => {
    const onResize = () => {
      if (dragRef.current) endDrag(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (dragRef.current) endDrag(false);
      setSelected(null);
    };
    window.addEventListener("resize", onResize);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("resize", onResize);
      window.removeEventListener("keydown", onKey);
    };
  }, [endDrag]);

  /** A keyboard nudge: a tenth of a second, or a whole one with shift. */
  const nudge = useCallback(
    (region: Region, end: End, direction: 1 | -1, big: boolean) => {
      const rate = region.rate > 0 ? region.rate : 1;
      const step = (big ? 1 : 0.1) * rate * direction;
      const t = (end === "start" ? region.start_s : region.end_s) + step;
      const next = trim(region, regionsRef.current, rowsByHash.get(region.hash)?.duration_s ?? null, end, t);
      if (next.start_s === region.start_s && next.end_s === region.end_s) return;
      if (playingId === region.id) stopRegion();
      change(regionsRef.current.map((r) => (r.id === region.id ? next : r)));
    },
    [change, playingId, rowsByHash, stopRegion],
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

  const size = canvasSize(regions);
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
          longer resolves. {unresolved === 1 ? "It is" : "They are"} drawn, and cannot be played or trimmed.
        </div>
      ) : null}

      {playError ? (
        <div className="error collage-note" data-testid="collage-play-error">
          could not play that region: {playError}
        </div>
      ) : null}

      {/* The canvas. Genuinely empty until something is stamped: no lanes, no
          ticks. It scrolls down through time and across through tracks. */}
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
          {regions.map((region) => {
            const box = regionBox(region);
            const row = rowsByHash.get(region.hash);
            const source = sources.get(region.hash);
            const playing = playingId === region.id;
            const isSelectedRegion = selection?.id === region.id;
            const grab = grabZone(region, regions);
            const zones = handleZones(region);
            const dragging = drag && drag.id === region.id ? drag : null;
            const offset = dragging ? dragOffsetPx(region, dragging.preview, dragging.end) : 0;
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
                className={`region${playing ? " playing" : ""}${row ? "" : " unresolved"}${isSelectedRegion ? " selected" : ""}`}
                data-testid="region"
                data-region-id={region.id}
                data-track={region.track}
                data-hash={region.hash}
                data-playing={playing}
                data-selected={isSelectedRegion}
                aria-label={row ? `${playing ? "stop" : "play"} ${row.filename}` : name}
                aria-pressed={playing}
                style={{
                  left: box.left,
                  top: box.top,
                  width: box.width,
                  height: box.height,
                  ["--hue" as string]: hueFor(region.hash),
                }}
                onPointerDown={(event) => {
                  event.stopPropagation();
                  beginTap(event);
                }}
                onPointerUp={(event) => {
                  event.stopPropagation();
                  if (!endTap(event)) return;
                  // A tap takes the region up and plays it. Taking it up
                  // again keeps whichever handle was already selected.
                  setSelected((was) => (was?.id === region.id ? was : { id: region.id, end: null }));
                  if (row) toggleRegion(region);
                }}
                onPointerCancel={(event) => {
                  event.stopPropagation();
                  dropTap();
                }}
                onKeyDown={(event) => {
                  if (event.key !== "Enter" && event.key !== " ") return;
                  event.preventDefault();
                  event.stopPropagation();
                  setSelected((was) => (was?.id === region.id ? was : { id: region.id, end: null }));
                  if (row) toggleRegion(region);
                }}
              >
                {/* The grab: where a thumb can take hold of a region whose
                    box is thinner than a thumb. A hit area, not a drawing;
                    it never crosses the middle of the gap to a neighbour. */}
                <span
                  className="region-grab"
                  data-testid="region-grab"
                  style={{ top: grab.top, height: grab.height }}
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
                  />
                ) : null}
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
                    outlined. The box itself keeps its true length until the
                    thumb lifts, and then there is one write. */}
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

                {/* The handles. Only on the region taken up: outside its box,
                    a thumb tall, one at each end, raised over the neighbours.
                    A thumb on one drags it straight away, and a tap on one
                    selects it. A region cut from a sound the index cannot
                    resolve has nothing to trim against, and gets none. */}
                {row && isSelectedRegion
                  ? ([zones.start, zones.end] as const).map((zone) => {
                      const isSelected = selection?.end === zone.end;
                      const moving = dragging !== null && dragging.end === zone.end;
                      return (
                        <div
                          key={zone.end}
                          role="button"
                          tabIndex={0}
                          className={`handle ${zone.end}${isSelected ? " selected" : ""}${moving ? " moving" : ""}`}
                          data-testid="handle"
                          data-end={zone.end}
                          data-region-id={region.id}
                          data-selected={isSelected}
                          aria-label={`${zone.end === "start" ? "trim the start of" : "trim the end of"} ${row.filename}`}
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

      {hint ? (
        <div className="collage-hint" data-testid="collage-hint" role="status">
          {hint}
        </div>
      ) : null}

      {/* The bar the thumb lives on. One big target: what is being stamped, or
          the way to choose it. Undo appears beside it once there is something
          to take back, and says how many steps it holds. */}
      <div className="collage-bar">
        <button
          type="button"
          className={`collage-choose${chosen ? " chosen" : ""}`}
          data-testid="collage-choose"
          data-hash={chosen?.hash ?? ""}
          onClick={() => {
            setHint(null);
            setPickerOpen(true);
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

      {pickerOpen ? (
        <Picker
          rows={detail.items}
          onChoose={(row) => {
            setChosen(row);
            setHint("now tap the blank where it should go");
          }}
          onClose={() => setPickerOpen(false)}
        />
      ) : null}
    </div>
  );
}
