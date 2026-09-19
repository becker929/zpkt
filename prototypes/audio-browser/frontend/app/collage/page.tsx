"use client";

/**
 * Collage: the view where something is made.
 *
 * Time runs down the screen and tracks run across it. It starts with nothing:
 * no lanes, no ruler, no grid, and no number of seconds anywhere. Time exists
 * because a sound was stamped into it, and a track exists because something
 * was stamped there.
 *
 * This is the first tracer bullet, and only it: choose a sound from the
 * project's frozen set, tap the canvas to stamp it, hear it back. Every change
 * is written whole to `PUT /api/projects/{id}/collage`, so a reload shows what
 * was on screen. A region plays through Web Audio from a bounded slice the
 * server cuts; nothing decodes a whole file.
 *
 * The geometry is in `lib/collage.ts` and is pure. This file is the shell
 * around it: fetches, the audio context, and the DOM.
 */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useBoard } from "@/components/BoardProvider";
import { usePlayer } from "@/components/PlayerProvider";
import { Waveform } from "@/components/Waveform";
import {
  ApiRefusal,
  collageRouteIsMissing,
  fetchProject,
  fetchSpans,
  putCollage,
  type ProjectDetail,
} from "@/lib/api";
import { MIN_REGION_H, canvasSize, collageProject, hueFor, regionBox, stamp, trackCount } from "@/lib/collage";
import { formatCount } from "@/lib/format";
import type { Region } from "@/lib/project";
import { SlicePlayer } from "@/lib/slicePlayer";
import type { FileRow, Span } from "@/lib/types";

type SaveState = "idle" | "saving" | "saved" | "failed" | "absent";

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
  /** The arrangement before the last stamp, so a mis-stamp can be taken back. */
  const [before, setBefore] = useState<Region[] | null>(null);
  const [chosen, setChosen] = useState<FileRow | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [hint, setHint] = useState<string | null>(null);
  const [save, setSave] = useState<SaveState>("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [playError, setPlayError] = useState<string | null>(null);

  const spaceRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const sliceRef = useRef<SlicePlayer | null>(null);

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
        setBefore(null);
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

  /* Saving ------------------------------------------------------------------ */

  /**
   * Write the latest arrangement, one request at a time.
   *
   * Two stamps in quick succession must not race: each write replaces the
   * whole description, so the later of two out-of-order arrivals would store
   * the older state. Writes are queued, and a queued write always sends what
   * is latest, so a burst of stamps ends in one request carrying all of them.
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
      latestRef.current = next;
      void flush();
    },
    [flush],
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

  /* Stamping ---------------------------------------------------------------- */

  const onCanvasClick = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      const space = spaceRef.current;
      if (!space || !detail) return;
      if (!chosen) {
        setHint("choose a sound first, then tap here to stamp it");
        setPickerOpen(true);
        return;
      }
      const rect = space.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      const region = stamp(regions, chosen.hash, chosen.duration_s ?? 0, x, y);
      const next = [...regions, region];
      setBefore(regions);
      setHint(null);
      commitRegions(next);
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
        const box = regionBox(region, next);
        const right = box.left + box.width;
        const bottom = box.top + Math.min(box.height, MIN_REGION_H);
        const left = right > canvas.scrollLeft + canvas.clientWidth ? right - canvas.clientWidth : canvas.scrollLeft;
        const top = bottom > canvas.scrollTop + canvas.clientHeight ? bottom - canvas.clientHeight : canvas.scrollTop;
        if (left !== canvas.scrollLeft || top !== canvas.scrollTop) canvas.scrollTo({ left, top });
      }
    },
    [detail, chosen, regions, commitRegions],
  );

  const undo = useCallback(() => {
    if (before === null) return;
    stopRegion();
    commitRegions(before);
    setBefore(null);
  }, [before, commitRegions, stopRegion]);

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
    <div className="collage" data-testid="collage" data-project-id={project.id} data-regions={regions.length} data-tracks={tracks}>
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
          longer resolves. {unresolved === 1 ? "It is" : "They are"} drawn, and cannot be played.
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
          onClick={onCanvasClick}
        >
          {regions.map((region) => {
            const box = regionBox(region, regions);
            const row = rowsByHash.get(region.hash);
            const playing = playingId === region.id;
            // As many lines of the name as the block has room for, and never
            // fewer than one. The block is not clipped, so a label longer than
            // the block would spill past it.
            const lines = Math.max(1, Math.floor((box.height - 12) / 14.3));
            // A `div` with the button role, not a `button`: WebKit will not
            // stick a label inside a button, and the label has to stay in view
            // on a region taller than the screen.
            return (
              <div
                key={region.id}
                role="button"
                tabIndex={0}
                className={`region${playing ? " playing" : ""}${row ? "" : " unresolved"}`}
                data-testid="region"
                data-region-id={region.id}
                data-track={region.track}
                data-hash={region.hash}
                data-playing={playing}
                aria-label={row ? `${playing ? "stop" : "play"} ${row.filename}` : "a sound the index does not resolve"}
                aria-pressed={playing}
                style={{
                  left: box.left,
                  top: box.top,
                  width: box.width,
                  height: box.height,
                  ["--hue" as string]: hueFor(region.hash),
                }}
                onClick={(event) => {
                  event.stopPropagation();
                  if (row) toggleRegion(region);
                }}
                onKeyDown={(event) => {
                  if (event.key !== "Enter" && event.key !== " ") return;
                  event.preventDefault();
                  event.stopPropagation();
                  if (row) toggleRegion(region);
                }}
              >
                {playing ? (
                  <span className="region-progress" style={{ height: `${progress * 100}%` }} aria-hidden="true" />
                ) : null}
                <span className="region-label">
                  <span className="region-label-text" style={{ WebkitLineClamp: lines }}>
                    {row ? row.filename : "not in the index"}
                  </span>
                </span>
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
          the way to choose it. Undo appears beside it after a stamp. */}
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
              <span className="collage-choose-sub">tap the canvas to stamp it · tap here to change</span>
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
        {before !== null ? (
          <button
            type="button"
            className="collage-undo"
            data-testid="collage-undo"
            title="take back the last stamp"
            onClick={undo}
          >
            undo
          </button>
        ) : null}
      </div>

      {pickerOpen ? (
        <Picker
          rows={detail.items}
          onChoose={(row) => {
            setChosen(row);
            setHint("now tap the canvas where it should go");
          }}
          onClose={() => setPickerOpen(false)}
        />
      ) : null}
    </div>
  );
}
