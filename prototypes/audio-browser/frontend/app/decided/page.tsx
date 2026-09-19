"use client";

/**
 * Decided: what has already been answered.
 *
 * This is a record, not a catalogue. It holds only sounds that have been taken
 * into a project or discarded, so there is no way through it to a sound that
 * has never been heard. Three filters: which of the two answers, which project
 * a taken sound went into, and the name.
 *
 * The two answers are read from different places, and neither is guessed at.
 * Taken sounds are the members of the project files, so they are read from the
 * projects themselves. Discarded sounds are a filter on the index, so they are
 * paged like any other filtered set.
 */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useBoard } from "@/components/BoardProvider";
import { FileList } from "@/components/FileList";
import { Length } from "@/components/Length";
import { Marquee } from "@/components/Marquee";
import { usePlayer } from "@/components/PlayerProvider";
import { SelectionBar } from "@/components/SelectionBar";
import { useTriage } from "@/components/TriageProvider";
import { ApiRefusal, fetchProject, filesUrl, setProjectSound } from "@/lib/api";
import { isEncumbered } from "@/lib/boardConfig";
import { formatCount } from "@/lib/format";
import { soundSetOpen } from "@/lib/project";
import { EMPTY_QUERY, type FileRow } from "@/lib/types";
import { PAGE_SIZE, useFiles } from "@/lib/useFiles";
import { useSelection } from "@/lib/useSelection";
import type { ProjectSummary } from "@/lib/project";

type Answer = "taken" | "discarded";

/** One taken sound, and the project it went into. */
interface TakenRow {
  row: FileRow;
  project: ProjectSummary;
}

/* Taken -------------------------------------------------------------------- */

function TakenList({ needle, projectId }: { needle: string; projectId: string }) {
  const board = useBoard();
  const player = usePlayer();
  const [rows, setRows] = useState<TakenRow[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const projects = useMemo(() => board.projects ?? [], [board.projects]);
  const version = board.version;

  useEffect(() => {
    let cancelled = false;
    const wanted = projects.filter((p) => projectId === "" || p.id === projectId);
    if (wanted.length === 0) {
      setRows([]);
      return;
    }
    Promise.all(wanted.map((project) => fetchProject(project.id).then((detail) => ({ project, detail }))))
      .then((results) => {
        if (cancelled) return;
        const out: TakenRow[] = [];
        for (const { project, detail } of results) {
          for (const row of detail?.items ?? []) out.push({ row, project });
        }
        out.sort((a, b) => a.row.filename.localeCompare(b.row.filename));
        setRows(out);
      })
      .catch(() => {
        if (!cancelled) setRows([]);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, version, projects.length]);

  const untake = useCallback(
    async (entry: TakenRow) => {
      if (busy) return;
      setBusy(true);
      setProblem(null);
      try {
        await setProjectSound(entry.project.id, entry.row.hash, false);
        board.refresh();
      } catch (err) {
        setProblem(err instanceof ApiRefusal ? err.detail : err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [board, busy],
  );

  if (board.status === "absent") {
    return (
      <div className="notice" data-testid="taken-absent">
        projects are not being served: <code>/api/projects</code> answered “not here”. what was taken cannot
        be read.
      </div>
    );
  }

  if (rows === null) return <div className="notice">loading…</div>;

  const shown = needle
    ? rows.filter((entry) => entry.row.filename.toLowerCase().includes(needle.toLowerCase()))
    : rows;

  if (shown.length === 0) {
    return (
      <div className="notice" data-testid="taken-empty">
        {needle ? `nothing taken is called “${needle}”.` : "nothing has been taken into a project yet."}
      </div>
    );
  }

  return (
    <div className="scroller" data-testid="scroller">
      {problem ? <div className="error">{problem}</div> : null}
      {shown.map((entry) => {
        const open = soundSetOpen(entry.project);
        const isCurrent = player.current?.hash === entry.row.hash;
        return (
          <div
            key={`${entry.project.id}:${entry.row.hash}`}
            className={`row${isCurrent ? " playing" : ""}`}
            data-testid="row"
            data-hash={entry.row.hash}
            data-project-id={entry.project.id}
            onClick={() => player.play(entry.row, { query: EMPTY_QUERY, index: 0, total: 1, rows: [entry.row] })}
          >
            <div className="col-name">
              <Link href={`/sounds/${entry.row.hash}`} onClick={(e) => e.stopPropagation()}>
                <Marquee text={entry.row.filename} active={isCurrent} />
              </Link>
            </div>
            <div className="col-dur mono">
              <Length soundingS={entry.row.sounding_s} wallS={entry.row.duration_s} />
            </div>
            <div className="col-project">
              <Link href="/board" onClick={(e) => e.stopPropagation()} data-testid="row-project">
                {entry.project.name}
              </Link>
            </div>
            <div className="col-taken">
              {open ? (
                <button
                  type="button"
                  className="drop"
                  data-testid="untake-row"
                  aria-label={`take ${entry.row.filename} back out of ${entry.project.name}`}
                  title="put it back in the queue. the project has not been committed, so its sound set is still open."
                  disabled={busy}
                  onClick={(e) => {
                    e.stopPropagation();
                    void untake(entry);
                  }}
                >
                  ↩
                </button>
              ) : (
                <span
                  className="dim mono"
                  data-testid="frozen-row"
                  title="the sound set of this project was frozen when it committed. it can never gain or lose a sound."
                >
                  frozen
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* Discarded ---------------------------------------------------------------- */

function DiscardedList({ needle }: { needle: string }) {
  const triage = useTriage();
  const query = useMemo(() => ({ ...EMPTY_QUERY, q: needle, deleted: "true" as const }), [needle]);
  const files = useFiles(query);
  const selection = useSelection(filesUrl(query, PAGE_SIZE, 0));

  useEffect(() => {
    if (triage.version > 0) files.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [triage.version]);

  return (
    <>
      <FileList
        files={files}
        query={query}
        update={() => undefined}
        selection={selection}
        empty={needle ? `nothing discarded is called “${needle}”.` : "nothing has been discarded yet."}
      />
      <SelectionBar selection={selection} mode="deleted" />
    </>
  );
}

/* The view ----------------------------------------------------------------- */

export default function DecidedPage() {
  const board = useBoard();
  const [answer, setAnswer] = useState<Answer>("taken");
  const [projectId, setProjectId] = useState("");
  const [needle, setNeedle] = useState("");

  const projects = board.projects ?? [];

  return (
    <div className="decided" data-testid="decided" data-answer={answer}>
      <div className="controls">
        <div className="controls-primary">
          <input
            type="search"
            placeholder="by name…"
            value={needle}
            aria-label="filter decided sounds by name"
            data-testid="decided-search"
            onChange={(e) => setNeedle(e.target.value)}
          />
          <div className="decided-tabs" role="group" aria-label="which answer">
            <button
              type="button"
              className={`chip${answer === "taken" ? " on" : ""}`}
              aria-pressed={answer === "taken"}
              data-testid="filter-taken"
              onClick={() => setAnswer("taken")}
            >
              taken
            </button>
            <button
              type="button"
              className={`chip${answer === "discarded" ? " on" : ""}`}
              aria-pressed={answer === "discarded"}
              data-testid="filter-discarded"
              onClick={() => setAnswer("discarded")}
            >
              discarded
            </button>
          </div>
          {answer === "taken" ? (
            <select
              value={projectId}
              aria-label="project"
              data-testid="filter-project"
              onChange={(e) => setProjectId(e.target.value)}
            >
              <option value="">every project</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name} ({formatCount(project.sound_count)})
                  {isEncumbered(project.sound_count, board.encumbrance) ? " · encumbered" : ""}
                </option>
              ))}
            </select>
          ) : null}
        </div>
      </div>

      {answer === "taken" ? <TakenList needle={needle} projectId={projectId} /> : <DiscardedList needle={needle} />}
    </div>
  );
}
