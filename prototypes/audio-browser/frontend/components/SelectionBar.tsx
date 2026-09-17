"use client";

/**
 * The bar that appears once rows are selected, and the list sheet it opens.
 *
 * It sits in the normal column flow, directly above the player bar, and the
 * scroller above it shrinks by its height. Nothing is floated over the player:
 * on a phone the transport is how the sound being judged gets played, so it
 * must stay reachable while a decision is being made.
 *
 * Every action is addressed by hash. The bar never sees a path.
 */

import { useCallback, useEffect, useState } from "react";

import { useBoard } from "@/components/BoardProvider";
import { plural, useTriage } from "@/components/TriageProvider";
import { ApiRefusal, addSoundsToProject, createList, createProject, fetchLists } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { soundSetOpen } from "@/lib/project";
import type { SelectionHandle } from "@/lib/useSelection";
import type { SoundList } from "@/lib/types";

/** Which sheet the bar has open, if any. */
type Sheet = null | "list" | "project";

export function SelectionBar({
  selection,
  /** `deleted` is the discard pile, where the destructive action is restore. */
  mode = "default",
  /** Set on a list's own page, which can also take sounds out of that list. */
  listId,
}: {
  selection: SelectionHandle;
  mode?: "default" | "deleted";
  listId?: number;
}) {
  const triage = useTriage();
  const board = useBoard();
  const [sheet, setSheet] = useState<Sheet>(null);
  const [lists, setLists] = useState<SoundList[] | null>(null);
  const [name, setName] = useState("");
  const [projectName, setProjectName] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  /** What the last add to a project actually did, in the user's words. */
  const [report, setReport] = useState<string | null>(null);
  /** A cap refusal from creating a project here, held so it can be overridden. */
  const [refusal, setRefusal] = useState<ApiRefusal | null>(null);

  const hashes = selection.hashes;

  // The sheet is only useful while something is selected.
  useEffect(() => {
    if (!selection.active) {
      setSheet(null);
      setProblem(null);
      setReport(null);
      setRefusal(null);
    }
  }, [selection.active]);

  const loadLists = useCallback(() => {
    fetchLists()
      .then(setLists)
      .catch(() => setLists([]));
  }, []);

  const openSheet = () => {
    setSheet("list");
    setProblem(null);
    if (lists === null) loadLists();
  };

  const openProjectSheet = () => {
    setSheet("project");
    setProblem(null);
    setReport(null);
    setRefusal(null);
    board.refresh();
  };

  const act = async (action: Parameters<typeof triage.run>[0], options?: { listId?: number }) => {
    if (busy || hashes.length === 0) return;
    setBusy(true);
    await triage.run(action, hashes, options);
    setBusy(false);
    setSheet(null);
    selection.clear();
  };

  const addToNewList = async () => {
    const wanted = name.trim();
    if (!wanted || busy) return;
    setBusy(true);
    setProblem(null);
    try {
      const created = await createList(wanted);
      await triage.run("add_to_list", hashes, { listId: created.id });
      setName("");
      setSheet(null);
      selection.clear();
      loadLists();
    } catch {
      setProblem(`could not make a list called "${wanted}". a list with that name may exist.`);
    } finally {
      setBusy(false);
    }
  };

  /**
   * Put the selection into a project.
   *
   * The report is what happened, not what was asked for. A project committed in
   * another tab stops the run part way through, and saying "added 40" over a
   * project that gained twelve would be the kind of lie this whole interface is
   * built to avoid.
   */
  const addToProject = async (id: string, label: string) => {
    if (busy || hashes.length === 0) return;
    setBusy(true);
    setProblem(null);
    setReport(null);
    try {
      const result = await addSoundsToProject(id, hashes);
      board.refresh();
      if (result.stopped) {
        setProblem(
          `added ${formatCount(result.added)} of ${formatCount(hashes.length)} to “${label}”, then stopped: ${
            result.stopped
          }`,
        );
      } else {
        setReport(
          `added ${formatCount(result.added)} to “${label}”${
            result.already > 0 ? `, ${formatCount(result.already)} already there` : ""
          }`,
        );
        setSheet(null);
        selection.clear();
      }
    } catch (err) {
      setProblem(err instanceof ApiRefusal ? err.detail : err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const addToNewProject = async (override: boolean) => {
    const wanted = projectName.trim();
    if (!wanted || busy) return;
    setBusy(true);
    setProblem(null);
    setRefusal(null);
    try {
      const created = await createProject(wanted, override);
      setProjectName("");
      board.refresh();
      if (created) await addToProject(created.id, created.name);
      else setProblem("the project was made, but the server did not say which one. nothing was added.");
    } catch (err) {
      // A cap refusal is offered again with an override. Anything else is said
      // plainly and not retried.
      if (err instanceof ApiRefusal && err.cap) setRefusal(err);
      else setProblem(err instanceof ApiRefusal ? err.detail : err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  /**
   * The projects that can actually take a sound.
   *
   * Only those in `stored` with no `stored` commit. A project further down the
   * board would answer 409, so offering it would be offering something that
   * cannot work.
   */
  const openProjects = (board.projects ?? []).filter(soundSetOpen);

  if (!selection.active) return null;

  return (
    <div className="selection" data-testid="selection-bar" data-count={selection.size}>
      {sheet === "project" ? (
        <div className="list-sheet" data-testid="project-sheet">
          <div className="sheet-head">
            <span>add {plural(selection.size, "sound")} to a project</span>
            <button type="button" className="chip" data-testid="sheet-close" onClick={() => setSheet(null)}>
              close
            </button>
          </div>

          <div className="sheet-lists">
            {board.status === "loading" ? <span className="dim">loading…</span> : null}

            {/* Not being served is not the same as having no projects, and the
                two must not read the same. Nothing is offered, and the reason
                is the route rather than the user's own board. */}
            {board.status === "absent" || (board.status === "ready" && board.projects === null) ? (
              <span className="dim" data-testid="project-sheet-absent">
                projects are not being served yet: <code>/api/projects</code> answered “not here”. nothing
                can be added.
              </span>
            ) : null}

            {board.status === "error" ? (
              <span className="dim" data-testid="project-sheet-error">
                could not read the projects: {board.error}
              </span>
            ) : null}

            {board.status === "ready" && board.projects !== null && openProjects.length === 0 ? (
              <span className="dim" data-testid="project-sheet-empty">
                no project can take sounds. a project only accepts them while it is in stored and its
                sound set has not been frozen. name one below, or start one on the board.
              </span>
            ) : null}

            {openProjects.map((project) => (
              <button
                key={project.id}
                type="button"
                className="chip"
                data-testid="sheet-project"
                data-project-id={project.id}
                disabled={busy}
                onClick={() => void addToProject(project.id, project.name)}
              >
                {project.name} <span className="dim">{formatCount(project.sound_count)}</span>
              </button>
            ))}
          </div>

          <form
            className="sheet-new"
            onSubmit={(e) => {
              e.preventDefault();
              void addToNewProject(false);
            }}
          >
            <input
              type="text"
              value={projectName}
              placeholder="new project…"
              aria-label="new project name"
              data-testid="new-project-name"
              maxLength={120}
              onChange={(e) => {
                setProjectName(e.target.value);
                setRefusal(null);
              }}
            />
            <button
              type="submit"
              className="chip"
              data-testid="new-project-create"
              disabled={busy || !projectName.trim() || board.projects === null}
            >
              start it and add
            </button>
          </form>

          {refusal ? (
            <div className="refusal" data-testid="cap-refusal" data-column={refusal.cap?.column ?? ""}>
              <p className="refusal-detail" data-testid="refusal-detail">
                {refusal.detail}
              </p>
              <div className="card-actions">
                <button
                  type="button"
                  className="chip override"
                  data-testid="cap-override"
                  disabled={busy}
                  onClick={() => void addToNewProject(true)}
                >
                  {refusal.cap
                    ? `go to ${refusal.cap.count + 1} in ${refusal.cap.column} anyway`
                    : "do it anyway"}
                </button>
                <button
                  type="button"
                  className="chip"
                  data-testid="cap-cancel"
                  disabled={busy}
                  onClick={() => setRefusal(null)}
                >
                  not now
                </button>
              </div>
            </div>
          ) : null}

          {problem ? (
            <div className="sheet-problem" data-testid="sheet-problem">
              {problem}
            </div>
          ) : null}
        </div>
      ) : null}

      {sheet === "list" ? (
        <div className="list-sheet" data-testid="list-sheet">
          <div className="sheet-head">
            <span>add {plural(selection.size, "sound")} to</span>
            <button type="button" className="chip" data-testid="sheet-close" onClick={() => setSheet(null)}>
              close
            </button>
          </div>

          <div className="sheet-lists">
            {lists === null ? <span className="dim">loading…</span> : null}
            {lists !== null && lists.length === 0 ? (
              <span className="dim">no lists yet. name one below.</span>
            ) : null}
            {(lists ?? []).map((list) => (
              <button
                key={list.id}
                type="button"
                className="chip"
                data-testid="sheet-list"
                data-list-id={list.id}
                disabled={busy}
                onClick={() => void act("add_to_list", { listId: list.id })}
              >
                {list.name} <span className="dim">{formatCount(list.member_count)}</span>
              </button>
            ))}
          </div>

          <form
            className="sheet-new"
            onSubmit={(e) => {
              e.preventDefault();
              void addToNewList();
            }}
          >
            <input
              type="text"
              value={name}
              placeholder="new list…"
              aria-label="new list name"
              data-testid="new-list-name"
              maxLength={120}
              onChange={(e) => setName(e.target.value)}
            />
            <button type="submit" className="chip" data-testid="new-list-create" disabled={busy || !name.trim()}>
              create and add
            </button>
          </form>

          {problem ? (
            <div className="sheet-problem" data-testid="sheet-problem">
              {problem}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="selection-row">
        <span className="count mono" data-testid="selection-count">
          {plural(selection.size, "sound")} selected
          {selection.full ? " · that is the most one action can take" : ""}
          {report ? <span className="dim" data-testid="project-report"> · {report}</span> : null}
        </span>

        <div className="selection-actions">
          <button type="button" className="chip" data-testid="bulk-star" disabled={busy} onClick={() => void act("star")}>
            ★ star
          </button>
          <button type="button" className="chip" data-testid="bulk-unstar" disabled={busy} onClick={() => void act("unstar")}>
            ☆ unstar
          </button>
          <button type="button" className="chip" data-testid="bulk-list" disabled={busy} onClick={openSheet}>
            + list
          </button>
          <button
            type="button"
            className="chip"
            data-testid="bulk-project"
            disabled={busy}
            onClick={openProjectSheet}
          >
            + project
          </button>
          {listId === undefined ? null : (
            <button
              type="button"
              className="chip"
              data-testid="bulk-remove-from-list"
              disabled={busy}
              onClick={() => void act("remove_from_list", { listId })}
            >
              − from list
            </button>
          )}
          {mode === "deleted" ? (
            <button
              type="button"
              className="chip restore"
              data-testid="bulk-restore"
              disabled={busy}
              onClick={() => void act("restore")}
            >
              ↩ restore
            </button>
          ) : (
            <button
              type="button"
              className="chip discard"
              data-testid="bulk-discard"
              disabled={busy}
              onClick={() => void act("delete")}
            >
              ✕ discard
            </button>
          )}
          <button type="button" className="chip" data-testid="selection-clear" onClick={() => selection.clear()}>
            done
          </button>
        </div>
      </div>
    </div>
  );
}
