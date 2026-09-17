"use client";

/**
 * Swipe: the view the collection is worked through.
 *
 * One sound fills the screen and loops until it is answered. There are two
 * answers and no third: take it into the project on the bench, or discard it.
 * "Not for this project but keep it" is deferral, deferral is what favourites
 * were, and a triage lane must not offer it. Discard is reversible, so the
 * cost of being decisive is small and the cost of being indecisive is the
 * whole problem.
 *
 * Silence is skipped, so a five minute stem with forty seconds of sound takes
 * forty seconds. A quarter of this collection is dead air; skipping it is what
 * makes a one-pass listen possible at all.
 *
 * This is a one-thumb interface. Everything that can be reached is inside the
 * bottom third of the screen, and the two answers are the widest targets on
 * it.
 */

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { useBoard } from "@/components/BoardProvider";
import { usePlayer } from "@/components/PlayerProvider";
import { useTriage } from "@/components/TriageProvider";
import { Waveform } from "@/components/Waveform";
import { ApiRefusal, currentProject, fetchSpans, setProjectSound } from "@/lib/api";
import { isEncumbered, ENCUMBERED_AT } from "@/lib/boardConfig";
import { formatCount, formatDuration } from "@/lib/format";
import { MIN_GAP_S, skippable } from "@/lib/silence";
import { SWIPE_THRESHOLD_PX, useSwipeGesture } from "@/lib/useSwipeGesture";
import { useSwipeQueue } from "@/lib/useSwipeQueue";
import type { FileRow, Span } from "@/lib/types";
import type { ProjectSummary } from "@/lib/project";

/** What was just answered, and how to take it back. */
type LastAnswer =
  | { kind: "taken"; row: FileRow; project: ProjectSummary }
  | { kind: "discarded"; row: FileRow };

/**
 * The project on the bench, its count, and whether it is carrying too much.
 *
 * Encumbered is a mark, not a limit. Adding still works and the mark stays
 * until the count comes back down, which is why it is on screen every time the
 * project is.
 */
function Bench({ project }: { project: ProjectSummary | null }) {
  if (!project) return null;
  const heavy = isEncumbered(project.sound_count);
  return (
    <div className="bench" data-testid="bench" data-project-id={project.id} data-encumbered={heavy}>
      <span className="bench-name">{project.name}</span>
      <span className="bench-count mono" data-testid="bench-count">
        {formatCount(project.sound_count)}
      </span>
      {heavy ? (
        <span
          className="bench-encumbered"
          data-testid="bench-encumbered"
          title={`more than ${ENCUMBERED_AT} sounds. a track is a kick, a rumble, a few textures and some impacts. adding still works.`}
        >
          encumbered
        </span>
      ) : null}
    </div>
  );
}

export default function SwipePage() {
  const player = usePlayer();
  const board = useBoard();
  const triage = useTriage();
  const queue = useSwipeQueue();

  const [spans, setSpans] = useState<Span[]>([]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [last, setLast] = useState<LastAnswer | null>(null);

  const row = queue.current;
  const hash = row?.hash ?? null;
  const project = currentProject(board.projects);

  // Looping is what this view runs on: reaching the end of a sound is not a
  // reason to move on, only a decision is. It is turned off on the way out so
  // the rest of the application plays through as it always has.
  const setLoop = player.setLoop;
  useEffect(() => {
    setLoop(true);
    return () => setLoop(false);
  }, [setLoop]);

  // Load each sound as it reaches the front of the queue. The player is the one
  // audio element in the application, so this is a source change rather than a
  // new element, and silence skipping comes with it.
  const play = player.play;
  const playedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!row || playedRef.current === row.hash) return;
    playedRef.current = row.hash;
    play(row);
  }, [row, play]);

  // One classifier's spans, asked for by name. Three opinions tinted over each
  // other say nothing about any of them.
  useEffect(() => {
    if (!hash) {
      setSpans([]);
      return;
    }
    const controller = new AbortController();
    setSpans([]);
    fetchSpans(hash, undefined, controller.signal)
      .then(setSpans)
      .catch(() => setSpans([]));
    return () => controller.abort();
  }, [hash]);

  const isCurrent = player.current?.hash === hash;
  const gaps = skippable(player.silence?.intervals ?? [], MIN_GAP_S, player.silence?.duration_s ?? row?.duration_s);
  const silentS = gaps.reduce((sum, gap) => sum + (gap.end_s - gap.start_s), 0);

  const take = useCallback(async () => {
    if (!row || !project || busy) return;
    setBusy(true);
    setProblem(null);
    try {
      await setProjectSound(project.id, row.hash, true);
      board.refresh();
      setLast({ kind: "taken", row, project });
      queue.answered(row.hash);
    } catch (err) {
      setProblem(err instanceof ApiRefusal ? err.detail : err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [row, project, busy, board, queue]);

  const discard = useCallback(async () => {
    if (!row || busy) return;
    setBusy(true);
    setProblem(null);
    const result = await triage.run("delete", [row.hash], {
      label: `discarded ${row.filename}`,
      undoable: false,
    });
    setBusy(false);
    if (result === null) return;
    setLast({ kind: "discarded", row });
    queue.answered(row.hash);
  }, [row, busy, triage, queue]);

  const undoLast = useCallback(async () => {
    if (!last || busy) return;
    setBusy(true);
    setProblem(null);
    try {
      if (last.kind === "taken") {
        await setProjectSound(last.project.id, last.row.hash, false);
        board.refresh();
      } else {
        await triage.run("restore", [last.row.hash], { undoable: false });
      }
      setLast(null);
      queue.refresh();
    } catch (err) {
      setProblem(err instanceof ApiRefusal ? err.detail : err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [last, busy, board, triage, queue]);

  const canTake = project !== null && !busy;
  const gesture = useSwipeGesture({
    onTake: () => void take(),
    onDiscard: () => void discard(),
    canTake,
    enabled: row !== null && !busy,
  });

  /* What is on screen when there is no sound to answer -------------------- */

  if (queue.status === "absent") {
    return (
      <div className="swipe empty" data-testid="swipe-absent">
        <p>
          the queue of undecided sounds cannot be read. <code>/api/swipe</code> is not being served, and
          neither <code>/api/files</code> nor <code>/api/projects</code> answered either.
        </p>
        <p className="dim">nothing is shown rather than a sound picked at random.</p>
      </div>
    );
  }

  if (queue.status === "error") {
    return (
      <div className="swipe empty" data-testid="swipe-error">
        <p className="error">could not read the queue: {queue.error}</p>
      </div>
    );
  }

  // A refill is in flight, so the queue has not said there is nothing left. It
  // has said nothing at all yet.
  if (!row && (queue.status === "loading" || queue.filling)) {
    return <div className="notice">loading…</div>;
  }

  if (!row) {
    return (
      <div className="swipe empty" data-testid="swipe-done">
        <p>nothing is undecided. every sound has been taken or discarded.</p>
        <p className="dim">
          <Link href="/decided">what was decided</Link> · <Link href="/board">the board</Link>
        </p>
      </div>
    );
  }

  /* The card -------------------------------------------------------------- */

  const lean = Math.max(-1, Math.min(1, gesture.dx / SWIPE_THRESHOLD_PX));

  return (
    <div className="swipe" data-testid="swipe" data-hash={row.hash} data-source={queue.source ?? ""}>
      <div className="swipe-top">
        <Bench project={project} />
        <span className="swipe-remaining mono" data-testid="swipe-remaining">
          {queue.remaining === null ? "—" : `${formatCount(queue.remaining)} left`}
        </span>
      </div>

      <div
        className={`swipe-card${gesture.dragging ? " dragging" : ""}`}
        data-testid="swipe-card"
        data-intent={gesture.intent ?? ""}
        style={{ transform: `translateX(${gesture.dx}px) rotate(${lean * 2}deg)` }}
        {...gesture.bind}
      >
        {/* The two answers, shown on the card as it is pushed. The card says
            what letting go would do before it does it. */}
        <span className="swipe-hint discard" style={{ opacity: Math.max(0, -lean) }} aria-hidden="true">
          discard
        </span>
        <span className="swipe-hint take" style={{ opacity: canTake ? Math.max(0, lean) : 0 }} aria-hidden="true">
          take
        </span>

        <h1 className="swipe-name" data-testid="swipe-name">
          {row.filename}
        </h1>

        <Waveform
          pairs={player.peaks?.pairs ?? []}
          durationS={(isCurrent ? player.duration : 0) || row.duration_s}
          progressS={isCurrent ? player.time : 0}
          spans={spans}
          silence={gaps}
          height={168}
          onSeek={(s) => player.seek(s)}
          seekable={!row.transcoded}
          placeholder="loading peaks…"
        />

        <div className="swipe-meta mono" data-testid="swipe-meta">
          <span>{formatDuration(row.sounding_s ?? row.duration_s)}</span>
          <span>{row.ext.replace(".", "")}</span>
          {silentS >= 1 ? (
            <span data-testid="swipe-skipping">
              {row.transcoded
                ? `${formatDuration(silentS)} silent, unskippable`
                : player.autoSkip
                  ? `skipping ${formatDuration(silentS)}`
                  : `${formatDuration(silentS)} silent`}
            </span>
          ) : null}
          <Link href={`/sounds/${row.hash}`} data-testid="swipe-detail-link">
            detail
          </Link>
        </div>
      </div>

      {/* Transport, then the two answers. The transport is a setting about how
          the sound is heard; the answers are the work. */}
      <div className="swipe-transport">
        <button
          type="button"
          className="btn primary"
          aria-label={player.playing ? "pause" : "play"}
          data-testid="swipe-play"
          onClick={() => player.toggle()}
        >
          {player.playing ? "⏸" : "▶"}
        </button>
        <button
          type="button"
          className={`chip${player.autoSkip ? " on" : ""}`}
          aria-pressed={player.autoSkip}
          data-testid="swipe-skip-toggle"
          title="gaps of 2 seconds or more. a scrub into one stays there."
          onClick={() => player.setAutoSkip(!player.autoSkip)}
        >
          skip silence
        </button>
        <span className="swipe-loop dim" data-testid="swipe-loop">
          looping
        </span>
      </div>

      {problem ? (
        <div className="error swipe-problem" data-testid="swipe-problem">
          {problem}
        </div>
      ) : null}

      {triage.error ? (
        <div className="error swipe-problem" data-testid="swipe-triage-error">
          that did not save: {triage.error}
        </div>
      ) : null}

      {last ? (
        <div className="swipe-last" data-testid="swipe-last">
          <span className="swipe-last-label">
            {last.kind === "taken" ? `took ${last.row.filename}` : `discarded ${last.row.filename}`}
          </span>
          <button type="button" className="chip" data-testid="swipe-undo" disabled={busy} onClick={() => void undoLast()}>
            undo
          </button>
        </div>
      ) : null}

      {project === null ? (
        <div className="swipe-nobench" data-testid="swipe-no-project">
          {board.status === "absent" ? (
            <>
              projects are not being served: <code>/api/projects</code> answered “not here”. nothing can be
              taken, and only discarding works.
            </>
          ) : (
            <>
              no project is on the bench, so there is nowhere to take a sound.{" "}
              <Link href="/board">start one</Link>.
            </>
          )}
        </div>
      ) : null}

      <div className="swipe-actions">
        <button
          type="button"
          className="swipe-act discard"
          data-testid="swipe-discard"
          disabled={busy}
          onClick={() => void discard()}
        >
          discard
        </button>
        <button
          type="button"
          className="swipe-act take"
          data-testid="swipe-take"
          disabled={!canTake}
          title={project ? `take it into ${project.name}` : "there is no project to take it into"}
          onClick={() => void take()}
        >
          take{project ? <span className="swipe-act-sub">{project.name}</span> : null}
        </button>
      </div>
    </div>
  );
}
